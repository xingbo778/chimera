"""
browser_login.py - 平台登录管理器
==================================
支持小红书、微博、豆瓣的手机号验证码登录。
使用 browser-use Agent（LLM 驱动）+ CDP 连接已有浏览器。
验证码通过文件信号机制传递（支持远程控制 UI 或 Telegram 通知）。

登录流程：
  1. Agent 通过 CDP 连接到已运行的 Chromium
  2. LLM 驱动浏览器完成登录操作（输入手机号、点击发送验证码等）
  3. 遇到验证码时，通过信号文件等待人工输入
  4. 登录成功后 cookie 自动持久化到 Chromium 的 user-data-dir
"""

import asyncio
import json
import os
import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# 信号文件路径
SIGNAL_DIR = os.path.expanduser("~/chimera/login_signals")
VERIFICATION_CODE_FILE = os.path.join(SIGNAL_DIR, "verification_code.txt")
WAITING_FOR_INPUT_FILE = os.path.join(SIGNAL_DIR, "waiting_for_input.txt")
LOGIN_STATUS_FILE = os.path.join(SIGNAL_DIR, "login_status.json")

# 确保信号目录存在
os.makedirs(SIGNAL_DIR, exist_ok=True)

# CDP 连接配置
CDP_URL = os.environ.get("CDP_URL", "http://localhost:9222")

# 回调：当需要人工输入时通知（可被外部设置，如 Telegram 通知）
_human_notify_callback: Optional[Callable] = None


def set_human_notify_callback(callback: Callable):
    """设置人工通知回调（如通过 Telegram 发消息通知用户）"""
    global _human_notify_callback
    _human_notify_callback = callback


def _clean_signal_files():
    """清理旧的信号文件"""
    for f in [VERIFICATION_CODE_FILE, WAITING_FOR_INPUT_FILE]:
        if os.path.exists(f):
            os.remove(f)


