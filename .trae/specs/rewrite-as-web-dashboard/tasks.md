# Tasks

## 阶段一：项目骨架与配置层

- [x] Task 1: 初始化项目结构与依赖
  - [ ] SubTask 1.1: 创建 `src/` 目录结构（`blueprints/` `config/` `plugins/` `static/` `templates/` `utils/`）
  - [ ] SubTask 1.2: 创建 `requirements.txt`（Flask、waitress、python-dotenv、requests、feedparser、pytz、psutil、pyyaml、recurring_ical_events、icalendar、yfinance、akshare、openai、google-genai、beautifulsoup4、Pillow 用于图片上传校验）
  - [ ] SubTask 1.3: 创建 `install/config_base/device.json`（含 `name` / `timezone` / `time_format` / `loop_enabled` / `startup` / `scheduler_sleep_time`，移除硬件键）
  - [ ] SubTask 1.4: 创建 `src/config/logging.conf` 与 `src/config/device_dev.json`
  - [ ] SubTask 1.5: 创建 `VERSION` 文件（v3.0.0-web）

- [x] Task 2: 实现配置存储层
  - [ ] SubTask 2.1: 移植 `src/config.py`，移除硬件键读写、`current_image_file`、`plugin_image_dir`，保留 `device.json` 原子写入与线程锁、`.env` 加载、`proxy` 设置、`plugin_order`、`plugin_last_settings_*`、`loop_manager`、`refresh_info`、`loop_override`
  - [ ] SubTask 2.2: 移植 `src/model.py` 全部（`RefreshInfo` / `LoopManager` / `Loop` / `PluginReference`），`RefreshInfo` 移除 `image_hash` 字段（无图像）

## 阶段二：插件系统与基类

- [x] Task 3: 实现插件注册与基类
  - [ ] SubTask 3.1: 移植 `src/plugins/plugin_registry.py`（`load_plugins` / `get_plugin_instance` / `PLUGIN_CLASSES`），加载逻辑不变
  - [ ] SubTask 3.2: 重写 `src/plugins/base_plugin/base_plugin.py`：移除 `AdaptiveImageLoader` 注入，将 `generate_image()` 替换为 `get_data(settings, device_config) -> dict`（抛 `NotImplementedError`），保留 `generate_settings_template()` / `cleanup()` / `get_loop_weight()` / `get_plugin_id()` / `get_plugin_dir()` / `FRAME_STYLES`
  - [ ] SubTask 3.3: 创建 `src/plugins/base_plugin/settings.html`（沿用原版样式设置模板）

## 阶段三：Flask 应用与蓝图

- [x] Task 4: 实现应用入口
  - [ ] SubTask 4.1: 重写 `src/dashpi.py`：初始化 `Config` / `RefreshTask`（仅状态查询服务，无线程渲染），`load_plugins()`，注册 5 个蓝图（`main` / `settings` / `plugin` / `loops` / `apikeys`），移除 `DisplayManager` 与 `WifiManager` 注入，waitress 启动（开发 8080，生产 80）
  - [ ] SubTask 4.2: 设置安全响应头（CSP 调整允许内联脚本以适配插件 dashboard.html，或改用 nonce），静态资源路由

- [x] Task 5: 实现 main 蓝图
  - [ ] SubTask 5.1: 移植 `src/blueprints/main.py`：保留 `/`（仪表盘首页）、`/display`（前端壳页面）、`/diagnostics`、`/api/plugin_order`、`/toggle_loop`、`/api/skip_to_next`、`/api/pin_plugin`、`/api/override_loop`、`/api/clear_override`、`/api/next_change_time`、`/api/weather_location`、`/api/diagnostics`
  - [ ] SubTask 5.2: 移除 `/api/current_image`、`/api/set_brightness`、`/api/clear_brightness_override`、`/api/display_capabilities`
  - [ ] SubTask 5.3: 新增 `/api/current_state` 端点返回 `{plugin_id, loop_name, remaining_seconds, next_plugin_id, override, loop_enabled}`，供前端轮询

