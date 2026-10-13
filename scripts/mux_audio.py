#!/usr/bin/env python3
"""混音合成：按 timeline.json 摆放旁白，叠上配乐并做侧链闪避，输出成片。

旁白链路：aresample 48k → 70Hz 高通（去隆隆）→ 延迟到落点 → 首尾微淡入淡出
        → 混成一条 → 响度归一 → apad 补齐到片长
配乐链路：绝对音量 → 侧链被旁白压低（闪避）→ 结尾淡出 → 限幅
总输出：与无声视频合流，loudnorm 统一响度 + 真峰值限制

⚠ 踩坑：sidechaincompress 在侧链（旁白）信号结束后会一并截止输出，
   必须给旁白链路 apad=whole_dur 补到整片长度，否则音轨比画面短、片尾淡出被截断。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import Paths, bootstrap_ffmpeg, load_config  # noqa: E402

SR = 48000
FADE_OUT = 3.8      # 片尾配乐淡出时长
NARR_GAIN = 1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()

    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    P = Paths(root)
    P.ensure()
    ff = bootstrap_ffmpeg(root, verbose=False)

    tl = json.loads(P.timeline.read_text(encoding="utf-8"))
    total = float(tl["total"])
    narr = [n for n in tl["narr"] if n.get("src")]
    bgm_gain = float(cfg["bgm"].get("gain", 0.30))
    use_bgm = bool(cfg["bgm"].get("enabled", True)) and P.bgm.exists()
    dest = P.video_path(cfg)

    cmd = [str(ff), "-y", "-v", "error", "-i", str(P.silent)]
    for n in narr:
        cmd += ["-i", str(root / n["src"])]
    if use_bgm:
        cmd += ["-i", str(P.bgm)]
    bgm_idx = 1 + len(narr)

    parts: list[str] = []
    tags: list[str] = []
    for i, n in enumerate(narr, start=1):
        ms = int(round(n["at"] * 1000))
        parts.append(f"[{i}:a]aresample={SR},highpass=f=70,"
                     f"afade=t=in:st=0:d=0.03,adelay={ms}:all=1[n{i}]")
        tags.append(f"[n{i}]")

    if narr:
        parts.append(
            f"{''.join(tags)}amix=inputs={len(narr)}:normalize=0,"
            f"volume={NARR_GAIN},loudnorm=I=-16:TP=-1.5:LRA=11,aresample={SR},"
            f"apad=whole_dur={total:.3f}[narr]")
    if use_bgm and narr:
        parts.append(f"[{bgm_idx}:a]aresample={SR},volume={bgm_gain},"
                     f"afade=t=out:st={total - FADE_OUT - 0.2:.2f}:d={FADE_OUT},"
                     f"alimiter=limit=0.9[bg]")
        parts.append("[narr]asplit=2[nA][nB]")
        parts.append("[bg][nA]sidechaincompress=threshold=0.05:ratio=4:"
                     "attack=200:release=1200:makeup=1[duck]")
        parts.append("[duck][nB]amix=inputs=2:normalize=0,"
                     "alimiter=limit=0.95[out]")
    elif use_bgm:
        parts.append(f"[{bgm_idx}:a]aresample={SR},volume={bgm_gain},"
                     f"afade=t=out:st={total - FADE_OUT - 0.2:.2f}:d={FADE_OUT},"
                     f"alimiter=limit=0.95,apad=whole_dur={total:.3f}[out]")
    else:
        parts.append(f"anullsrc=r={SR}:cl=mono,atrim=0:{total:.3f}[out]")

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "0:v", "-map", "[out]", "-t", f"{total:.3f}",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
            "-movflags", "+faststart", str(dest)]

    print(f"混音：{len(narr)} 段旁白"
          f"{' + 配乐' if use_bgm else '（无配乐）'}，总长 {total:.2f}s")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-3000:])
        raise SystemExit("混音失败")

    # 校验音轨长度是否与画面一致（曾因 sidechain 提前截止而短 3 秒）
    probe = subprocess.run(
        [str(ff), "-v", "error", "-i", str(dest), "-map", "0:a",
         "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
        capture_output=True).stdout
    adur = len(probe) / 2 / SR
    flag = "OK" if abs(adur - total) < 0.15 else f"⚠ 差 {adur - total:+.2f}s"
    print(f"成片: {dest.name}  画面 {total:.2f}s / 音轨 {adur:.2f}s  {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
