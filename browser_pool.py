"""
browser_pool.py - 基于 CDP 的浏览器管理器
==========================================
通过 Chrome DevTools Protocol 连接真实的 Chromium 浏览器实例，
支持持久化 cookie、多标签页管理、截图、JS 执行等。

架构：
  1. 外部 Chromium 进程（通过 start_browser.sh 启动，带 --remote-debugging-port）
  2. 本模块通过 CDP WebSocket 连接浏览器
  3. 使用 Playwright 的 cdp 连接模式（比原始 websocket 更易用）
  4. cookie 自动持久化到 user-data-dir

依赖：playwright（通过 cdp_url 连接，不自己启动浏览器）
"""

import json
import os
import subprocess
import time
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# 配置常量
# ============================================================

CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
CDP_URL = f"http://{CDP_HOST}:{CDP_PORT}"

BROWSER_DATA_DIR = os.path.expanduser(
    os.environ.get("BROWSER_DATA_DIR", "~/.browser_data_dir")
)
BROWSER_WINDOW_WIDTH = 1280
BROWSER_WINDOW_HEIGHT = 960

# Xvfb 虚拟显示配置
XVFB_DISPLAY = ":99"
XVFB_RESOLUTION = "1280x960x24"

# ============================================================
# 全局状态
# ============================================================

_playwright = None
_browser = None       # Playwright Browser (CDP 连接)
_context = None       # BrowserContext
_lock = threading.Lock()
_browser_process = None  # 外部 Chromium 进程
_xvfb_process = None     # Xvfb 进程


# ============================================================
# 浏览器生命周期管理
# ============================================================

def _is_cdp_ready() -> bool:
    """检查 CDP 端口是否就绪"""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=3)
        data = json.loads(resp.read())
        logger.info("CDP 已就绪: %s", data.get("Browser", "unknown"))
        return True
    except Exception:
        return False


