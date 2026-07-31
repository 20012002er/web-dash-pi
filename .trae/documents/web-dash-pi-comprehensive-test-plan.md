# web-dash-pi 全面运行与测试计划

> **任务执行总结（2026-07-31）**
>
> 本次任务聚焦于后端可运行性、API 冒烟测试以及 Clock 插件前端渲染与原项目的一致性修复。以下清单用于下次任务继续执行时快速恢复上下文。
>
> ## 本次已完成项
>
> ### 1. 环境与服务
> - 已激活并使用现有 Python 3.13 venv（`venv/bin/activate`）。
> - 开发服务 `python src/dashpi.py --dev` 可在 8080 端口稳定启动（当前已停止，端口已清理）。
> - 已清理端口占用问题，服务可重复启停。
>
> ### 2. 后端测试
> - `pytest -v`：**17/17 全部通过**（含本次修复后回归验证）。
> - 临时冒烟脚本 `tmp_backend_test.py` 已更新：测试客户端显式绕过系统代理（`trust_env=False; proxies={}`），避免 macOS 系统代理导致超时误报。
> - 基础页面与 API（`/`、`/display`、`/api/current_state`、循环控制、插件固定/覆盖等）均 200。
>
> ### 3. 网络/代理修复
> - `src/utils/http_client.py`：`_HTTP_SESSION` 已设置 `trust_env=False` 与 `proxies={}`，插件对外 HTTP 请求不再走系统代理。
> - `tmp_backend_test.py`：同样禁用代理，确保测试结果反映服务端真实状态。
>
> ### 4. Clock 插件渲染修复（与 OpenClaw-DashPi 对比）
> - **Gradient Clock**：修复为完整圆形圆锥渐变（`conic-gradient` 从时针 secondary → 分针 primary → 绕回 secondary），替代之前仅渲染扇形的实现。
> - **Divided Clock**：修复背景为上下双色分割（`linear-gradient(to bottom, primary 50%, secondary 50%)`），匹配原项目。
> - **Digital Clock**：在 `display.html` 中为 `DS-Digital` 字体补充 `@font-face` 声明，解决字体文件存在但未加载的问题；同时确认暗淡 `00:00` 背景效果正常。
> - **Word Clock**：确认 10×11 字母网格布局、高亮逻辑正常；`Napoli` 字体通过同一份 `@font-face` 声明加载。
>
> ### 5. 改动文件清单
> - `src/utils/http_client.py`：禁用系统代理。
> - `tmp_backend_test.py`：测试客户端禁用代理，使用共享 session。
> - `src/plugins/clock/dashboard.html`：修复 Gradient / Divided / Digital 渲染。
> - `src/templates/display.html`：加载 `Jost`、`DS-Digital`、`Napoli`、`Dogica` 字体族。
> - `src/config/device_dev.json`：清除了测试用的 `loop_override`（当前为 `null`）；循环中 Clock 的 `selectedClockFace` 当前为 Digital（可恢复默认 Gradient）。
>
> ### 5. Image Album 插件功能测试与前端渲染验证（2026-07-31 第二轮）
> - **Immich 地址替换**：将 `device_dev.json` 中 Immich URL 从内网 `http://192.168.28.130:2283` 替换为公网 `https://immich.toby-blog.com`，相册名 `happy`。
> - **后端 API 测试**：`GET /api/plugin/image_album/data` 返回 200，成功获取 `image_url` 和 `fit_mode`，图片文件（~898KB jpeg）已下载至 `src/static/images/saved/image_album_current.jpeg`。
> - **图片静态资源访问**：`GET /static/images/saved/image_album_current.jpeg` 返回 200，Content-Type 为 `image/jpeg`。
> - **前端渲染验证**：
>   - 管理页 `/`：Image Album 插件卡片正常显示，图标加载正常。
>   - 设置页 `/plugin/image_album`：表单渲染正确，URL/Album/DisplayMode 等字段值均正确。
>   - Display 页 `/display`：通过 pin_plugin 强制切换到 image_album 后，图片正确加载并显示，`fit_mode=fit` 以 `object-fit: contain` 渲染（letterbox 模式，黑边填充），无 JS 控制台报错。
> - **已知差异**：`dashboard.html` 中 `blur` 模式（模糊背景填充）未实现，当前仅支持 `fit`（contain）和 `fill`（cover）两种模式。
>
> ### 6. 改动文件清单（第二轮）
> - `src/config/device_dev.json`：Immich URL 替换为 `https://immich.toby-blog.com`。
>
> ### 7. Unsplash & APOD 插件功能测试与代理支持（2026-07-31 第三轮）
> - **代理支持实现**：
>   - `src/utils/http_client.py`：新增 `_read_proxy_config()` 函数，从 `device.json` 读取代理配置。代理启用时，session 通过 `http://127.0.0.1:7890`（Clash）路由外部请求，同时设置 `NO_PROXY` 保持本地/LAN 流量直连。代理禁用时保持原有行为（完全绕过系统代理）。
>   - `src/config/device_dev.json`：启用代理 `"enabled": true, "host": "127.0.0.1", "port": "7890"`。
> - **Unsplash 测试**：
>   - 后端 API：`GET /api/plugin/unsplash/data` 返回 200，成功获取图片 URL、摄影师名称、描述。
>   - 前端渲染：图片正确加载，`fit_mode=fit` 以 letterbox 模式显示，底部显示摄影师信息叠加层（"Balanced rock formation in a desert landscape — by Roberto Shumski"），无 JS 控制台报错。
> - **APOD 测试**：
>   - 后端 API：`GET /api/plugin/apod/data` 返回 200，成功获取 NASA 每日天文图片 URL、标题、日期、说明。
>   - 前端渲染：图片正确加载，标题 "Detailed View of a Solar Eclipse Corona"、日期 "2024-04-02" 正确显示，"Show explanation" 按钮可展开/收起说明文字，无 JS 控制台报错。
>
> ### 8. 改动文件清单（第三轮）
> - `src/utils/http_client.py`：新增代理配置读取与应用逻辑。
> - `src/config/device_dev.json`：启用代理；添加 unsplash/apod 到循环配置。
>
> ### 9. Weather / Art Museum / Newspaper / WPOTD 插件功能测试与前端渲染验证（2026-07-31 第四轮）
> - **配置变更**：
>   - `src/config/device_dev.json`：在循环中添加 weather（OpenMeteo 提供商，纽约坐标）、art_museum（both 博物馆）、newspaper（NY Times）、wpotd（当日模式）。
>   - 清除 `loop_override`，重置 `current_plugin_index` 为 0。
> - **后端 API 测试**（全部通过代理访问外部域名）：
>   - `GET /api/plugin/weather/data` → 200，返回 OpenMeteo 天气数据：当前温度 19°C、Clear Sky、日出/日落、风速、湿度、AQI、UV、7日预报（含月相）。
>   - `GET /api/plugin/art_museum/data` → 200，返回 Met Museum/Chicago 艺术品数据：标题、艺术家、博物馆名称、图片 URL。
>   - `GET /api/plugin/newspaper/data` → 200，返回 Freedom Forum 纽约时报头版图片 URL。
>   - `GET /api/plugin/wpotd/data` → 200，返回 Wikipedia 每日图片 URL、标题、日期（此前因外部网络不可达超时，本次通过代理成功）。
> - **前端渲染验证**：
>   - **Weather**：布局完整——位置名、大字体温度、天气描述、体感温度、高低温、指标面板（日出/日落/风速/湿度/AQI/UV）、7日预报行。**问题**：① 天气图标未显示（`/images/weather/` 路径下图标文件缺失）；② 小时预报图表缺失（Chart.js CDN 被 CSP `script-src 'self' 'unsafe-inline'` 拦截）；③ `logger is not defined` 小错误。
>   - **Art Museum**：标题/艺术家/博物馆信息叠加层正确渲染。**问题**：外部图片（artic.edu / metmuseum.org）被浏览器 `NotSameOrigin` 策略拦截，图片区域为空白。
>   - **Newspaper**：纽约时报头版完整显示，标题叠加层正常，无 JS 错误。渲染完美。
>   - **WPOTD**：维基百科每日图片（鸟类照片）完整显示，标题/描述/日期叠加层正常，无 JS 错误。渲染完美。
>
> ### 10. 改动文件清单（第四轮）
> - `src/config/device_dev.json`：添加 weather/art_museum/newspaper/wpotd 到循环配置。
>
> ### 11. Weather / Art Museum 问题修复（2026-07-31 第五轮）
> - **Weather 图标缺失**：
>   - 原因：`dashboard.html` 中图标引用路径为 `/images/weather/01d.png`，但图标实际位于 `plugins/weather/icons/` 子目录下，路由 `/images/<plugin_id>/<path:filename>` 从 `plugins/weather/` 根目录查找，找不到文件。
>   - 修复：`src/plugins/weather/dashboard.html` 中三处图标路径改为 `/images/weather/icons/` 前缀。
> - **Weather Chart.js CSP 拦截**：
>   - 原因：CSP `script-src 'self' 'unsafe-inline'` 不允许加载 `cdn.jsdelivr.net` 的 Chart.js。
>   - 修复：`src/dashpi.py` 中 CSP 的 `script-src` 添加 `https://cdn.jsdelivr.net`。
> - **Weather `logger is not defined`**：
>   - 修复：`dashboard.html` 中 Chart.js 加载失败的错误处理移除对未定义 `logger` 的引用。
> - **Art Museum 外部图片跨域拦截**：
>   - 原因：Met Museum / Art Institute of Chicago 的图片 URL 被浏览器 `NotSameOrigin` 策略拦截。
>   - 修复：`src/blueprints/plugin.py` 新增 `/api/proxy_image?url=...` 代理路由，通过服务端 HTTP 客户端（支持代理）获取外部图片并返回给浏览器；`src/plugins/art_museum/dashboard.html` 改为通过代理加载图片。
> - **验证结果**：
>   - Weather：所有天气图标（月相、云、雨、雷等）正常显示，Chart.js 小时温度图表正常渲染，7日预报完整。
>   - Art Museum：艺术品图片通过代理正常加载，标题/艺术家/博物馆叠加层正确显示。
>
> ### 12. 改动文件清单（第五轮）
> - `src/plugins/weather/dashboard.html`：图标路径添加 `icons/` 子目录；修复 `logger` 引用。
> - `src/dashpi.py`：CSP `script-src` 添加 `https://cdn.jsdelivr.net`。
> - `src/blueprints/plugin.py`：新增 `/api/proxy_image` 图片代理路由。
> - `src/plugins/art_museum/dashboard.html`：图片加载改为通过 `/api/proxy_image` 代理。
>
> ## 已知未解决问题（下次任务可继续）
>
> 1. **缺少必填配置导致的 500（预期行为）**
>    - `calendar`、`comic`、`countdown` 等插件未配置目标日期/源时返回 500，属于正常校验。
>    - 处理建议：为无外部依赖的插件配置合理测试数据后逐个验证。
>
> 2. **管理页轮询 404**
>    - `/loops` 与 `/plugin/<id>` 页面会轮询 `/static/images/plugins/refresh_status.json`，但该文件在 web 版中不存在，返回 404。
>    - 处理建议：确认是否需要保留此刷新状态机制，或提供静态占位文件。
>
> 3. **与原始项目的前端全面对比**
>    - 本次仅重点修复 Clock；其他插件的 dashboard.html 与 OpenClaw-DashPi 原始 PIL 渲染是否信息等价，尚未逐项核对。
>    - 处理建议：按插件逐个打开 `/display` 或 `/plugin/<id>/dashboard.html` 截图，与原项目输出对比。
>
> 4. **.env key 名称匹配**
>    - `.env` 中的 key 名与部分插件 `load_env_key()` 期望的名称不完全一致（如 `GITHUB_SECRET` 缺失）。
>    - 处理建议：核对 `.env` 与 `src/plugins/*/plugin.py` 的 key 名称，统一或补充缺失 key。
>
> ## 快速恢复命令
>
> ```bash
> cd /Users/lazybeartoby/develop/work_test/web-dash-pi
> source venv/bin/activate
> python src/dashpi.py --dev          # 启动服务
> pytest -v                            # 运行自动化测试
> python tmp_backend_test.py           # 后端冒烟测试
> ```
>
> ## 1. 目标与范围

