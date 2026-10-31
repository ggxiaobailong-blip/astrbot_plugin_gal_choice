# GalGame 选项

把 AstrBot 的回答变成一张 GalGame 界面图：角色立绘、连续对话、A/B/C/D 选项、好感度 HUD、TTS 语音，以及会自然走向结局的剧本。

> 当前版本 **0.8.0**。更新日志见 [CHANGELOG.md](CHANGELOG.md)。

![效果预览](docs/preview.jpg)

> 仅支持 **QQ 个人号私聊**（aiocqhttp / NapCat）。群聊触发会提示切到私聊。

## 最重要的几点

- **出图优先级**：T2I → 本地 Chromium HTML/CSS → Pillow 兜底。T2I 失败或超时 15 秒会自动切本地，不会因为远程 502/503 卡死。
- **本地浏览器可选**：执行 `python -m playwright install chromium` 后，T2I 不可用也能得到完整 HTML/CSS 效果；没有浏览器时 Pillow 仍可出图。
- **内置防抖**：同一用户连续消息会合并成一轮。**不要再同时启用 `reply_merge`**，否则会双重合并。
- **好感度**：初始 50，只在明显影响情绪的选项/自由回答时变化；数值隐藏，变化时显示粉色 `+3` 或蓝色 `-3`。
- **剧本与结局**：进入时生成开局大纲；没有固定幕数，剧情自然收束时才进入结局。`/gal start` 或 `/gal new` 开始新周目。
- **存档**：最多 10 个 JSON 存档，包含进度、好感、心情、剧本、分支和结局状态。

## 快速开始

```text
/gal start [题材]   进入 GalGame；可指定“校园恋爱”“雨夜悬疑”等
/gal new [题材]     开新周目
/gal stop           退出
/gal status         查看进度、好感、剧本、结局和语音状态
/gal save 名字      存档
/gal load 名字      读档；不带名字查看列表
/gal saves          查看存档列表
/gal delete 名字    删除存档
/gal model <id>     指定 gal 使用的模型
/gal voice on|off   开关语音
/gal help           查看全部命令
```

进入后：

1. 发一句话，或直接说“开始”，模型给出第一张图和选项；
2. 回 `A/B/C/D`、`1/2/3/4` 或选项原文；
3. 回 `0` 或直接说话自由输入；
4. 想退出说“退出gal模式”或发 `/gal stop`。

## 环境要求

- AstrBot `>=4.21,<5`；
- 私聊平台：QQ 个人号（aiocqhttp / NapCat）；
- 出图：优先使用 AstrBot 的 T2I；T2I 不可用时需要本地 Chromium（推荐）或 Pillow 兜底；
- 语音可选：FishAudio 等 AstrBot TTS；
- QQ 语音需要 `silk-python`（`requirements.txt` 已声明）和 `ffmpeg`。

## 功能

- **选项成图**：1280×720，立绘按情绪切换，2~3 行连续台词，选项和自由输入位。
- **三种选择方式**：字母、数字、选项原文；`0` 或直接说话自由输入。
- **WebUI 资源工作台**：多角色、18 类情绪差分、自定义背景、位置/高度/宽度可视化调整。
- **TTS 配音**：台词按句合成，句间可配置静音；QQ 侧预转 SILK 兼容 NapCat。
- **好感度 HUD**：阶段颜色进度条 + 8 类心情脸；条下显示当前心情。
- **剧本大纲**：标题、题材、背景、主线、预计幕数、关键分支、结局候选；不固定幕数。
- **关键分支**：情感/理性分支用粉/蓝边框和标签提示，一屏最多 1~2 个。
- **结局与周目**：结局图隐藏选项，显示大号 ENDING 标题；可开新周目。
- **存档/防抖/角色视角/失败降级**：状态原子写，模型输出不合格时退回可读文字。

## 安装

### 插件市场

在 AstrBot WebUI 的「插件」页搜索 **GalGame 选项** 安装。

