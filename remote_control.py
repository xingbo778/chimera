"""
remote_control.py - 浏览器远程控制服务器
=========================================
提供 Web UI 让用户可以：
  1. 实时查看浏览器截图
  2. 手动完成验证码（滑块、点选等）
  3. 提交验证码输入
  4. 查看登录状态

基于 FastAPI + WebSocket，通过 CDP 获取浏览器截图。
"""

import asyncio
import base64
import json
import os
import time
import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

app = FastAPI(title="Chimera Remote Control")

# ============================================================
# 配置
# ============================================================

SCREENSHOT_DIR = os.path.expanduser("~/chimera/screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# 信号文件（与 browser_login.py 共享）
SIGNAL_DIR = os.path.expanduser("~/chimera/login_signals")
VERIFICATION_CODE_FILE = os.path.join(SIGNAL_DIR, "verification_code.txt")
WAITING_FOR_INPUT_FILE = os.path.join(SIGNAL_DIR, "waiting_for_input.txt")
LOGIN_STATUS_FILE = os.path.join(SIGNAL_DIR, "login_status.json")


# ============================================================
# API 端点
# ============================================================

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    from browser_pool import get_cdp_info
    cdp_info = get_cdp_info()

    # 检查是否在等待输入
    waiting = None
    if os.path.exists(WAITING_FOR_INPUT_FILE):
        with open(WAITING_FOR_INPUT_FILE) as f:
            waiting = f.read().strip()

    # 登录状态
    login_status = {}
    if os.path.exists(LOGIN_STATUS_FILE):
        try:
            with open(LOGIN_STATUS_FILE) as f:
                login_status = json.load(f)
        except Exception:
            pass

    return {
        "browser_connected": cdp_info is not None,
        "browser_info": cdp_info,
        "waiting_for_input": waiting,
        "login_status": login_status,
        "timestamp": time.time(),
    }


@app.get("/api/screenshot")
async def take_screenshot():
    """获取浏览器当前截图（通过 CDP 原始协议，避免 sync/async 冲突）"""
    try:
        data = await _cdp_screenshot()
        if data:
            return {"success": True, "image": f"data:image/png;base64,{data}"}
        return {"success": False, "error": "截图失败：无活动页面"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _cdp_screenshot() -> Optional[str]:
    """通过 CDP WebSocket 直接截图，返回 base64 字符串"""
    import websockets
    # 获取当前活动页面的 WS URL
    try:
        import requests as _req
        resp = _req.get("http://127.0.0.1:9222/json", timeout=3)
        pages = resp.json()
        if not pages:
            return None
        # 取第一个 page 类型的目标
        ws_url = None
        for p in pages:
            if p.get("type") == "page":
                ws_url = p.get("webSocketDebuggerUrl")
                break
        if not ws_url:
            ws_url = pages[0].get("webSocketDebuggerUrl")
        if not ws_url:
            return None
    except Exception:
        return None

    async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Page.captureScreenshot",
            "params": {"format": "png"}
        }))
        result = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        return result.get("result", {}).get("data")


@app.post("/api/submit_code")
async def submit_code(payload: dict):
    """提交验证码"""
    code = payload.get("code", "").strip()
    if not code:
        return {"success": False, "error": "验证码不能为空"}

    os.makedirs(SIGNAL_DIR, exist_ok=True)
    with open(VERIFICATION_CODE_FILE, "w") as f:
        f.write(code)

    logger.info("收到验证码: %s", code)
    return {"success": True, "message": f"验证码已提交: {code}"}


