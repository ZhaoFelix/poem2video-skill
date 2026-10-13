#!/usr/bin/env python3
"""帧合成（风格驱动）：把画作与文字排版成镜头卡与字幕叠加层。

产物（frames/）：
  title.png            片头卡（题名 + 朝代作者 + 体裁 + 印章）
  scene1..N.png        场景卡（画作 cover 铺满全帧 + 底部 smoothstep 压暗）
  ending.png           片尾一：全诗长卷底卡（诗句由叠加层逐句浮现）
  ending2.png          片尾二：作者信息卡（可选）
  sub1..N.png          场景字幕条（透明，横排诗句 + 「其N」朱印）
  line1..N.png         片尾逐句诗句条（透明）
  overlays.json        各叠加层在 2560x1440 画布中的坐标
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (Paths, load_config, make_font_fn,  # noqa: E402
                        resolve_style)

W, H = 2560, 1440
SUB_Y0 = 1040
SUB_H = 320
LINE_TOP = 610
LINE_BOTTOM = 1400
LINE_STRIP_H = 260
CN = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

STYLE: dict = {}
F = None                     # font(weight, size)
PAL: dict = {}


# ---------------------------------------------------------------- 基础图元
def cover(im: Image.Image, w=W, h=H) -> Image.Image:
    k = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def ghost_bg(im: Image.Image, veil=0.88, blur=12) -> Image.Image:
    bg = cover(im).filter(ImageFilter.GaussianBlur(blur))
    return Image.blend(bg, Image.new("RGB", (W, H), tuple(PAL["paper"])), veil)


def bottom_scrim(im: Image.Image) -> Image.Image:
    sc = STYLE["caption"]["scrim"]
    y0, amax = sc["y0"], sc["alpha"]
    col = np.array(sc["color"], np.float32)
    arr = np.asarray(im, np.float32)
    t = np.clip((np.arange(H, dtype=np.float32) - y0) / max(1, H - y0), 0, 1)
    t = t * t * (3 - 2 * t)
    a = (t * amax)[:, None, None]
    return Image.fromarray(np.clip(arr * (1 - a) + col * a, 0, 255).astype(np.uint8))


def draw_h(dr, text, cx, y, fnt, fill, spacing=0.0, shadow=None):
    adv = [dr.textlength(c, font=fnt) for c in text]
    sp = fnt.size * spacing
    total = sum(adv) + sp * (len(text) - 1)
    x = cx - total / 2
    for c, aw in zip(text, adv):
        if shadow:
            ox, oy = shadow["offset"]
            dr.text((x + ox, y + oy), c, font=fnt,
                    fill=tuple(shadow["color"]) + (int(255 * shadow["alpha"]),))
        dr.text((x, y), c, font=fnt, fill=fill)
        x += aw + sp
    return total


def draw_seal(dr, cx, y, text, size=84):
    pad = int(size * 0.24)
    fnt = F("regular", int(size * 0.7))
    adv = [dr.textlength(c, font=fnt) for c in text]
    tw = sum(adv) + int(size * 0.16) * (len(text) - 1)
    w, h = int(tw + pad * 2), int(size * 1.26)
    x0 = int(cx - w / 2)
    dr.rounded_rectangle([x0, y, x0 + w, y + h], radius=12,
                         fill=tuple(PAL["seal_fill"]))
    x, cy = x0 + pad, y + (h - int(size * 0.7)) // 2 - int(size * 0.06)
    for c, aw in zip(text, adv):
        dr.text((x, cy), c, font=fnt, fill=tuple(PAL["seal_text"]))
        x += aw + int(size * 0.16)


def fit_font(text, max_w, start, floor=58, spacing=0.14):
    """自动缩字号使 text 在 max_w 内放得下。"""
    size = start
    while size > floor:
        fnt = F("heavy", size)
        sp = size * spacing
        adv = [fnt.getlength(c) for c in text]
        if sum(adv) + sp * (len(text) - 1) <= max_w:
            return fnt, sp
        size -= 4
    return F("heavy", floor), floor * spacing


# ---------------------------------------------------------------- 载入画作
def painting_paths(P: Paths, n: int) -> list[Path]:
    def pick(d: Path):
        if not d.exists():
            return []
        exts = {".png", ".jpg", ".jpeg", ".webp"}
        files = sorted(p for p in d.iterdir()
                       if p.suffix.lower() in exts and not p.name.startswith("_"))
        # 优先按 01/02 前缀匹配
        hit = []
        for i in range(1, n + 1):
            pre = f"{i:02d}"
            m = [p for p in files if p.name.startswith(pre)]
            hit.append(m[0] if m else None)
        if all(hit):
            return hit
        return files[:n]

    got = pick(P.clean)
    if len(got) < n:
        got = pick(P.images)
    if len(got) < n:
        raise SystemExit(f"画作不足：需要 {n} 张，"
                         f"{P.clean} 与 {P.images} 中只找到 {len(got)} 张")
    return got


# ---------------------------------------------------------------- 各卡片
def make_title(lines, paintings):
    im = ghost_bg(Image.open(paintings[-1]), STYLE["card"]["veil"] - 0.04,
                  STYLE["card"]["blur"] - 3)
    dr = ImageDraw.Draw(im)
    title = _cfg["poem"]["title"]
    draw_h(dr, title, W / 2, 380, F("heavy", 390), tuple(PAL["ink"]), 0.22)
    dr.line([W / 2 - 320, 930, W / 2 + 320, 930],
            fill=tuple(PAL["faint"]), width=3)
    credit = " · ".join(x for x in [_cfg["poem"].get("dynasty", ""),
                                    _cfg["poem"].get("author", "")] if x)
    draw_h(dr, credit, W / 2, 985, F("light", 94), tuple(PAL["mid"]), 0.14)
    if _cfg["poem"].get("genre"):
        draw_h(dr, _cfg["poem"]["genre"], W / 2, 1150, F("light", 56),
               tuple(PAL["faint"]), 0.30)
    draw_seal(dr, W / 2, 1262, "诗画", size=84)
    im.save(P.frames / "title.png")


def make_scene(idx, paintings):
    im = bottom_scrim(cover(Image.open(paintings[idx - 1]).convert("RGB")))
    im.save(P.frames / f"scene{idx}.png")


def make_sub(idx, lines):
    verse = lines[idx - 1]
    im = Image.new("RGBA", (W, SUB_H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    cap = STYLE["caption"]
    sh = cap.get("shadow") if cap.get("shadow", {}).get("enable") else None

    numbering = _cfg["video"].get("scene_numbering", True)
    seal_w, gap = 0, 0
    if numbering:
        fnt_seal = F("regular", 46)
        label = f"其{CN[idx - 1]}" if idx <= len(CN) else str(idx)
        lw = sum(dr.textlength(c, font=fnt_seal) for c in label) + 12
        pw, ph = int(lw + 44), 84
        seal_w, gap = pw, 48

    max_w = W * 0.78 - seal_w - gap
    fnt, sp = fit_font(verse, max_w, 112)
    vw = sum(dr.textlength(c, font=fnt) for c in verse) + sp * (len(verse) - 1)
    total = seal_w + gap + vw
    x0 = (W - total) / 2

    if numbering:
        py = (SUB_H - 84) // 2
        dr.rounded_rectangle([x0, py, x0 + seal_w, py + 84], radius=10,
                             fill=tuple(PAL["seal_fill"]))
        label = f"其{CN[idx - 1]}" if idx <= len(CN) else str(idx)
        fnt_seal = F("regular", 46)
        x = x0 + 22
        for c in label:
            dr.text((x, py + 17), c, font=fnt_seal, fill=tuple(PAL["seal_text"]))
            x += dr.textlength(c, font=fnt_seal) + 12

    vy = (SUB_H - fnt.size) // 2 - int(fnt.size * 0.06)
    x = x0 + seal_w + gap
    for c in verse:
        if sh:
            ox, oy = sh["offset"]
            dr.text((x + ox, vy + oy), c, font=fnt,
                    fill=tuple(sh["color"]) + (int(255 * sh["alpha"]),))
        dr.text((x, vy), c, font=fnt, fill=tuple(cap["text"]))
        x += dr.textlength(c, font=fnt) + sp
    im.save(P.frames / f"sub{idx}.png")
    return dict(file=f"sub{idx}.png", x0=0, y0=SUB_Y0, w=W, h=SUB_H)


def make_ending(paintings):
    im = ghost_bg(Image.open(paintings[-1]), STYLE["card"]["veil"] + 0.02,
                  STYLE["card"]["blur"] + 2)
    dr = ImageDraw.Draw(im)
    draw_h(dr, _cfg["poem"]["title"], W / 2, 175, F("heavy", 150),
           tuple(PAL["ink"]), 0.20)
    credit = " · ".join(x for x in [_cfg["poem"].get("dynasty", ""),
                                    _cfg["poem"].get("author", "")] if x)
    draw_h(dr, credit, W / 2, 400, F("light", 64), tuple(PAL["mid"]), 0.16)
    draw_seal(dr, 1730, 200, "诗画", size=64)
    im.save(P.frames / "ending.png")


def make_ending_lines(lines):
    n = len(lines)
    avail = LINE_BOTTOM - LINE_TOP - LINE_STRIP_H
    gap = min(190, avail / max(1, n - 1)) if n > 1 else 0
    meta = []
    for i, verse in enumerate(lines):
        im = Image.new("RGBA", (W, LINE_STRIP_H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        fnt, sp = fit_font(verse, W * 0.62, 96)
        draw_h(dr, verse, W / 2, 60, fnt, tuple(PAL["ink"]) + (255,), 0.16)
        im.save(P.frames / f"line{i + 1}.png")
        cy = LINE_TOP + LINE_STRIP_H // 2 + i * gap
        meta.append(dict(file=f"line{i + 1}.png", x0=0,
                         y0=int(cy - LINE_STRIP_H // 2), w=W, h=LINE_STRIP_H))
    return meta


def make_ending2(paintings):
    bio = _cfg["poem"].get("author_bio", {})
    im = ghost_bg(Image.open(paintings[min(1, len(paintings) - 1)]),
                  STYLE["card"]["veil"] + 0.02, STYLE["card"]["blur"] + 2)
    dr = ImageDraw.Draw(im)
    name = bio.get("name") or _cfg["poem"].get("author", "")
    draw_h(dr, name, W / 2, 225, F("heavy", 170), tuple(PAL["ink"]), 0.24)
    head = "　·　".join(x for x in [bio.get("years", ""),
                                    bio.get("courtesy", ""),
                                    bio.get("hometown", "")] if x)
    if head:
        draw_h(dr, head, W / 2, 510, F("light", 64), tuple(PAL["mid"]), 0.05)
    dr.line([W / 2 - 440, 648, W / 2 + 440, 648], fill=tuple(PAL["faint"]), width=3)
    y = 710
    for t in bio.get("facts", [])[:4]:
        draw_h(dr, t, W / 2, y, F("light", 60), tuple(PAL["mid"]), 0.05)
        y += 112
    if bio.get("epigraph"):
        draw_h(dr, bio["epigraph"], W / 2, min(y + 60, 1190),
               F("light", 52), tuple(PAL["faint"]), 0.08)
    full = "，".join(_cfg["poem"]["lines"][:-1]) + "。" + _cfg["poem"]["lines"][-1] + "。"
    draw_h(dr, full, W / 2, 1290, F("regular", 56), tuple(PAL["ink"]), 0.04)
    draw_seal(dr, 2240, 1290, "诗画", size=64)
    im.save(P.frames / "ending2.png")


# ---------------------------------------------------------------- 主流程
_cfg: dict = {}
P: Paths = None


def main() -> int:
    global STYLE, F, PAL, _cfg, P
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()

    _cfg = load_config(a.config)
    STYLE = resolve_style(_cfg)
    F = make_font_fn(STYLE)
    PAL = STYLE["palette"]
    P = Paths(_cfg["_root"])
    P.ensure()

    lines: list[str] = _cfg["poem"]["lines"]
    n = len(lines)
    paintings = painting_paths(P, n)
    print(f"风格: {STYLE['name']}（{STYLE['id']}）  诗句 {n} 句")
    print("画作:", ", ".join(p.name for p in paintings))

    for f in P.frames.glob("*.png"):
        f.unlink()

    make_title(lines, paintings)
    for i in range(1, n + 1):
        make_scene(i, paintings)
    make_ending(paintings)

    meta = []
    if _cfg["video"].get("caption") == "horizontal":
        meta += [make_sub(i, lines) for i in range(1, n + 1)]
    meta += make_ending_lines(lines)
    if _cfg["video"].get("title_credit", True):
        make_ending2(paintings)

    (P.frames / "overlays.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"帧合成完成：{len(list(P.frames.glob('*.png')))} 张卡片，"
          f"{len(meta)} 个叠加层")
    return 0


if __name__ == "__main__":
    sys.exit(main())