### 手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/ggxiaobailong-blip/astrbot_plugin_gal_choice.git
pip install -r astrbot_plugin_gal_choice/requirements.txt
```

可选安装本地 Chromium，让 T2I 失败时仍能使用完整 HTML/CSS：

```bash
python -m playwright install chromium
```

重启 AstrBot 或重载插件。市场安装会自动处理 `requirements.txt`。

## 使用

```text
/gal                进入 GalGame 模式（也可以直接说“gal”）
/gal start [题材]   进入 GalGame 模式；可指定“校园恋爱”等题材
/gal new [题材]     结束当前局，开启新周目
/gal stop           退出
/gal status         查看当前模式、选项、幕数、模型、语音状态
/gal model <id>     指定 gal 模式使用的模型；default 恢复跟随会话
/gal voice on|off   开关本会话语音
/gal save 名字      保存当前进度（最多 10 个）
/gal load 名字      读取存档；不带名字查看列表
/gal saves          查看存档列表
/gal delete 名字    删除存档
/gal reset          清空本会话状态
/gal help           查看帮助
```

GalGame 仅在私聊开放；群聊触发会提示切到私聊。启动/退出是模糊匹配的：`gal启动！`、`启动gal`、`来玩gal` 都会进入；`结束gal`、`gal结束`、`不玩了`、`退出`、`关闭` 都会退出。**退出优先**，所以 `结束gal` 不会被当成再次启动。

进入模式后：

1. 发一句话，或直接说“开始”，模型会给出第一张图和选项。
2. 回 `A` / `B` / `C` / `D`（或 `1` / `2` / `3` / `4`）选择。
3. 没有想选的，回 `0`，或者直接说你想说的话。
4. 想退出，说“退出gal模式”或发 `/gal stop`。


## 自定义立绘 / 背景

在 AstrBot WebUI 的插件详情页打开 **「GalGame 资源工作台」**：

- **角色**：新建角色 → 上传「默认」立绘 → 给 18 类情绪上传差分；没有单独画的情绪会自动回退默认。
- **共用**：某个情绪卡片的下拉框可以选一张已经上传的立绘，让多个情绪共用同一张图。
- **位置**：拖「水平位置 / 垂直位置 / 立绘高度上限 / 立绘宽度上限」四个滑块；立绘按原图比例缩放，不会被拉伸。先用本地草稿调，再点「生成最终图」确认，最后保存。
- **背景**：上传自己的背景，点选固定；也可以保留“跟随背景模式”。
- **外观**：角色名标签、自由输入位文案、对话框透明度、出图质量。

资源保存到：

```text
data/plugin_data/astrbot_plugin_gal_choice/
├── characters.json
└── assets/
    ├── characters/<角色 id>/
    └── backgrounds/
