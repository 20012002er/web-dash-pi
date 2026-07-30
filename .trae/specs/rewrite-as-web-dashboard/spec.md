# Web DashPi 重写 Spec

## Why

OpenClaw-DashPi 通过劫持树莓派显示输出并绘制 PIL 图像来呈现仪表盘，每种显示硬件（LCD/Inky/Waveshare）都需要独立驱动，渲染能力受限于图像绘制。将其重写为纯 Web 形式：仪表盘直接以网页渲染，浏览器负责显示，后台仍用插件管理各仪表盘。这样可消除硬件驱动依赖、获得更丰富的渲染能力（图表/地图/动画/视频），并降低部署门槛（无需 systemd 劫持 framebuffer）。

## What Changes

### 架构变更
- **渲染方式**：插件不再实现 `generate_image() -> PIL.Image`，改为提供前端视图（`dashboard.html` + JS）与后端数据接口（`get_data() -> dict`），由浏览器渲染
- **显示层**：移除 `display/` 硬件驱动层（LCD/Inky/Waveshare/Mock），改为浏览器全屏打开 `/display` 页面
- **刷新引擎**：原后台 `RefreshTask` 线程渲染图像推送硬件，改为前端轮询当前活动插件并加载其视图；Loop 调度与状态仍由后端计算与持久化
- **插件契约**：`BasePlugin.generate_image()` → `BasePlugin.get_data()`；新增 `dashboard.html` 前端视图文件

### 保留的核心能力
- 插件化架构（动态发现、`plugin-info.json` 注册、`plugin_registry.py` 加载）
- 配置存储（`device.json` + 原子写入 + 线程安全）
- 数据模型（`LoopManager` / `Loop` / `PluginReference` / `RefreshInfo`）
- Loop 调度（按时段、跨午夜、随机权重、Pin 固定、Override）
- 自动刷新（每个插件可配置刷新间隔，前端按间隔轮询数据 API）
- Web 管理 UI（仪表盘首页、插件设置、Loop 管理、设备设置、API 密钥）
- 手动更新 / 跳过下一个 / 固定插件 / 覆盖 Loop
- 多设备友好（hostname.local 访问）
- 诊断面板（psutil 采集 Pi 系统指标）
- API 密钥管理（`.env` 读写）
- 图片上传 / 删除 / 文件校验

### 移除的能力（硬件相关，Web 版无需）
- **BREAKING** 显示硬件自动检测（Inky I2C / LCD framebuffer / Waveshare SPI）
- **BREAKING** 显示驱动层（`lcd_display` / `inky_display` / `waveshare_display` / `mock_display`）
- **BREAKING** 背光亮度调度（`brightness_schedule`，硬件 sysfs 背光控制）
- **BREAKING** LCD 过渡动画（`display_transitions`，硬件相关）
- **BREAKING** WiFi AP 模式 / Captive Portal（OS 级配网，超出 Web 应用范围）
- **BREAKING** 开机启动画面 / splash 服务 / 内核 cmdline 静默启动
- **BREAKING** systemd 服务 / CPU与内存限额 / swap 扩容 / earlyoom（部署期可选，不在应用 spec 内）
- **BREAKING** Chrome 无头模式 HTML→PNG 渲染（不再需要，浏览器直接渲染）
- **BREAKING** 图像处理流水线（方向旋转/缩放/增强/过渡，改由前端 CSS 处理）
- **BREAKING** PWA manifest / service worker（可选保留，但非核心）

### 调整的能力
- **设备配置**：移除 `display_type` / `resolution` / `orientation` / `inverted_image` / `brightness_schedule` / `display_transitions`；保留 `name` / `timezone` / `time_format` / `loop_config` / `loop_enabled` / `loop_override` / `refresh_info` / `plugin_order` / `plugin_last_settings_*` / `proxy`
- **刷新信息**：`RefreshInfo` 仍记录上次刷新元数据，供管理 UI 显示；不再存图像哈希（无图像）
- **图片处理工具**：`utils/image_utils.py`（`pad_image_blur` 等）与 `AdaptiveImageLoader` 不再需要；图片类插件直接返回 URL，由前端 `<img>` 渲染
- **ShazamPi**：原依赖 USB 麦克风 + TFLite，Web 版需麦克风权限（Web Audio API）或保留为后端录音插件（降级支持，标记为实验性）
- **Spotify Web**：原通过 Chromium kiosk 劫持 framebuffer，Web 版直接在前端 iframe 嵌入或链接，无需 kiosk 进程管理

## Impact