def _ensure_xvfb():
    """确保 Xvfb 虚拟显示在运行（无头服务器需要）"""
    global _xvfb_process

    # 检查是否已有 DISPLAY
    if os.environ.get("DISPLAY"):
        return

    # 检查 Xvfb 是否已在运行
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"Xvfb {XVFB_DISPLAY}"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            os.environ["DISPLAY"] = XVFB_DISPLAY
            logger.info("Xvfb 已在运行 (%s)", XVFB_DISPLAY)
            return
    except Exception:
        pass

    # 安装 Xvfb（如果需要）
    try:
        subprocess.run(["which", "Xvfb"], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        logger.info("安装 Xvfb...")
        subprocess.run(
            ["sudo", "apt-get", "update", "-qq"],
            capture_output=True
        )
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "-qq", "xvfb"],
            capture_output=True
        )

    # 启动 Xvfb
    logger.info("启动 Xvfb (%s, %s)...", XVFB_DISPLAY, XVFB_RESOLUTION)
    _xvfb_process = subprocess.Popen(
        [
            "Xvfb", XVFB_DISPLAY,
            "-screen", "0", XVFB_RESOLUTION,
            "-ac", "+extension", "GLX", "+render", "-noreset"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    os.environ["DISPLAY"] = XVFB_DISPLAY
    logger.info("Xvfb 已启动 (PID: %d)", _xvfb_process.pid)


def _find_chrome_binary() -> Optional[str]:
    """查找 Chrome/Chromium 可执行文件"""
    candidates = [
        "chromium-browser", "chromium",
        "google-chrome", "google-chrome-stable",
    ]
    for name in candidates:
        try:
            result = subprocess.run(
                ["which", name], capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            continue
    return None


def start_browser() -> bool:
    """
    启动外部 Chromium 浏览器进程（带 CDP 远程调试端口）。
    如果已经在运行则跳过。
    返回是否成功。
    """
    global _browser_process

    if _is_cdp_ready():
        logger.info("Chromium 已在运行，跳过启动")
        return True

    _ensure_xvfb()

    chrome_bin = _find_chrome_binary()
    if not chrome_bin:
        logger.error("未找到 Chrome/Chromium，请先安装")
        return False

    os.makedirs(BROWSER_DATA_DIR, exist_ok=True)

    cmd = [
        chrome_bin,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={BROWSER_DATA_DIR}",
        f"--window-size={BROWSER_WINDOW_WIDTH},{BROWSER_WINDOW_HEIGHT}",
        "--window-position=0,0",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-sync",
        "--no-sandbox",
        "--disable-gpu-sandbox",
        "--noerrdialogs",
        "--lang=zh-CN",
    ]

    logger.info("启动 Chromium: %s (CDP port: %d)", chrome_bin, CDP_PORT)
    _browser_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", XVFB_DISPLAY)},
    )

    # 等待 CDP 就绪
    for i in range(30):
        if _is_cdp_ready():
            logger.info("Chromium 已就绪 (PID: %d)", _browser_process.pid)
            return True
        time.sleep(1)

    logger.error("Chromium 启动超时")
    return False


def stop_browser():
    """停止外部 Chromium 进程"""
    global _browser_process, _xvfb_process
    if _browser_process:
        try:
            _browser_process.terminate()
            _browser_process.wait(timeout=5)
        except Exception:
            try:
                _browser_process.kill()
            except Exception:
                pass
        _browser_process = None
        logger.info("Chromium 已停止")

    if _xvfb_process:
        try:
            _xvfb_process.terminate()
        except Exception:
            pass
        _xvfb_process = None


# ============================================================
# Playwright CDP 连接
# ============================================================

def get_context():
    """
    获取 Playwright BrowserContext（通过 CDP 连接到外部 Chromium）。
    自动启动浏览器（如果未运行）。
    Cookie 由 Chromium 自身的 user-data-dir 持久化，无需手动管理。
    """
    global _playwright, _browser, _context

    with _lock:
        # 检查现有连接是否还活着
        if _context is not None:
            try:
                _context.pages  # 测试连接
                return _context
            except Exception:
                logger.warning("CDP 连接已断开，重新连接...")
                _cleanup_playwright()

        # 确保浏览器在运行
        if not start_browser():
            raise RuntimeError("无法启动 Chromium 浏览器")

        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()

        # 通过 CDP 连接到已运行的 Chromium
        _browser = _playwright.chromium.connect_over_cdp(CDP_URL)
        logger.info("Playwright 已通过 CDP 连接到 Chromium")

        # 获取默认上下文（包含 Chromium 自身的 cookie）
        contexts = _browser.contexts
        if contexts:
            _context = contexts[0]
            logger.info("使用已有的浏览器上下文 (pages: %d)", len(_context.pages))
        else:
            _context = _browser.new_context(
                viewport={"width": BROWSER_WINDOW_WIDTH, "height": BROWSER_WINDOW_HEIGHT},
                locale="zh-CN",
            )
            logger.info("创建了新的浏览器上下文")

        return _context


def _cleanup_playwright():
    """清理 Playwright 连接（不停止外部浏览器）"""
    global _playwright, _browser, _context
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _playwright:
            _playwright.stop()
    except Exception:
        pass
    _context = None
    _browser = None
    _playwright = None


# ============================================================
# 页面操作 API
# ============================================================

def new_page(url: Optional[str] = None, wait_seconds: float = 2.0):
    """
    在浏览器中打开新标签页。
    返回 Playwright Page 对象。
    """
    ctx = get_context()
    page = ctx.new_page()
    if url:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        page.wait_for_timeout(int(wait_seconds * 1000))
    return page


def fetch_page(url: str, wait_seconds: float = 2.0,
               extract_js: Optional[str] = None, max_chars: int = 3000):
    """
    通用页面抓取：导航到 URL，等待加载，提取文本。
    extract_js: 可选的自定义 JS 提取函数。
    """
    page = new_page(url, wait_seconds)
    try:
        if extract_js:
            return page.evaluate(extract_js)
        else:
            text = page.evaluate(f"""
                () => {{
                    const el = document.querySelector('article')
                        || document.querySelector('.article-content')
                        || document.querySelector('main')
                        || document.body;
                    return el.innerText.substring(0, {max_chars});
                }}
            """)
            return text
    except Exception as e:
        logger.warning("fetch_page 异常: %s", e)
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


def screenshot(page=None, path: Optional[str] = None, full_page: bool = False) -> Optional[bytes]:
    """
    对页面截图。
    如果不传 page，则对当前活动页面截图。
    返回 PNG 字节数据。
    """
    if page is None:
        ctx = get_context()
        pages = ctx.pages
        if not pages:
            return None
        page = pages[-1]

    data = page.screenshot(full_page=full_page)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return data


def get_login_status() -> dict:
    """
    检查各平台的登录状态。
    通过访问需要登录的页面，检查是否被重定向到登录页。
    """
    status = {}
    platforms = {
        "xiaohongshu": {
            "check_url": "https://www.xiaohongshu.com/user/profile/self",
            "login_indicator": "login",  # URL 中包含 login 表示未登录
        },
        "weibo": {
            "check_url": "https://weibo.com/ajax/profile/info",
            "login_indicator": "passport",
        },
        "douban": {
            "check_url": "https://www.douban.com/mine/",
            "login_indicator": "accounts.douban.com",
        },
    }

    for name, config in platforms.items():
        try:
            page = new_page(config["check_url"], wait_seconds=3)
            current_url = page.url
            is_logged_in = config["login_indicator"] not in current_url.lower()
            status[name] = {
                "logged_in": is_logged_in,
                "url": current_url,
            }
            page.close()
        except Exception as e:
            status[name] = {"logged_in": False, "error": str(e)}

    return status


# ============================================================
# Cookie 持久化
# ============================================================

COOKIE_DIR = os.path.expanduser("~/.browser_cookies")

PLATFORM_DOMAINS = {
    "xiaohongshu": [".xiaohongshu.com", "xiaohongshu.com"],
    "weibo": [".weibo.com", "weibo.com", ".weibo.cn", ".sina.com.cn", "sina.com.cn"],
    "douban": [".douban.com", "douban.com"],
}


def save_cookies(platform: Optional[str] = None) -> dict:
    """
    保存浏览器 cookie 到磁盘。
    如果指定 platform，只保存该平台的 cookie；
    否则保存所有平台 + 全量 cookie。
    返回各平台保存的 cookie 数量。
    """
    ctx = get_context()
    if not ctx:
        return {}

    cookies = ctx.cookies()
    os.makedirs(COOKIE_DIR, exist_ok=True)
    result = {}

    targets = {platform: PLATFORM_DOMAINS[platform]} if platform and platform in PLATFORM_DOMAINS else PLATFORM_DOMAINS

    for name, domains in targets.items():
        platform_cookies = [c for c in cookies if any(d in c.get("domain", "") for d in domains)]
        if platform_cookies:
            path = os.path.join(COOKIE_DIR, f"{name}_cookies.json")
            with open(path, "w") as f:
                json.dump(platform_cookies, f, ensure_ascii=False, indent=2)
            result[name] = len(platform_cookies)
            logger.info("保存 %s cookie: %d 个 -> %s", name, len(platform_cookies), path)

    # 保存全量
    all_path = os.path.join(COOKIE_DIR, "all_cookies.json")
    with open(all_path, "w") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    result["_total"] = len(cookies)

    return result


def load_cookies(platform: Optional[str] = None) -> int:
    """
    从磁盘加载 cookie 到浏览器。
    如果指定 platform，只加载该平台；否则加载所有平台。
    返回加载的 cookie 总数。
    """
    ctx = get_context()
    if not ctx:
        return 0

    total = 0
    if platform:
        files = [os.path.join(COOKIE_DIR, f"{platform}_cookies.json")]
    else:
        files = [os.path.join(COOKIE_DIR, f"{p}_cookies.json") for p in PLATFORM_DOMAINS]

    for path in files:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                cookies = json.load(f)
            ctx.add_cookies(cookies)
            total += len(cookies)
            logger.info("加载 cookie: %d 个 <- %s", len(cookies), path)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("加载 cookie 失败 (%s): %s", path, e)

    return total


# ============================================================
# CDP 原始操作（用于远程控制和验证码处理）
# ============================================================

def get_cdp_ws_url() -> Optional[str]:
    """获取 CDP WebSocket URL"""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"{CDP_URL}/json")
        pages = json.loads(resp.read())
        for page in pages:
            if page.get("type") == "page":
                return page["webSocketDebuggerUrl"]
    except Exception:
        pass
    return None


def get_cdp_info() -> Optional[dict]:
    """获取 CDP 浏览器信息"""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=3)
        return json.loads(resp.read())
    except Exception:
        return None


