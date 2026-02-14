"""
browser_pool.py - 管理 Playwright 浏览器实例和 cookie
提供一个全局的浏览器上下文，复用 Chromium 的登录状态
"""

import json
import os
import sqlite3
import time
import threading

# 延迟导入 playwright
_playwright = None
_browser = None
_context = None
_lock = threading.Lock()

COOKIE_DB = os.path.expanduser("~/.browser_data_dir/Default/Cookies")
COOKIE_CACHE = os.path.expanduser("~/chimera/browser_cookies.json")


def _decrypt_chromium_cookies(domains):
    """从 Chromium cookie 数据库解密 cookie"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
    except ImportError:
        print("⚠️ cryptography 未安装，尝试用缓存的 cookie")
        return _load_cached_cookies()

    if not os.path.exists(COOKIE_DB):
        print("⚠️ Chromium cookie 数据库不存在")
        return _load_cached_cookies()

    # Linux Chromium 默认密钥
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b'saltysalt',
        iterations=1,
    )
    key = kdf.derive(b'peanuts')

    conn = sqlite3.connect(COOKIE_DB)
    c = conn.cursor()

    conditions = " OR ".join([f"host_key LIKE '%{d}%'" for d in domains])
    c.execute(f"""
        SELECT host_key, name, encrypted_value, value, path,
               expires_utc, is_secure, is_httponly, samesite
        FROM cookies WHERE {conditions}
    """)

    cookies = []
    for row in c.fetchall():
        host, name, enc_val, plain_val, path, expires, secure, httponly, samesite = row

        if plain_val:
            value = plain_val
        elif enc_val:
            value = _decrypt_v10(enc_val, key)
            if value is None:
                continue
        else:
            continue

        cookie = {
            "name": name,
            "value": value,
            "domain": host,
            "path": path or "/",
            "secure": bool(secure),
            "httpOnly": bool(httponly),
        }

        samesite_map = {-1: "None", 0: "None", 1: "Lax", 2: "Strict"}
        cookie["sameSite"] = samesite_map.get(samesite, "None")

        if expires and expires > 0:
            cookie["expires"] = (expires / 1000000) - 11644473600
        else:
            cookie["expires"] = -1

        cookies.append(cookie)

    conn.close()

    # 缓存到文件
    with open(COOKIE_CACHE, 'w') as f:
        json.dump(cookies, f)

    print(f"🍪 从 Chromium 导出了 {len(cookies)} 个 cookie")
    return cookies


def _decrypt_v10(encrypted_value, key):
    """解密 v10 前缀的 cookie"""
    if encrypted_value[:3] != b'v10':
        try:
            return encrypted_value.decode('utf-8', errors='replace')
        except:
            return None

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        iv = b' ' * 16
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        data = encrypted_value[3:]
        decrypted = decryptor.update(data) + decryptor.finalize()
        pad_len = decrypted[-1]
        if pad_len > 16:
            return None
        return decrypted[:-pad_len].decode('utf-8')
    except:
        pass

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = encrypted_value[3:15]
        ciphertext_with_tag = encrypted_value[15:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        return plaintext.decode('utf-8')
    except:
        pass

    return None


def _load_cached_cookies():
    """从缓存文件加载 cookie"""
    if os.path.exists(COOKIE_CACHE):
        with open(COOKIE_CACHE) as f:
            cookies = json.load(f)
        print(f"🍪 从缓存加载了 {len(cookies)} 个 cookie")
        return cookies
    return []


def get_context():
    """获取或创建浏览器上下文（带 cookie）"""
    global _playwright, _browser, _context

    with _lock:
        if _context is not None:
            try:
                # 检查上下文是否还活着
                _context.pages
                return _context
            except:
                _context = None
                _browser = None
                _playwright = None

        from playwright.sync_api import sync_playwright

        # 尝试加载 stealth 反检测插件
        stealth_obj = None
        try:
            from playwright_stealth import Stealth
            stealth_obj = Stealth(
                navigator_languages_override=('zh-CN', 'zh', 'en-US', 'en'),
                navigator_platform_override='Linux x86_64',
                navigator_vendor_override='Google Inc.',
            )
            print("🥷 playwright-stealth 已加载")
        except ImportError:
            print("⚠️ playwright-stealth 未安装，用普通模式")

        _playwright = sync_playwright().start()

        # stealth hook: 在 launch 之前注入反检测脚本
        if stealth_obj:
            stealth_obj.hook_playwright_context(_playwright)

        _browser = _playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
            ]
        )
        _context = _browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )

        # 对 context 应用 stealth
        if stealth_obj:
            stealth_obj.apply_stealth_sync(_context)

        # 加载 cookie
        domains = ["xiaohongshu", "douban", "weibo"]
        cookies = _decrypt_chromium_cookies(domains)
        if cookies:
            # playwright 的 add_cookies 需要特定格式
            valid_cookies = []
            for c in cookies:
                try:
                    cookie = {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c["domain"],
                        "path": c["path"],
                    }
                    if c.get("expires") and c["expires"] > 0:
                        cookie["expires"] = c["expires"]
                    if c.get("secure"):
                        cookie["secure"] = True
                    if c.get("httpOnly"):
                        cookie["httpOnly"] = True
                    if c.get("sameSite") in ("Strict", "Lax", "None"):
                        cookie["sameSite"] = c["sameSite"]
                    valid_cookies.append(cookie)
                except Exception as e:
                    pass

            try:
                _context.add_cookies(valid_cookies)
                print(f"🍪 已加载 {len(valid_cookies)} 个 cookie 到浏览器上下文")
            except Exception as e:
                print(f"⚠️ 加载 cookie 失败: {e}")

        return _context


def fetch_page(url, wait_seconds=2, extract_js=None, max_chars=3000):
    """
    通用页面抓取：导航到 URL，等待加载，提取文本
    extract_js: 可选的自定义 JS 提取函数
    """
    ctx = get_context()
    page = ctx.new_page()

    try:
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(wait_seconds * 1000)

        if extract_js:
            result = page.evaluate(extract_js)
            return result
        else:
            # 默认提取 body 文本
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
        print(f"fetch_page 异常: {e}")
        return None
    finally:
        try:
            page.close()
        except:
            pass


def close():
    """关闭浏览器"""
    global _playwright, _browser, _context
    with _lock:
        try:
            if _context:
                _context.close()
            if _browser:
                _browser.close()
            if _playwright:
                _playwright.stop()
        except:
            pass
        _context = None
        _browser = None
        _playwright = None
