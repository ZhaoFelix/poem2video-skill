#!/usr/bin/env python3
"""poem2video 主编排：一条命令跑通「古诗 → 诗画影片 + 发布文案」。

阶段（--stage）：
  prompts   生成 images/prompts.md —— 每句诗一条生图提示词（交给 ImageGen）
  clean     去水印：images/ → clean/
  tts       用 MiMo-TTS 按配置音色合成旁白 → audio/mimo/
  frames    帧合成（风格驱动）→ frames/
  timeline  时间轴（按旁白实际时长反推）→ tmp/timeline.json
  render    逐帧渲染无声视频 → tmp/video_silent.mp4
  bgm       合成配乐 → audio/bgm.wav
  mux       混音合成成片 → <输出目录>/
  copy      生成抖音/小红书文案 → <输出目录>/
  check     成片质检（帧时序 / 平滑度 / 频谱 / 音画同步）
  build     一键 = clean → frames → timeline → render → bgm → mux → copy
  all       build + check

用法：
  python3 poem2video.py --config poem.json --stage prompts
  python3 poem2video.py --config poem.json --stage build
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (Paths, load_config, resolve_style,  # noqa: E402
                        resolve_voice)

HERE = Path(__file__).resolve().parent
PY = sys.executable

STAGE_SCRIPTS = {
    "clean": ["remove_watermark.py"],
    "tts": ["tts_mimo.py"],
    "frames": ["compose_frames.py"],
    "timeline": ["make_timeline.py"],
    "render": ["render_video.py"],
    "bgm": ["bgm_synth.py"],
    "mux": ["mux_audio.py"],
    "copy": ["make_copy.py"],
    "check": ["check_quality.py"],
}
ORDER = ["clean", "tts", "frames", "timeline", "render", "bgm", "mux", "copy"]
BUILD = ["clean", "frames", "timeline", "render", "bgm", "mux", "copy"]


def write_prompts(cfg: dict, P: Paths) -> None:
    """生成逐句生图提示词清单（含文件名约定），供 ImageGen 使用。"""
    style = resolve_style(cfg)
    poem = cfg["poem"]
    imagery = poem.get("line_imagery", {}) or {}
    lines = poem["lines"]
    P.images.mkdir(parents=True, exist_ok=True)
    md = [f"# 《{poem['title']}》逐句生图提示词 · {style['name']}",
          "",
          f"- 风格 ID：`{style['id']}`（{style['name']}）：{style['desc']}",
          f"- 建议尺寸：`{style['size']}`　画幅：{style['aspect']}",
          f"- 输出目录：`{P.images}`　命名：`NN-<诗句>.png`（NN 从 01 起，两位数字）",
          f"- 共 {len(lines)} 条，**每条单独调用一次生图**（不要一次生成四格拼图）。",
          ""]
    for i, line in enumerate(lines, 1):
        img = imagery.get(line, "")
        prompt = (f"{style['image_prefix']}主题：{line}。"
                  + (f"画面内容：{img}。" if img else "")
                  + style["image_suffix"])
        md += [f"## {i:02d}　{line}", "", "```", prompt, "```",
               f"→ 保存为 `{i:02d}-{line}.png`", ""]
    md += ["## 生成后", "",
           "1. 检查每张图是否与诗句对应、构图饱满（主体大致居中，便于 16:9 居中裁切）；",
           "2. 若某张不满意，单独重生成该张即可；",
           "3. 接着运行 `--stage clean` 去掉右下角水印。", ""]
    out = P.images / "prompts.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"生图提示词已写入 {out}（{len(lines)} 条）")
    for i, line in enumerate(lines, 1):
        print(f"  {i:02d} {line}")


def run_stage(stage: str, cfg_path: str, extra: list[str]) -> None:
    for script in STAGE_SCRIPTS[stage]:
        cmd = [PY, str(HERE / script), "--config", cfg_path] + extra
        print(f"\n▶ {stage}: {script}")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise SystemExit(f"阶段 {stage} 失败（{script}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--stage", default="build",
                    help="prompts|clean|tts|frames|timeline|render|bgm|mux|copy|check"
                         "|build|all")
    ap.add_argument("--voice", default="", help="临时覆盖音色（仅 tts 阶段）")
    a = ap.parse_args()

    cfg = load_config(a.config)
    P = Paths(cfg["_root"])
    P.ensure()
    style = resolve_style(cfg)
    voice = resolve_voice(cfg)

    print("=" * 66)
    print(f"poem2video ·《{cfg['poem']['title']}》  "
          f"{cfg['poem'].get('dynasty', '')}·{cfg['poem'].get('author', '')}")
    print(f"风格 {style['name']}（{style['id']}） | 音色 {voice['name']}"
          f" | 诗句 {len(cfg['poem']['lines'])} 句"
          f" | {cfg['video']['resolution'][0]}x{cfg['video']['resolution'][1]}"
          f"@{cfg['video']['fps']}fps")
    print(f"工作目录 {P.root}")
    print("=" * 66)

    if a.stage == "prompts":
        write_prompts(cfg, P)
        return 0

    stages = {"build": BUILD, "all": BUILD + ["check"]}.get(a.stage,
                                                            [a.stage])
    for s in stages:
        if s not in STAGE_SCRIPTS:
            raise SystemExit(f"未知阶段 {s}")
        extra = ["--voice", a.voice] if (s == "tts" and a.voice) else []
        run_stage(s, a.config, extra)

    print("\n" + "=" * 66)
    if a.stage in ("build", "all"):
        print(f"成片: {P.video_path(cfg)}")
        if cfg["copy"].get("enabled", True):
            print(f"文案: {P.out_dir(cfg) / (P.basename(cfg) + '·发布文案.md')}")
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
