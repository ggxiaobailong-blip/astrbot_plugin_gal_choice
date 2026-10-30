# Changelog

## 0.4.5 - 2026-10-30

- 出图优先级改为 **T2I → 本地 Chromium HTML/CSS → Pillow**；`auto` 的 T2I 尝试最多 15 秒，失败后立即切本地，不让坏端点拖满 90 秒；失败端点冷却 180 秒，后续轮次直接走本地，避免连续等待。
- 旧配置值 `render_backend=local` 自动迁移为 `auto`；想强制 Pillow 请选 `pillow`。
- 恢复左上角 `GAL MODE` 标签；HTML 模板和 Pillow 兜底都保留该元素，界面布局不缺东西。
- WebUI 出图方式同步改为 T2I 优先描述。
- 保留 `render_backend=browser/local/remote` 供手动指定。

## 0.4.4 - 2026-10-30

- 新增本地 Chromium/Playwright 出图：直接截图真实 HTML/CSS 模板，效果与 T2I 一致（图标、幕数、选项卡、阴影全部保留），不经过网络。
- 默认 `render_backend=auto`：有本地 Chromium 时用浏览器，没装浏览器时用改进后的 Pillow，再失败才回退远程 T2I。
- 修复底栏「第 N 幕」被右下角图标遮挡：HTML footer 和 Pillow 底栏都留出图标区域。
- Pillow 兜底补全 6 个控件图标，不再只画 4 个占位条。
- 本地浏览器渲染依赖 Playwright + Chromium；可用 `python -m playwright install chromium` 安装，未安装会自动走 Pillow。

## 0.4.3 - 2026-10-30

- 新增本地 Pillow 出图，默认 `render_backend=local`，不再依赖远程 T2I；单张出图从数秒降到本地几十毫秒，且不会因 t2i 502/503 失败。
- 本地渲染复用同一套立绘、背景、选项、2~3 行对话和外观配置；内置 Droid Sans Fallback 字体，无系统中文字体也能正常显示。
- 保留 `render_backend=remote` 作为可选后端；本地渲染异常时才回退远程 T2I。
- 新增 WebUI「出图方式」选择。

## 0.4.2 - 2026-10-30

- 修复插件未出现在 WebUI 插件列表的问题：移除错误的 `@register` 装饰位置，改为主类 `GalChoicePlugin` 自动识别，WebUI 可正常看到插件和配置页。
- 内置防抖不再对 `reply_merge` 自动让位：gal 插件自身完整负责防抖，新用户不需要额外安装防抖插件；README 提示不要同时启用外部防抖。
- 防抖逻辑保持按用户合并、静默 1 秒、最长 5 秒，支持主消息选项匹配 + 补充消息上下文。

## 0.4.1 - 2026-10-30

- 新增 gal 模式内置防抖：同一用户连续消息在 `on_waiting_llm_request` 阶段合并，后续消息 donate 后 `stop_event`，只请求一次模型。
- 新增 `gal_debounce_enabled`、`gal_debounce_seconds`（默认 1.0s）、`gal_debounce_max_seconds`（默认 5s）以及 WebUI「外观」控件。
- 合并后的主消息用于选项匹配，补充消息作为同一轮上下文追加到 prompt；退出判断会同时检查主消息和补充消息。
- 检测到外部 `astrbot_plugin_reply_merge` 防抖时内置防抖自动让位，避免双重合并冲突。
- 旧 AstrBot 没有 waiting hook 时自动跳过内置防抖，不影响插件加载。

## 0.4.0 - 2026-10-30

- P0 多行对话：模型可用 2~3 个 `<line><emo>...</emo><say>...</say></line>` 输出连续台词；一张 1280×720 图内自适应排版，不额外增加 T2I 次数。
- 单图多行模板：首行显示角色名，后续行共享缩进；字号按 1/2/3 行和总字数自动收缩，最低 17px。
- 多行语音：每句独立 FishAudio 合成（保留各自情绪标签），按 `voice_line_gap_ms`（默认 1000ms）插入静音，再合成一条语音发送。
- 新增 `dialogue_max_lines`、`voice_line_gap_ms` 配置和 WebUI「外观」控件。
- 旧版单行 `<emo><say>` 格式继续兼容。

## 0.3.11 - 2026-10-30

- 修复 QQ 语音仍然被转成 WAV 的问题：AstrBot 的 `Record.convert_to_base64()` 会强制 `target_format="wav"`，把预转的 SILK 又转回 WAV，导致 NapCat 的 ntsilk 编码器报错。
- 新增 `_SilkRecord`：只覆盖 `convert_to_base64()`，直接发送 SILK 的 base64；普通 `Record` 仍用于非 QQ 平台。
- QQ 平台判断增加 `umo.startswith("bot:")` 兜底，避免平台名差异导致漏转。
- 服务器实测：直发 SILK 后 NapCat 日志为“语音文件已就绪 / 发送 -> 私聊 [语音 4s]”，没有 ntsilk 报错。

