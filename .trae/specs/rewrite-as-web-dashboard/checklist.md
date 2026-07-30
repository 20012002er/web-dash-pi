# Checklist

## 架构与配置
- [x] `device.json` 不再包含 `display_type` / `resolution` / `orientation` / `inverted_image` / `brightness_schedule` / `display_transitions` 键
- [x] `src/config.py` 保留原子写入（tempfile + os.replace）与 `threading.Lock` 线程安全
- [x] `src/config.py` 保留 `.env` 加载与 `proxy` 设置应用
- [x] `src/config.py` 保留 `plugin_order` / `plugin_last_settings_*` / `loop_manager` / `refresh_info` / `loop_override` 读写
- [x] `src/model.py` 的 `RefreshInfo` 不再含 `image_hash` 字段
- [x] `src/model.py` 的 `LoopManager` / `Loop` / `PluginReference` 调度逻辑（按时段、跨午夜、优先级、随机权重、预计算下一个）与原版一致

## 插件系统
- [x] `src/plugins/plugin_registry.py` 仍通过扫描 `plugins/` + `plugin-info.json` + `importlib` 动态加载
- [x] `src/plugins/base_plugin/base_plugin.py` 的 `generate_image()` 已替换为 `get_data(settings, device_config) -> dict`
- [x] `BasePlugin` 保留 `generate_settings_template()` / `cleanup()` / `get_loop_weight()` / `get_plugin_id()` / `get_plugin_dir()`
- [x] `BasePlugin` 不再注入 `AdaptiveImageLoader`
- [x] 每个插件目录含 `dashboard.html` 前端视图片段（不含 html/head/body 包裹）

## Flask 应用
- [x] `src/dashpi.py` 不再注入 `DisplayManager` 或 `WifiManager`
- [x] 注册 5 个蓝图：`main` / `settings` / `plugin` / `loops` / `apikeys`（移除 `wifi` / `bluetooth`）
- [x] waitress 启动端口（开发 8080，生产 80）

## main 蓝图
- [x] 保留 `/`（仪表盘首页）、`/display`（前端壳页面）、`/diagnostics`
- [x] 保留 `/api/plugin_order`、`/toggle_loop`、`/api/skip_to_next`、`/api/pin_plugin`、`/api/override_loop`、`/api/clear_override`、`/api/next_change_time`、`/api/weather_location`、`/api/diagnostics`
- [x] 移除 `/api/current_image`、`/api/set_brightness`、`/api/clear_brightness_override`、`/api/display_capabilities`
- [x] 新增 `/api/current_state` 返回 `{plugin_id, loop_name, remaining_seconds, next_plugin_id, override, loop_enabled}`

## plugin 蓝图
- [x] 保留 `/plugin/<id>` 设置页、`/images/<id>/<file>`、`/upload_image`、`/check_files`、`/delete_image`、`/save_image_list`、stocks 子路由
- [x] 移除 spotify_web kiosk 相关路由
- [x] `/update_now` 与 `/update_now_async` 不再生成图像，改为记录刷新元数据 + 返回数据 JSON
- [x] 新增 `/api/plugin/<plugin_id>/data` 端点：调用 `get_data()`，捕获 `RuntimeError` 返回 `{error}` + 500

## loops / settings / apikeys 蓝图
- [x] `loops.py` 全部路由保留（创建/编辑/删除/添加/移除/排序/间隔/设置/随机化/搜索城市/立即刷新）
- [x] `settings.py` 移除硬件相关字段表单，保留 `name` / `timezone` / `time_format` / `proxy`
- [x] `apikeys.py` 保留 `.env` 读写

## 刷新引擎
- [x] `src/refresh_task.py` 不再有后台渲染线程
- [x] 不再调用 `generate_image` 或推送图像到硬件
- [x] 不再有 WiFi 检查或 AP 模式逻辑
- [x] 提供 `determine_current_plugin()` 基于 LoopManager + override + loop_enabled
- [x] 提供 `record_refresh(plugin_id, refresh_type, loop_name)` 写 `RefreshInfo`
- [x] `queue_manual_update()` 改为立即记录并返回

## 前端显示壳
- [x] `src/templates/display.html` 全屏布局含 `#dashboard-container`
- [x] `src/static/js/display.js` 每秒轮询 `/api/current_state`
- [x] `plugin_id` 变化时 fetch `/plugin/<id>/dashboard.html` 插入容器
- [x] 按插件 `refresh_interval_seconds` 重复 fetch `/api/plugin/<id>/data` 更新
- [x] 处理错误态（数据 API 500 时显示错误提示）
- [x] 处理无活动 Loop 占位
- [x] 处理 Pin 状态

## 移除项验证
- [x] `src/display/` 目录不存在
- [x] `src/utils/image_loader.py`、`image_utils.py`、`wifi_manager.py`、`wifi_display.py`、`bluetooth_manager.py` 不存在
- [x] `src/blueprints/wifi.py`、`bluetooth.py` 不存在
- [x] `src/templates/wifi_setup.html` 不存在
- [x] `static/images/current_image.png` 不再被引用或生成
- [x] 不依赖 chromium / chrome-headless-shell

## 插件移植（25 个）
- [x] clock / countdown / year_progress / todo_list / calendar / newspaper / comic / rss / wpotd / art_museum / astro_targets / iss_tracker / flight_tracker / github（数据型）
- [x] image_url / image_folder / image_upload / image_album / unsplash（图片型）
- [x] weather / stocks / apod / ai_image / ai_text（API Key 型）
- [x] spotify_web（iframe 嵌入，无 kiosk）
- [x] shazam_pi（实验性，前端 getUserMedia + 后端 fallback）

## 测试
- [x] `tests/test_config.py` 通过（无硬件键断言）
- [x] `tests/test_model.py` 通过
- [x] `tests/test_blueprints.py` 通过（调整断言）
- [x] `tests/test_plugin_data_api.py` 通过
- [x] `tests/test_current_state.py` 通过
- [x] `pytest` 全部通过
