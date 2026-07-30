# DashPi（Web 版）

[English](README.md) | [简体中文](README.zh-CN.md)

一个面向树莓派（以及任何带浏览器的设备）的 Web 仪表盘显示系统。与原项目 [OpenClaw-DashPi](https://github.com/OpenClaw-DashPi/OpenClaw-DashPi) 通过劫持树莓派的 framebuffer 并绘制图片不同，DashPi 将仪表盘渲染为网页 —— 前端直接在桌面浏览器中运行，后端通过插件系统管理各仪表盘。

- **版本：** `3.0.0-web`
- **许可证：** Apache License 2.0
- **语言：** Python 3.10+（Flask + Waitress）

---

## 特性亮点

- **Web 优先渲染。** 每个插件提供 `dashboard.html` 片段和 `get_data()` API；显示壳（`/display`）每秒轮询 `/api/current_state`，加载当前插件的片段，再从 `/api/plugin/<id>/data` 拉取数据。
- **基于插件的仪表盘。** 内置 26 个插件，覆盖数据型、图片型、API Key 型和特殊型四类。
- **保留 Loop 调度逻辑。** `LoopManager` / `Loop` / `PluginReference` 维持原版的调度能力（按时段、跨午夜、优先级、随机权重、预计算下一个）。
- **保留管理界面。** 在浏览器中管理插件、Loop、设置、API 密钥和诊断信息。
- **无 framebuffer / 无 Chromium kiosk / 无 WiFi 管理器。** 作为普通的 Flask + Waitress 服务运行。

## 架构

```
浏览器（树莓派桌面）
   │  /display（HTML 壳页面）
   │  每秒轮询 /api/current_state
   ▼
Flask + Waitress（src/dashpi.py）
   │  蓝图：main / settings / plugin / loops / apikeys
   ▼
插件系统（src/plugins/*）
   │  BasePlugin.get_data(settings, device_config) -> dict
   │  dashboard.html（前端片段）
   ▼
配置层（src/config.py + src/model.py）
   │  device.json（原子写入）
   │  LoopManager / RefreshInfo / loop_override
```

## 项目结构

```
web-dash-pi/
├── src/
│   ├── dashpi.py              # Flask 入口（5 个蓝图，waitress）
│   ├── config.py              # 配置原子写入，.env 加载
│   ├── model.py               # RefreshInfo / LoopManager / Loop / PluginReference
│   ├── refresh_task.py        # 无状态的状态查询服务
│   ├── blueprints/            # main / settings / plugin / loops / apikeys
│   ├── plugins/               # 26 个插件 + base_plugin
│   ├── templates/             # 管理 UI + 显示壳
│   ├── static/                # js、css、字体、图标
│   └── utils/                 # app_utils、http_client、time_utils 等
├── tests/                     # pytest 测试套件
├── install/config_base/       # 初始 device.json
├── requirements.txt
├── pytest.ini
├── VERSION
└── LICENSE
```

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 开发模式运行（端口 8080）

```bash
python src/dashpi.py --dev
```

打开 `http://<树莓派-IP>:8080/` 进入管理界面，或 `http://<树莓派-IP>:8080/display` 查看全屏仪表盘。

### 3. 生产模式运行（端口 80）

```bash
sudo python src/dashpi.py
```

开机自启可配置为 `systemd` 服务，命令为 `python src/dashpi.py`（不带 `--dev`）。无需劫持 framebuffer。

### 4. Kiosk 模式打开仪表盘（可选）

在树莓派桌面上以全屏方式启动默认浏览器，指向 `http://localhost/display`：

```bash
chromium-browser --kiosk --noerrdialogs --disable-translate --no-first-run --fast --fast-start http://localhost/display
```

## 内置插件（26 个）

| 分类 | 插件 |
| --- | --- |
| 数据型 | clock、countdown、year_progress、todo_list、calendar、newspaper、comic、rss、wpotd、art_museum、astro_targets、iss_tracker、flight_tracker、github |
| 图片型 | image_url、image_folder、image_upload、image_album、unsplash |
| API Key 型 | weather、stocks、apod、ai_image、ai_text |
| 特殊型 | spotify_web（iframe 嵌入，无 kiosk）、shazam_pi（实验性，getUserMedia） |

每个插件目录包含：

- `<id>.py` —— 实现 `get_data(settings, device_config) -> dict`
- `plugin-info.json` —— 插件元数据
- `settings.html` —— 管理端设置表单片段
- `dashboard.html` —— 前端仪表盘片段（不含 `<html>`/`<head>`/`<body>` 包裹）
- `icon.png` —— 插件图标
- `resources/`、`icons/`、辅助模块 —— 视插件需要而定

## 前端事件协议

显示壳（`src/static/js/display.js`）会派发以下事件，让每个插件的 `dashboard.html` 可以自包含：

| 事件 | 触发时机 | 详情 |
| --- | --- | --- |
| `plugin-dashboard-loaded` | 插件片段插入容器后 | `{ pluginId }` |
| `plugin-data` | 从 `/api/plugin/<id>/data` 拉到新数据 | `{ pluginId, data }` |
| `plugin-data-error` | 拉取数据失败（HTTP 500） | `{ pluginId, error }` |

插件也可以调用以下 window 辅助方法：

- `window.setDataRefreshInterval(ms)` —— 覆盖默认 60 秒的数据刷新间隔
- `window.refreshPluginData()` —— 立即强制刷新一次数据

## 配置文件

`device.json`（开发态位于 `src/config/`，初始安装位于 `install/config_base/`）：

```json
{
    "name": "DashPi",
    "timezone": "America/New_York",
    "time_format": "12h",
    "scheduler_sleep_time": 60,
    "startup": true,
    "loop_enabled": true,
    "loop_config": { "loops": [], "rotation_interval_seconds": 300, "active_loop": null },
    "refresh_info": { "refresh_time": null, "refresh_type": null, "plugin_id": null },
    "plugin_order": [],
    "proxy": { "enabled": false, "host": "", "port": "" }
}
```

API 密钥保存在 `.env` 文件中（由 `apikeys` 蓝图读写）。

## 关键 API 一览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/` | 管理仪表盘首页 |
| GET | `/display` | 全屏显示壳页面 |
| GET | `/diagnostics` | 诊断页 |
| GET | `/api/current_state` | `{plugin_id, loop_name, remaining_seconds, next_plugin_id, override, loop_enabled}` —— 每秒轮询 |
| GET | `/api/plugin/<id>/data` | 插件数据 JSON（调用 `get_data()`） |
| GET | `/plugin/<id>/dashboard.html` | 插件前端片段 |
| GET | `/api/plugin_order` | 当前插件顺序 |
| POST | `/toggle_loop` | 开关 Loop |
| POST | `/api/skip_to_next` | 跳到下一个插件 |
| POST | `/api/pin_plugin` | 固定当前插件（override） |
| POST | `/api/clear_override` | 清除固定/override |
| GET | `/api/next_change_time` | 距下次切换的剩余秒数 |

## 测试

```bash
pytest
```

测试位于 `tests/` 目录：

- `test_config.py` —— 配置读取、原子写入、无硬件键断言
- `test_model.py` —— `RefreshInfo`、`LoopManager` 调度、跨午夜、优先级、随机化
- `test_current_state.py` —— `/api/current_state` 的 JSON 结构
- `test_plugin_data_api.py` —— `/api/plugin/<id>/data`（未知插件返回 404，`clock` 成功）

## 相对 OpenClaw-DashPi 移除的内容

| 移除项 | 原因 |
| --- | --- |
| `src/display/`（DisplayManager、framebuffer 劫持） | 改由浏览器渲染 |
| `src/utils/image_loader.py`、`image_utils.py` | 不再生成 PIL 图片 |
| `src/utils/wifi_manager.py`、`wifi_display.py`、`bluetooth_manager.py` | 不需要 AP 模式 / WiFi 配网 |
| `src/blueprints/wifi.py`、`bluetooth.py` | 同上 |
| `static/images/current_image.png` | 不再生成图片 |
| `BasePlugin` 中的 `AdaptiveImageLoader` 注入 | 插件返回字典而非 PIL 图片 |
| `BasePlugin.generate_image()` | 由 `get_data()` 替代 |
| Spotify Web kiosk 子进程管理 | 改为 iframe 嵌入 |
| `RefreshInfo.image_hash` | 无图片可哈希 |
| `device.json` 中的硬件键（`display_type`、`resolution`、`orientation`、`inverted_image`、`brightness_schedule`、`display_transitions`） | 无物理显示器 |

## 致谢

本项目是 [OpenClaw-DashPi](https://github.com/OpenClaw-DashPi/OpenClaw-DashPi) 的 Web 化重写。原始架构、插件设计与 LoopManager 调度逻辑均归功于 OpenClaw-DashPi 的作者。
