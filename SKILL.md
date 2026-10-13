---
name: poem2video
display_name: 以诗入画 · 诗画影片
display_name_en: Poem to Video
description: 以诗入画——把一首古诗做成有旁白、配乐、字幕的诗画影片，并产出抖音/小红书发布文案。适用于「以诗入画」「古诗做成视频」「诗画影片」「诗词短视频」「给古诗配画面/配音」「古风短视频」等需求。内置 8 种画风与 MiMo 全系音色，一键产出 1080p 成片 + 发布文案。
description_zh: 把一首古诗一键做成有旁白、民乐配乐、横排字幕的 1080p 诗画影片，并生成抖音/小红书发布文案。内置 8 种画风与 MiMo 全系音色。
description_en: Turn a classical Chinese poem into a narrated 1080p short film with music and subtitles, plus ready-to-post copy for Douyin and Xiaohongshu. 8 art styles and MiMo voices built in.
version: 1.0.0
author: felix
---

# poem2video · 以诗入画

把一首古诗变成一部**能直接发出去的短视频**：每句诗对应一幅画，AI 深情朗诵，
民乐铺底，横排字幕，片尾全诗 + 作者生平；同时产出抖音与小红书文案。

## 何时用

用户提到：以诗入画 / 把古诗做成视频 / 诗画影片 / 诗词短视频 / 给诗词配画面配音 /
古风短视频 / 抖音古诗词账号内容。**只要涉及「古诗 → 视频」，就用本技能**，
不要手写 ffmpeg 拼一遍。

## 核心理念

1. **一句一画**：每句诗单独生成一幅画，镜头逐一对应，绝不"一张图撑全片"。
2. **时长由声音决定**：先合成旁白，再按旁白实际时长反推镜头长度与字幕落点。
   顺序反了必然出现"话说完了画面还在飘"或"画面切走了话还没说完"。
3. **平滑与无杂音是硬指标**：见下文《质量红线》。这两项都要用数据验收，不能靠感觉。
4. **成片必须是"可发布"状态**：无水印、音画等长、字幕不叠压、片尾有完整信息。

## 前置依赖

| 依赖 | 说明 |
|---|---|
| Python | 用本会话的托管解释器；需 `pillow numpy requests`（缺失时按清华源安装） |
| ffmpeg | 需**含 libx264 的真 ffmpeg**，脚本会自动定位并落地到 `<项目>/bin/ffmpeg` |
| ImageGen | 生成画作（技能本身不生成图，由你调用生图工具） |
| MiMo API Key | 环境变量 `MIMO_API_KEY`，或 `~/.workbuddy/mimo_api_key`。**不要写进任何文件** |
| OpenCV（可选） | `opencv-python-headless`，去水印用；缺失时降级为模糊合成 |

装依赖（只装缺的）：

```bash
<py> -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pillow numpy requests imageio-ffmpeg opencv-python-headless
```

## 工作流

### 0. 定需求

先和用户确认三件事，其余都可用默认值：**选哪首诗**、**画风**（8 选 1）、**音色**（见音色库）。
用户没指定就按诗的情绪自动选：孤寂苍凉 → `ink` + `baihua`；明快田园 → `qinglv` + `suda`；
婉约思念 → `moonlight` + `moli`；豪迈壮阔 → `realistic` + `baihua`。

### 1. 建项目 + 写配置

```bash
mkdir -p <项目目录> && cp <SKILL>/assets/config.example.json <项目目录>/poem.json
```

编辑 `poem.json`：填 `poem`（题名/朝代/作者/体裁/主题/诗句/每句意象/作者生平）、
`style`、`voice`，其余用默认。字段说明见文件内 `_note`。

### 2. 生成画作

```bash
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage prompts
```

它会输出 `images/prompts.md`——**每句诗一条完整生图提示词**（风格前缀 + 诗句 + 意象 +
约束后缀）。然后你用生图工具逐条生成，保存到 `images/NN-<诗句>.png`。

要求：一条提示词生成一张图，画幅 3:2；构图主体大致居中（成片是 16:9 居中裁切铺满）。

### 3. 生成旁白

```bash
MIMO_API_KEY=... <py> <SKILL>/scripts/poem2video.py --config poem.json --stage tts
```

用 MiMo-TTS 按配置的**音色**与**导演指令**（按 `poem.theme` 自动选）合成
`open / s1..sN / author` 各段。先跑 `--dry-run` 可以只看文本不花钱。

想换音色：改配置 `voice`，或临时 `--voice moli`。想凭空造音色：把
`narration.model` 改成 `mimo-v2.5-tts-voicedesign`，并把描述写进
`narration.voice_design_prompt`。

