# 使用说明（速查）

> 面向「已经装好这个技能、要立刻出片」的人。参数细节与故障排查见 `pipeline.md`，
> 画风与音色分别在 `styles.md` / `voices.md`。

## 一、这个技能做什么

一句话：**给一首古诗，还你一部能直接发的短视频 + 两套发布文案。**

- 每句诗单独生成一幅画，逐句对应，不是"一张图撑全片"；
- AI 旁白深情朗诵（MiMo-TTS），程序合成的民乐铺底，旁白压得住配乐；
- 横排字幕 + 片头报题 + 片尾全诗复诵 + 作者生平卡；
- 产出可直接发的 1080p 成片，以及抖音、小红书两套文案。

## 二、怎么触发

对话里直接说需求即可，例如：

- 「以诗入画，把《静夜思》做成视频」
- 「用《登鹳雀楼》做一条宣传向的短视频」
- 「给《春晓》配画面和配音，水墨风，女声」

技能会自动接管。**只要涉及「古诗 → 视频」，都不要手写 ffmpeg 拼一遍。**

没指定画风/音色时，按诗的情绪自动选（见下表）；也可以直接点名：

| 诗的情绪 | 画风 | 音色 |
|---|---|---|
| 孤寂苍凉 | `ink` 水墨国画 | `baihua` 白桦（男，苍老） |
| 明快田园 | `qinglv` 青绿山水 | `suda` 苏打（男，清朗） |
| 婉约思念 | `moonlight` 月下水墨 | `moli` 茉莉（女） |
| 豪迈壮阔 | `realistic` 电影写实 | `baihua` / `suda` |

## 三、前置依赖

| 依赖 | 要求 |
|---|---|
| Python | 需 `pillow numpy`；去水印另需 `opencv-python-headless` |
| ffmpeg | 需**含 libx264 的真 ffmpeg**；脚本会自动定位，找不到就装 `imageio-ffmpeg` |
| ImageGen | 画作由你调用生图工具生成（技能只产出提示词） |
| MiMo API Key | `MIMO_API_KEY` 环境变量，或写入 `~/.workbuddy/mimo_api_key` |

```bash
# 一次装齐（缺哪个装哪个）
<py> -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    pillow numpy requests imageio-ffmpeg opencv-python-headless
```

> **解释器怎么选**：用本会话的**托管 venv**（`.../python/envs/default/bin/python3`）。
> 直接用裸 `python3` 常缺 `imageio-ffmpeg`，脚本会报「找不到可用的 ffmpeg」。
>
> **密钥纪律**：Key 只走环境变量或 `~/.workbuddy/mimo_api_key`，**绝不写进任何配置文件**。

## 四、五步出片

设 `<SKILL>` 为技能目录，设工作目录为你的项目目录。

### 1. 建项目、写配置

```bash
mkdir -p mypoem && cp <SKILL>/assets/config.example.json mypoem/poem.json
```

编辑 `mypoem/poem.json`：只需填 `poem`（题名/朝代/作者/体裁/主题/诗句/每句意象/作者生平）、
`style`、`voice`。**每个字段都带 `_note` 说明，其余留默认即可。**
拿不准就直接改 `examples/` 里的现成配置。

### 2. 生成画作

```bash
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage prompts
```

输出 `images/prompts.md`：每句诗一条完整生图提示词，**一条提示词生成一张图**，
按 `NN-<诗句>.png` 保存（画幅 3:2，建议 1536×1024，主体大致居中）。

> 生成完**逐张看一眼**再往下走。生图工具偶发同名覆盖，或个别图会带水印/文字——
> 早发现只需重生成一张，晚发现就得重渲染整片。

### 3. 生成旁白

```bash
MIMO_API_KEY=... <py> <SKILL>/scripts/poem2video.py --config poem.json --stage tts
```

先跑 `--dry-run` 可以只看文本、不花钱。想换音色改配置里的 `voice`，或临时 `--voice moli`。

### 4. 一键成片