- [x] Task 6: 实现 plugin 蓝图
  - [ ] SubTask 6.1: 移植 `src/blueprints/plugin.py`：保留 `/plugin/<id>` 设置页、`/images/<id>/<file>` 静态服务、`/upload_image`、`/check_files`、`/delete_image`、`/save_image_list`、`/update_now_async`、`/update_now`、stocks 子路由
  - [ ] SubTask 6.2: 移除 spotify_web kiosk 相关路由（`/plugin/spotify_web/start` 等）
  - [ ] SubTask 6.3: 修改 `/update_now` 与 `/update_now_async`：不再生成图像，改为触发 `RefreshTask` 记录刷新元数据 + 返回最新数据 JSON；保留设置保存到 `plugin_last_settings_<id>`
  - [ ] SubTask 6.4: 新增 `/api/plugin/<plugin_id>/data` 端点：实例化插件，调用 `get_data(settings, device_config)`，捕获 `RuntimeError` 返回 `{error}` + 500

- [x] Task 7: 实现 loops / settings / apikeys 蓝图
  - [ ] SubTask 7.1: 移植 `src/blueprints/loops.py` 全部（创建/编辑/删除/添加/移除/排序/间隔/设置/随机化/搜索城市/立即刷新）
  - [ ] SubTask 7.2: 移植 `src/blueprints/settings.py`，移除 `display_type` / `resolution` / `orientation` / `brightness_schedule` / `display_transitions` 相关字段与表单，保留 `name` / `timezone` / `time_format` / `proxy`
  - [ ] SubTask 7.3: 移植 `src/blueprints/apikeys.py`（`.env` 读写，API 密钥列表与更新）

## 阶段四：刷新引擎（状态查询服务）

- [x] Task 8: 重写刷新任务为状态服务
  - [ ] SubTask 8.1: 重写 `src/refresh_task.py`：移除后台渲染线程、`generate_image` 调用、`DisplayManager` 推送、WiFi 检查、AP 模式、`image_hash` 计算
  - [ ] SubTask 8.2: 保留 `LoopRefresh` / `ManualRefresh` / `AutoRefresh` 动作类作为状态标记，`RefreshTask` 提供 `determine_current_plugin()`（基于 `LoopManager.determine_active_loop` + `loop_override` + `loop_enabled`）与 `record_refresh(plugin_id, refresh_type, loop_name)`（写 `RefreshInfo` + 周期性 `write_config`）
  - [ ] SubTask 8.3: 保留 `signal_config_change()` 用于配置变更时让前端下次轮询生效（通过返回新的 `current_state`）
  - [ ] SubTask 8.4: `queue_manual_update()` 改为立即记录手动刷新并返回（无需异步队列，因为不再有耗时渲染）

## 阶段五：前端显示壳页面

- [x] Task 9: 实现显示壳页面
  - [ ] SubTask 9.1: 重写 `src/templates/display.html`：全屏布局，包含 `#dashboard-container` 容器，引入 `static/js/display.js`
  - [ ] SubTask 9.2: 创建 `src/static/js/display.js`：每秒轮询 `/api/current_state`，当 `plugin_id` 变化时 fetch `/plugin/<id>/dashboard.html` 片段插入容器，再触发该片段内的脚本加载数据；按插件 `refresh_interval_seconds` 重复 fetch `/api/plugin/<id>/data` 更新
  - [ ] SubTask 9.3: 处理错误态（数据 API 返回 500 时显示错误提示）、无活动 Loop 占位、Pin 状态
  - [ ] SubTask 9.4: 提供 `plugin-settings-ready` 事件机制，让各插件 dashboard.html 在加载完成后自行初始化

## 阶段六：管理 UI 模板