def _save_login_status(platform: str, success: bool, detail: str = ""):
    """保存登录状态"""
    status = {}
    if os.path.exists(LOGIN_STATUS_FILE):
        try:
            with open(LOGIN_STATUS_FILE) as f:
                status = json.load(f)
        except Exception:
            pass

    status[platform] = {
        "logged_in": success,
        "detail": detail,
        "timestamp": time.time(),
    }

    with open(LOGIN_STATUS_FILE, "w") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def get_login_status() -> dict:
    """获取所有平台的登录状态"""
    if os.path.exists(LOGIN_STATUS_FILE):
        try:
            with open(LOGIN_STATUS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ============================================================
# Browser-Use Agent 登录
# ============================================================

def _create_ask_human_tools():
    """创建 ask_human 工具（通过文件信号等待人工输入）"""
    try:
        from browser_use import Tools, ActionResult
    except ImportError:
        logger.error("browser-use 未安装，请运行: pip install browser-use")
        raise

    tools = Tools()

    @tools.action(description=(
        "当你需要用户提供信息时调用此工具（例如：验证码、密码、确认操作等）。"
        "传入一个清晰的问题描述，系统会通知用户并等待回复。"
    ))
    async def ask_human(question: str) -> ActionResult:
        """通过文件信号等待人工输入"""
        logger.info("等待人工输入: %s", question)

        # 写入等待标志
        with open(WAITING_FOR_INPUT_FILE, "w") as f:
            f.write(question)

        # 通知回调（如 Telegram）
        if _human_notify_callback:
            try:
                _human_notify_callback(question)
            except Exception as e:
                logger.warning("通知回调失败: %s", e)

        # 轮询等待验证码文件
        timeout = 300  # 5 分钟超时
        elapsed = 0
        while not os.path.exists(VERIFICATION_CODE_FILE):
            await asyncio.sleep(1)
            elapsed += 1
            if elapsed >= timeout:
                if os.path.exists(WAITING_FOR_INPUT_FILE):
                    os.remove(WAITING_FOR_INPUT_FILE)
                return ActionResult(extracted_content="等待超时，用户未提供输入")

        # 读取回复
        with open(VERIFICATION_CODE_FILE, "r") as f:
            answer = f.read().strip()

        # 清理信号文件
        os.remove(VERIFICATION_CODE_FILE)
        if os.path.exists(WAITING_FOR_INPUT_FILE):
            os.remove(WAITING_FOR_INPUT_FILE)

        logger.info("收到人工输入: %s", answer)
        return ActionResult(extracted_content=f"用户回复: {answer}")

    return tools


def _get_login_task(platform: str, phone: str) -> str:
    """生成各平台的登录任务描述"""
    tasks = {
        "xiaohongshu": f"""
请完成以下操作来登录小红书 https://www.xiaohongshu.com：

1. 打开网站 https://www.xiaohongshu.com
2. 等待页面加载完成
3. 找到登录入口，选择"手机号登录"方式
   - 如果页面显示的是二维码登录，请找到并点击"其他登录方式"或类似的切换按钮
   - 然后选择"手机号登录"或"验证码登录"
4. 在手机号输入框中输入: {phone}
5. 如果需要勾选用户协议/隐私政策的复选框，请先勾选
6. 点击"发送验证码"按钮
7. 如果弹出了图形验证码（如滑块、点选图标等），使用 ask_human 工具通知用户："页面弹出了图形验证码，请通过远程控制界面手动完成验证，完成后输入 ok"
8. 使用 ask_human 工具向用户索要验证码（问题写："验证码已发送到 {phone}，请查看手机短信，输入收到的6位验证码"）
9. 将用户提供的验证码输入到验证码输入框中
10. 点击登录/确认按钮
11. 等待页面跳转，确认登录成功
12. 报告登录结果

重要提示：
- 遇到验证码时，必须使用 ask_human 工具向用户索要，不要猜测
- 如果遇到图形验证码/滑块验证，也使用 ask_human 告知用户手动完成
- 如果操作失败，使用 ask_human 请求用户帮助
""",
        "weibo": f"""
请完成以下操作来登录微博 https://weibo.com：

1. 打开一个新标签页，导航到 https://weibo.com
2. 等待页面加载完成
3. 找到登录入口
   - 如果页面已经有登录表单，直接使用
   - 如果需要点击"登录"按钮才能看到登录表单，请先点击
   - 找到并切换到"手机号登录"或"短信验证码登录"方式
4. 在手机号输入框中输入: {phone}
5. 如果需要勾选用户协议/隐私政策的复选框，请先勾选
6. 点击"获取验证码"或"发送验证码"按钮
7. 如果弹出了图形验证码（如滑块、点选图标等），使用 ask_human 工具通知用户："页面弹出了图形验证码，请通过远程控制界面手动完成验证，完成后输入 ok"
8. 使用 ask_human 工具向用户索要短信验证码（问题写："验证码已发送到 {phone}，请查看手机短信，输入收到的验证码"）
9. 将用户提供的验证码输入到验证码输入框中
10. 点击"登录"按钮
11. 等待页面跳转，确认登录成功
12. 报告登录结果

重要提示：
- 遇到需要输入验证码时，必须使用 ask_human 工具向用户索要，不要猜测
- 如果遇到图形验证码/滑块验证，使用 ask_human 告知用户手动完成
- 如果操作失败或遇到问题，使用 ask_human 请求用户帮助
""",
        "douban": f"""
请完成以下操作来登录豆瓣 https://www.douban.com：

1. 打开 https://accounts.douban.com/passport/login
2. 等待页面加载完成
3. 找到"手机号登录"或"密码登录"入口
   - 如果默认是密码登录，切换到手机号验证码登录
4. 在手机号输入框中输入: {phone}
5. 如果需要勾选用户协议，请先勾选
6. 点击"获取验证码"按钮
7. 如果弹出了图形验证码，使用 ask_human 工具通知用户："页面弹出了图形验证码，请通过远程控制界面手动完成验证，完成后输入 ok"
8. 使用 ask_human 工具向用户索要验证码（问题写："验证码已发送到 {phone}，请查看手机短信，输入收到的验证码"）
9. 将验证码输入到输入框中
10. 点击登录按钮
11. 确认登录成功
12. 报告结果

重要提示：
- 遇到验证码必须使用 ask_human 工具
- 图形验证码让用户通过远程控制界面手动完成
""",
    }
    return tasks.get(platform, "")


async def login_platform(platform: str, phone: str,
                         model: str = "gpt-4.1-mini") -> dict:
    """
    使用 Browser-Use Agent 登录指定平台。

    Args:
        platform: 平台名 ("xiaohongshu", "weibo", "douban")
        phone: 手机号
        model: LLM 模型名

    Returns:
        {"success": bool, "detail": str, "elapsed": float}
    """
    try:
        from browser_use import Agent, BrowserProfile, ChatOpenAI
    except ImportError:
        return {"success": False, "detail": "browser-use 未安装"}

    _clean_signal_files()

    task = _get_login_task(platform, phone)
    if not task:
        return {"success": False, "detail": f"不支持的平台: {platform}"}

    llm = ChatOpenAI(
        model=model,
        temperature=0.0,
        dont_force_structured_output=True,
        add_schema_to_system_prompt=True,
    )

    browser_profile = BrowserProfile(
        cdp_url=CDP_URL,
        keep_alive=True,
        minimum_wait_page_load_time=2.0,
        wait_between_actions=1.0,
    )

    tools = _create_ask_human_tools()

    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=browser_profile,
        tools=tools,
        max_steps=30,
        use_vision=True,
    )

    logger.info("开始 %s 登录 (手机号: %s)", platform, phone)
    start = time.time()

    try:
        history = await agent.run()
        elapsed = time.time() - start
        result_text = history.final_result()
        success = "成功" in str(result_text) or "登录" in str(result_text)

        _save_login_status(platform, success, str(result_text))

        logger.info("%s 登录完成 (%.1f秒): %s", platform, elapsed, result_text)
        return {
            "success": success,
            "detail": str(result_text),
            "elapsed": elapsed,
            "steps": len(history.history),
        }
    except Exception as e:
        elapsed = time.time() - start
        logger.error("%s 登录失败 (%.1f秒): %s", platform, elapsed, e)
        _save_login_status(platform, False, str(e))
        return {
            "success": False,
            "detail": str(e),
            "elapsed": elapsed,
        }


