#!/usr/bin/env python3
"""发布文案生成：从配置与成片信息自动产出抖音 / 小红书的标题、正文、话题、封面大字。

说明：脚本产出的是**结构化初稿**（事实与骨架都由数据驱动，不会写错诗名、朝代、
作者、时长、画风），措辞层面建议由模型再润色一遍（见 SKILL.md 的「文案」步骤）。

产物：<输出目录>/<题名>·发布文案.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import Paths, load_config, resolve_style, resolve_voice  # noqa: E402

THEME_HASHTAGS = {
    "孤高清冷": ["孤独", "清冷", "治愈"],
    "雄浑豪放": ["豪迈", "气势", "壮阔"],
    "清新田园": ["田园生活", "松弛感", "慢生活"],
    "婉约思念": ["思念", "温柔", "深夜emo"],
    "苍凉边塞": ["边塞", "大漠", "家国"],
    "明快节令": ["节气", "年味", "喜庆"],
}
DYNASTY_TAG = {"唐": "#唐诗", "宋": "#宋词", "元": "#元曲",
               "汉": "#汉乐府", "魏": "#建安文学", "晋": "#魏晋风骨"}

# 主题 → 文案里的「情绪核心词」（比四字主题更适合进标题）
THEME_KEYWORDS = {
    "孤高清冷": "孤独", "雄浑豪放": "豪迈", "清新田园": "松弛",
    "婉约思念": "思念", "苍凉边塞": "苍凉", "明快节令": "欢喜",
}


def keep(items: list[str | None]) -> list[str]:
    """保留空行（排版用），只过滤 None。"""
    return [x for x in items if x is not None]


def join_poem(lines: list[str]) -> str:
    """按绝句/律诗句读习惯加标点：奇数句后逗号、偶数句后句号。"""
    out = []
    for i, ln in enumerate(lines):
        out.append(ln + ("，" if i % 2 == 0 else "。"))
    return "".join(out)


def credit(dyn: str, author: str) -> str:
    return "·".join(x for x in [dyn, author] if x)


def build(cfg: dict, style: dict, voice: dict, meta: dict) -> str:
    p = cfg["poem"]
    lines = p["lines"]
    n = len(lines)
    nchars = sum(len(l) for l in lines)
    title = p["title"]
    author = p.get("author", "")
    dyn = p.get("dynasty", "")
    theme = p.get("theme", "")
    kw = (cfg.get("copy", {}).get("keyword")
          or THEME_KEYWORDS.get(theme, theme or title))
    by = credit(dyn, author)
    bio = p.get("author_bio", {})
    full = join_poem(lines)
    voice_style = cfg.get("copy", {}).get("account_voice", "素雅")
    plat = cfg.get("copy", {}).get("platforms", ["douyin", "xiaohongshu"])
    dur = meta.get("duration", 0)
    dur_s = f"{dur:.0f}秒" if dur else "短片"
    res = "×".join(str(x) for x in cfg["video"]["resolution"])
    bgm_name = {"guqin": "古琴", "guzheng": "筝", "xiao": "箫",
                "silence": "无配乐"}.get(cfg["bgm"].get("mood", ""), "配乐")
    emoji_on = voice_style == "活泼"
    flake = " ❄️" if emoji_on else ""

    # ---------- 标题候选 ----------
    titles = [
        f"{nchars}个字，写尽{kw}｜《{title}》{style['name']}",
        f"{lines[0]}，{lines[1]}——我把它画成了一部{style['name']}短片" if n > 1
        else f"{lines[0]}——我把它画成了一部{style['name']}短片",
        f"用{dur_s}，把《{title}》画给你看",
        f"{by}笔下的{kw}，全在「{lines[0]}」" if by else f"「{lines[0]}」里的{kw}",
        f"你有多久没有完整读完一首诗了？｜《{title}》",
        f"全网最{kw}的{nchars}个字，读一遍，静一遍",
    ]
    short_titles = [
        f"{lines[-1]}｜{title}",
        f"{nchars}个字，一场{kw}",
        f"{title}·{style['name']}版",
        "读一首诗的时间",
    ]
    poem_block = "\n".join(
        f"{lines[i]}，{lines[i + 1]}。" for i in range(0, n - 1, 2))
    if n % 2:
        poem_block += f"\n{lines[-1]}。"

    # ---------- 话题标签 ----------
    precise = [f"#{title}", "#古诗词", "#古诗"]
    if author:
        precise.append(f"#{author}")
    precise.append(DYNASTY_TAG.get(dyn, f"#{dyn}诗" if dyn else "#古诗词"))
    mood_tags = [f"#{t}" for t in THEME_HASHTAGS.get(theme, ["治愈", "国学"])]
    style_tags = [f"#{style['name']}", "#中国风", "#东方美学", "#以诗入画"]
    hot = ["#传统文化", "#诗词朗诵"]
    extra = [t if t.startswith("#") else f"#{t}"
             for t in cfg.get("copy", {}).get("extra_hashtags", [])]
    tags_all = precise[:4] + mood_tags[:2] + style_tags[:3] + hot[:2] + extra

    # ---------- 正文 ----------
    fact1 = bio.get("facts", [""])[0] if bio.get("facts") else ""
    body_long = "\n".join(keep([
        full,
        "",
        (f"{nchars}个字，{kw}，一个人。" if "孤" in kw
         else f"{nchars}个字，{kw}。"),
        "",
        f"{by}。{fact1}。" if (by and fact1) else
        (f"{by}。" if by else (fact1 + "。" if fact1 else "")),
        "",
        f"这一版把每句诗各画成一幅{style['name']}，逐句对上画面，"
        f"配{voice['name']}的朗诵与{bgm_name}，做成{dur_s}短片。"
        + ("片尾附全诗与作者生平。" if cfg["video"].get("title_credit", True) else ""),
        "",
        "听完整首，给自己留一点安静的时间。",
        "",
        f"你最喜欢哪一句？写下来，我看看谁的{kw}最深。",
    ]))
    body_short = "\n".join([
        full,
        f"——{by}《{title}》" if by else f"——《{title}》",
        "",
        f"{nchars}个字，{style['name']}。{dur_s}。",
        "你最喜欢哪一句？",
    ])

    # ---------- 封面大字 ----------
    covers = [
        (lines[-1] if lines else title, f"{nchars}个字，写尽{kw}"),
        (lines[0] if lines else title, f"{by}《{title}》{style['name']}"),
        (f"{nchars}字 · {kw}", f"全网最{kw}的一首诗"),
    ]

    out = []
    W = out.append

    W(f"# 发布文案 ·《{title}》{style['name']}影片{flake}")
    W("")
    W(f"> 素材：{style['name']}诗画短片 {dur_s}（{res}）｜{dyn}·{author}《{title}》"
      f"｜每句诗各配一幅画 · {voice['name']}朗诵 · {bgm_name}"
      + ("｜片尾全诗 + 作者生平" if cfg["video"].get("title_credit", True) else ""))
    W("")

    if "douyin" in plat:
        W("## 一、抖音")
        W("")
        W("### 标题候选（首行即标题，建议 15–25 字，太长会被折叠）")
        W("")
        W(f"**主推**\n> {titles[0]}")
        W("")
        W("**备选**")
        for i, t in enumerate(titles[1:], 1):
            W(f"{i}. {t}")
        W("")
        W("### 正文（可直接粘贴，前三行是黄金钩子）")
        W("")
        W("```")
        W(body_long)
        W("```")
        W("")
        W(f"**短版（适合配乐卡点或二次搬运）**{flake}")
        W("```")
        W(body_short)
        W("```")
        W("")
        W("### 话题标签")
        W("")
        W(f"`{'` `'.join(tags_all)}`")
        W("")
        W(f"> 建议总数 6–8 个，太多会稀释：3 个精准 + 2 个情绪 + 2–3 个风格/热词。")
        W("")
        W("### 封面大字")
        W("")
        W("| 方案 | 大字 | 小字 |")
        W("|---|---|---|")
        for k, (big, small) in zip("ABC", covers):
            W(f"| {k}{'（主推）' if k == 'A' else ''} | {big} | {small} |")
        W("")
        W(f"> 封面建议用片中「{lines[-1]}」那一帧作底图，"
          f"大字压在画面下三分之一处。")
        W("")
        W("### 发布小提示")
        W("")
        W(f"- **黄金 3 秒**：开头直接用「{lines[0]}」那句旁白 + 全屏画面，不要留白开场。")
        W(f"- **发布时间**：静品类内容，建议 21:00–23:00 或 06:30–08:00。")
        W(f"- **评论区置顶**：把「{lines[-1]}」单独发一条，问「这句你想到的是"
          f"{kw}，还是自由？」引导互动。")
        W(f"- **系列化**：下一首沿用同一套画风与配音，主页形成「以诗入画」合集。")
        if not emoji_on:
            W(f"- 若想更「抖音味」，可在正文首尾各加 1–2 个 emoji；本篇保持素雅风。")
        W("")

    if "xiaohongshu" in plat:
        W("## 二、小红书")
        W("")
        W("### 标题（≤20 字最佳，可用 1 个 emoji）")
        W("")
        W(f"**主推**\n> {short_titles[0]}")
        W("")
        W("**备选**")
        for i, t in enumerate(short_titles[1:], 1):
            W(f"{i}. {t}")
        W("")
        W("### 正文（笔记体，短句分行）")
        W("")
        W("```")
        W("\n".join(keep([
            poem_block,
            "",
            f"花了好几天，把《{title}》的每一句都画了出来。",
            "",
            f"🎨 {style['name']}｜每句一图，逐句对上",
            f"🎙 {voice['name']}朗诵｜{bgm_name}铺底",
            f"⏱ 全片 {dur_s}，片尾附全诗与{author}生平",
            "",
            "整首看完，像把心放进了一场雪里。",
            "",
            "你最喜欢哪一句？评论区告诉我 👇",
        ])))
        W("```")
        W("")
        W("### 话题（10 个以内）")
        W("")
        W(f"`{'` `'.join(tags_all[:10])}`")
        W("")
        W("### 笔记封面")
        W("")
        W(f"- 首图用「{covers[0][0]}」那一帧，左上角加小字「{covers[0][1]}」")
        W("- 第二张图放四句诗的四联画拼图，第三张放作者信息卡")
        W("")

    W("## 三、通用注意")
    W("")
    W("- 文案里的诗句、朝代、作者、时长均由配置生成，**不要手改**以免出错；"
      "措辞可按账号调性自由润色。")
    W("- 当前管线输出 16:9 横版；竖屏平台（抖音全屏/小红书）建议直接发横版，"
      "或后续用封面图补竖版首图。")
    W("- 背景音乐为程序合成的原创曲，无版权风险；旁白为 AI 合成音色。")
    W("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--duration", type=float, default=0.0,
                    help="成片时长（秒），留空则读 tmp/timeline.json")
    a = ap.parse_args()

    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    P = Paths(root)
    style = resolve_style(cfg)
    voice = resolve_voice(cfg)

    dur = a.duration
    if not dur and P.timeline.exists():
        dur = float(json.loads(P.timeline.read_text(encoding="utf-8"))["total"])

    out = P.out_dir(cfg) / f"{P.basename(cfg)}·发布文案.md"
    out.write_text(build(cfg, style, voice, {"duration": dur}),
                   encoding="utf-8")
    print(f"文案已生成: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
