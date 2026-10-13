# poem2video · 以诗入画

> 给一首古诗，还你一部**能直接发出去的短视频**：每句诗各配一幅画，AI 深情朗诵，民乐铺底，
> 横排字幕，片尾全诗 + 作者生平 —— 同时产出**抖音与小红书两套发布文案**。

![version](https://img.shields.io/badge/version-1.1.0-blue)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![platform](https://img.shields.io/badge/WorkBuddy-Skill-0052D9)
![output](https://img.shields.io/badge/output-1920%C3%971080%20%C2%B7%2025fps-000000)
![watermark](https://img.shields.io/badge/watermark-none-success)

---

## 这是什么

`poem2video` 是一个 **WorkBuddy / Claude 技能**：把「古诗 → 短视频」这条流水线固化下来，
从生图提示词一直做到成片与文案，**不需要手写 ffmpeg**。

一句话流程：

```
古诗配置 → 逐句生图提示词 → ImageGen 出画 → MiMo 深情旁白 → 帧合成 → 亚像素运镜渲染
        → 程序合成民乐 → 智能混音 → 量化质检 → 成片 + 抖音/小红书文案
```

产出物固定为两件：

| 交付物 | 说明 |
|---|---|
| `<题名>·诗画影片.mp4` | 1920×1080 / 25fps，无第三方水印，音画等长 |
| `<题名>·发布文案.md` | 抖音 + 小红书双平台标题、正文、话题、封面大字 |

---

## 效果预览

仓库不内嵌视频（体积原因），下表是两套内置样例的**实测产出**，
对应配置在 [`examples/`](examples/) —— 复制即可复现。

| 样例 | 组合 | 片长 / 帧数 | 定位 |
|---|---|---|---|
| [《江雪》水墨孤高](examples/01-jiangxue-ink.poem.json) | `ink` 水墨 + 白桦（苍老男声）+ 古琴 | 80.0s / 2000 帧 | 深夜情绪向、国学号冷启动 |
| [《望庐山瀑布》电影写实](examples/02-lushan-realistic.poem.json) | `realistic` 写实 + 苏打（清朗男声）+ 筝 | 71.6s / 1790 帧 | 品牌宣传、文旅向 |

**质检实测（两套样例全部通过）**

| 指标 | 江雪 | 望庐山瀑布 |
|---|---|---|
| 帧时序偏差帧数 | 0 | 0 |
| 镜头内帧间差 | 0.096 / 255 | 0.135 / 255 |
| 转场帧差峰值 | 3.3 / 255 | 0.63 – 7.26 / 255 |
| 6kHz 以上噪声占比 | 0.44% | 0.00% |
| 音画长度差 | 0.00s | +0.01s |
| 旁白落点命中 | 10 / 10 | 10 / 10 |

样例二的**发布文案全文**见
[`examples/02-lushan-realistic.expected-copy.md`](examples/02-lushan-realistic.expected-copy.md)（真实生成、未润色）。

---

## 特性

- **一句一画**：每句诗单独生成一幅画，镜头逐句对应，绝不"一张图撑全片"。
- **时长由声音决定**：先合成旁白，再按旁白实际时长反推镜头长度与字幕落点 —
  不会出现"话说完了画面还在飘"。
- **8 种画风**：从水墨留白到敦煌矿物重彩，按诗的情绪选。
- **MiMo 全系音色**：内置 4 个中文音色 + 4 个英文音色，支持**凭空造音色**（VoiceDesign）。
- **画面不抖、音频不噪**：这两项是硬指标，且用**数据验收**（见上文质检表），不靠感觉。
- **一次产出两件交付物**：成片 + 双平台文案，文案里的事实（诗名/朝代/作者/时长）由配置驱动，不会写错。

### 画风库

| ID | 名称 | 气质 | 适用题材 |
|---|---|---|---|
| `ink` | 水墨国画 | 宣纸质感、浓淡墨色、大面积留白 | 默认首选，最贴古诗气质 |
| `qinglv` | 青绿山水 | 矿物青绿重彩，华丽而古朴 | 山水、盛世、壮阔 |
| `gongbi` | 工笔重彩 | 细笔勾勒、层层渲染 | 花鸟、庭院、人物 |
| `realistic` | 电影级写实 | 真实光影、电影分镜质感 | 边塞、山水、夜泊等大场景 |
| `illustration` | 唯美插画 | 色彩柔和通透、海报感 | 社媒传播、轻快题材 |
| `moonlight` | 月下水墨 | 青蓝墨调、银白月光 | 夜景、思乡、怀人 |
| `papercut` | 剪纸木版 | 平面高饱和、粗轮廓 | 节庆、童趣 |
| `dunhuang` | 敦煌壁画 | 土红赭石加泥金、斑驳矿物感 | 边塞、大漠、佛理 |

### 音色库

| 音色 | 定位 | 适合 |
|---|---|---|
| `baihua` 白桦 | 男声，苍劲醇厚 | 孤寂、苍凉、怀古 |
| `suda` 苏打 | 男声，清朗温润 | 豪迈、田园、叙事 |
| `bingtang` 冰糖 | 女声，清甜 | 明快、童趣 |
| `moli` 茉莉 | 女声，清雅 | 婉约、思念 |
| `mia` / `chloe` / `milo` / `dean` | 英文音色 | 英译诗、双语内容 |

还支持 `mimo-v2.5-tts-voicedesign` 模型**描述即造音色**（如"年逾七旬的朗诵大家，嗓音苍劲略带沙哑"）。

---

## 快速开始

### 1. 安装

作为 WorkBuddy 技能，放进用户级技能目录即可（技能识别**只依赖 `SKILL.md`**）：

**方式 A · 从本仓库克隆（推荐）**

```bash
git clone https://github.com/<your-name>/poem2video-skill.git ~/.workbuddy/skills/poem2video
```

**方式 B · 解压发行包**

```bash
unzip poem2video-v1.1.0.zip -d ~/.workbuddy/skills/   # 得到 ~/.workbuddy/skills/poem2video/
```

**方式 C · 从技能市场安装**：在 WorkBuddy 左侧【专家 · 技能 · 连接器】→【技能】中搜索安装。

### 2. 前置依赖

| 依赖 | 说明 |
|---|---|
| Python 3.10+ | 需 `pillow numpy requests`；去水印另需 `opencv-python-headless` |
| ffmpeg | 需**含 libx264 的真 ffmpeg**；脚本自动定位，缺失时用 `imageio-ffmpeg` 静态版 |
| ImageGen | 画作由宿主生图能力生成（技能只产出提示词） |
| MiMo API Key | 环境变量 `MIMO_API_KEY`，或写入 `~/.workbuddy/mimo_api_key` |

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    pillow numpy requests imageio-ffmpeg opencv-python-headless
```

> **密钥纪律**：Key 只走环境变量或 `~/.workbuddy/mimo_api_key`，**绝不写进任何配置文件**，
> 发布/分发前请再确认一次。

### 3. 四步出片

```bash
# 0) 准备配置（或直接用 examples/ 里的现成样例）
mkdir -p my-poem && cd my-poem
cp <SKILL>/assets/config.example.json ./poem.json     # 按注释改 poem / style / voice

# 1) 生成逐句生图提示词 → 用 ImageGen 逐条出画，存为 images/NN-<诗句>.png
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage prompts

# 2) 合成旁白（想先看不花钱的文本，加 --dry-run）
MIMO_API_KEY=... <py> <SKILL>/scripts/poem2video.py --config poem.json --stage tts

# 3) 一键成片：去水印 → 帧合成 → 时间轴 → 渲染 → 配乐 → 混音 → 文案
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage build

# 4) 质检（任何 ❌ 修掉再交付）；--stage all 可一次跑完成片 + 质检
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage check
```

> `<py>` 请用托管 venv 解释器（如 `.../python/envs/default/bin/python3`），
> 裸 `python3` 常缺 `imageio-ffmpeg`，会报「找不到可用的 ffmpeg」。

**只改音频不用重渲染画面**：

```bash
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage bgm
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage mux
```

---

## 配置速查

| 字段 | 作用 | 常用值 |
|---|---|---|
| `poem.*` | 题名/朝代/作者/体裁/主题/诗句/每句意象/作者生平 | 唯一必填项 |
| `style` | 画风 | `ink` 等 8 选 1 |
| `voice` | 音色 | `baihua` / `suda` / `moli` / `bingtang` … |
| `narration.tone_tags` | 每句情绪标签 | `"飞流直下三千尺": "激昂 澎湃"` |
| `video.fade` | 转场叠化时长（秒） | `1.0` 利落 / `1.6` 柔和 / `2.0+` 悠长 |
| `video.kenburns` | 推拉运镜 | `true` / `false`（静止） |
| `video.caption` | 字幕 | `horizontal` / `none` |
| `bgm.mood` | 配乐 | `guqin` 清冷 / `guzheng` 明亮 / `xiao` 幽远 / `silence` |
| `copy.platforms` | 文案平台 | `["douyin", "xiaohongshu"]` |

完整字段说明见 `assets/config.example.json`（每个字段都带 `_note`）。

---

## 目录结构

```
poem2video/
├── SKILL.md                 ★ 技能定义（YAML frontmatter + 指令正文）
├── README.md                本文件
├── references/
│   ├── quickstart.md        使用说明：依赖、五步出片、阶段速查、常见问题
│   ├── styles.md            8 种画风的选择指南与生图要点
│   ├── voices.md            MiMo 音色、导演指令写法、情绪标签速查
│   ├── copywriting.md       抖音/小红书文案规范与钩子公式
│   └── pipeline.md          管线细节、参数手册、故障排查
├── scripts/                 11 个配置驱动脚本（poem2video.py 为编排入口）
├── examples/                2 套可跑样例 + 文案样张
└── assets/                  config.example.json / styles.json / voices.json
```

---

## 常见问题

<details>
<summary><b>报「找不到可用的 ffmpeg（含 libx264）」</b></summary>

换成托管 venv 解释器，或 `pip install imageio-ffmpeg`。技能会自动把真 ffmpeg 落到 `<项目>/bin/ffmpeg`。
</details>

<details>
<summary><b>画面抖动 / 沸腾</b></summary>

根因是用 ffmpeg `zoompan` 做运镜（整数取整 + 非整数重采样），或画面底纹含逐像素白噪点。
本技能用 **PIL 亚像素仿射逐帧渲染 + rawvideo 管道**规避，别改回 `zoompan`。
</details>

<details>
<summary><b>音频有沙沙声</b></summary>

配乐不要用宽带白噪声铺底；滑音插值不要用 `np.interp` 的 `period` 回绕（会产生宽带混叠）。
</details>

<details>
<summary><b>音轨比画面短几秒</b></summary>

`sidechaincompress` 在侧链（旁白）结束后会截止输出，旁白链路必须加 `apad=whole_dur=<片长>`。
</details>

<details>
<summary><b>字幕发黑 / 朱印变黑块</b></summary>

叠加层预乘色与画布色标不一致（0–1 vs 0–255）。正确写法 `rgb * alpha * 255` 后再合成。
</details>

<details>
<summary><b>TTS 不出声 / 返回 401</b></summary>

文本必须放在 **assistant** 角色（放 user 不出声）；401 是 Key 缺失或失效。
</details>

约 20 条完整故障表见 `references/pipeline.md`。

---

## 文档

| 文档 | 内容 |
|---|---|
| `references/quickstart.md` | 使用说明（面向安装者） |
| `examples/README.md` | 演示样例详解：实测数据、分镜表、差异对照 |
| `references/styles.md` | 画风选择与生图要点 |
| `references/voices.md` | 音色与配音（MiMo-V2.5-TTS） |
| `references/copywriting.md` | 发布文案规范 |
| `references/pipeline.md` | 管线手册与故障排查 |

---

## 关于

- 版本：**1.1.0**

- 音色与合成能力基于小米 **MiMo-V2.5-TTS**；画作由宿主生图能力生成。

- 配乐为**程序合成的原创曲**（Karplus-Strong 拨弦合成民乐），无版权风险；旁白为 AI 合成音色。

  