- **Affected specs**: 无（新项目，首份 spec）
- **Affected code**（参考来源 `OpenClaw-DashPi/src/`）:
  - 复用：`config.py`、`model.py`、`blueprints/main.py`、`blueprints/loops.py`、`blueprints/settings.py`、`blueprints/apikeys.py`、`blueprints/plugin.py`（部分）、`utils/app_utils.py`、`utils/http_client.py`、`utils/text_utils.py`、`utils/time_utils.py`、`utils/layout_utils.py`（部分）、`plugins/plugin_registry.py`、`plugins/base_plugin/base_plugin.py`
  - 重写：`dashpi.py`（移除 DisplayManager/WifiManager 注入）、`refresh_task.py`（改为状态查询服务，非渲染线程）、所有插件的 `generate_image` → `get_data` + 新增 `dashboard.html`
  - 移除：`display/` 整个目录、`utils/image_loader.py`、`utils/image_utils.py`、`utils/wifi_manager.py`、`utils/wifi_display.py`、`utils/bluetooth_manager.py`、`templates/display.html`（原 PNG 轮询页）、`templates/wifi_setup.html`、`blueprints/wifi.py`、`blueprints/bluetooth.py`、`static/images/current_image.png`
  - 新增：`templates/display.html`（前端仪表盘壳页面）、各插件 `dashboard.html`、`static/js/display.js`（前端轮询与视图加载逻辑）

## ADDED Requirements

### Requirement: Web 仪表盘显示
系统 SHALL 提供一个 `/display` 路由，返回全屏浏览器视图，该视图根据当前活动 Loop 与插件动态加载对应插件的 `dashboard.html` 视图并渲染。

#### Scenario: 正常轮播
- **WHEN** 浏览器打开 `/display` 且 Loop 已启用
- **THEN** 视图加载当前活动 Loop 的当前插件，渲染其 `dashboard.html`，并在轮播间隔到期后切换到下一个插件

#### Scenario: 无活动 Loop
- **WHEN** 当前时间无任何活动 Loop 或 Loop 为空
- **THEN** 视图显示占位提示（如"无活动仪表盘"），并保持轮询状态

#### Scenario: 插件固定（Pin）
- **WHEN** 管理员通过 `/api/pin_plugin` 固定某插件
- **THEN** 显示视图在下次轮询时加载该固定插件，忽略 Loop 调度，直到调用 `/api/clear_override`

### Requirement: 插件前端视图契约
每个插件 SHALL 在其目录下提供 `dashboard.html` 文件，该文件 SHALL 包含完整的 HTML 片段（不含 `<html>`/`<head>`/`<body>` 包裹），可被加载到显示壳页面的容器中。插件前端视图 SHALL 通过调用 `/api/plugin/<plugin_id>/data` 获取后端数据并自行渲染。

#### Scenario: 视图加载与数据获取
- **WHEN** 显示视图加载插件 `weather` 的 `dashboard.html`
- **THEN** 该视图内的脚本请求 `/api/plugin/weather/data`，后端返回 `{settings: {...}, data: {...}}`，视图据此渲染天气仪表盘

#### Scenario: 自动刷新
- **WHEN** 插件配置了 `refresh_interval_seconds`
- **THEN** 视图按该间隔重复请求 `/api/plugin/<id>/data` 并更新渲染，无需整页刷新

### Requirement: 插件后端数据契约
每个插件 SHALL 实现后端方法 `get_data(settings, device_config) -> dict`，返回前端渲染所需的全部数据（JSON 可序列化）。该方法 SHALL 替代原 `generate_image()`。

#### Scenario: 数据获取成功
- **WHEN** 前端请求 `/api/plugin/weather/data`
- **THEN** 后端实例化 Weather 插件，调用 `get_data(settings, device_config)`，返回包含当前天气、预报、小时曲线等的字典

#### Scenario: 数据获取失败
- **WHEN** 插件 `get_data` 抛出 `RuntimeError`（如 API key 无效、网络失败）
- **THEN** 后端返回 `{"error": "面向用户的清晰错误信息"}` 与 500 状态码，前端视图显示错误提示

### Requirement: Loop 调度状态查询
系统 SHALL 提供 `/api/current_state` 端点，返回当前应显示的插件 ID、所属 Loop、轮播剩余秒数、是否被 Pin 等信息，供前端轮询决策。

#### Scenario: 查询当前状态
- **WHEN** 前端定期请求 `/api/current_state`
- **THEN** 返回 `{plugin_id, loop_name, remaining_seconds, next_plugin_id, override}`，前端据此决定是否切换视图

### Requirement: 插件设置页保留
系统 SHALL 保留原 `/plugin/<plugin_id>` 设置页，渲染插件 `settings.html` 表单，保存设置到 `plugin_last_settings_<id>` 与 Loop 内 `plugin_settings`。

#### Scenario: 编辑插件设置
- **WHEN** 用户在管理 UI 修改天气插件位置并提交
- **THEN** 后端保存到 `plugin_last_settings_weather`，下次显示视图加载时使用新设置