```

更新/重装插件不会清空这个目录。内置角色只读；位置仍然可以调。

> WebUI 视图依赖 AstrBot 的插件页面能力（4.29.x 已实测）。旧版本仍可正常出图，但没有可视化工作台，可以手动编辑 `characters.json` 和 `assets/`。

## 情绪与差分

模型可以写 18 个中文视觉组，也可以直接写 FishAudio 的英文情绪标签（例如 `<emo>sarcastic</emo>`）。插件会把标签归到最接近的视觉组来选立绘，但 TTS 仍使用你写的具体标签。

| 视觉组 | 代表标签 | 同组可共用的标签 |
| --- | --- | --- |
| 开心 | `happy` | satisfied, delighted, optimistic |
| 兴奋 | `excited` | excited |
| 平静 | `calm` | relaxed |
| 难过 | `sad` | unhappy, depressed, disappointed, regretful, pessimistic, lonely |
| 生气 | `angry` | upset, frustrated |
| 惊讶 | `surprised` | surprised |
| 害羞 | `embarrassed` | guilty, ashamed |
| 害怕 | `scared` | hysterical |
| 担心 | `worried` | nervous, anxious, uncertain |
| 疲惫 | `resigned` | tired（别名） |
| 温柔 | `compassionate` | empathetic, sympathetic, grateful |
| 得意 | `proud` | confident, determined |
| 困惑 | `confused` | doubtful |
| 无语 | `indifferent` | bored |
| 坏笑 | `sarcastic` | jealous, envious |
| 感动 | `moved` | hopeful, nostalgic |
| 厌恶 | `disgusted` | disdainful, contemptuous |
| 好奇 | `curious` | curious |

完整标签列表见 [FishAudio Emotion Control](https://docs.fish.audio/developer-guide/core-features/emotions)。在 WebUI 里，每个情绪卡片都有「上传新图」下拉：选择已上传的图，就能让多个情绪共用一张立绘。

### 内置差分

- 平静 → 默认立绘
- 难过 → `emotions/teary.webp`（流泪）
- 害羞 / 疲惫 / 担心 / 感动 → `emotions/blank.webp`（呆脸）
- 困惑 / 无语 / 疲惫 → `emotions/frown.webp`
- 害怕 → `emotions/endure.webp`
- 其余未单独配置的视觉组按相近关系回退

`blank.webp` / `teary.webp` 目前带白边和未抠图内部，后续替换同名文件即可，不需要改配置。

> GalGame 仅在私聊开放。第一次进入直接说“进入gal模式”或发 `/gal start`；群聊会提示切到私聊。

## 配置

配置文件在 `data/config/astrbot_plugin_gal_choice_config.json`，也可以在 WebUI 插件配置里改。

| 配置项 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `mode_on_words` | string | 见默认配置 | 进入模式的说法；支持整条匹配和 `gal 题材` 前缀 |
| `mode_off_words` | string | 见默认配置 | 退出模式的说法，整条消息基本一致才触发 |
| `mode_idle_minutes` | int | `120` | 无互动自动退出模式的分钟数 |
| `option_ttl` | int | `600` | 选项有效秒数 |
| `bot_label` | string | `小鲸鱼` | 台词框前的名字标签 |
| `default_say` | string | `这几个方向，你想先聊哪个？` | 台词为空时的兜底 |
| `say_max_units` | float | `46` | 单行台词字数上限（中文算 1，半角约 0.55） |
| `dialogue_max_lines` | int | `3` | 单图最多对话行数（1~3） |
| `voice_line_gap_ms` | int | `1000` | 多行语音每句之间的静音毫秒数 |
| `gal_debounce_enabled` | bool | `true` | gal 模式内置防抖 |
| `gal_debounce_seconds` | float | `1.0` | 最后一条消息后的静默等待 |
| `gal_debounce_max_seconds` | float | `5.0` | 连续输入时最长等待 |
| `option_max_units` | float | `16` | 选项字数上限 |
| `free_option_hint` | string | `✎ 自己说点什么…` | 自由输入位文案，字母位固定为 0 |
| `free_input_enabled` | bool | `true` | 是否显示自由输入位 |
| `emotion_default_file` | string | `whale_girl_moe.webp` | 默认立绘 |
| `emotion_map` | dict | 见默认配置 | 表情 → 立绘文件 |
| `background_file` | string | 空 | 固定背景文件名 |
| `background_mode` | string | `session` | `session` / `random` / `fixed` |
| `background_blur` | int | `20` | 背景模糊 px |
| `box_alpha` | float | `0.94` | 对话框不透明度 |
| `show_icons` | bool | `true` | 右下角装饰图标 |
| `show_turn_label` | bool | `true` | 右下角“序章 / 第 N 幕” |
| `say_font_size` | int | `26` | 台词基准字号 |
| `image_quality` | int | `90` | 出图 JPEG 质量 |
| `render_backend` | string | `auto` | `auto` T2I→浏览器→Pillow；`browser` 本地浏览器；`pillow` Pillow；`remote` 只 T2I |
| `render_endpoint` | string | `""` | 首选文转图端点，多个用逗号分隔；留空用 AstrBot 全局 T2I，失败会自动尝试端点池 |
| `voice_enabled` | bool | `true` | 台词配音总开关 |
| `voice_probability` | float | `1.0` | 每条台词配音概率 |
| `tts_provider_id` | string | 空 | 指定 TTS 提供商；留空用当前会话 |
| `tts_emotion_mode` | string | `auto` | `auto` / `fishaudio` / `off` |
| `gal_provider_id` | string | 空 | gal 模式固定模型；留空跟随会话。指定后会临时切换本会话 provider，退出/停用插件时恢复原模型 |
| `avatar_enabled` | bool | `true` | 是否显示提问者头像 |
| `avatar_size` | int | `100` | QQ 头像请求尺寸 |

## 工作原理

```text
用户私聊消息
  └─ gal_gate：私聊 + gal 模式 → 放行
      └─ gal_debounce：同一用户连续消息合并
          └─ inject_choice：注入剧本大纲、分支、好感/心情、结局和输出格式
              └─ 模型输出 <line>/<opt>/<affection>/<ending>
                  └─ decorate_result：解析 → HUD/选项/结局 → 出图
                      └─ after_message_sent → TTS 语音
