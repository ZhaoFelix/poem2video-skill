#!/usr/bin/env python3
"""成片质检：把「抖动」「杂音」「音画不同步」这些主观问题变成可量化指标。

检查项：
  1. 帧时序均匀性   —— 应严格等于 1/fps，任何偏差即抖动来源
  2. 镜头内平滑度   —— 帧间差的均值/波动，量化运镜是否平滑
  3. 转场柔和度     —— 叠化窗口内帧间差峰值（硬切通常 >20/255）
  4. 音频频谱       —— 6kHz 以上能量占比，>1% 基本可判定有嘶声/混叠
  5. 音画等长       —— 音轨与画面时长差（侧链闪避曾导致音轨被截短）
  6. 旁白落点       —— 逐秒 RMS，核对与 timeline 设计是否吻合
  7. 削波检测       —— 满刻度样本数

用法：python3 check_quality.py --config poem.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import Paths, bootstrap_ffmpeg, load_config  # noqa: E402

OK, WARN, BAD = "✅", "⚠️", "❌"


def decode_video(ff, path, w, h):
    raw = subprocess.run(
        [str(ff), "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)


def decode_audio(ff, path, sr=32000):
    raw = subprocess.run(
        [str(ff), "-v", "error", "-i", str(path), "-map", "0:a?", "-ac", "1",
         "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True).stdout
    d = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    return d, sr


def band_pct(x, sr):
    if len(x) < 2048:
        return None
    S = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1 / sr)
    tot = float((S ** 2).sum()) + 1e-12
    out = []
    for a, b in [(0, 120), (120, 400), (400, 1200), (1200, 3000),
                 (3000, 6000), (6000, 10000), (10000, 16000)]:
        out.append(100 * float((S[(fr >= a) & (fr < b)] ** 2).sum()) / tot)
    return out


def decode_rgb(ff, path, t):
    """抽取指定时刻一帧（RGB）。"""
    raw = subprocess.run(
        [str(ff), "-v", "error", "-ss", str(t), "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True).stdout
    return raw


def caption_check(ff, P, video, fps, W, H):
    """字幕颜色检查：抓场景字幕条，验证白字/朱印没有被渲染成黑色。

    （历史 bug：叠加层预乘色用 0–1 尺度与 0–255 画布合成，白字变黑块，
    且因压暗底上"看着像有字"而难以在小图抽帧里发现。）"""
    try:
        ovmeta = {m["file"]: m for m in
                  json.loads(P.overlays.read_text(encoding="utf-8"))}
        subs = [m for k, m in ovmeta.items() if k.startswith("sub")]
        if not subs:
            return
        scale = W / 2560
        m = subs[0]
        y0, h = int(m["y0"] * scale), int(m["h"] * scale)
        shots = [s for s in json.loads(P.timeline.read_text(encoding="utf-8"))["shots"]
                 if s["name"].startswith("scene")]
        t = shots[0]["start"] + 2.0
        raw = decode_rgb(ff, video, t)
        if len(raw) < W * H * 3:
            return
        frame = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.int16)
        band = frame[y0:y0 + h]
        white = int(((band.min(axis=2) > 195)).sum())
        red = int((((band[..., 0] - band[..., 2]) > 50) &
                   (band[..., 0] > 110)).sum())
        bright = 100 * white / band[..., 0].size
        print(f"\n7.5) 字幕颜色  {t:.1f}s 处字幕条：白字像素 {bright:.2f}%  "
              f"朱印像素 {100 * red / band[...,0].size:.2f}%  "
              f"{OK if (bright > 0.5 or red > 50) else BAD + ' 疑似发黑（预乘尺度 bug）'}")
    except Exception as e:                                   # noqa: BLE001
        print(f"\n7.5) 字幕颜色  跳过（{e}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()

    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    P = Paths(root)
    ff = bootstrap_ffmpeg(root, verbose=False)
    video = P.video_path(cfg)
    if not video.exists():
        raise SystemExit(f"找不到成片 {video}")

    tl = json.loads(P.timeline.read_text(encoding="utf-8"))
    fps = float(tl["fps"])
    total = float(tl["total"])
    fade = float(tl["fade"])
    print(f"质检对象: {video.name}\n")

    # 1) 帧时序
    out = subprocess.run([str(ff), "-v", "info", "-i", str(video),
                          "-vf", "showinfo", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ts = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", out)]
    d = np.diff(ts) if len(ts) > 1 else np.array([0.0])
    ideal = 1.0 / fps
    dev = int((np.abs(d - ideal) > 1e-4).sum())
    # 帧序列的"结束时刻"= 末帧 PTS + 一帧时长（末帧 PTS 本身是起点，不是全片时长）
    vid_end = (ts[-1] + ideal) if len(ts) else 0.0
    print(f"1) 帧时序   {len(ts)} 帧  间隔 {d.min():.5f}–{d.max():.5f}s "
          f"(理想 {ideal:.5f})  偏差帧 {dev}  "
          f"{OK if dev == 0 else BAD + ' 存在抖动来源'}")
    print(f"   片长 {vid_end:.2f}s / timeline {total:.2f}s  "
          f"{OK if abs(vid_end - total) <= ideal * 1.5 else WARN}")

    # 2/3) 画面平滑度与转场
    W, H = 384, 216
    f = decode_video(ff, video, W, H)
    mad = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)) if len(f) > 1 \
        else np.array([0.0])
    fades = []
    for s0, s1 in zip(tl["shots"][:-1], tl["shots"][1:]):
        if s1["start"] < s0["end"]:
            fades.append((s1["start"], s1["start"] + fade))
    span = [x for x in fades]
    inside = np.zeros(len(mad), bool)
    for x0, x1 in span:
        inside[int(x0 * fps):int(x1 * fps)] = True
    keep = mad[~inside] if inside.any() else mad
    print(f"\n2) 镜头内平滑度  帧间差 均值 {keep.mean():.4f}/255  "
          f"波动 {keep.std():.4f}  最大突变 {np.abs(np.diff(keep)).max():.4f}")
    print(f"   {OK if keep.mean() < 6 else WARN}（<6 视为平滑运镜）")
    if fades:
        peaks = []
        for x0, x1 in fades:
            seg = mad[max(0, int(x0 * fps)):int(x1 * fps)]
            if len(seg):
                peaks.append(float(seg.max()))
        print(f"3) 转场柔和度  {len(fades)} 处叠化，窗口内帧差峰值 "
              f"{min(peaks):.2f}–{max(peaks):.2f}/255  "
              f"{OK if max(peaks) < 12 else WARN + '（硬切通常 >20）'}")

    # 4–7) 音频
    ad, sr = decode_audio(ff, video)
    if len(ad) == 0:
        print("\n4–7) 无音轨，跳过音频检查")
        return 0
    print(f"\n4) 音频频谱（低→高能量占比，6k+ 应 ≈0%）")
    # 取旁白间隙：自动找 RMS 最低的若干 1.5s 窗口
    win = int(1.5 * sr)
    nseg = len(ad) // win
    rms = np.array([np.sqrt((ad[i * win:(i + 1) * win] ** 2).mean() + 1e-12)
                    for i in range(nseg)])
    quiet = np.argsort(rms)[:3]
    for i in sorted(quiet):
        b = band_pct(ad[i * win:(i + 1) * win], sr)
        if b:
            hi = b[5] + b[6]
            print(f"   静段 {i*1.5:6.1f}s | " +
                  " ".join(f"{v:5.1f}" for v in b) +
                  f"   6k+ = {hi:.2f}% {OK if hi < 1.0 else BAD + ' 有嘶声'}")
    print("    分带        >0-120 120-400 400-1.2k 1.2-3k 3-6k 6-10k 10-16k")

    adur = len(ad) / sr
    print(f"\n5) 音画等长  画面 {total:.2f}s / 音轨 {adur:.2f}s  "
          f"差 {adur - total:+.2f}s  {OK if abs(adur - total) < 0.15 else BAD}")

    clip = int((np.abs(ad) > 0.999).sum())
    peak = 20 * np.log10(float(np.abs(ad).max()) + 1e-9)
    print(f"6) 电平      峰值 {peak:.1f} dBFS  RMS "
          f"{20*np.log10(float(np.sqrt((ad**2).mean()))+1e-9):.1f} dB  "
          f"削波样本 {clip}  {OK if clip == 0 else WARN}")

    print(f"\n7) 旁白落点核对（timeline 设计 → 实际）")
    for n in tl["narr"]:
        at = float(n["at"])
        i0, i1 = int(at * sr), int((at + 1.0) * sr)
        seg = ad[i0:i1]
        db = 20 * np.log10(float(np.sqrt((seg ** 2).mean())) + 1e-9) if len(seg) else -99
        mark = OK if db > -42 else WARN
        print(f"   {Path(n['src']).stem:<8} @ {at:7.2f}s  {db:6.1f} dB  {mark}")

    RW, RH = cfg["video"]["resolution"]
    caption_check(ff, P, video, fps, RW, RH)

    print("\n质检完成。任何 ❌ 项都应在交付前修复。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
