# DashPi 树莓派部署指南

本文档介绍如何将 DashPi 部署到树莓派（Raspberry Pi）并配置为 7 寸触摸屏 Kiosk 信息面板。

---

## 1. 系统要求

| 项目 | 最低要求 |
|---|---|
| 硬件 | Raspberry Pi 4 / 5（推荐 2GB+ RAM） |
| 系统 | Raspberry Pi OS (Bookworm) 或更新，64-bit 推荐 |
| Python | 3.10+（Bookworm 自带 Python 3.11） |
| 屏幕 | 7 寸触摸屏（1024×600）或任意 HDMI 显示器 |
| 网络 | Wi-Fi 或以太网（用于获取天气、图片等在线数据） |

---

## 2. 安装步骤

### 2.1 安装系统依赖

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git chromium-browser
```

### 2.2 克隆项目

```bash
cd ~
git clone https://github.com/SHagler2/DashPi.git
cd DashPi
```

### 2.3 创建 Python 虚拟环境并安装依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2.4 配置文件

#### 设备配置

从模板复制 `device.json`：

```bash
cp install/config_base/device.json src/config/device.json
```

编辑 `src/config/device.json`，按需修改：

```json
{
    "name": "DashPi",
    "timezone": "Asia/Shanghai",
    "time_format": "24h",
    "loop_enabled": true,
    "loop_config": {
        "loops": [
            {
                "name": "Default",
                "start_time": "00:00",
                "end_time": "24:00",
                "plugin_order": []
            }
        ],
        "rotation_interval_seconds": 300,
        "active_loop": null
    },
    "proxy": {
        "enabled": false,
        "host": "",
        "port": ""
    }
}
```

**关键配置项说明：**

- `timezone`：设置为你的时区，如 `Asia/Shanghai`、`America/New_York`
- `time_format`：`12h`（12小时制）或 `24h`（24小时制）
- `rotation_interval_seconds`：插件轮换间隔（秒），默认 300（5 分钟）
- `proxy`：如需代理访问外部服务，设置 `enabled: true` 并填写代理地址

#### API 密钥

部分插件需要 API 密钥（如 OpenWeatherMap、NASA APOD、AI 服务等）。在项目根目录创建 `.env` 文件：

```bash
cd ~/DashPi
cat > .env << 'EOF'
OPENWEATHERMAP_API_KEY=your_key_here
NASA_APOD_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
DEEPSEEK_API_KEY=your_key_here
SILICONFLOW_API_KEY=your_key_here
EOF
```

> 也可以通过 DashPi Web 界面的 **Settings → API Keys** 页面配置密钥。

#### 代理配置（可选）

如果树莓派需要通过代理访问外部服务（如使用 Clash），编辑 `src/config/device.json`：

```json
{
    "proxy": {
        "enabled": true,
        "host": "127.0.0.1",
        "port": "7890"
    }
}
```

> 代理仅影响外部请求（天气 API、图片下载等），局域网设备（如 Immich、Spotify）不受影响。

### 2.5 通过 Web 界面配置插件

首次启动后，通过浏览器访问管理界面添加和配置插件：

1. 访问 `http://<树莓派IP>:80/`
2. 进入 **Settings** 配置各插件参数
3. 进入 **Loops** 页面将插件添加到轮换列表
4. 访问 `http://<树莓派IP>:80/display` 查看全屏展示效果

---

## 3. 运行服务

### 3.1 生产模式（推荐）

使用 Waitress 生产级 WSGI 服务器，监听端口 80：

```bash
cd ~/DashPi
source venv/bin/activate
sudo python src/dashpi.py
```

> 端口 80 需要 root 权限，因此使用 `sudo`。如果不想使用 root，可修改 `src/dashpi.py` 中的 `PORT = 8080`。

### 3.2 开发模式

使用 Flask 内置开发服务器，监听端口 8080，使用 `device_dev.json` 配置：

```bash
cd ~/DashPi
source venv/bin/activate
python src/dashpi.py --dev
```

> 开发模式启用热重载和详细日志，适合调试插件。

---

## 4. 开机自启（systemd 服务）

### 4.1 创建 service 文件

```bash
sudo tee /etc/systemd/system/dashpi.service << 'EOF'
[Unit]
Description=DashPi Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/DashPi/src
Environment=PATH=/home/pi/DashPi/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/pi/DashPi/venv/bin/python /home/pi/DashPi/src/dashpi.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

> **注意**：如果你的用户名不是 `pi`，请将上述所有 `/home/pi` 替换为实际路径（可用 `echo $HOME` 查看）。

### 4.2 启用并启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable dashpi
sudo systemctl start dashpi
```

### 4.3 管理命令

```bash
# 查看状态
sudo systemctl status dashpi

# 查看日志
sudo journalctl -u dashpi -f

# 重启服务
sudo systemctl restart dashpi

# 停止服务
sudo systemctl stop dashpi
```

---

## 5. 浏览器全屏 Kiosk 模式

将 Chromium 配置为开机自动全屏打开 DashPi 展示页面。

### 5.1 创建 Kiosk 启动脚本

