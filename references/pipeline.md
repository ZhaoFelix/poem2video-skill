# 管线手册与故障排查

## 脚本一览

| 脚本 | 职责 | 关键产物 |
|---|---|---|
| `poem2video.py` | 主编排（阶段调度） | — |
| `lib_common.py` | 配置加载、风格/音色解析、ffmpeg 定位、字体、时长 | — |
| `tts_mimo.py` | MiMo-TTS 合成旁白 | `audio/mimo/*.wav` |
| `remove_watermark.py` | 自动识别并修复四角浅色水印 | `clean/*.png` |
| `compose_frames.py` | 风格驱动的帧合成与排版 | `frames/*.png`, `overlays.json` |
| `make_timeline.py` | 按旁白实际时长反推镜头与落点 | `tmp/timeline.json` |
| `render_video.py` | 逐帧亚像素运镜 + 柔和叠化 + 字幕叠加 | `tmp/video_silent.mp4` |
| `bgm_synth.py` | 程序化合成民乐配乐 | `audio/bgm.wav` |
| `mux_audio.py` | 旁白摆放 + 侧链闪避 + 混流 | 成片 mp4 |
| `make_copy.py` | 抖音/小红书文案初稿 | `<题名>·发布文案.md` |
| `check_quality.py` | 量化质检 | 控制台报告 |

## 参数手册（config 关键项）

**视频**
- `video.fade`：叠化时长。`1.0` 利落 / `1.6` 柔和（默认）/ `2.0+` 悠长。
- `video.kenburns`：推拉运镜开关。关掉则画面静止只做叠化，适合纯朗读向。
- `video.caption`：`horizontal` 横排字幕 / `none` 不烧字幕。
- `video.scene_numbering`：字幕左侧「其一/其二」朱印开关。
- `video.title_credit`：片尾作者信息卡开关。
- `video.resolution` / `fps`：默认 `1920x1080` / `25`。改分辨率无需改脚本。

**音频**
- `bgm.mood`：`guqin` 古琴清冷 / `guzheng` 筝曲明亮 / `xiao` 箫声幽远 / `silence`。
- `bgm.gain`：配乐绝对音量，默认 `0.30`。**旁白永远压得住配乐**，觉得配乐弱宁可调 0.35。
- `narration.repeat_full_poem`：片尾是否逐句复诵全诗（再念一遍）。
- `narration.tone_tags`：按诗句覆盖情绪标签。

**时长节奏**（改 `make_timeline.py` 顶部常量）
- `LEAD` 0.9 片头留白；`LINE_LEAD` 1.8 旁白比镜头晚开口；`LINE_TAIL` 1.5 句后留白；
  `MIN_SCENE` 6.8 单场景最短；`LAST_TAIL` 2.2 末句额外留白；`REPEAT_GAP` 1.4 复诵句间停顿。

## 时间轴逻辑（理解它才能改节奏）

```
片头:  0 → LEAD + 报题时长 + 1.4
场景k: 上一镜 end − FADE 起，长度 = max(6.8, LINE_LEAD + 旁白 + 留白)
片尾1: 末镜 end − FADE + 1.5 起，逐句复诵（每句 旁白 + 1.4~1.6）
片尾2: 复诵完 + 1.0 起，作者介绍 24s 左右，末尾留 3.2s
```

- 旁白较长时场景自动变长 → 成片变长 → 配乐自动延展 → 无需手工对时。
- 想加快整体节奏：调小 `LINE_TAIL` / `REPEAT_GAP` / `LAST_TAIL`。
- 想慢：调大 `LINE_LEAD`（等更久再开口）。

## 故障排查

| 现象 | 根因 | 处理 |
|---|---|---|
| 画面抖动/沸腾 | 用了 `zoompan`，或画面底纹含逐像素白噪点 | 本技能已避开；若自加了纹理，改成低频斑驳 |
| 转场生硬 | `fade` 太小或权重是线性的 | `fade` 提到 1.6+；权重必须 smoothstep |
| 音频有沙沙声 | 配乐用了白噪声铺底，或滑音插值用了 `period` 回绕 | 用纯音铺底；滑音用频率倍率累积 |
| 音轨比画面短 3 秒 | `sidechaincompress` 在旁白结束后截止输出 | 旁白链路 `apad=whole_dur=<片长>` |
| 人声发金属 | 加了 `aecho`（16–24kHz 源上易出金属声） | 去掉回声，只留 `highpass` + `loudnorm` |
| 两层文字叠压 | 叠加层没有退场时刻 | 给每条 overlay 设 `out` / `rout` |
| 字幕/印章发黑（白字变黑、朱印变黑块） | 叠加层预乘色是 0–1 尺度，画布是 0–255 | 预乘后乘回 255：`rgb * alpha * 255` |
| 字幕随镜头缩放"呼吸" | 字幕被合进卡片帧一起缩放 | 字幕必须是独立叠加层，在输出空间合成 |
| 帧时序不均 | 用 `-r` 重采样而非 rawvideo 管道恒定帧率 | 逐帧渲染 + `-framerate` 管道 |
| 卡片图改了但成片没变 | 渲染器已把帧读进内存 | 改帧后必须重跑 `render` |
| ffmpeg 报滤镜不支持 | 环境里的 `ffmpeg` 是 PIL 包装脚本 | `bootstrap_ffmpeg` 会自动换成真 ffmpeg |
| 水印没去掉 | 水印不在检测阈值内（非浅色） | 用 `--region x0,y0,x1,y1` 手指定区域 |
| 生图带文字/印章 | 模型未遵守约束 | 单独重生成该张；提示词已含禁文字约束 |
| TTS 不出声 | 文本写进了 `user` 角色 | 文本必须在 `assistant` |
| TTS 返回 401 | 缺 Key / Key 失效 | 设 `MIMO_API_KEY` 或写 `~/.workbuddy/mimo_api_key` |
| pip 装包超时 | 直连 PyPI 慢 | 加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |

## 质检怎么读（check_quality.py）

- **帧时序**：偏差帧必须为 0。非 0 说明某处重采样了。
- **镜头内平滑度**：均值 < 6/255 视为平滑；波动大说明有取整或纹理噪声。
- **转场柔和度**：窗口内帧差峰值应 < 12/255（硬切通常 >20）。
- **音频频谱**：静段 6kHz 以上应 < 1%。超过基本可判定有嘶声/混叠。
- **音画等长**：差值应 < 0.15s。
- **旁白落点**：每段落点处 RMS 应 > −42dB，否则说明该段没出声或位置错了。

## 性能参考

- 逐帧渲染 1920×1080：约 2000 帧需 2 分钟量级（`preset slow`）。
- 想更快：`render_video.py` 里 `-preset` 改 `medium`，`-crf` 17 → 19。
- 想更小体积：`-crf` 提到 20–21（画质损失在静品类内容上不易察觉）。

## 只改音频不重渲染

```bash
<py> poem2video.py --config poem.json --stage bgm   # 换配乐
<py> poem2video.py --config poem.json --stage mux   # 重新混音
```

换音色重录旁白后同理：`--stage tts && --stage timeline && --stage mux`
（时间轴要重算，但画面不用重渲染——镜头是按时长生成的，若旁白大幅变长，
仍建议跑一次 `--stage timeline --stage render` 让镜头节奏跟上）。