## MODIFIED Requirements

### Requirement: 配置存储
系统 SHALL 继续使用 `device.json` 单文件存储设备配置，采用临时文件 + `os.replace` 原子写入与 `threading.Lock` 线程安全。配置字段 SHALL 移除硬件相关键（`display_type` / `resolution` / `orientation` / `inverted_image` / `brightness_schedule` / `display_transitions`），保留 `name` / `timezone` / `time_format` / `loop_config` / `loop_enabled` / `loop_override` / `refresh_info` / `plugin_order` / `plugin_last_settings_*` / `proxy` / `scheduler_sleep_time` / `startup`。

### Requirement: 插件注册与加载
系统 SHALL 继续通过扫描 `plugins/` 目录下含 `plugin-info.json` 的子目录发现插件，使用 `importlib` 动态加载插件类并实例化。`plugin-info.json` 字段保持 `display_name` / `id` / `class` / `repository`（可选）。加载后插件类 SHALL 实现 `get_data()` 而非 `generate_image()`。

### Requirement: Loop 管理
系统 SHALL 保留 `LoopManager` / `Loop` / `PluginReference` 数据模型与全部 Loop API（创建/编辑/删除/添加插件/移除/排序/随机化/更新间隔/覆盖/清除覆盖）。Loop 调度逻辑（按时段、跨午夜、优先级、随机权重、预计算下一个）保持不变。

### Requirement: 管理 Web UI
系统 SHALL 保留原 6 个 Flask 蓝图中的 5 个（移除 `wifi`）：`main`（仪表盘首页、显示、诊断、Loop 控制、当前状态、亮度—亮度相关移除）、`settings`（设备设置）、`plugin`（插件列表、设置页、图片上传/删除、更新）、`loops`（Loop CRUD）、`apikeys`（API 密钥管理）。所有管理页面 SHALL 通过 Jinja2 模板渲染。

### Requirement: 诊断面板
系统 SHALL 保留 `/diagnostics` 页面与 `/api/diagnostics` 端点，通过 `psutil` 采集 CPU/内存/磁盘/温度/负载/运行时长/网络 IO/应用进程指标。WiFi 信号强度字段在非 Linux 平台允许返回 null。

## REMOVED Requirements

### Requirement: 显示硬件驱动层
**Reason**: Web 版由浏览器渲染，不再需要 LCD/Inky/Waveshare 硬件驱动。
**Migration**: 无需迁移。原 `display/` 目录整体删除，`DisplayManager` 移除，`dashpi.py` 不再注入显示管理器。

### Requirement: 背光亮度调度
**Reason**: 浏览器无法控制物理背光，亮度由显示器硬件/OS 电源管理决定。
**Migration**: `brightness_schedule` 配置键废弃。管理 UI 移除亮度设置区块与首页亮度滑块。`/api/set_brightness` 与 `/api/clear_brightness_override` 端点移除。

### Requirement: WiFi AP 模式与 Captive Portal
**Reason**: OS 级配网超出 Web 应用范围；树莓派桌面版可通过图形界面或 `raspi-config` 配网。
**Migration**: `blueprints/wifi.py`、`utils/wifi_manager.py`、`utils/wifi_display.py`、`templates/wifi_setup.html` 移除。`RefreshTask` 中的 WiFi 检查与 AP 进入逻辑移除。

### Requirement: 图像渲染流水线
**Reason**: 不再生成 PIL 图像，无需方向旋转/缩放/增强/过渡动画。方向与适配由前端 CSS 响应式处理。
**Migration**: `utils/image_utils.py`、`utils/image_loader.py` 移除。插件不再调用 `self.image_loader`。

### Requirement: Chrome 无头渲染
**Reason**: 浏览器直接渲染 HTML，无需后端 HTML→PNG 转换。
**Migration**: 移除 Chrome/headless 依赖与查找逻辑。`install/debian-requirements.txt` 中的 `chromium-headless-shell` 移除。

### Requirement: 开机启动画面与 systemd 静默启动
**Reason**: 树莓派桌面版直接打开浏览器即可，无需 splash 动画与 framebuffer 劫持。
**Migration**: `install/dashpi-splash.service`、`install/generate_splash.py`、`install/show_splash.py`、`install/dashpi-fbcon.conf` 移除。部署文档改为指导用户设置浏览器开机全屏启动。

### Requirement: ShazamPi 硬件麦克风录音（降级）
**Reason**: Web 版优先使用浏览器 Web Audio API 录音；若不可用则降级为后端录音（保留 pyaudio 依赖）。
**Migration**: ShazamPi 插件标记为实验性，前端视图尝试 `getUserMedia`，失败时提示需后端录音支持。