```

- 模板在 `templates/gal.html`，所有用户文本都通过 Jinja2 的 `data` 传入并用 `|e` 转义，不拼进模板源码。
- 出图优先级：T2I → 本地 Chromium → Pillow；T2I 失败端点冷却，避免每轮等超时。
- 每轮会保存剧本、好感、心情、选项和分支状态；结局后停止普通 gal 回合。
- 状态在 `data/plugin_data/astrbot_plugin_gal_choice/sessions.json`，手动存档在 `saves.json`，均为原子写。
- 模型输出不合格、选项不足 2 个时降级为可读文字；结局回合允许没有选项。

## 常见问题

**Q：群里回 A 没反应？**  
A：GalGame 已改为仅私聊开放；群里发送 `/gal start` 会提示切到私聊。

**Q：图片没生成，发了一段文字？**  
A：说明 T2I 渲染失败或模型没给出 2 个以上选项。插件会发可读的文字选项，不会泄露 `<say>` 标签。检查 AstrBot 的文转图服务。

**Q：预览/出图一直转圈或超时？**  
A：WebUI 里拖动滑块用的是**本地草稿**，不会调用 T2I；只有点「生成最终图」才会请求远端。若最终图 502/503，插件会先试配置端点，再自动切换 AstrBot 端点池并重试；全部失败才报错。可以填一个或多个可用地址（逗号分隔），例如 `https://t2i.soulter.top/text2img,https://t2i.rcfortress.site/text2img`。

**Q：没有语音？**  
A：检查 AstrBot 的 TTS 是否启用、是否配置了提供商；`/gal voice` 看会话开关；FishAudio 之外提供商会自动去掉情绪标签。QQ 语音需要 `silk-python` 和 `ffmpeg`，插件会先转成 SILK 再发；如果日志出现 `ntsilk_s16le`，说明 NapCat 仍在尝试自己转码，通常是没有装依赖或插件版本过旧。

**Q：模型老是不按 `<say><opt>` 输出？**  
A：插件会尝试解析编号列表和代码块；仍失败就降级文字。建议用指令遵循较好的模型，或把 `/gal model` 指到更稳的模型。

**Q：能换角色/背景吗？**  
A：把立绘放进 `assets/`，在 `emotion_map` 里配置表情→文件；背景放进 `background/`，用 `background_file` 或 `background_mode` 选择。

## 隐私

- 头像通过 `q1.qlogo.cn` 获取提问者 QQ 头像；可在配置里关闭 `avatar_enabled`，关闭后显示昵称首字占位。
- 台词文本会发送给你配置的 TTS 提供商（如 FishAudio）。
- 会话状态只保存在本机 `data/plugin_data/astrbot_plugin_gal_choice/`，包含 QQ 号、会话 key、最近选项和选择摘要；`mode_idle_minutes` 到期会自动清理。
- 插件不发送遥测，不访问除头像/T2I/TTS 之外的网络。

## 兼容性

- 只声明支持 `aiocqhttp`（QQ 个人号 / NapCat）。语音依赖 OneBot 的 `Record`，头像依赖 QQ 头像接口。
- 其他平台理论上能出图，但语音、头像、`Record` 行为未验证，因此不在 `support_platforms` 里声明。
- 依赖 AstrBot 的 `html_render`、`on_llm_request`、`on_decorating_result`、`after_message_sent`、`ProviderManager.set_provider`，范围 `>=4.21,<5`；已在 **4.29.3** 实测。

## 开发

```bash
python -m unittest discover -s tests -t .
```

测试覆盖解析、选项匹配、状态 TTL/持久化、模板数据和路径穿越校验。

## 致谢与许可

- 本插件基于 [bvzrays/astrbot_plugin_qqgal](https://github.com/bvzrays/astrbot_plugin_qqgal) 修改，原项目为 **AGPL-3.0**。
- 立绘为 DeepSeek 娘二创形象；背景素材沿用上游插件；主界面 UI 为本项目重新绘制。
- 修改日期与修改说明见 [`NOTICE`](NOTICE)。

本项目按 **GNU Affero General Public License v3.0** 发布，见 [`LICENSE`](LICENSE)。由于上游是 AGPL-3.0，本插件也必须保持 AGPL-3.0 并公开源码；分发时请保留 `NOTICE` 和 `LICENSE`。