- [x] Task 10: 移植并精简管理模板
  - [ ] SubTask 10.1: 移植 `src/templates/dash.html`（仪表盘首页），移除亮度滑块与显示能力区块，保留插件网格、Loop 状态、Pin/Override 按钮、跳过下一个、倒计时显示
  - [ ] SubTask 10.2: 移植 `src/templates/plugin.html`（插件设置页），保留表单渲染与 `pluginSettings` 预填充 JS
  - [ ] SubTask 10.3: 移植 `src/templates/loops.html`（Loop 管理页）
  - [ ] SubTask 10.4: 移植 `src/templates/settings.html`（设备设置页），移除硬件相关表单
  - [ ] SubTask 10.5: 移植 `src/templates/apikeys.html`（API 密钥页）
  - [ ] SubTask 10.6: 移植 `src/templates/diagnostics.html`（诊断页）
  - [ ] SubTask 10.7: 移植 `src/templates/refresh_settings_form.html`、`response_modal.html`
  - [ ] SubTask 10.8: 移动 `static/icons/`、`static/fonts/`（保留 Jost、DS-Digital 等仍被设置页使用的字体）

## 阶段七：工具模块

- [x] Task 11: 移植并精简工具模块
  - [ ] SubTask 11.1: 移植 `src/utils/app_utils.py`（`resolve_path` / `get_font` / `handle_request_files` / `parse_form` / `sanitize_filename`）
  - [ ] SubTask 11.2: 移植 `src/utils/http_client.py`（`get_http_session`）
  - [ ] SubTask 11.3: 移植 `src/utils/text_utils.py`（`get_text_dimensions` / `truncate_text` / `draw_multiline_text`）— 仅后端设置页预览或诊断用到时保留，否则可删
  - [ ] SubTask 11.4: 移植 `src/utils/time_utils.py`（`calculate_seconds` 等）
  - [ ] SubTask 11.5: 移植 `src/utils/layout_utils.py`（`draw_rounded_rect` / `calculate_grid`）— 仅插件仍用则保留，否则删
  - [ ] SubTask 11.6: 不移植 `image_loader.py` / `image_utils.py` / `wifi_manager.py` / `wifi_display.py` / `bluetooth_manager.py`

## 阶段八：插件移植（25 个）

- [x] Task 12: 移植无 API Key 插件（数据型）
  - [ ] SubTask 12.1: `clock` — `get_data` 返回 `{time, date, face, colors}`，`dashboard.html` 用 JS 渲染四种面（Gradient/Digital/Divided/Word）
  - [ ] SubTask 12.2: `countdown` — `get_data` 返回 `{title, date, days, label}`，前端渲染
  - [ ] SubTask 12.3: `year_progress` — `get_data` 返回 `{year, percent, days_left}`，前端进度条
  - [ ] SubTask 12.4: `todo_list` — `get_data` 返回 `{title, lists[]}`，前端列表渲染
  - [ ] SubTask 12.5: `calendar` — `get_data` 返回 `{events[], viewMode, ...}`，前端用 FullCalendar 或自绘
  - [ ] SubTask 12.6: `newspaper` — `get_data` 返回 `{image_url, title}`，前端 `<img>`
  - [ ] SubTask 12.7: `comic` — `get_data` 返回 `{image_url, title, caption}`，前端 `<img>`
  - [ ] SubTask 12.8: `rss` — `get_data` 返回 `{items[], title}`，前端列表
  - [ ] SubTask 12.9: `wpotd` — `get_data` 返回 `{image_url, title, description}`，前端 `<img>`
  - [ ] SubTask 12.10: `art_museum` — `get_data` 返回 `{image_url, title, artist, year}`，前端 `<img>` + 叠加
  - [ ] SubTask 12.11: `astro_targets` — `get_data` 返回 `{targets[], moon_phase}`，前端表格 + 图标
  - [ ] SubTask 12.12: `iss_tracker` — `get_data` 返回 `{iss_pos, ground_track, next_pass, crew_count}`，前端用 Leaflet 地图
  - [ ] SubTask 12.13: `flight_tracker` — `get_data` 返回 `{aircraft[], map_bounds}`，前端 Leaflet + 标记
  - [ ] SubTask 12.14: `github` — `get_data` 返回 `{type, contributions|sponsors|stars}`，前端热力图/列表/曲线（Chart.js）