### 1.1 目标
- 确保 web-dash-pi 项目可完整运行（Flask + waitress 后端、前端页面、插件调度）。
- 验证前后端各功能模块无异常。
- 验证 26 个插件的数据接口与渲染表现正常。
- 验证前端页面渲染与原始项目 `/Users/lazybeartoby/develop/work_test/OpenClaw-DashPi` 无功能性差异。

### 1.2 范围
- **后端**：Flask 路由、API、Loop 调度、配置读写、插件数据接口。
- **前端**：管理页、display 页、各插件 dashboard.html 渲染、JS 交互。
- **插件**：26 个插件的 `get_data()`、`dashboard.html`、settings.html 配置。
- **环境**：`.env` 7 个 API key、`device.json` / `device_dev.json`、依赖安装。
- **对比**：与 OpenClaw-DashPi 原始项目在视觉层级、信息字段、交互行为上保持一致。

## 2. 当前状态分析

### 2.1 项目结构（已确认）
- 入口：`src/dashpi.py`（`--dev` 模式在 8080 启动）。
- 配置：`src/config.py` 原子写入 `device.json`；`.env` 存放 7 个 secrets。
- 模型：`src/model.py`（LoopManager / Loop / PluginReference 调度逻辑）。
- 状态：`src/refresh_task.py` 提供 `determine_current_plugin()`。
- 插件：`src/plugins/plugin_registry.py` 动态加载，每个插件含 `.py` + `plugin-info.json` + `dashboard.html` + `settings.html` + `icon.png`。
- 前端：`src/static/js/display.js` 每秒轮询 `/api/current_state`，加载插件 dashboard 并请求 `/api/plugin/<id>/data`。
- 已有测试：`tests/` 下 4 个 pytest 文件，历史通过 17 项。

