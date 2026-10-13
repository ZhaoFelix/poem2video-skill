#!/usr/bin/env python3
"""画面渲染：逐帧亚像素运镜 + 柔和叠化转场 + 固定位置字幕叠加。

为什么不用 ffmpeg zoompan：
  zoompan 在输入像素空间做整数取整、再逐帧非整数重采样，叠加画面上任何高频
  纹理都会出现"沸腾/蠕动"。这里改用 PIL 仿射变换按浮点缩放系数精确映射
  （输出坐标 → 输入坐标），逐帧渲染后以 rawvideo 管道直接喂给编码器：
  帧时序严格均匀、运镜绝对平滑。

转场：相邻镜头在 FADE 秒窗口内交叉叠化，权重用 smoothstep（中点最慢、两端渐快）。
字幕：叠加层在输出空间固定位置合成，不随镜头缩放，独立淡入淡出。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import Paths, bootstrap_ffmpeg, load_config  # noqa: E402


def smooth(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)


def ease(u: float) -> float:
    """正弦缓入缓出，避免运镜起停生硬。"""
    return 0.5 - 0.5 * np.cos(np.pi * min(max(u, 0.0), 1.0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()

    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    P = Paths(root)
    P.ensure()
    ff = bootstrap_ffmpeg(root, verbose=False)

    W, H = cfg["video"]["resolution"]
    CARD_W = 2560                      # 卡片帧的基准宽度
    SCALE = W / CARD_W
    kenburns = bool(cfg["video"].get("kenburns", True))

    tl = json.loads(P.timeline.read_text(encoding="utf-8"))
    FPS = int(tl["fps"])
    DUR = float(tl["total"])
    FADE = float(tl["fade"])
    NFRAMES = int(round(DUR * FPS))
    SHOTS = [(s["name"], s["start"], s["end"], s["z0"] if kenburns else 1.0,
              s["z1"] if kenburns else 1.0) for s in tl["shots"]]

    # ---- 载入卡片帧（一次性高质量降采样到输出尺寸作为基准）----
    bases: dict[str, np.ndarray] = {}
    for name, *_ in SHOTS:
        p = P.frames / f"{name}.png"
        if not p.exists():
            raise SystemExit(f"缺少卡片帧 {p}，请先跑 compose_frames.py")
        bases[name] = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)

    # ---- 载入叠加层 ----
    # 注意尺度：acc 以 0-255 存储叠加层也必须预乘到 0-255，
    # 否则 rgb*al 的 0-1 值会把白色字幕压成近黑（这里曾出过隐形 bug）。
    overlays = []
    for ov in tl.get("overlays", []):
        im = Image.open(P.frames / ov["file"]).convert("RGBA")
        im = im.resize((round(im.width * SCALE), round(im.height * SCALE)),
                       Image.LANCZOS)
        arr = np.asarray(im, np.float32) / 255.0
        rgb, al = arr[..., :3], arr[..., 3:]
        overlays.append(dict(
            x=round(ov["x0"] * SCALE), y=round(ov["y0"] * SCALE),
            rgb=rgb * al * 255.0, coef=al[..., 0], at=ov["at"],
            rin=ov.get("rin", 1.0), out=ov.get("out"),
            rout=ov.get("rout", 1.0)))

    def render(base: Image.Image, z: float) -> np.ndarray:
        s = 1.0 / z
        ox = W / 2 - (W / 2) * s
        oy = H / 2 - (H / 2) * s
        img = base.transform(
            (W, H), Image.AFFINE, (s, 0, ox, 0, s, oy),
            resample=Image.BICUBIC, fillcolor=(0, 0, 0))
        return np.asarray(img, dtype=np.float32)

    P.tmp.mkdir(parents=True, exist_ok=True)
    cmd = [str(ff), "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-framerate", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", "17",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(P.silent)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    print(f"渲染 {W}x{H} @ {FPS}fps  {NFRAMES} 帧（{DUR:.2f}s）"
          f"  镜头 {len(SHOTS)}  叠加层 {len(overlays)}  运镜={'开' if kenburns else '关'}")

    for i in range(NFRAMES):
        t = i / FPS
        active = [s for s in SHOTS if s[1] <= t < s[2]]
        if not active:                       # 末帧兜底
            active = [SHOTS[-1]]
        acc = None
        for name, a0, b0, z0, z1 in active:
            u = (t - a0) / max(1e-6, b0 - a0)
            z = z0 + (z1 - z0) * ease(u)
            img = render(bases[name], z)
            if len(active) == 1:
                acc = img
            else:
                latest = max(active, key=lambda s: s[1])
                w = smooth((t - latest[1]) / FADE)
                if name != latest[0]:
                    w = 1.0 - w
                acc = img * w if acc is None else acc + img * w

        for ov in overlays:
            al = smooth((t - ov["at"]) / ov["rin"])
            if ov["out"] is not None:
                al *= smooth((ov["out"] - t) / ov["rout"])
            if al <= 0.002:
                continue
            x, y = ov["x"], ov["y"]
            h, wd = ov["coef"].shape
            region = acc[y:y + h, x:x + wd]
            f = al * ov["coef"][..., None]
            acc[y:y + h, x:x + wd] = region * (1 - f) + ov["rgb"] * f

        proc.stdin.write(np.clip(acc, 0, 255).astype(np.uint8).tobytes())
        if i % 250 == 0:
            print(f"  frame {i}/{NFRAMES}", flush=True)

    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise SystemExit("ffmpeg 编码失败")
    print("无声视频完成:", P.silent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