# ============================================================
# 浏览器原子操作 — 涌现的基础层
# ============================================================

class BrowserAtomicOps:
    """
    浏览器原子操作集合 — Agent 的"手"和"眼"。
    
    这些操作是最底层的能力单元，Agent 可以通过 LLM 将它们组合成
    更高级的技能（如"截图分享"="screenshot + send_to_chat"）。
    
    每个操作都是幂等的、独立的，返回统一格式的结果字典。
    """
    
    # 所有可用原子操作的描述（供 LLM 理解和组合）
    OPERATIONS = {
        "screenshot": {
            "description": "对当前浏览器页面截图，返回图片文件路径",
            "params": {"full_page": "是否全页截图（默认否，只截可见区域）"},
            "returns": "图片文件路径",
            "category": "capture",
        },
        "get_current_url": {
            "description": "获取当前浏览器页面的 URL 地址",
            "params": {},
            "returns": "当前页面的 URL 字符串",
            "category": "info",
        },
        "get_page_title": {
            "description": "获取当前浏览器页面的标题",
            "params": {},
            "returns": "页面标题字符串",
            "category": "info",
        },
        "extract_text": {
            "description": "提取当前页面的文字内容",
            "params": {"selector": "CSS选择器（可选，默认提取整个页面）", "max_chars": "最大字符数（默认2000）"},
            "returns": "页面文字内容",
            "category": "capture",
        },
        "navigate": {
            "description": "导航到指定的 URL",
            "params": {"url": "目标网址"},
            "returns": "导航是否成功",
            "category": "action",
        },
        "click": {
            "description": "点击页面上的元素",
            "params": {"selector": "CSS选择器"},
            "returns": "点击是否成功",
            "category": "action",
        },
        "type_text": {
            "description": "在页面输入框中输入文字",
            "params": {"selector": "CSS选择器", "text": "要输入的文字"},
            "returns": "输入是否成功",
            "category": "action",
        },
        "scroll": {
            "description": "滚动页面",
            "params": {"direction": "方向（up/down）", "amount": "滚动像素数（默认500）"},
            "returns": "滚动是否成功",
            "category": "action",
        },
    }
    
    @staticmethod
    def get_operations_description():
        """生成原子操作的文字描述，供 LLM 理解可用能力"""
        lines = ["你拥有以下浏览器原子操作能力："]
        for op_name, op_info in BrowserAtomicOps.OPERATIONS.items():
            params_str = ""
            if op_info["params"]:
                params_list = [f"{k}({v})" for k, v in op_info["params"].items()]
                params_str = f"，参数：{', '.join(params_list)}"
            lines.append(f"- **{op_name}**: {op_info['description']}{params_str}")
        return "\n".join(lines)
    
    @staticmethod
    def execute(operation, params=None):
        """
        执行一个原子操作。
        
        Args:
            operation: 操作名称（如 'screenshot', 'get_current_url'）
            params: 操作参数字典
        
        Returns:
            {"success": bool, "result": any, "error": str|None}
        """
        params = params or {}
        
        dispatch = {
            "screenshot": BrowserAtomicOps._op_screenshot,
            "get_current_url": BrowserAtomicOps._op_get_current_url,
            "get_page_title": BrowserAtomicOps._op_get_page_title,
            "extract_text": BrowserAtomicOps._op_extract_text,
            "navigate": BrowserAtomicOps._op_navigate,
            "click": BrowserAtomicOps._op_click,
            "type_text": BrowserAtomicOps._op_type_text,
            "scroll": BrowserAtomicOps._op_scroll,
        }
        
        handler = dispatch.get(operation)
        if not handler:
            return {"success": False, "result": None, "error": f"未知操作: {operation}"}
        
        try:
            return handler(params)
        except Exception as e:
            logger.error("原子操作 %s 执行失败: %s", operation, e)
            return {"success": False, "result": None, "error": str(e)}
    
    @staticmethod
    def _get_active_page():
        """获取当前活跃页面"""
        ctx = get_context()
        pages = ctx.pages
        if not pages:
            return None
        return pages[-1]
    
    @staticmethod
    def _op_screenshot(params):
        """截图操作"""
        page = BrowserAtomicOps._get_active_page()
        if not page:
            return {"success": False, "result": None, "error": "没有打开的页面"}
        
        full_page = params.get("full_page", False)
        timestamp = int(time.time())
        filepath = os.path.join(
            os.path.expanduser("~"), ".chimera_screenshots",
            f"screenshot_{timestamp}.png"
        )
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        data = page.screenshot(full_page=full_page)
        with open(filepath, "wb") as f:
            f.write(data)
        
        logger.info("截图保存: %s (%d bytes)", filepath, len(data))
        return {"success": True, "result": filepath, "error": None}
    
    @staticmethod
    def _op_get_current_url(params):
        """获取当前 URL"""
        page = BrowserAtomicOps._get_active_page()
        if not page:
            return {"success": False, "result": None, "error": "没有打开的页面"}
        
        url = page.url
        return {"success": True, "result": url, "error": None}
    
    @staticmethod
    def _op_get_page_title(params):
        """获取页面标题"""
        page = BrowserAtomicOps._get_active_page()
        if not page:
            return {"success": False, "result": None, "error": "没有打开的页面"}
        
        title = page.title()
        return {"success": True, "result": title, "error": None}
    
    @staticmethod
    def _op_extract_text(params):
        """提取页面文字"""
        page = BrowserAtomicOps._get_active_page()
        if not page:
            return {"success": False, "result": None, "error": "没有打开的页面"}
        
        selector = params.get("selector", "")
        max_chars = params.get("max_chars", 2000)
        
        try:
            if selector:
                text = page.evaluate(f"""
                    () => {{
                        const el = document.querySelector('{selector}');
                        return el ? el.innerText.substring(0, {max_chars}) : '';
                    }}
                """)
            else:
                text = page.evaluate(f"""
                    () => {{
                        const el = document.querySelector('article')
                            || document.querySelector('.article-content')
                            || document.querySelector('main')
                            || document.body;
                        return el.innerText.substring(0, {max_chars});
                    }}
                """)
            return {"success": True, "result": text, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}
    
    @staticmethod
    def _op_navigate(params):
        """导航到 URL"""
        url = params.get("url", "")
        if not url:
            return {"success": False, "result": None, "error": "缺少 url 参数"}
        
        page = BrowserAtomicOps._get_active_page()
        if not page:
            # 没有页面则新建
            page = new_page(url)
            return {"success": True, "result": page.url, "error": None}
        
        try:
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            return {"success": True, "result": page.url, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}
    
    @staticmethod
    def _op_click(params):
        """点击元素"""
        selector = params.get("selector", "")
        if not selector:
            return {"success": False, "result": None, "error": "缺少 selector 参数"}
        
        page = BrowserAtomicOps._get_active_page()
        if not page:
            return {"success": False, "result": None, "error": "没有打开的页面"}
        
        try:
            page.click(selector, timeout=5000)
            return {"success": True, "result": True, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}
    
    @staticmethod
    def _op_type_text(params):
        """输入文字"""
        selector = params.get("selector", "")
        text = params.get("text", "")
        if not selector or not text:
            return {"success": False, "result": None, "error": "缺少 selector 或 text 参数"}
        
        page = BrowserAtomicOps._get_active_page()
        if not page:
            return {"success": False, "result": None, "error": "没有打开的页面"}
        
        try:
            page.fill(selector, text, timeout=5000)
            return {"success": True, "result": True, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}
    
    @staticmethod
    def _op_scroll(params):
        """滚动页面"""
        direction = params.get("direction", "down")
        amount = params.get("amount", 500)
        
        page = BrowserAtomicOps._get_active_page()
        if not page:
            return {"success": False, "result": None, "error": "没有打开的页面"}
        
        try:
            y = amount if direction == "down" else -amount
            page.evaluate(f"window.scrollBy(0, {y})")
            return {"success": True, "result": True, "error": None}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}


# ============================================================
# 清理
# ============================================================

def close():
    """关闭 Playwright 连接（不停止外部浏览器）"""
    with _lock:
        _cleanup_playwright()
    logger.info("Playwright 连接已关闭")


def close_all():
    """关闭一切：Playwright 连接 + 外部浏览器 + Xvfb"""
    close()
    stop_browser()
    logger.info("所有浏览器资源已释放")