```bash
mkdir -p ~/.config/autostart

cat > ~/dashpi-kiosk.sh << 'SCRIPT'
#!/bin/bash
# Wait for DashPi service to be ready
sleep 10

# Disable screen blanking and power management
xset s off
xset s noblank
xset -dpms

# Launch Chromium in kiosk mode
chromium-browser \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --kiosk \
    --incognito \
    --start-fullscreen \
    --overscroll-history-navigation=0 \
    --disable-pinch \
    --disable-features=TranslateUI \
    http://localhost/display
SCRIPT

chmod +x ~/dashpi-kiosk.sh
```

### 5.2 配置自动启动

编辑 LXDE 自动启动文件：

```bash
mkdir -p ~/.config/lxsession/LXDE-pi

cat > ~/.config/lxsession/LXDE-pi/autostart << 'EOF'
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@~/dashpi-kiosk.sh
EOF
```

> 如果系统使用 Wayland（Bookworm 默认），需要切换回 X11：
> ```bash
> sudo raspi-config
> # 选择：6 Advanced Options → A6 Wayland → W1 X11
> # 重启
> sudo reboot
> ```

### 5.3 隐藏鼠标光标（可选）

```bash
sudo apt install -y unclutter
unclutter -idle 3 &
```

---

## 6. 屏幕旋转与显示设置

### 6.1 屏幕旋转

编辑 `/boot/config.txt`：

```bash
sudo nano /boot/config.txt
```

添加/修改以下行（根据屏幕安装方向选择）：

```ini
# 旋转 90°（竖屏）
display_rotate=1

# 旋转 180°（倒置）
# display_rotate=2

# 旋转 270°
# display_rotate=3

# 对于 DSI 触摸屏（官方 7 寸屏），可能需要：
lcd_rotate=0
```

修改后重启生效：`sudo reboot`

### 6.2 调整屏幕分辨率

如果使用非标准屏幕，可能需要在 `/boot/config.txt` 中设置自定义分辨率：

```ini
hdmi_group=2
hdmi_mode=87
hdmi_cvt=1024 600 60 3 0 0 0
```

> `hdmi_cvt` 参数：`宽度 高度 刷新率 宽高比(3=16:9) margins(0=off) 交错(0=off) 立体(0=off)`

### 6.3 触摸屏校准（如需要）

```bash
sudo apt install -y xinput-calibrator
xinput_calibrator
```

按提示触摸屏幕四角，将输出的校准值写入配置文件：

```bash
sudo nano /etc/X11/xorg.conf.d/99-calibration.conf
```

---

## 7. 目录结构参考

```
DashPi/
├── install/
│   ├── config_base/
│   │   └── device.json          # 默认配置模板
│   └── RASPBERRY_PI_SETUP.md    # 本文档
├── src/
│   ├── blueprints/              # Flask 路由（API、页面）
│   ├── config/
│   │   ├── device.json          # 生产配置（自动生成）
│   │   ├── device_dev.json      # 开发配置（--dev 模式）
│   │   └── logging.conf         # 日志配置
│   ├── plugins/                 # 插件目录
│   │   ├── clock/
│   │   ├── weather/
│   │   ├── image_album/
│   │   └── ...
│   ├── static/                  # 静态资源（JS、CSS）
│   ├── templates/               # HTML 模板
│   ├── dashpi.py                # 主入口
│   ├── config.py                # 配置管理
│   ├── model.py                 # Loop 调度模型
│   └── refresh_task.py          # 状态服务
├── tests/                       # 单元测试
├── requirements.txt             # Python 依赖
├── VERSION                      # 版本号
└── .env                         # API 密钥（需手动创建）
```

---

## 8. 常见问题

### Q: 端口 80 被占用？

检查是否有其他服务占用 80 端口：
```bash
sudo lsof -i :80
```
常见原因：Apache/Nginx 正在运行。停止它们或改用 8080 端口。

### Q: 插件无法加载外部图片？

1. 检查网络连接：`curl -I https://api.nasa.gov`
2. 如需代理，在 `device.json` 中启用 proxy 配置
3. DashPi 内置图片代理（`/api/proxy_image`），可绕过 CORS 限制

### Q: 屏幕出现黑边或显示不全？

1. 检查 `/boot/config.txt` 中是否有 `disable_overscan=1`
2. 对于 HDMI 屏幕，尝试调整 `hdmi_cvt` 参数
3. DashPi 使用 `100vw/100vh` 响应式布局，适配任意分辨率

### Q: Chromium Kiosk 模式不自动启动？

1. 确认使用 X11（非 Wayland）：`sudo raspi-config → Advanced Options → X11`
2. 检查自动启动文件权限：`ls -la ~/.config/lxsession/LXDE-pi/autostart`
3. 手动测试启动脚本：`~/dashpi-kiosk.sh`

### Q: 如何远程管理？

DashPi 提供完整的 Web 管理界面：
- 主页：`http://<IP>/`
- 设置：`http://<IP>/settings`
- Loop 管理：`http://<IP>/loops`
- API Keys：`http://<IP>/apikeys`
- 全屏展示：`http://<IP>/display`

---

## 9. 更新 DashPi

```bash
cd ~/DashPi
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart dashpi
```

> 更新前建议备份配置：`cp src/config/device.json ~/device.json.backup`
