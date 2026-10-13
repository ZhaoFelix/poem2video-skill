#!/usr/bin/env python3
"""poem2video 公共库：配置加载、风格/音色解析、ffmpeg 定位、字体、时长度量。

所有子脚本都从这里取路径与配置，保证单一事实来源。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS = SKILL_ROOT / "assets"

# ---------------------------------------------------------------- 字体族
# (字体文件, {heavy,regular,light} 字面 index)；按顺序取第一个存在的
FONT_FAMILIES: dict[str, list[tuple[str, dict[str, int]]]] = {
    "songti": [("/System/Library/Fonts/Supplemental/Songti.ttc",
                {"heavy": 0, "regular": 6, "light": 3})],
    "hiragino": [("/System/Library/Fonts/Hiragino Sans GB.ttc",
                  {"heavy": 2, "regular": 2, "light": 0})],
    "heiti": [("/System/Library/Fonts/STHeiti Light.ttc",
               {"heavy": 0, "regular": 0, "light": 0})],
}
FONT_FALLBACK = ["songti", "hiragino", "heiti"]

# ---------------------------------------------------------------- 默认配置
DEFAULTS = {
    "style": "ink",
    "voice": "baihua",
    "narration": {"enabled": True, "model": "mimo-v2.5-tts",
                  "repeat_full_poem": True, "voice_design_prompt": ""},
    "video": {"resolution": [1920, 1080], "fps": 25, "fade": 1.6,
              "kenburns": True, "scene_numbering": True,
              "caption": "horizontal", "title_credit": True},
    "bgm": {"enabled": True, "mood": "guqin", "gain": 0.30},
    "copy": {"enabled": True, "platforms": ["douyin", "xiaohongshu"],
             "account_voice": "素雅", "extra_hashtags": []},
    "output": {"dir": "poem2video_out", "basename": "", "video_filename": ""},
}


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"配置文件不存在: {p}\n可复制 {ASSETS / 'config.example.json'} 修改")
    raw = json.loads(p.read_text(encoding="utf-8"))
    cfg = deep_merge(DEFAULTS, raw)
    poison = cfg.setdefault("poem", {})
    if not poison.get("lines"):
        raise SystemExit("配置缺少 poem.lines（诗句数组）")
    cfg["_config_path"] = str(p)
    cfg["_root"] = str(p.parent)
    return cfg


def load_styles() -> dict:
    return json.loads((ASSETS / "styles.json").read_text(encoding="utf-8"))


def load_voices() -> dict:
    return json.loads((ASSETS / "voices.json").read_text(encoding="utf-8"))


def resolve_style(cfg: dict) -> dict:
    lib = load_styles()
    key = cfg.get("style", "ink")
    if key not in lib or key.startswith("_"):
        raise SystemExit(f"未知风格 '{key}'，可选: "
                         + ", ".join(k for k in lib if not k.startswith("_")))
    st = dict(lib[key])
    st["id"] = key
    return st


def resolve_voice(cfg: dict) -> dict:
    lib = load_voices()
    key = cfg.get("voice", "baihua")
    presets = lib["presets"]
    if key not in presets:
        raise SystemExit(f"未知音色 '{key}'，可选: " + ", ".join(presets))
    v = dict(presets[key])
    v["id"] = key
    v["_director"] = lib["director"]
    return v


def director_prompt(cfg: dict, scene: str, extra: str = "") -> str:
    """按 poem.theme 组装导演指令（【角色】【场景】【指导】三段式）。"""
    lib = load_voices()
    d = lib["director"]
    mood = cfg["poem"].get("theme", "")
    spec = d["by_mood"].get(mood)
    role = (spec or {}).get("role", d["default_role"])
    direc = (spec or {}).get("direction", d["default_direction"])
    title = cfg["poem"]["title"]
    auth = cfg["poem"].get("author", "")
    sc = f"正在录制《{title}》（{auth}）的诗画影片旁白。{scene}"
    if extra:
        direc = direc + extra
    return d["template"].format(role=role, scene=sc, direction=direc)


# ---------------------------------------------------------------- ffmpeg
def _ffmpeg_ok(p: Path) -> bool:
    """真 ffmpeg 检查：必须能列出编码器且含 libx264（环境里的 PIL 包装脚本会失败）。"""
    try:
        r = subprocess.run([str(p), "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and "libx264" in r.stdout
    except Exception:
        return False


def bootstrap_ffmpeg(root: Path, verbose: bool = True) -> Path:
    """按 项目 bin/ → imageio-ffmpeg → 系统 的顺序找一个可用的真 ffmpeg，并落地到 <root>/bin/ffmpeg。"""
    root = Path(root).expanduser().resolve()
    local = root / "bin" / "ffmpeg"
    if local.exists() and _ffmpeg_ok(local):
        return local

    cands: list[Path] = []
    try:
        import imageio_ffmpeg  # type: ignore
        cands.append(Path(imageio_ffmpeg.get_ffmpeg_exe()))
    except Exception:
        pass
    w = shutil.which("ffmpeg")
    if w:
        cands.append(Path(w))
    cands += [Path("/opt/homebrew/bin/ffmpeg"), Path("/usr/local/bin/ffmpeg")]

    for c in cands:
        if c.exists() and _ffmpeg_ok(c):
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(c, local)
            os.chmod(local, 0o755)
            if verbose:
                print(f"[ffmpeg] 使用 {c} → {local}")
            return local
    raise SystemExit(
        "找不到可用的 ffmpeg（含 libx264）。请先安装：\n"
        "  <py> -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple imageio-ffmpeg"
    )


# ---------------------------------------------------------------- 字体
def font_file(family: str) -> tuple[str, dict[str, int]]:
    for fam in [family] + [f for f in FONT_FALLBACK if f != family]:
        for path, idx in FONT_FAMILIES.get(fam, []):
            if Path(path).exists():
                return path, idx
    raise SystemExit("找不到任何中文字体（Songti/Hiragino/STHeiti）")


def make_font_fn(style: dict):
    """返回 font(weight, size) 闭包，weight ∈ {heavy, regular, light}。"""
    from PIL import ImageFont
    path, idx = font_file(style.get("font", {}).get("family", "songti"))
    fdef = style.get("font", {})

    def f(weight: str, size: int):
        i = fdef.get(weight, idx.get(weight, 0))
        try:
            return ImageFont.truetype(path, size, index=i)
        except Exception:
            return ImageFont.truetype(path, size, index=0)
    return f


# ---------------------------------------------------------------- 项目路径
class Paths:
    """poem2video 工作目录布局。

    <root>/
      poem.json               配置文件
      images/                 ImageGen 原始输出（可能带水印）
      clean/                  去水印后的画作
      audio/mimo/             原始旁白 wav
      audio/mimo/prep/        裁掉首尾静音后的旁白
      audio/bgm.wav           配乐
      frames/                 卡片帧 + 叠加层 + overlays.json
      tmp/                    timeline.json、无声视频
      bin/ffmpeg              本地 ffmpeg
      输出: <dir>/<basename>·诗画影片.mp4、文案 md
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.images = self.root / "images"
        self.clean = self.root / "clean"
        self.audio = self.root / "audio"
        self.mimo = self.audio / "mimo"
        self.prep = self.mimo / "prep"
        self.frames = self.root / "frames"
        self.tmp = self.root / "tmp"
        self.bin = self.root / "bin"
        self.ffmpeg = self.bin / "ffmpeg"

    @property
    def timeline(self) -> Path:
        return self.tmp / "timeline.json"

    @property
    def overlays(self) -> Path:
        return self.frames / "overlays.json"

    @property
    def bgm(self) -> Path:
        return self.audio / "bgm.wav"

    @property
    def silent(self) -> Path:
        return self.tmp / "video_silent.mp4"

    def out_dir(self, cfg: dict) -> Path:
        d = self.root / cfg["output"].get("dir", "poem2video_out")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def video_path(self, cfg: dict) -> Path:
        name = cfg["output"].get("video_filename") or \
            f"{self.basename(cfg)}·诗画影片.mp4"
        return self.out_dir(cfg) / name

    @staticmethod
    def basename(cfg: dict) -> str:
        return cfg["output"].get("basename") or cfg["poem"]["title"]

    def ensure(self) -> None:
        for d in (self.images, self.clean, self.audio, self.mimo, self.prep,
                  self.frames, self.tmp, self.bin):
            d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 工具
def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-3000:] + "\n")
        raise SystemExit(f"命令失败: {' '.join(str(c) for c in cmd[:6])} ...")
    return r


def duration(ff: Path, p: Path) -> float:
    s = subprocess.run([str(ff), "-hide_banner", "-i", str(p)],
                       capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", s)
    if not m:
        raise SystemExit(f"无法读取时长: {p}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def ensure_py_deps(pkgs: tuple[str, ...] = ("PIL", "numpy", "requests")) -> None:
    missing = []
    for m in pkgs:
        try:
            __import__(m)
        except ImportError:
            missing.append({"PIL": "pillow", "numpy": "numpy",
                            "requests": "requests"}.get(m, m))
    if missing:
        raise SystemExit(
            "缺少 Python 依赖: " + ", ".join(missing) +
            "\n请安装: <py> -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "
            + " ".join(missing))
