#!/usr/bin/env python3
"""去水印（通用）：自动识别画作四角的浅色水印并做图像修复。

生图模型常在右下角压 "AI生成 / 品牌名" 一类浅色文字水印。本脚本：
  1. 在四角 ROI 内找「高亮度 + 低彩度」像素（水印文字特征），形态学膨胀覆盖抗锯齿边缘；
  2. 掩膜覆盖率落在合理区间即用 OpenCV TELEA 修复，否则判为无水印并跳过；
  3. 无 OpenCV 时退化为「局部模糊 + 掩膜合成」，效果略弱但不中断流程。

用法：
  python3 remove_watermark.py --root <项目目录> [--corner br|bl|tr|tl|all] [--region x0,y0,x1,y1]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

SRC_EXT = {".png", ".jpg", ".jpeg", ".webp"}

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def corner_roi(w: int, h: int, corner: str, fx=0.16, fy=0.11):
    """四角 ROI（相对比例）。水印文字块极小，通常贴在 <15% 宽 × <10% 高的角落。
    ROI 收得紧是为了避免把雪点、纸纹等画面亮部误判成水印。"""
    rw, rh = int(w * fx), int(h * fy)
    return {
        "br": (w - rw, h - rh, w, h),
        "bl": (0, h - rh, rw, h),
        "tr": (w - rw, 0, w, rh),
        "tl": (0, 0, rw, rh),
    }[corner]


def detect_mask(arr: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    """在 ROI 内检测浅色低彩度的**文字块** → 返回整图 uint8 掩膜。

    为什么不能直接阈值亮度：水墨画的宣纸底本身就近乎纯白（实测中位亮度 225），
    白字水印压在白纸上，全局阈值会把整片纸纹都选进来。
    改用**局部对比**：像素 > 局部中位数 + 6 才算候选（水印字比纸亮一截），
    再「先聚簇、后验证」过滤两类误判：
      · 散点（雪点/纸纹高光）——聚簇后密度极低（<6%），剔除；
      · 大片亮区——聚簇块面积超过画面 3%，剔除。
    """
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = roi
    gray = arr.max(axis=2)                       # 最亮通道，白字最突出
    chroma = arr.max(axis=2).astype(np.int16) - arr.min(axis=2)
    k = max(3, min(51, (min(y1 - y0, x1 - x0) // 2) * 2 - 1))
    med = cv2.medianBlur(gray, k) if HAS_CV2 else np.asarray(
        Image.fromarray(gray).filter(ImageFilter.MedianFilter(min(k, 9))))

    cand = ((gray.astype(np.int16) > med.astype(np.int16) + 6) &
            (chroma <= 26)).astype(np.uint8) * 255
    raw = np.zeros_like(cand)
    raw[y0:y1, x0:x1] = cand[y0:y1, x0:x1]

    if HAS_CV2 and raw.any():
        big = cv2.dilate(raw, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (31, 31)))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(big, connectivity=8)
        keep = np.zeros_like(raw)
        for i in range(1, n):
            bx, by, bw, bh, _ = stats[i]
            if bw * bh > 0.03 * w * h:          # 太铺开 → 是画面亮区，不是水印
                continue
            box = raw[by:by + bh, bx:bx + bw]
            density = float((box > 0).mean())
            if not (0.06 <= density <= 0.65):   # 太疏=散点；太密=整片亮区
                continue
            keep[by:by + bh, bx:bx + bw] = box
        m = cv2.dilate(keep, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (7, 7)))
    else:
        m = np.asarray(
            Image.fromarray(raw).filter(ImageFilter.MaxFilter(7)), np.uint8)

    return m


def inpaint(arr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if HAS_CV2:
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        out = cv2.inpaint(bgr, mask, 6, cv2.INPAINT_TELEA)
        return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    # 退化方案：局部模糊后按掩膜合成
    base = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(7))
    b = np.asarray(base, np.float32)
    a = (mask.astype(np.float32) / 255.0)[..., None]
    return np.clip(arr.astype(np.float32) * (1 - a) + b * a, 0, 255).astype(np.uint8)


def clean_one(path: Path, dst: Path, corners: list[str],
              region: tuple[int, int, int, int] | None) -> tuple[bool, float]:
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im)
    h, w = arr.shape[:2]

    if region:
        mask = np.zeros((h, w), np.uint8)
        x0, y0, x1, y1 = region
        mask[y0:y1, x0:x1] = 255
        cov = 1.0
    else:
        mask = np.zeros((h, w), np.uint8)
        for c in corners:
            mask = np.maximum(mask, detect_mask(arr, corner_roi(w, h, c)))
        cov = float((mask > 0).sum()) / mask.size

    # 覆盖率过低=没检测到；过高=阈值把画面亮部也吃了，都不动手
    if cov < 0.0004:
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst)
        return False, cov
    if cov > 0.03:
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst)
        return False, cov

    out = inpaint(arr, mask)
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out).save(dst)

    # 存一张右下角对比图便于人工确认
    if not region:
        x0, y0, x1, y1 = corner_roi(w, h, "br")
        cy0, cy1 = max(0, y0 - int(h * 0.06)), y1
        cx0 = max(0, x0 - int(w * 0.08))
        a = arr[cy0:cy1, cx0:x1]
        b = out[cy0:cy1, cx0:x1]
        sep = np.full((a.shape[0], 6, 3), 255, np.uint8)
        Image.fromarray(np.hstack([a, sep, b])).save(
            dst.parent / f"_check_{dst.name}")
    return True, cov


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="", help="项目目录（含 images/）")
    ap.add_argument("--config", default="", help="也可直接传 poem.json，自动取项目目录")
    ap.add_argument("--src", default="images", help="源目录名，默认 images")
    ap.add_argument("--dst", default="clean", help="输出目录名，默认 clean")
    ap.add_argument("--corner", default="br",
                    help="br|bl|tr|tl|all，默认 br；all=四角都查")
    ap.add_argument("--region", default="",
                    help="手动指定区域 x0,y0,x1,y1（像素），指定后不自动检测")
    a = ap.parse_args()

    if not a.root and a.config:
        import json
        a.root = str(Path(a.config).expanduser().resolve().parent)
    if not a.root:
        raise SystemExit("需指定 --root 或 --config")
    root = Path(a.root).expanduser().resolve()
    src = root / a.src
    dst = root / a.dst
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in SRC_EXT)
    if not files:
        raise SystemExit(f"{src} 里没有图片")

    corners = ["br", "bl", "tr", "tl"] if a.corner == "all" else [a.corner]
    region = tuple(int(v) for v in a.region.split(",")) if a.region else None

    print(f"去水印：{'OpenCV TELEA' if HAS_CV2 else '模糊合成(退化)'}"
          f"  角落={corners}  共 {len(files)} 张")
    for p in files:
        done, cov = clean_one(p, dst / p.name, corners, region)
        flag = "已修复" if done else ("未检出" if cov < 0.0004 else "跳过(掩膜过大)")
        print(f"  {p.name:<34} {flag:<14} 掩膜占比 {cov*100:.3f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