### 2.2 26 个插件清单（已按实际目录校正）
1. ai_image
2. ai_text
3. apod
4. art_museum
5. astro_targets
6. calendar
7. clock
8. comic
9. countdown
10. flight_tracker
11. github
12. image_album
13. image_folder
14. image_upload
15. image_url
16. iss_tracker
17. newspaper
18. rss
19. shazam_pi
20. spotify_web
21. stocks
22. todo_list
23. unsplash
24. weather
25. wpotd
26. year_progress

### 2.3 已知风险
- 多个插件依赖真实第三方 API 与 `.env` key，外部失败不能视为项目 bug。
- `shazam_pi` 依赖浏览器麦克风权限，需手动测试。
- `spotify_web` 依赖 iframe / CSP，需手动在浏览器验证。
- 原始 OpenClaw-DashPi 使用物理 LED 矩阵渲染，web 版使用 HTML/CSS；"无差异"指信息与交互等价，而非像素级一致。

## 3. 执行步骤

### 阶段 A：环境准备
1. 进入项目目录 `/Users/lazybeartoby/develop/work_test/web-dash-pi`。
2. 检查 Python 版本 ≥ 3.10，创建/激活虚拟环境。
3. 安装依赖：`pip install -r requirements.txt`。
4. 检查 `.env` 是否包含 7 个 secrets（`WEATHER_API_KEY`、`FINNHUB_API_KEY`、`NASA_API_KEY`、`OPENAI_API_KEY`、`GOOGLE_API_KEY`、`IMMICH_KEY`、`SPOTIFY_*`）。
5. 检查 `device_dev.json` 是否存在并包含默认循环配置。