- [x] Task 13: 移植图片类插件
  - [ ] SubTask 13.1: `image_url` — `get_data` 返回 `{url, fitMode}`，前端 `<img>` + object-fit
  - [ ] SubTask 13.2: `image_folder` — `get_data` 返回 `{image_path}`（随机选一张，后端扫描），前端 `<img>`
  - [ ] SubTask 13.3: `image_upload` — `get_data` 返回 `{image_path}`（按索引轮播），前端 `<img>`；保留上传 API
  - [ ] SubTask 13.4: `image_album` — `get_data` 返回 `{image_url}`（Immich/Google 随机），前端 `<img>`
  - [ ] SubTask 13.5: `unsplash` — `get_data` 返回 `{image_url, photographer}`，前端 `<img>` + 署名

- [x] Task 14: 移植 API Key 插件
  - [ ] SubTask 14.1: `weather` — `get_data` 返回 `{current, hourly[], daily[], moon_phase, units}`，前端用图标 + 图表渲染
  - [ ] SubTask 14.2: `stocks` — `get_data` 返回 `{stocks[{symbol, name, price, change, hist[]}]}`，前端卡片 + 迷你图（Chart.js）
  - [ ] SubTask 14.3: `apod` — `get_data` 返回 `{image_url, title, explanation}`，前端 `<img>` + 说明
  - [ ] SubTask 14.4: `ai_image` — `get_data` 返回 `{image_url, title}`（后端生成并返回 URL），前端 `<img>`
  - [ ] SubTask 14.5: `ai_text` — `get_data` 返回 `{title, text}`，前端文本渲染
  - [ ] SubTask 14.6: `github`（已在 Task 12.14 覆盖，API Key 为 GITHUB_SECRET）

- [x] Task 15: 移植特殊插件
  - [ ] SubTask 15.1: `spotify_web` — 改为前端 iframe 嵌入 Spotify Web Player 或外链，移除 kiosk 进程管理；`get_data` 返回 `{embed_url, logged_in_hint}`；`dashboard.html` 用 iframe
  - [ ] SubTask 15.2: `shazam_pi` — 标记实验性，前端 `dashboard.html` 尝试 `getUserMedia` 录音 + Web Audio API + 调用后端识别 API；后端保留 TFLite + shazamio 作为 fallback；`get_data` 返回 `{status, song?, artist?, album_art?}`

## 阶段九：静态资源与字体

- [x] Task 16: 迁移静态资源
  - [ ] SubTask 16.1: 复制 `static/fonts/Jost*.ttf`、`DS-DIGI/DS-DIGI.TTF`（设置页与前端时钟面可能用到）
  - [ ] SubTask 16.2: 复制 `static/icons/`（favicon、设置/编辑/删除图标）
  - [ ] SubTask 16.3: 复制各插件 `icon.png` 与 `resources/`（weather 图标、iss_tracker 地图、astro_targets targets.json 等）
  - [ ] SubTask 16.4: 引入前端库（Chart.js、Leaflet、FullCalendar 可选）via CDN 或 `static/vendor/`

## 阶段十：测试与文档

- [x] Task 17: 编写测试
  - [ ] SubTask 17.1: 移植 `tests/test_config.py`、`tests/test_model.py`、`tests/test_blueprints.py`（调整断言移除硬件键）
  - [ ] SubTask 17.2: 新增 `tests/test_plugin_data_api.py` 测试 `/api/plugin/<id>/data` 端点
  - [ ] SubTask 17.3: 新增 `tests/test_current_state.py` 测试 `/api/current_state` 返回结构
  - [ ] SubTask 17.4: 创建 `pytest.ini`

- [ ] Task 18: 编写部署说明（仅当用户后续要求时）
  - [ ] SubTask 18.1: README 说明如何在树莓派桌面版设置 Chromium 开机全屏打开 `/display`
  - [ ] SubTask 18.2: 可选的 systemd 服务用于启动 waitress（非劫持 framebuffer）

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 2
- Task 4 依赖 Task 2、Task 3
- Task 5、6、7、8 依赖 Task 4
- Task 9 依赖 Task 5（`/api/current_state`）、Task 6（`/api/plugin/<id>/data`）
- Task 10 依赖 Task 5、6、7
- Task 11 可与 Task 5-7 并行
- Task 12、13、14、15 依赖 Task 3、9、11
- Task 16 可与 Task 12-15 并行
- Task 17 依赖 Task 12-15 完成
- Task 18 最后