```bash
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage build
```

内部依次跑：去水印 → 帧合成 → 时间轴 → 逐帧渲染 → 配乐 → 混音 → 文案。

### 5. 质检并交付

```bash
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage check
```

任何 ❌ 项都修掉再交付。最后把**成片 + 文案**一起交付给用户。

## 五、阶段速查

| 阶段 | 作用 | 何时单跑 |
|---|---|---|
| `prompts` | 生成生图提示词 | 每次新诗 |
| `clean` | 去水印 | 生图带水印时 |
| `tts` | 合成旁白 | 换音色/改词后 |
| `frames` / `timeline` | 帧卡与时间轴 | 改配置后 |
| `render` | 逐帧渲染 | 改画面后 |
| `bgm` / `mux` | 配乐与混音 | **只改音频时不用重渲染** |
| `copy` | 生成发布文案 | 单独补文案 |
| `check` | 质检 | 交付前 |
| `all` | build + check | 一次跑完 |

```bash
# 只换配乐：不用重渲染画面
<py> poem2video.py --config poem.json --stage bgm && <py> poem2video.py --config poem.json --stage mux
```

## 六、常用配置

| 字段 | 作用 | 常用值 |
|---|---|---|
| `video.fade` | 转场叠化时长 | `1.0` 利落 / `1.6` 柔和（默认）/ `2.0+` 悠长 |
| `video.kenburns` | 推拉运镜 | `true` 有运镜 / `false` 静止 |
| `video.caption` | 字幕 | `horizontal` 横排（默认）/ `none` 不烧字幕 |
| `narration.repeat_full_poem` | 片尾复诵全诗 | `true` / `false` |
| `bgm.mood` | 配乐 | `guqin` 清冷 / `guzheng` 明亮 / `xiao` 幽远 / `silence` |
| `bgm.gain` | 配乐音量 | `0.30`（默认），最多提到 `0.35` |
| `copy.platforms` | 产出文案平台 | `["douyin", "xiaohongshu"]` |

## 七、演示样例

`examples/` 里有两套**可直接跑**的完整配置，附实测产出数据与文案样张：

- `examples/01-jiangxue-ink.poem.json` —— 《江雪》，水墨孤高（80s / 2000 帧）
- `examples/02-lushan-realistic.poem.json` —— 《望庐山瀑布》，电影写实宣传向（71.6s / 1790 帧）
- `examples/02-lushan-realistic.expected-copy.md` —— 样例二真实生成的发布文案全文

用法：复制到自己的项目目录再改。

```bash
mkdir -p ~/my-poem && cd ~/my-poem
cp <SKILL>/examples/02-lushan-realistic.poem.json ./poem.json
<py> <SKILL>/scripts/poem2video.py --config poem.json --stage prompts
```

见 `examples/README.md`。

## 八、常见问题

| 现象 | 处理 |
|---|---|
| 「找不到可用的 ffmpeg」 | 换托管 venv 解释器，或装 `imageio-ffmpeg` |
| 画面抖动 | 本技能已避开 `zoompan`；若自加纹理要改低频 |
| 音频有沙沙声 | 别用白噪声铺底；滑音不要用 `period` 回绕 |
| 音轨比画面短 | 旁白链路必须 `apad=whole_dur=<片长>` |
| 字幕发黑 | 叠加层预乘色要乘回 255（`rgb*alpha*255`） |
| TTS 不出声 / 401 | 文本必须在 `assistant` 角色；Key 是否就位 |
| 水印没去掉 | 用 `--region x0,y0,x1,y1` 手动指定区域 |

完整故障表（约 20 条）见 `pipeline.md`。

## 九、交付与发布注意

- 成片与文案**必须一并交付**，文案里的事实（诗名、朝代、作者、时长）由配置驱动，不要手改。
- 配乐为程序合成的原创曲，无版权风险；旁白为 AI 合成音色。
- 若把本技能再分发给别人：**打包前务必确认没有把自己的 API Key 带进去**。