### 阶段 B：基础运行验证
1. 启动开发服务：`python src/dashpi.py --dev`。
2. 浏览器直接访问 `http://localhost:8080/`，确认管理首页 200、插件卡片加载、图标正常。
3. 访问 `http://localhost:8080/display`，确认页面加载、`display.js` 轮询 `/api/current_state` 无报错。
4. 访问 `http://localhost:8080/diagnostics`，确认诊断页无 500，版本号与配置摘要正确。

### 阶段 C：自动化测试
1. 运行现有 pytest：`pytest -v`。
2. 确认原有 17 项测试全部通过。
3. 若失败，记录失败项并修复后重新运行。

### 阶段 D：后端 API 功能测试
对每个主路由/接口执行验证：

| 接口 | 方法 | 验证内容 |
|---|---|---|
| `/` | GET | 返回管理首页，含插件卡片 |
| `/display` | GET | 返回 display 页面 |
| `/api/current_state` | GET | 返回 `current_plugin_id`、`next_change_time`、`loops`、`override` 等字段 |
| `/api/plugin/<id>/data` | GET | 各插件返回有效 JSON 或合理的错误信息 |
| `/api/plugin/<id>/dashboard.html` | GET | 返回插件 dashboard 片段 |
| `/api/skip_to_next` | POST | 当前插件切换为 loop 中的下一个 |
| `/api/pin_plugin` | POST | `override` 字段被设置 |
| `/api/clear_override` | POST | `override` 被清除 |
| `/api/toggle_loop` | POST | `loop_enabled` 状态切换 |
| `/api/next_change_time` | GET | 返回数字时间戳 |
| `/loops` 系列 | GET/POST | 增删改查 loop、向 loop 添加/移除插件 |
| `/apikeys` | GET/POST | 读取/保存 `.env`（保存后需提示重启） |