@app.post("/api/click")
async def cdp_click(payload: dict):
    """通过 CDP 在浏览器中点击指定坐标"""
    x = payload.get("x", 0)
    y = payload.get("y", 0)

    try:
        import websockets
        from browser_pool import get_cdp_ws_url

        ws_url = get_cdp_ws_url()
        if not ws_url:
            return {"success": False, "error": "无法获取 CDP WebSocket URL"}

        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            # mousePressed
            await ws.send(json.dumps({
                "id": 1,
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mousePressed",
                    "x": x, "y": y,
                    "button": "left", "clickCount": 1,
                }
            }))
            await asyncio.wait_for(ws.recv(), timeout=5)

            await asyncio.sleep(0.05)

            # mouseReleased
            await ws.send(json.dumps({
                "id": 2,
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mouseReleased",
                    "x": x, "y": y,
                    "button": "left", "clickCount": 1,
                }
            }))
            await asyncio.wait_for(ws.recv(), timeout=5)

        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/login")
async def trigger_login(payload: dict):
    """触发平台登录"""
    platform = payload.get("platform", "")
    phone = payload.get("phone", "")

    if not platform or not phone:
        return {"success": False, "error": "需要 platform 和 phone 参数"}

    try:
        from browser_login import login_platform
        # 在后台运行登录
        asyncio.create_task(_run_login(platform, phone))
        return {"success": True, "message": f"已开始 {platform} 登录"}
    except ImportError:
        return {"success": False, "error": "browser_login 模块不可用"}


async def _run_login(platform: str, phone: str):
    """后台运行登录任务"""
    try:
        from browser_login import login_platform
        result = await login_platform(platform, phone)
        logger.info("登录结果 (%s): %s", platform, result)
    except Exception as e:
        logger.error("登录失败 (%s): %s", platform, e)


# ============================================================
# WebSocket 实时截图推送
# ============================================================

@app.websocket("/ws/screen")
async def websocket_screen(websocket: WebSocket):
    """WebSocket 端点：实时推送浏览器截图"""
    await websocket.accept()
    logger.info("WebSocket 客户端已连接")

    try:
        while True:
            try:
                b64 = await _cdp_screenshot()
                if b64:
                    await websocket.send_json({
                        "type": "screenshot",
                        "image": f"data:image/png;base64,{b64}",
                        "timestamp": time.time(),
                    })

                # 检查是否在等待输入
                waiting = None
                if os.path.exists(WAITING_FOR_INPUT_FILE):
                    with open(WAITING_FOR_INPUT_FILE) as f:
                        waiting = f.read().strip()
                if waiting:
                    await websocket.send_json({
                        "type": "waiting_for_input",
                        "question": waiting,
                    })

            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })

            await asyncio.sleep(2)  # 每 2 秒推送一次

    except WebSocketDisconnect:
        logger.info("WebSocket 客户端已断开")


# ============================================================
# 前端 UI
# ============================================================