## 0.3.10 - 2026-10-30

- 强化 GalGame 角色视角：`<say>` 必须是角色第一人称直接对玩家说的话，禁止旁白、小说叙述、动作/环境/心理描写、第三人称和舞台提示。
- 所有阶段提示（开场、选项、自由输入、图片、模糊选项）统一改为“角色直接说话”，避免模型写成旁白。
- 增加错误/正确示例，例如“她轻轻叹了口气”应改成“这雨下得人心烦……你就打算一直站那儿看着我？”。
- `<opt>` 明确要求写成玩家可以直接说出口的回应。

## 0.3.9 - 2026-10-30

- 启动/退出改为模糊意图匹配：`gal启动！`、`启动gal`、`来玩gal`、`gal模式` 都能进入；`结束gal`、`gal结束`、`不玩了`、`退出`、`关闭` 都能退出。
- 退出优先级高于启动：`结束gal` 只退出，不会被 `gal` 关键词重新启动；`不要结束` 不会误退出。
- 群聊仍会先剥离 `@机器人` 前缀。

## 0.3.8 - 2026-10-30

- 修复群聊启动 gal 模式失败/返回 `<say>` 原始标签：
  - 群聊 `@机器人 gal启动` 会先剥离 @ 前缀再匹配触发词；
  - 默认触发词补充 `gal启动 / 启动gal / 开始gal模式 / 开启gal / 开gal`；
  - `on_decorating_result` 发现未进入会话但回复带 `<say>/<opt>` 时自动接管为本轮 gal 出图，避免标签泄漏。
- 群聊测试：`@iv小白龙 gal启动` 正常进入，未进入时带标签的回复也会转成图片。

## 0.3.7 - 2026-10-30

- 内置「无语」和「疲惫」改为和「困惑」共用 `emotions/frown.webp`。
- 其余情感映射保持不变。

## 0.3.6 - 2026-10-30

- 替换默认差分 `assets/whale_girl_moe.webp`，使用新抠图版本，1152×2048，保留透明通道。
- 默认立绘同时用于「开心 / 平静」以及未单独配置的视觉组回退。

## 0.3.5 - 2026-10-30

- 替换抠图后的 `blank.webp` / `teary.webp`，保留透明通道，尺寸 1152×2089。
- 内置「害怕」映射改为 `emotions/endure.webp`。
- 重新打包 0.3.5。

## 0.3.4 - 2026-10-30

- 新增内置差分：呆脸 `emotions/blank.webp`、流泪 `emotions/teary.webp`。
- 修正内置角色映射：平静 → 默认，难过 → 流泪，害羞/疲惫/担心/感动 → 呆脸，困惑 → 皱眉。
- 内置映射改为按视觉组（happy/calm/sad...）读取，旧中文键配置自动忽略，避免旧图覆盖新映射。
- 新增两个差分白边/内部未抠图，后续替换同名文件即可。

## 0.3.3 - 2026-10-30

- 立绘改为固定显示框 + `object-fit: contain`，只按原图比例缩放，不再被拉伸/挤扁。
- 位置滑块改为「立绘高度上限 / 立绘宽度上限」，避免误解为强制高度。
- WebUI 增加本地草稿预览：拖滑块即时更新，不调用 T2I；「生成最终图」才走远端渲染。
- 草稿使用背景/立绘缩略图组合，位置、比例和最终模板一致；T2I 生成失败时草稿仍然可用。

## 0.3.2 - 2026-10-30

- 修复 WebUI 上传时 `Plugin bridge endpoint is invalid`：bridge 不允许 endpoint 带查询参数，上传改为路径参数 `/upload/sprite/<角色>/<情绪>` 和 `/upload/background`。
- 优化预览速度：位置滑块只在松开时触发一次渲染，增加相同参数缓存；生成新图时保留上一张预览并显示“正在更新”。
- 新增 `character_id` / `emotion` 路径路由，旧 `/upload?...` 接口保留兼容。

## 0.3.1 - 2026-10-30

- 修复 WebUI 在 AstrBot 沙箱 iframe 中 `window.prompt` / `window.confirm` 被禁用，导致「新建角色」无反应：改为侧栏内联输入，删除改为二次确认。
- 修复位置滑块预览不生效：`preview` 接口现在接收当前 layout 覆盖值，拖动即可看到位置/高度/宽度变化，保存后持久化。
- 修复拖动滑块时预览请求并发丢弃最后一次更新，增加 pending 重绘。
- 修复内置角色新增情绪组没有对应差分时直接落到默认图的问题，改为映射到最接近的内置立绘。

