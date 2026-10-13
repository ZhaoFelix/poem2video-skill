#!/usr/bin/env python3
"""旁白生成：调用小米 MiMo-V2.5-TTS，按配置的音色与导演指令合成全部旁白。

接口（OpenAI 兼容）：
  POST https://api.xiaomimimo.com/v1/chat/completions
  messages: role=user 放风格/导演指令（可空）；role=assistant 放待朗读文本
  audio:    {"format": "wav", "voice": "<音色名>"}
鉴权：环境变量 MIMO_API_KEY，或 ~/.workbuddy/mimo_api_key（权限 600）

用法：
  python3 tts_mimo.py --config poem.json [--voice moli] [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (Paths, bootstrap_ffmpeg, director_prompt,  # noqa: E402
                        load_config, resolve_voice)

URL = "https://api.xiaomimimo.com/v1/chat/completions"

# 主题 → 逐句情绪标签（未在 config.narration.tone_tags 指定时的兜底）
AUTO_TAGS = {
    "孤高清冷": ["深沉 苍老", "苍凉 深沉", "沉稳 磁性", "孤高 深沉"],
    "雄浑豪放": ["雄浑 有力", "磅礴 浑厚", "高亢 沉稳", "豪迈 深沉"],
    "清新田园": ["清朗 温柔", "轻快 明亮", "从容 清亮", "恬淡 清雅"],
    "婉约思念": ["温柔 怅然", "轻缓 空灵", "气声 温柔", "怅然 空灵"],
    "苍凉边塞": ["苍凉 沙哑", "沉郁 厚重", "顿挫 粗粝", "悲壮 深沉"],
    "明快节令": ["喜悦 明亮", "轻快 活泼", "欢欣 清亮", "热烈 明快"],
}
DEFAULT_TAGS = ["深沉 苍老", "苍凉 深沉", "沉稳 磁性", "孤高 深沉"]

# 每句的演绎提示（放进导演模式的【场景】段）
LINE_SCENES = [
    "画面对应第一句，气息放空，像对着茫茫天地自语。",
    "画面对应第二句，语气更空、更冷，尾音轻轻收住。",
    "画面对应第三句，稍许停顿后再说，带一丝注视感。",
    "这是全诗落点，关键处略作沉吟，末三字放慢、气声收束，如叹息般落下。",
]


def get_key() -> str:
    k = os.environ.get("MIMO_API_KEY", "").strip()
    if k:
        return k
    p = Path.home() / ".workbuddy" / "mimo_api_key"
    if p.exists():
        return p.read_text().strip()
    raise SystemExit("缺少 API Key：设置环境变量 MIMO_API_KEY 或写入 "
                     "~/.workbuddy/mimo_api_key")


def build_segments(cfg: dict) -> list[tuple[str, str, str]]:
    """返回 [(名称, 导演指令/风格描述, 待朗读文本), ...]"""
    poem = cfg["poem"]
    lines: list[str] = poem["lines"]
    nar = cfg["narration"]
    model = nar.get("model", "mimo-v2.5-tts")
    tags = nar.get("tone_tags") or {}
    auto = AUTO_TAGS.get(poem.get("theme", ""), DEFAULT_TAGS)

    # 片头报题
    open_text = (nar.get("open") or "").strip() or \
        f"{poem['title']}。{poem.get('dynasty', '')}，{poem.get('author', '')}。"
    open_style = director_prompt(
        cfg, "这是影片开篇的报题，请像题写卷首一样庄重，一字一顿。")
    segs = [("open", open_style, f"({auto[0]}){open_text}")]

    # 四句（或 N 句）诗
    for i, line in enumerate(lines):
        tag = (tags.get(line) or "").strip() or auto[min(i, len(auto) - 1)]
        scene = LINE_SCENES[i] if i < len(LINE_SCENES) else \
            f"画面对应第 {i + 1} 句。"
        segs.append((f"s{i + 1}", director_prompt(cfg, scene), f"({tag}){line}。"))

    # 片尾作者介绍
    bio = poem.get("author_bio", {})
    au_text = (nar.get("author") or "").strip()
    if not au_text:
        name = bio.get("name") or poem.get("author", "")
        head = f"{name}，{bio.get('courtesy', '')}，"
        head += "，".join(bio.get("facts", [])[:1]) + "。"
        body = "这首诗，写于他被贬的岁月。" if bio.get("facts") else ""
        au_text = head + body
    au_style = director_prompt(
        cfg, "这是片尾的作者介绍，转为平实而温厚的讲述口吻，仍要保持沉静舒缓，娓娓道来。")
    segs.append(("author", au_style, au_text))
    _ = model
    return segs


def synth(key: str, model: str, voice: str, style: str, text: str,
          dst: Path, design_prompt: str = "") -> None:
    import requests
    if model.endswith("voicedesign"):
        user = design_prompt or style
        body = {"model": model,
                "messages": [{"role": "user", "content": user},
                             {"role": "assistant", "content": text}],
                "audio": {"format": "wav", "optimize_text_preview": False}}
    else:
        body = {"model": model,
                "messages": [{"role": "user", "content": style},
                             {"role": "assistant", "content": text}],
                "audio": {"format": "wav", "voice": voice}}
    r = requests.post(URL, headers={"Authorization": f"Bearer {key}",
                                    "Content-Type": "application/json"},
                      json=body, timeout=300)
    if r.status_code != 200:
        raise SystemExit(f"接口返回 {r.status_code}: {r.text[:600]}")
    try:
        b64 = r.json()["choices"][0]["message"]["audio"]["data"]
    except (KeyError, IndexError, TypeError):
        raise SystemExit(f"响应结构异常: {json.dumps(r.json())[:600]}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(base64.b64decode(b64))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--voice", default="", help="覆盖配置中的音色 key")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要合成的文本")
    a = ap.parse_args()

    cfg = load_config(a.config)
    if a.voice:
        cfg["voice"] = a.voice
    root = Path(cfg["_root"])
    P = Paths(root)
    P.ensure()
    v = resolve_voice(cfg)
    nar = cfg["narration"]
    model = nar.get("model", "mimo-v2.5-tts")
    design = nar.get("voice_design_prompt", "")
    segs = build_segments(cfg)

    print(f"音色: {v['name']}（{v['lang']}/{v['gender']}·{v['tone']}）"
          f"  模型: {model}  段落: {len(segs)}")
    if a.dry_run:
        for name, style, text in segs:
            print(f"\n--- {name} ---\n指令: {style}\n文本: {text}")
        return 0

    key = get_key()
    ff = bootstrap_ffmpeg(root, verbose=False)
    for name, style, text in segs:
        dst = P.mimo / f"{name}.wav"
        synth(key, model, v["voice_id"], style, text, dst, design)
        info = subprocess.run([str(ff), "-hide_banner", "-i", str(dst)],
                              capture_output=True, text=True).stderr
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
        secs = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                if m else -1)
        print(f"  {name:<7} {dst.stat().st_size/1024:8.1f} KB  {secs:6.2f}s")
    print("旁白生成完成 →", P.mimo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
