#!/usr/bin/env python3
"""时间轴生成：依据旁白实际时长反推镜头顺序与配音落点。

产物：tmp/timeline.json
  {fps, fade, total, shots:[{name,start,end,z0,z1}], narr:[{src,at}], overlays:[...]}

设计要点：
- 先裁掉 TTS 自动生成的首尾静音，让每句诗干净入画；
- 旁白比镜头起点晚 LINE_LEAD 秒开口（等叠化完成）；
- 相邻镜头重叠 FADE 秒 = 交叉叠化窗口；
- 字幕/诗句叠加层由 frames/overlays.json 的坐标 + 本脚本计算的时刻合成。
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import Paths, bootstrap_ffmpeg, duration, load_config  # noqa: E402

LEAD = 0.9          # 片头开场留白
LINE_LEAD = 1.8     # 旁白比镜头起点晚多少（等叠化完成再开口）
LINE_TAIL = 1.5     # 一句诗念完后的留白
MIN_SCENE = 6.8     # 单场景最短时长
LAST_TAIL = 2.2     # 最后一句诗后额外留白
PAD = 0.07          # 裁剪静音后保留的头尾呼吸
REPEAT_GAP = 1.4    # 片尾复诵时句间停顿


def load_wav(ff, p: Path, sr=24000):
    import subprocess
    raw = subprocess.run([str(ff), "-v", "error", "-i", str(p), "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768, sr


def prep(ff, P: Paths, name: str) -> tuple[str, float]:
    """裁掉首尾静音，写回 audio/mimo/prep/，返回（相对路径, 时长）。"""
    x, sr = load_wav(ff, P.mimo / f"{name}.wav")
    hop = int(sr * 0.02)
    n = len(x) // hop
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9
    thr = max(10 ** (-48 / 20), 0.04 * rms.max())
    idx = np.nonzero(rms > thr)[0]
    a, b = (idx[0], idx[-1] + 1) if len(idx) else (0, n)
    a = max(0, int(a * hop - PAD * sr))
    b = min(len(x), int(b * hop + PAD * sr))
    y = (np.clip(x[a:b], -1, 1) * 32767).astype(np.int16)
    P.prep.mkdir(parents=True, exist_ok=True)
    dst = P.prep / f"{name}.wav"
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())
    return str(dst.relative_to(P.root)), round(len(y) / sr, 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()

    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    P = Paths(root)
    P.ensure()
    ff = bootstrap_ffmpeg(root, verbose=False)

    lines: list[str] = cfg["poem"]["lines"]
    n = len(lines)
    FPS = int(cfg["video"]["fps"])
    FADE = float(cfg["video"]["fade"])
    use_narr = bool(cfg["narration"].get("enabled", True))
    repeat = bool(cfg["narration"].get("repeat_full_poem", True))
    credit = bool(cfg["video"].get("title_credit", True))

    names = ["open"] + [f"s{i}" for i in range(1, n + 1)] + ["author"]
    src, lengths = {}, {}
    if use_narr:
        print("旁白裁剪（原始 → 去首尾静音）：")
        for nm in names:
            sp, d = prep(ff, P, nm)
            src[nm] = sp
            lengths[nm] = d
            print(f"  {nm:<7} {duration(ff, P.mimo / f'{nm}.wav'):6.2f}s → {d:6.2f}s")
    else:
        for nm in names:
            src[nm], lengths[nm] = "", MIN_SCENE

    narr: list[dict] = []
    shots: list[dict] = []

    # ---- 片头 ----
    t_open = LEAD
    end_t = t_open + (lengths["open"] + 1.4 if use_narr else 3.0)
    shots.append(dict(name="title", start=0.0, end=round(end_t, 3),
                      z0=1.000, z1=1.050))
    if use_narr:
        narr.append(dict(src=src["open"], at=round(t_open, 3)))

    # ---- N 个诗句场景 ----
    scene_times = []
    for k in range(1, n + 1):
        d = lengths[f"s{k}"]
        tail = LAST_TAIL if k == n else LINE_TAIL
        start = shots[-1]["end"] - FADE
        length = max(MIN_SCENE, LINE_LEAD + d + tail) if use_narr else MIN_SCENE
        end = start + length
        z = (1.050, 1.000) if k % 2 == 1 else (1.000, 1.050)
        shots.append(dict(name=f"scene{k}", start=round(start, 3),
                          end=round(end, 3), z0=z[0], z1=z[1]))
        if use_narr:
            narr.append(dict(src=src[f"s{k}"], at=round(start + LINE_LEAD, 3)))
        scene_times.append(start)

    # ---- 片尾一：全诗复诵（可选）----
    e = shots[-1]["end"] - FADE
    t = e + 1.5
    line_times: list[float] = []
    if use_narr and repeat:
        for i in range(n):
            narr.append(dict(src=src[f"s{i + 1}"], at=round(t, 3)))
            line_times.append(round(t, 3))
            t += lengths[f"s{i + 1}"] + (1.6 if i == n - 2 else REPEAT_GAP)

    # ---- 片尾二：作者信息（可选）----
    if use_narr and credit:
        au_at = t + 1.0
        total = au_at + lengths["author"] + 3.2
    elif use_narr:
        total = t + 2.5
        au_at = total
    else:
        au_at = t + 2.0
        total = au_at + 6.0

    if credit:
        e2 = (au_at - 0.3) if use_narr else e + 1.5
        shots.append(dict(name="ending", start=round(e, 3),
                          end=round(e2 + FADE, 3), z0=1.000, z1=1.030))
        shots.append(dict(name="ending2", start=round(e2, 3),
                          end=round(total, 3), z0=1.000, z1=1.040))
    else:
        shots.append(dict(name="ending", start=round(e, 3),
                          end=round(total, 3), z0=1.000, z1=1.035))
        e2 = total
    if use_narr and credit:
        narr.append(dict(src=src["author"], at=round(au_at, 3)))

    # ---- 叠加层：场景字幕 + 片尾逐句诗句 ----
    overlays: list[dict] = []
    if P.overlays.exists():
        ovmeta = {m["file"]: m for m in
                  json.loads(P.overlays.read_text(encoding="utf-8"))}
        if cfg["video"].get("caption") == "horizontal":
            for k in range(1, n + 1):
                key = f"sub{k}.png"
                if key not in ovmeta:
                    continue
                s = shots[k]
                overlays.append({**ovmeta[key],
                                 "at": round(s["start"] + 0.5, 3), "rin": 1.0,
                                 "out": round(s["end"] - 0.2, 3), "rout": 1.3})
        for i, tt in enumerate(line_times):
            key = f"line{i + 1}.png"
            if key not in ovmeta:
                continue
            overlays.append({**ovmeta[key], "at": round(tt - 0.2, 3),
                             "rin": 1.0, "out": round(e2, 3), "rout": 1.2})

    data = dict(fps=FPS, fade=FADE, total=round(total, 3), shots=shots,
                narr=narr, overlays=overlays,
                durations=dict(zip(names, (lengths[k] for k in names))),
                style=cfg["style"], lines=lines)
    P.tmp.mkdir(parents=True, exist_ok=True)
    P.timeline.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    print(f"\n总时长 {total:.2f}s（{int(round(total * FPS))} 帧）  "
          f"旁白 {len(narr)} 段  叠加层 {len(overlays)} 个")
    print("镜头:")
    for s in shots:
        print(f"  {s['name']:<9} {s['start']:7.2f} → {s['end']:7.2f} "
              f"({s['end'] - s['start']:5.2f}s)")
    if narr:
        print("旁白落点:")
        for x in narr:
            print(f"  {Path(x['src']).stem:<8} @ {x['at']:7.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
