# Changelog

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