REMOTE_CONTROL_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chimera 远程控制</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: #16213e;
            padding: 12px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #0f3460;
        }
        .header h1 { font-size: 18px; color: #e94560; }
        .status-dot {
            width: 10px; height: 10px; border-radius: 50%;
            display: inline-block; margin-right: 6px;
        }
        .status-dot.connected { background: #4ecca3; }
        .status-dot.disconnected { background: #e94560; }
        .main {
            display: flex;
            height: calc(100vh - 50px);
        }
        .screen-panel {
            flex: 1;
            padding: 10px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .screen-container {
            position: relative;
            border: 2px solid #0f3460;
            border-radius: 8px;
            overflow: hidden;
            max-width: 100%;
            cursor: crosshair;
        }
        .screen-container img {
            max-width: 100%;
            height: auto;
            display: block;
        }
        .control-panel {
            width: 320px;
            background: #16213e;
            padding: 16px;
            border-left: 1px solid #0f3460;
            overflow-y: auto;
        }
        .section {
            margin-bottom: 16px;
            padding: 12px;
            background: #1a1a2e;
            border-radius: 8px;
            border: 1px solid #0f3460;
        }
        .section h3 {
            font-size: 14px;
            color: #4ecca3;
            margin-bottom: 8px;
        }
        .alert-box {
            background: #e94560;
            color: white;
            padding: 10px;
            border-radius: 6px;
            margin-bottom: 12px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        input[type="text"] {
            width: 100%;
            padding: 8px 12px;
            background: #0f3460;
            border: 1px solid #4ecca3;
            border-radius: 4px;
            color: white;
            font-size: 16px;
            margin-bottom: 8px;
        }
        button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            margin: 2px;
        }
        .btn-primary { background: #4ecca3; color: #1a1a2e; }
        .btn-danger { background: #e94560; color: white; }
        .btn-secondary { background: #0f3460; color: #e0e0e0; }
        .login-row {
            display: flex;
            gap: 4px;
            margin-bottom: 6px;
        }
        .login-row input { flex: 1; }
        .login-status {
            font-size: 12px;
            padding: 4px 8px;
            border-radius: 4px;
            margin: 2px 0;
        }
        .login-status.ok { background: #1a4a3a; color: #4ecca3; }
        .login-status.fail { background: #4a1a2a; color: #e94560; }
        .log-area {
            font-family: monospace;
            font-size: 11px;
            background: #0a0a1a;
            padding: 8px;
            border-radius: 4px;
            max-height: 150px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .click-marker {
            position: absolute;
            width: 20px; height: 20px;
            border: 2px solid #e94560;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            pointer-events: none;
            animation: clickFade 1s forwards;
        }
        @keyframes clickFade {
            0% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
            100% { opacity: 0; transform: translate(-50%, -50%) scale(2); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔮 Chimera 远程控制</h1>
        <div>
            <span class="status-dot" id="statusDot"></span>
            <span id="statusText">连接中...</span>
        </div>
    </div>
    <div class="main">
        <div class="screen-panel">
            <div class="screen-container" id="screenContainer" onclick="handleScreenClick(event)">
                <img id="screenImg" src="" alt="等待截图...">
            </div>
            <div style="margin-top: 8px; font-size: 12px; color: #666;">
                点击截图可在浏览器中执行点击操作
            </div>
        </div>
        <div class="control-panel">
            <!-- 等待输入提示 -->
            <div id="waitingAlert" class="alert-box" style="display:none;">
                <strong>⏳ 等待输入</strong>
                <p id="waitingQuestion"></p>
            </div>

            <!-- 验证码输入 -->
            <div class="section">
                <h3>📱 验证码输入</h3>
                <input type="text" id="codeInput" placeholder="输入验证码..." maxlength="10">
                <button class="btn-primary" onclick="submitCode()">提交验证码</button>
            </div>

            <!-- 登录管理 -->
            <div class="section">
                <h3>🔐 平台登录</h3>
                <div class="login-row">
                    <input type="text" id="phoneInput" placeholder="手机号">
                </div>
                <button class="btn-secondary" onclick="triggerLogin('xiaohongshu')">小红书</button>
                <button class="btn-secondary" onclick="triggerLogin('weibo')">微博</button>
                <button class="btn-secondary" onclick="triggerLogin('douban')">豆瓣</button>
                <div id="loginStatus" style="margin-top: 8px;"></div>
            </div>

            <!-- 操作 -->
            <div class="section">
                <h3>🎮 操作</h3>
                <button class="btn-secondary" onclick="refreshScreenshot()">🔄 刷新截图</button>
                <button class="btn-secondary" onclick="checkStatus()">📊 检查状态</button>
            </div>

            <!-- 日志 -->
            <div class="section">
                <h3>📋 日志</h3>
                <div class="log-area" id="logArea"></div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let connected = false;

        function log(msg) {
            const area = document.getElementById('logArea');
            const time = new Date().toLocaleTimeString();
            area.textContent += `[${time}] ${msg}\\n`;
            area.scrollTop = area.scrollHeight;
        }

        function updateStatus(isConnected) {
            connected = isConnected;
            document.getElementById('statusDot').className = 'status-dot ' + (isConnected ? 'connected' : 'disconnected');
            document.getElementById('statusText').textContent = isConnected ? '已连接' : '未连接';
        }

        function connectWebSocket() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws/screen`);

            ws.onopen = () => {
                updateStatus(true);
                log('WebSocket 已连接');
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'screenshot') {
                    document.getElementById('screenImg').src = data.image;
                } else if (data.type === 'waiting_for_input') {
                    document.getElementById('waitingAlert').style.display = 'block';
                    document.getElementById('waitingQuestion').textContent = data.question;
                } else if (data.type === 'error') {
                    log('错误: ' + data.message);
                }
            };

            ws.onclose = () => {
                updateStatus(false);
                log('WebSocket 断开，3秒后重连...');
                setTimeout(connectWebSocket, 3000);
            };

            ws.onerror = () => {
                updateStatus(false);
            };
        }

        async function submitCode() {
            const code = document.getElementById('codeInput').value.trim();
            if (!code) { alert('请输入验证码'); return; }

            const resp = await fetch('/api/submit_code', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code}),
            });
            const result = await resp.json();
            log(result.success ? `✅ 验证码已提交: ${code}` : `❌ ${result.error}`);
            document.getElementById('codeInput').value = '';
            document.getElementById('waitingAlert').style.display = 'none';
        }

        async function triggerLogin(platform) {
            const phone = document.getElementById('phoneInput').value.trim();
            if (!phone) { alert('请输入手机号'); return; }

            const resp = await fetch('/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({platform, phone}),
            });
            const result = await resp.json();
            log(result.success ? `🚀 ${platform} 登录已启动` : `❌ ${result.error}`);
        }

        async function handleScreenClick(event) {
            const img = document.getElementById('screenImg');
            const rect = img.getBoundingClientRect();
            const scaleX = img.naturalWidth / rect.width;
            const scaleY = img.naturalHeight / rect.height;
            const x = Math.round((event.clientX - rect.left) * scaleX);
            const y = Math.round((event.clientY - rect.top) * scaleY);

            // 显示点击标记
            const marker = document.createElement('div');
            marker.className = 'click-marker';
            marker.style.left = (event.clientX - rect.left) + 'px';
            marker.style.top = (event.clientY - rect.top) + 'px';
            document.getElementById('screenContainer').appendChild(marker);
            setTimeout(() => marker.remove(), 1000);

            const resp = await fetch('/api/click', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({x, y}),
            });
            const result = await resp.json();
            log(result.success ? `🖱️ 点击 (${x}, ${y})` : `❌ 点击失败: ${result.error}`);
        }

        async function refreshScreenshot() {
            const resp = await fetch('/api/screenshot');
            const result = await resp.json();
            if (result.success) {
                document.getElementById('screenImg').src = result.image;
                log('📸 截图已刷新');
            } else {
                log('❌ 截图失败: ' + result.error);
            }
        }

        async function checkStatus() {
            const resp = await fetch('/api/status');
            const result = await resp.json();
            log('状态: ' + JSON.stringify(result, null, 2));

            // 更新登录状态
            const statusDiv = document.getElementById('loginStatus');
            statusDiv.innerHTML = '';
            if (result.login_status) {
                for (const [platform, info] of Object.entries(result.login_status)) {
                    const cls = info.logged_in ? 'ok' : 'fail';
                    const icon = info.logged_in ? '✅' : '❌';
                    statusDiv.innerHTML += `<div class="login-status ${cls}">${icon} ${platform}</div>`;
                }
            }
        }

        // 回车提交验证码
        document.getElementById('codeInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') submitCode();
        });

        // 启动
        connectWebSocket();
        checkStatus();
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    """远程控制首页"""
    return REMOTE_CONTROL_HTML


# ============================================================
# 启动入口
# ============================================================

def start_server(host: str = "0.0.0.0", port: int = 8899):
    """启动远程控制服务器"""
    import uvicorn
    logger.info("远程控制服务器启动: http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Chimera 远程控制服务器")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start_server(args.host, args.port)