### 4. 一键成片 + 文案

```bash
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage build
```

依次执行：去水印 → 帧合成 → 时间轴 → 逐帧渲染 → 配乐 → 混音 → 文案。
（`--stage all` 会额外跑一遍质检。）

单步重跑：`--stage frames|timeline|render|bgm|mux|copy|check`。
**只改音频时不用重渲染**：`--stage bgm && --stage mux` 即可。

### 5. 质检并交付

```bash
<py> <SKILL>/scripts/check_quality.py --config poem.json
```

任何 ❌ 项都要修掉再交付。最后用 `present_files` 把**成片 + 文案**一起交付，
并顺手记一条工作日志。

## 产物

```
<项目>/
  images/            生图原图 + prompts.md
  clean/             去水印后的画作
  audio/mimo/        旁白（prep/ 为裁掉首尾静音的版本）
  audio/bgm.wav      程序合成配乐
  frames/            镜头卡 + 字幕叠加层
  tmp/               timeline.json、无声视频
  poem2video_out/
    <题名>·诗画影片.mp4      ← 交付物 1
    <题名>·发布文案.md        ← 交付物 2（抖音 + 小红书）
```

## 影片结构

| 段落 | 内容 |
|---|---|
| 片头 | 宣纸底竖题 + 朝代作者 + 体裁 + 朱印，旁白报题 |
| 场景 ×N | 每句诗一幅画**铺满全屏**，横排字幕压在底部压暗条上（左侧「其N」朱印） |
| 片尾一 | 全诗逐句浮现，与复诵旁白同步；作者卡叠化前柔和退场 |
| 片尾二 | 作者信息卡：生卒/字号/籍贯/评价 + 全诗 + 印章 |

## 质量红线（踩过的坑，必须遵守）

**画面**
- **禁止用 ffmpeg `zoompan` 做运镜**：它整数取整 + 逐帧非整数重采样，会让画面
  "沸腾/蠕动"。本技能用 PIL 亚像素仿射变换逐帧渲染 + rawvideo 管道送编码器。
- 画面底纹**不要加逐像素白噪点**（高频内容在重采样下会闪）；要用低频斑驳纹理。
- 转场用 1.6s 交叉叠化 + smoothstep 权重（不要硬切）。帧时序必须严格等于 `1/fps`。

**音频**
- 合成配乐**禁止用宽带白噪声做铺底/风声**，那正是"沙沙"杂音的来源；要用纯音长音。
- 滑音插值必须用**频率倍率的时间累积**得到非整数采样位置，不能用 `np.interp` 的
  `period` 回绕（会产出宽带混叠噪声）。
- 混音时**必须**给旁白链路 `apad=whole_dur=<片长>`：`sidechaincompress` 在侧链
  结束后会一并截止输出，否则音轨比画面短、片尾淡出被截断。
- 旁白只做 `highpass=f=70` + `loudnorm`；**不要加 `aecho`**（在 16–24kHz 源上易出金属声）。

**字幕与排版**
- 字幕是**独立叠加层**，固定在输出空间不随镜头缩放（随镜头缩放会"呼吸"）。
- 每条叠加层都要有明确退场时刻，否则会压在下一张卡的文字上（两层文字打架）。
- 长句要自动缩字号（脚本已按 `0.78×画宽` 自适应）。
- 画作裁切前先确认主体在画面中部，避免 16:9 铺满时把主体切掉。
- **叠加层颜色尺度必须与背景一致（都是 0–255）**：若把 RGBA 归一化到 0–1 后
  预乘，再与 0–255 的画布合成，白色字幕会变成近黑、朱印变成黑块——
  而且因为压暗底上"看着像有字"，极难在小尺寸抽帧质检里发现。
  正确写法：`rgb * alpha * 255` 后再参与合成（脚本已内置）。

**其他**
- 合帧后**不要**再改卡片图——渲染器启动时已把帧读进内存，改了必须重渲染。
- 生成的画作带模型水印时，先跑 `--stage clean` 再去合成。
- API Key 只走环境变量，不落盘、不出现在交付文件里。

## 文档索引

- `references/styles.md` —— 8 种画风的选择指南与生图要点
- `references/voices.md` —— MiMo 全系音色、导演指令写法、情绪标签速查
- `references/copywriting.md` —— 抖音/小红书文案规范与钩子公式
- `references/pipeline.md` —— 管线细节、参数手册、故障排查
- `assets/config.example.json` —— 配置模板（每个字段都带 `_note`）
- `assets/styles.json` / `assets/voices.json` —— 机器可读的风格与音色库