## 0.3.0 - 2026-10-30

- 新增 `views/settings/` WebUI 资源工作台：角色管理、默认立绘 + 18 类情绪差分上传、背景上传/选择、可视化位置与尺寸调整、实时预览。
- 修复 WebUI 在 AstrBot 沙箱 iframe 中 `window.prompt` / `window.confirm` 被禁用，导致「新建角色」无反应：改为侧栏内联输入，删除改为二次确认。
- 修复位置滑块预览不生效：`preview` 接口现在接收当前 layout 覆盖值，拖动即可看到位置/高度/宽度变化，保存后持久化。
- 修复拖动滑块时预览请求并发丢弃最后一次更新，增加 pending 重绘。
- 新增用户资源库 `data/plugin_data/astrbot_plugin_gal_choice/assets/`，自定义立绘/背景与插件更新解耦。
- 立绘位置改为每个角色独立保存：水平位置、垂直位置、高度、最大宽度。
- 角色支持多个自定义档案，可切换、重命名、删除；内置角色只读但位置可调。
- `characters.json` 原子持久化，上传文件做扩展名/图片头/路径穿越校验，单张上限 12MB。
- 新增 18 类视觉情绪组，覆盖 FishAudio 49 个情绪标签；同一张立绘可通过 WebUI 下拉共用给多个情绪。
- 新增 `/sprite/bind`，允许把已上传的立绘绑定到另一个情绪标签。
- 文转图增加首选端点 + AstrBot 端点池 + 502/503 自动重试，端点池全部失败才报错。
- 新增 `render_endpoint` 配置与 WebUI「文转图端点」，可填一个或多个端点，规避单个端点故障。
- 内嵌立绘/背景在渲染前压缩为紧凑 WebP/JPEG，显著降低远端 T2I 的上传体积，减少超时。
- 新增 `core/assets.py`、`core/webui.py`、`core/render_utils.py` 和后台 Web API；`metadata.repo` 填为 GitHub 仓库地址。
- 版本号更新为 `0.3.0`。

## 0.2.0 - 2026-10-30

- 重构为 `core/` 模块：配置、状态、解析、提示词、渲染、语音。
- 重绘界面：角色左移、对话框更实、两行台词、选项标题、自由输入位改为 `0`。
- 新增 `/gal` 指令组：`start`、`stop`、`status`、`model`、`voice`、`reset`、`help`。
- 修复群聊里裸字母无法触发 LLM 的问题（显式设置 `is_at_or_wake_command`）。
- 修复 QQ 语音：NapCat 自带 ffmpeg 缺少 `ntsilk_s16le` 编码器，插件现在先用 `silk-python` + ffmpeg 预转 Tencent SILK 再发，绕开 NapCat 转码失败。
- 新增 `requirements.txt`（`silk-python`），QQ 语音不再依赖 NapCat 的 ffmpeg 编码能力。
- 修复裸 `gal` 被指令组当成“参数不足”的问题：改为单条 `/gal [start|stop|status|model|voice|reset|help]` 指令。
- gal 模式抑制模型思考过程，避免 `🤔 思考: ...` 出现在图片前面；引用栏清理 `[MSG_ID:...]`。
- 核心模块改用 `astrbot.api.logger`，修复插件日志缺少 `plugin_tag` 导致的配音误报失败。
- 修复进入/退出词子串误触发；改为整句精确匹配。
- 状态迁移到 `data/plugin_data/`，增加 TTL、原子写、会话上限与并发锁。
- 删除 `pysilk` / `ffmpeg` / `voice_cache`，改用 AstrBot 的 `Record` 链路。
- 模板改为静态 Jinja2 文件，用户文本通过 `data` + `|e` 传入，消除模板注入。
- 解析器支持代码块、编号列表、`A.` 列表、缺少闭合标签等兜底。
- 出图失败/选项不足 2 个时降级为可读文字，不再泄露 `<say><opt>`。
- 新增资源路径校验、状态损坏容错、头像开关、TTS 提供商/情绪模式配置。
- 压缩资源到约 2MB，移除 `src_png`、`bg_src`、开发工具与重复立绘。
- 增加 `logo.png`、`README.md`、`NOTICE`、`LICENSE`（AGPL-3.0）、单元测试。

## 0.1.0

- 初版：gal 模式、选项图、表情立绘、自由输入、TTS、状态续接。
