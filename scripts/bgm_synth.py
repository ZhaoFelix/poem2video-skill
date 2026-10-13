#!/usr/bin/env python3
"""配乐合成：程序化生成不喧宾夺主的氛围民乐，长度自动跟随影片。

三种音色（config.bgm.mood）：
  guqin   古琴——Karplus-Strong 拨弦、A 羽调五声、低沉悠远，配清冷孤寂的诗
  guzheng 筝  ——羽/宫调、更明亮的拨弦与稍密的音型，配明快舒展的诗
  xiao    箫  ——正弦加气声与颤音、长音绵延，配婉约思念的诗
  silence     静音（仅靠旁白）

无杂音是硬指标：不使用任何宽带白噪声铺底，滑音改为正确的非整数采样位置
重采样（历史上这里写错过坐标系，产生过宽带混叠噪声），末端整体限带。

产物：audio/bgm.wav
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import Paths, load_config  # noqa: E402

FS = 44100
RNG = np.random.default_rng(42)

# ---------------------------------------------------------------- 基础工具
def one_pole_lp(x, alpha):
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha * (x[i] - acc)
        y[i] = acc
    return y


def fft_band(x, lo=None, hi=None, order=4):
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / FS)
    g = np.ones_like(fr)
    if hi:
        g *= 1.0 / (1.0 + (fr / hi) ** (2 * order))
    if lo:
        g *= 1.0 - 1.0 / (1.0 + (fr / lo) ** (2 * order))
    return np.fft.irfft(X * g, len(x))


def pluck(f, dur, damp=0.9962, glide=0.0, bright=0.22):
    """Karplus-Strong 拨弦。bright 越小音色越暗。"""
    n = int(dur * FS)
    N = max(2, int(round(FS / f)))
    buf = one_pole_lp(RNG.standard_normal(N), bright)
    buf = fft_band(buf, hi=3000.0)
    buf -= buf.mean()
    out = np.empty(n)
    idx = 0
    for i in range(n):
        j = idx % N
        out[i] = buf[j]
        buf[j] = damp * 0.5 * (buf[j] + buf[(j + 1) % N])
        idx += 1
    env = np.ones(n)
    atk = min(int(FS * 0.012), n)
    env[:atk] = np.linspace(0, 1, atk)
    rel = int(FS * 0.25)
    env[-rel:] *= np.linspace(1, 0, rel)
    out *= env
    if glide > 0:
        # 频率倍率随时间的累积 → 非整数采样位置 → 线性插值（无 period 回绕）
        u = np.arange(n) / n
        ratio = 1.0 - glide * np.exp(-u * 18.0)
        pos = np.clip(np.cumsum(ratio), 0, n - 2)
        out = np.interp(pos, np.arange(n), out)
    return out


def flute(f, dur, breath=0.06, vib=5.0, vib_depth=0.004):
    """箫/笛：正弦 + 缓慢颤音 + 极轻气声（窄带，非白噪声）。"""
    n = int(dur * FS)
    t = np.arange(n) / FS
    fm = f * (1 + vib_depth * np.sin(2 * np.pi * vib * t))
    ph = 2 * np.pi * np.cumsum(fm) / FS
    tone = np.sin(ph) + 0.22 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    # 气声：带通噪声，只留 800-2600Hz，能量极低
    br = fft_band(RNG.standard_normal(n), lo=800.0, hi=2600.0)
    br /= (np.max(np.abs(br)) or 1)
    atk = max(1, int(FS * 0.10))
    env = np.ones(n)
    env[:atk] = np.linspace(0, 1, atk) ** 1.6
    rel = int(FS * 0.35)
    env[-rel:] *= np.linspace(1, 0, rel) ** 0.8
    return (tone + br * breath) * env


def reverb(x, hi_cut=4500.0, tail=2.8, decay=1.4):
    ir_n = int(tail * FS)
    t = np.arange(ir_n) / FS
    ir = RNG.standard_normal(ir_n) * np.exp(-t / decay) * np.exp(-t * 2.0)
    ir[:120] = 0
    ir = fft_band(ir, hi=hi_cut)
    n = len(x) + ir_n
    y = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n))[:len(x)]
    return y / (np.max(np.abs(y)) or 1)


# ---------------------------------------------------------------- 曲调库
def notes(**spec):
    """音名 → 频率表。"""
    return spec


MOODS = {
    "guqin": {
        "name": "古琴·清冷",
        "note": notes(A1=55.0, E2=82.41, A2=110.0, C3=130.81, D3=146.83,
                      E3=164.81, G3=196.0, A3=220.0, C4=261.63, D4=293.66,
                      E4=329.63, G4=392.0, A4=440.0),
        "gen": "pluck", "damp": 0.9962, "bright": 0.20,
        "hi": 7000.0, "drone": ("A1", "E2"), "drone_amp": 0.030,
        "theme": [(0.6, "A2", 1.00, 7.0), (4.2, "E3", 0.75, 6.0),
                  (7.6, "G3", 0.70, 6.0), (11.2, "A3", 0.80, 6.5),
                  (15.2, "C4", 0.65, 6.0), (18.6, "A3", 0.70, 6.0),
                  (22.4, "G3", 0.65, 6.0), (26.0, "E3", 0.70, 6.5),
                  (29.6, "D3", 0.60, 6.0), (32.6, "A3", 0.85, 7.0),
                  (36.4, "C4", 0.70, 6.0), (39.6, "E4", 0.75, 7.0),
                  (43.6, "G3", 0.55, 6.0), (43.6, "A3", 0.70, 6.0),
                  (47.8, "E3", 0.65, 6.0), (51.2, "D3", 0.60, 6.0),
                  (55.2, "C3", 0.65, 6.5), (59.4, "A2", 0.90, 7.5),
                  (63.6, "E3", 0.55, 6.0), (67.4, "A2", 1.00, 6.5)],
        "cycle": [(0.6, "A3", 0.70, 6.5), (4.6, "C4", 0.62, 6.0),
                  (8.6, "D3", 0.58, 6.0), (12.6, "E3", 0.66, 6.5)],
        "cycle_len": 16.0, "base_len": 74.0, "close": "A2",
        "gain": 0.32, "rev_hi": 4500.0,
    },
    "guzheng": {
        "name": "筝·明亮",
        "note": notes(D2=73.42, A2=110.0, D3=146.83, E3=164.81, G3=196.0,
                      A3=220.0, B3=246.94, D4=293.66, E4=329.63, G4=392.0,
                      A4=440.0, D5=587.33),
        "gen": "pluck", "damp": 0.9940, "bright": 0.42,
        "hi": 9000.0, "drone": ("D2", "A2"), "drone_amp": 0.022,
        "theme": [(0.4, "D3", 0.95, 5.0), (2.8, "A3", 0.70, 4.5),
                  (5.2, "D4", 0.80, 5.0), (8.0, "E4", 0.65, 4.5),
                  (10.4, "G4", 0.72, 5.0), (13.2, "E4", 0.62, 4.5),
                  (15.6, "D4", 0.75, 5.0), (18.4, "B3", 0.60, 4.5),
                  (20.8, "A3", 0.68, 5.0), (23.6, "D4", 0.82, 5.5),
                  (26.8, "G4", 0.70, 5.0), (29.6, "A4", 0.74, 5.5),
                  (33.0, "G4", 0.58, 4.5), (35.4, "E4", 0.64, 5.0),
                  (38.4, "D4", 0.72, 5.0), (41.4, "A3", 0.60, 4.5),
                  (44.0, "D4", 0.88, 6.0), (47.6, "G3", 0.55, 4.5),
                  (50.0, "A3", 0.66, 5.0), (53.2, "D4", 0.86, 6.0),
                  (57.0, "A3", 0.58, 5.0), (60.0, "D3", 0.92, 6.5)],
        "cycle": [(0.5, "D4", 0.72, 5.0), (3.4, "E4", 0.60, 4.5),
                  (6.6, "G4", 0.66, 5.0), (9.8, "A4", 0.70, 5.5),
                  (13.0, "D4", 0.64, 5.0)],
        "cycle_len": 16.0, "base_len": 64.0, "close": "D3",
        "gain": 0.30, "rev_hi": 6000.0,
    },
    "xiao": {
        "name": "箫·幽远",
        "note": notes(G2=98.0, D3=146.83, G3=196.0, A3=220.0, C4=261.63,
                      D4=293.66, E4=329.63, G4=392.0, A4=440.0),
        "gen": "flute", "damp": 0, "bright": 0,
        "hi": 8000.0, "drone": ("G2", "D3"), "drone_amp": 0.020,
        "theme": [(1.0, "G3", 0.90, 8.0), (7.0, "A3", 0.72, 7.0),
                  (13.0, "C4", 0.70, 8.0), (20.0, "D4", 0.78, 8.5),
                  (27.0, "C4", 0.66, 7.0), (33.0, "A3", 0.70, 8.0),
                  (40.0, "G3", 0.84, 8.5), (47.0, "D4", 0.68, 7.5),
                  (53.0, "C4", 0.66, 8.0), (60.0, "G3", 0.88, 8.0)],
        "cycle": [(1.0, "C4", 0.68, 8.0), (9.0, "D4", 0.64, 7.5),
                  (17.0, "A3", 0.70, 8.0)],
        "cycle_len": 24.0, "base_len": 68.0, "close": "G3",
        "gain": 0.34, "rev_hi": 5200.0,
    },
}


def synth(mood_key: str, target: float) -> np.ndarray | None:
    if mood_key == "silence":
        return None
    m = MOODS.get(mood_key)
    if m is None:
        raise SystemExit(f"未知配乐 mood '{mood_key}'，可选: "
                         + ", ".join(list(MOODS) + ["silence"]))
    total = max(m["base_len"], target + 3.5)
    melody = list(m["theme"])
    c = m["base_len"]
    while c + m["cycle_len"] <= total - 6.0:
        for off, nm, amp, d in m["cycle"]:
            melody.append((c + off, nm, amp, d))
        c += m["cycle_len"]
    melody.append((total - 7.5, m["close"], 0.95, 7.5))

    buf = np.zeros(int(total * FS))
    for t, name, amp, dur in melody:
        if m["gen"] == "pluck":
            glide = 0.035 if (name.endswith("2") or dur >= 6.5) else 0.0
            s = pluck(m["note"][name], dur, damp=m["damp"], glide=glide,
                      bright=m["bright"])
        else:
            s = flute(m["note"][name], dur)
        i = int(t * FS)
        seg = s[:max(0, len(buf) - i)]
        if len(seg):
            buf[i:i + len(seg)] += seg * amp * m["gain"]
    buf = reverb(buf, hi_cut=m["rev_hi"])

    # 纯音长音铺底（正弦叠加，绝无噪声）
    t = np.arange(len(buf)) / FS
    d1, d2 = (m["note"][k] for k in m["drone"])
    drone = np.sin(2 * np.pi * d1 * t) * 0.6 + np.sin(2 * np.pi * d2 * t) * 0.4
    trem = 1 + 0.25 * np.sin(2 * np.pi * 0.06 * t)
    env = np.clip(np.minimum(t / 6.0, 1.0) *
                  np.minimum((total - t) / 5.0, 1.0), 0, 1)
    buf += drone * trem * env * m["drone_amp"]
    buf = fft_band(buf, lo=32.0, hi=m["hi"])
    return buf / (np.max(np.abs(buf)) or 1) * 0.85


def band_report(x, label):
    S = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1 / FS)
    tot = (S ** 2).sum() + 1e-12
    out = [f"{100 * (S[(fr >= a) & (fr < b)] ** 2).sum() / tot:5.1f}%"
           for a, b in [(0, 4000), (4000, 6000), (6000, 10000), (10000, 16000)]]
    print(f"  {label:<16}| <4k {out[0]}  4-6k {out[1]}  6-10k {out[2]}  >10k {out[3]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()

    cfg = load_config(a.config)
    root = Path(cfg["_root"])
    P = Paths(root)
    P.ensure()

    mood = cfg["bgm"].get("mood", "guqin")
    target = 70.0
    if P.timeline.exists():
        target = float(json.loads(P.timeline.read_text(encoding="utf-8"))["total"])

    if not cfg["bgm"].get("enabled", True) or mood == "silence":
        n = int((target + 3.5) * FS)
        with wave.open(str(P.bgm), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS)
            w.writeframes(np.zeros(n, np.int16).tobytes())
        print(f"配乐已关闭（写入 {n / FS:.2f}s 静音轨）")
        return 0

    buf = synth(mood, target)
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(P.bgm), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS)
        w.writeframes(pcm.tobytes())

    print(f"配乐: {MOODS[mood]['name']}  时长 {len(buf) / FS:.2f}s "
          f"（影片 {target:.2f}s） → {P.bgm}")
    print("自检（频谱能量占比，6kHz 以上应为 0.0%）：")
    for a0, b0 in [(10.5, 12.5), (24.0, 25.5)]:
        if int(b0 * FS) < len(buf):
            band_report(buf[int(a0 * FS):int(b0 * FS)], f"{a0}-{b0}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