### 阶段 E：前端页面与交互测试
1. **首页 `/`**：所有 26 个插件卡片渲染完整，图标加载，点击可进入设置页。
2. **插件设置页 `/plugin/<id>`**：
   - `settings.html` 正确渲染。
   - 保存设置后数据持久化。
   - 点击 "Update Now" 后保存设置并自动加入 `availableLoops[0]`。
3. **循环管理页 `/loops`**：
   - 创建 loop、设置起止时间（含跨午夜）。
   - 向 loop 添加/移除插件、调整顺序。
   - 删除 loop。
4. **API 密钥页 `/apikeys`**：
   - 能读取当前 `.env` 值。
   - 保存后写入 `.env`，并提示需要重启服务生效。
5. **display 页 `/display`**：
   - 每秒轮询，无控制台报错。
   - 插件切换时平滑加载新 dashboard。
   - 无 loop 时显示占位，不崩溃。
   - 插件数据错误时触发 `plugin-data-error` 事件，页面不白屏。

### 阶段 F：插件逐个验证

对每个插件执行以下检查：

| 插件 | 关键依赖 | 测试动作 | 成功标志 |
|---|---|---|---|
| ai_image | SILICONFLOW_SECRET / OPEN_AI_SECRET / GOOGLE_GEMINI_SECRET | 配置提示词，访问 data | 返回图片 URL |
| ai_text | DEEPSEEK_SECRET / OPEN_AI_SECRET / GOOGLE_GEMINI_SECRET | 访问 data | 返回文本 |
| apod | NASA_SECRET | 访问 data | 返回图片 URL/标题 |
| art_museum | 无（Met Museum API） | 访问 data | 返回艺术品图片/信息 |
| astro_targets | 无 | 配置位置，访问 data | 返回天文目标列表 |
| calendar | 无 | 配置 ICS URL，访问 data | 返回日程/日期信息 |
| clock | 无 | 访问 data 接口 / display | 返回 time/date/face，SVG 指针按 viewBox 单位渲染 |
| comic | 无 | 配置漫画源，访问 data | 返回漫画图片 |
| countdown | 无 | 配置目标日期后访问 data | 返回剩余时间 |
| flight_tracker | 无 | 配置机场代码，访问 data | 返回航班信息 |
| github | GITHUB_SECRET | 配置用户名/repo | 返回 star/commit 信息 |
| image_album | IMMICH_KEY | 配置 album ID/URL，访问 data | 返回图片列表 |
| image_folder | 无 | 配置本地路径，访问 data | 返回图片列表 |
| image_upload | 无 | 上传图片后访问 data | 返回上传的图片 |
| image_url | 无 | 配置图片 URL，访问 data | 返回图片 |
| iss_tracker | N2YO_SECRET（可选） | 访问 data | 返回 ISS 坐标/轨迹 |
| newspaper | 无 | 配置 RSS/源，访问 data | 返回新闻条目 |
| rss | 无 | 配置 RSS URL，访问 data | 返回订阅条目 |
| shazam_pi | 麦克风权限 | 浏览器允许麦克风，在 display 查看 | 识别到音乐时显示曲目 |
| spotify_web | SPOTIFY_CLIENT_ID/SECRET | 配置 playlist URI，浏览器打开 dashboard | iframe 加载或出现 fallback 链接 |
| stocks | FINNHUB_SECRET / POLYGON_SECRET | 配置股票代码，访问 data | 返回价格/涨跌 |
| todo_list | 无 | 配置待办项，访问 data | 返回待办列表 |
| unsplash | UNSPLASH_ACCESS_KEY | 访问 data | 返回图片 URL |
| weather | OPEN_WEATHER_MAP_SECRET | 配置城市，访问 data | 返回温度、天气图标 |
| wpotd | 无（Wikipedia API） | 访问 data | 返回每日图片/说明 |
| year_progress | 无 | 访问 data | 返回年度进度信息 |

