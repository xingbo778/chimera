"""
utils.py - 公共工具模块
统一管理：LLM 客户端、时间工具、JSON 解析、常量映射等。
"""

import json
import re
import logging
from datetime import datetime, timezone, timedelta
from openai import OpenAI

logger = logging.getLogger(__name__)

# ============================================================
# 全局 LLM 客户端（单例）
# ============================================================

_client = None


def get_llm_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


# ============================================================
# 时间工具
# ============================================================

_BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> datetime:
    """返回带有北京时区信息的 datetime"""
    return datetime.now(_BEIJING_TZ)


# ============================================================
# JSON 解析
# ============================================================

def parse_json_robust(text):
    """健壮的 JSON 解析：处理 markdown 代码块、尾部多余字符、截断等问题"""
    # 去掉 markdown 代码块
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = text.strip()

    # 策略1：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略2：用 brace 匹配提取最外层 JSON 对象
    brace_count = 0
    start = -1
    in_string = False
    escape = False
    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            if brace_count == 0:
                start = i
            brace_count += 1
        elif c == '}':
            brace_count -= 1
            if brace_count == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = -1

    # 策略3：如果 brace 不平衡（可能被截断），尝试补全
    if start >= 0 and brace_count > 0:
        partial = text[start:]
        for _ in range(brace_count):
            partial += '}'
        try:
            return json.loads(partial)
        except json.JSONDecodeError:
            for suffix in [']', ']}', ']}]', ']}}']:
                try:
                    return json.loads(partial + suffix)
                except json.JSONDecodeError:
                    continue

    return None


# ============================================================
# 常量映射
# ============================================================

PLATFORM_CN_NAMES = {
    "xhs": "小红书",
    "douban": "豆瓣",
    "weibo": "微博",
}