async def login_all(phone: str, platforms: Optional[list] = None):
    """依次登录所有平台"""
    if platforms is None:
        platforms = ["xiaohongshu", "weibo", "douban"]

    results = {}
    for platform in platforms:
        logger.info("=" * 50)
        logger.info("开始登录: %s", platform)
        result = await login_platform(platform, phone)
        results[platform] = result
        logger.info("%s 结果: %s", platform, "成功" if result["success"] else "失败")

        # 登录之间等待一下
        if platform != platforms[-1]:
            await asyncio.sleep(3)

    return results


# ============================================================
# 提供验证码的便捷函数（供外部调用）
# ============================================================

def submit_verification_code(code: str):
    """提交验证码（写入信号文件）"""
    with open(VERIFICATION_CODE_FILE, "w") as f:
        f.write(code)
    logger.info("验证码已提交: %s", code)


def is_waiting_for_input() -> Optional[str]:
    """检查是否正在等待人工输入，返回问题描述或 None"""
    if os.path.exists(WAITING_FOR_INPUT_FILE):
        with open(WAITING_FOR_INPUT_FILE) as f:
            return f.read().strip()
    return None


# ============================================================
# CLI 入口
# ============================================================

def main():
    """命令行登录入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Chimera 平台登录工具")
    parser.add_argument("platform", choices=["xiaohongshu", "weibo", "douban", "all"],
                        help="要登录的平台")
    parser.add_argument("--phone", required=True, help="手机号")
    parser.add_argument("--model", default="gpt-4.1-mini", help="LLM 模型")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.platform == "all":
        results = asyncio.run(login_all(args.phone))
    else:
        results = asyncio.run(login_platform(args.platform, args.phone, args.model))

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