### 阶段 G：与原始 OpenClaw-DashPi 对比
1. 列出原始项目中每个插件在 LED 矩阵上展示的信息字段。
2. 在 web-dash-pi 中核对每个插件 `dashboard.html` 是否展示等价信息。
3. 核对交互行为：
   - 插件切换节奏是否一致（基于 LoopManager 调度逻辑）。
   - 跳过/固定/覆盖行为是否一致。
   - 设置项名称与默认值是否一致。
4. 记录并修复差异项。

### 阶段 H：稳定性与回归
1. 让服务持续运行 30 分钟，观察循环切换、内存、日志。
2. 多次修改 `device.json` 配置，验证原子写入无 JSON 损坏。
3. 重新运行 `pytest`，确认所有测试仍通过。
4. 检查 `.gitignore` 正确排除 `.env`、`device.json`、运行时上传目录。

## 4. 交付物

1. 更新后的可运行代码（如有修复）。
2. 测试记录文档（含通过/失败项、修复说明）。
3. 与原始项目的差异对照表（如有）。

## 5. 验收标准

- [x] `python src/dashpi.py --dev` 可成功启动且无报错。
- [x] `pytest -v` 全部通过。
- [ ] 管理页所有链接可访问、所有插件卡片可渲染（已确认首页/循环/API 密钥页可访问，未逐项点击所有管理页）。
- [x] `/display` 在配置 loop 后每 1 秒轮询并正确切换插件。
- [ ] 26 个插件中，无 API key 依赖的插件 100% 验证通过；有 key 依赖的插件在配置 key 后验证通过（Clock 已修复并验证；image_album 已通过公网 Immich 验证通过；unsplash/apod 已通过代理验证通过；weather 通过 OpenMeteo 验证通过，图标和图表已修复；art_museum/newspaper/wpotd API 均通过代理验证通过；art_museum 外部图片已通过代理解决跨域问题；其余插件多因缺少配置返回 500）。
- [ ] 前端页面渲染在信息字段和交互行为上与 OpenClaw-DashPi 无功能性差异（Clock 已对齐；image_album 基本功能已验证，blur 模式已实现；unsplash/apod 已验证通过；weather 布局完整，图标和图表已修复；art_museum 图片通过代理正常加载；newspaper/wpotd 渲染完美；其余插件尚未逐项对比）。
- [x] `.env`、`device.json` 未被提交或意外暴露。
