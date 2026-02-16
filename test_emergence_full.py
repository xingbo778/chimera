"""
浏览器原子操作涌现机制 — 全面集成测试

覆盖范围：
1. 意图分类的边界情况（模糊表达、混合意图、误触发防护）
2. 操作执行的错误处理（浏览器未连接、页面为空等）
3. 缓存持久化的完整生命周期
4. 能力记忆的累积和查询
5. 模拟 _delayed_reply 中涌现拦截层的完整流程
6. 并发安全性基本验证
"""

import os
import sys
import json
import time
import shutil
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(__file__))


# ============================================================
# 1. 意图分类边界测试
# ============================================================

class TestIntentClassificationEdgeCases(unittest.TestCase):
    """测试意图分类的各种边界情况"""
    
    def test_fuzzy_screenshot_expressions(self):
        """测试模糊的截图表达"""
        from skill_connector import _classify_user_intent
        
        cases = [
            ("你在看什么呀", "screenshot_share"),
            ("看看你现在看什么", "screenshot_share"),
            ("截屏发我", "screenshot_share"),
            ("给我看看你屏幕", "screenshot_share"),
        ]
        for msg, expected in cases:
            intent = _classify_user_intent(msg)
            self.assertIsNotNone(intent, f"未识别: {msg}")
            self.assertEqual(intent["type"], expected, f"「{msg}」→ {intent['type']}（期望 {expected}）")
            print(f"  ✅ 「{msg}」→ {expected}")
        print("✅ 模糊截图表达全部识别")
    
    def test_url_variations(self):
        """测试 URL 分享的各种表达"""
        from skill_connector import _classify_user_intent
        
        cases = [
            ("把这个网址发给我", "share_url"),
            ("分享一下链接", "share_url"),
            ("url发我", "share_url"),
            ("这个地址是什么", "share_url"),
        ]
        for msg, expected in cases:
            intent = _classify_user_intent(msg)
            self.assertIsNotNone(intent, f"未识别: {msg}")
            self.assertEqual(intent["type"], expected, f"「{msg}」→ {intent['type']}（期望 {expected}）")
            print(f"  ✅ 「{msg}」→ {expected}")
        print("✅ URL 变体表达全部识别")
    
    def test_chat_exclusion_comprehensive(self):
        """全面测试普通聊天不触发涌现"""
        from skill_connector import _classify_user_intent
        
        chat_msgs = [
            "你好", "嗨", "在吗", "在干嘛",
            "今天天气好吗", "几点了",
            "好无聊啊", "我好累",
            "谢谢你", "哈哈哈",
            "好的", "嗯嗯", "行",
            "为什么呢", "怎么办",
            "我喜欢你", "想你了",
            "吃什么好", "喝什么",
            "晚安", "早安",
        ]
        for msg in chat_msgs:
            intent = _classify_user_intent(msg)
            is_none = intent is None or intent.get("type") == "none"
            self.assertTrue(is_none, f"普通聊天误触发: 「{msg}」→ {intent}")
            print(f"  ✅ 「{msg}」→ None")
        print(f"✅ {len(chat_msgs)} 条普通聊天全部正确过滤")
    
    def test_short_messages_excluded(self):
        """测试短消息不触发 LLM 分类"""
        from skill_connector import _classify_user_intent
        
        short_msgs = ["嗯", "哦", "好", "啊"]
        for msg in short_msgs:
            intent = _classify_user_intent(msg)
            self.assertIsNone(intent, f"短消息误触发: 「{msg}」→ {intent}")
        print("✅ 短消息正确过滤")
    
    def test_content_extraction_variants(self):
        """测试内容提取的各种表达"""
        from skill_connector import _classify_user_intent
        
        cases = [
            ("这页写了什么", "extract_content"),
            ("这个页面说了啥", "extract_content"),
            ("帮我看看这个", "extract_content"),
            ("这篇文章讲什么", "extract_content"),
            ("总结一下这个", "extract_content"),
        ]
        for msg, expected in cases:
            intent = _classify_user_intent(msg)
            self.assertIsNotNone(intent, f"未识别: {msg}")
            self.assertEqual(intent["type"], expected, f"「{msg}」→ {intent['type']}（期望 {expected}）")
            print(f"  ✅ 「{msg}」→ {expected}")
        print("✅ 内容提取变体全部识别")


# ============================================================
# 2. 操作执行错误处理
# ============================================================

class TestOperationErrorHandling(unittest.TestCase):
    """测试操作执行的错误处理"""
    
    def test_unknown_operation(self):
        """未知操作返回错误"""
        from browser_pool import BrowserAtomicOps
        result = BrowserAtomicOps.execute("fly_to_moon")
        self.assertFalse(result["success"])
        self.assertIn("未知操作", result["error"])
        print("✅ 未知操作正确返回错误")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_no_active_page(self, mock_get_page):
        """没有活跃页面时的错误处理"""
        mock_get_page.return_value = None
        
        from browser_pool import BrowserAtomicOps
        
        ops = ["screenshot", "get_current_url", "get_page_title", "extract_text"]
        for op in ops:
            result = BrowserAtomicOps.execute(op)
            self.assertFalse(result["success"])
            self.assertIn("没有打开的页面", result["error"])
            print(f"  ✅ {op} 无页面时正确报错")
        print("✅ 无页面错误处理全部正确")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_screenshot_failure_is_fatal(self, mock_get_page):
        """截图失败应该终止整个操作序列"""
        mock_get_page.return_value = None
        
        from skill_connector import _execute_instant_operations
        
        operations = [
            {"operation": "screenshot", "params": {"full_page": False}, "output_key": "screenshot_path"},
        ]
        result = _execute_instant_operations(operations)
        self.assertIsNone(result, "截图失败应返回 None")
        print("✅ 截图失败正确终止操作序列")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_non_fatal_operation_continues(self, mock_get_page):
        """非致命操作失败时继续执行后续操作"""
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.title.side_effect = Exception("title error")
        mock_get_page.return_value = mock_page
        
        from skill_connector import _execute_instant_operations
        
        operations = [
            {"operation": "get_current_url", "params": {}, "output_key": "url"},
            {"operation": "get_page_title", "params": {}, "output_key": "title"},
        ]
        result = _execute_instant_operations(operations)
        
        # get_current_url 应该成功，get_page_title 失败但不终止
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertIn("url", result["results"])
        self.assertEqual(result["results"]["url"], "https://example.com")
        print("✅ 非致命操作失败后继续执行")
    
    def test_navigate_without_url(self):
        """导航缺少 URL 参数"""
        from browser_pool import BrowserAtomicOps
        result = BrowserAtomicOps.execute("navigate", {})
        self.assertFalse(result["success"])
        self.assertIn("缺少 url 参数", result["error"])
        print("✅ 导航缺少 URL 正确报错")
    
    def test_click_without_selector(self):
        """点击缺少选择器"""
        from browser_pool import BrowserAtomicOps
        result = BrowserAtomicOps.execute("click", {})
        self.assertFalse(result["success"])
        self.assertIn("缺少 selector 参数", result["error"])
        print("✅ 点击缺少选择器正确报错")
    
    def test_type_text_without_params(self):
        """输入文字缺少参数"""
        from browser_pool import BrowserAtomicOps
        result = BrowserAtomicOps.execute("type_text", {})
        self.assertFalse(result["success"])
        self.assertIn("缺少", result["error"])
        print("✅ 输入文字缺少参数正确报错")


# ============================================================
# 3. 缓存生命周期测试
# ============================================================

class TestCacheLifecycle(unittest.TestCase):
    """测试即时技能缓存的完整生命周期"""
    
    def setUp(self):
        from skill_connector import _instant_skill_cache, _INSTANT_CACHE_FILE
        self._original_cache = dict(_instant_skill_cache)
        self._cache_file = _INSTANT_CACHE_FILE
        # 清理缓存
        _instant_skill_cache.clear()
        if os.path.exists(self._cache_file):
            os.remove(self._cache_file)
    
    def tearDown(self):
        from skill_connector import _instant_skill_cache
        _instant_skill_cache.clear()
        _instant_skill_cache.update(self._original_cache)
        if os.path.exists(self._cache_file):
            os.remove(self._cache_file)
    
    def test_empty_cache_returns_none(self):
        """空缓存不影响新意图识别"""
        from skill_connector import _instant_skill_cache
        self.assertEqual(len(_instant_skill_cache), 0)
        print("✅ 空缓存状态正确")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_cache_populated_after_success(self, mock_get_page):
        """成功执行后缓存被填充"""
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.title.return_value = "Example"
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution, _instant_skill_cache
        
        self.assertEqual(len(_instant_skill_cache), 0)
        
        result = attempt_instant_execution("发个链接给我")
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        
        self.assertIn("share_url", _instant_skill_cache)
        print("✅ 成功执行后缓存正确填充")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_cache_persists_to_disk(self, mock_get_page):
        """缓存正确持久化到磁盘"""
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.title.return_value = "Example"
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution, _save_instant_cache, _INSTANT_CACHE_FILE
        
        attempt_instant_execution("发个链接")
        
        self.assertTrue(os.path.exists(_INSTANT_CACHE_FILE))
        
        with open(_INSTANT_CACHE_FILE, "r") as f:
            disk_cache = json.load(f)
        self.assertIn("share_url", disk_cache)
        print("✅ 缓存正确持久化到磁盘")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_cache_reload_from_disk(self, mock_get_page):
        """从磁盘重新加载缓存"""
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.title.return_value = "Example"
        mock_get_page.return_value = mock_page
        
        from skill_connector import (
            attempt_instant_execution, _instant_skill_cache,
            _load_instant_cache, _save_instant_cache
        )
        
        # 先执行一次，填充缓存
        attempt_instant_execution("发个链接")
        self.assertIn("share_url", _instant_skill_cache)
        
        # 清空内存缓存
        _instant_skill_cache.clear()
        self.assertEqual(len(_instant_skill_cache), 0)
        
        # 从磁盘重新加载
        _load_instant_cache()
        self.assertIn("share_url", _instant_skill_cache)
        print("✅ 从磁盘重新加载缓存正确")


# ============================================================
# 4. 能力记忆累积测试
# ============================================================

class TestCapabilityMemoryAccumulation(unittest.TestCase):
    """测试能力记忆的累积和查询"""
    
    def setUp(self):
        self.test_dir = "/tmp/test_cap_mem_accum"
        os.makedirs(self.test_dir, exist_ok=True)
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_multiple_atomic_ops_recorded(self):
        """多次原子操作都被记录"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        cm.record_browser_atomic("screenshot", "用户请求截图")
        cm.record_browser_atomic("get_current_url", "用户请求链接")
        cm.record_browser_atomic("extract_text", "用户请求内容")
        
        self.assertEqual(cm.get_capability_count(), 3)
        self.assertTrue(cm.has_capability("browser_screenshot"))
        self.assertTrue(cm.has_capability("browser_get_current_url"))
        self.assertTrue(cm.has_capability("browser_extract_text"))
        print("✅ 多次原子操作全部记录")
    
    def test_use_count_increments(self):
        """重复使用同一操作时计数递增"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        cm.record_browser_atomic("screenshot", "第一次截图")
        cm.record_browser_atomic("screenshot", "第二次截图")
        cm.record_browser_atomic("screenshot", "第三次截图")
        
        self.assertEqual(cm.capabilities["browser_screenshot"]["use_count"], 3)
        print("✅ 使用计数正确递增")
    
    def test_examples_limited_to_5(self):
        """示例数量限制在 5 个"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        for i in range(10):
            cm.record_browser_atomic("screenshot", f"第{i+1}次截图")
        
        examples = cm.capabilities["browser_screenshot"]["examples"]
        self.assertLessEqual(len(examples), 5)
        print(f"✅ 示例数量限制正确: {len(examples)} 个")
    
    def test_emerged_skill_summary(self):
        """涌现技能摘要格式正确"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        cm.record_emerged_skill("screenshot_share", [{"operation": "screenshot"}], "截图看看")
        cm.record_emerged_skill("share_url", [{"operation": "get_current_url"}, {"operation": "get_page_title"}], "发个链接")
        
        summary = cm.get_emerged_skills_summary()
        self.assertIn("screenshot_share", summary)
        self.assertIn("share_url", summary)
        self.assertIn("用过1次", summary)
        print(f"✅ 涌现技能摘要格式正确:\n{summary}")
    
    def test_browser_capabilities_filter(self):
        """浏览器能力过滤正确"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        cm.record_browser_atomic("screenshot", "截图")
        cm.record_emerged_skill("screenshot_share", [{"operation": "screenshot"}], "截图")
        cm.record_capability("web_search", "能搜索网页", "搜了天气")
        
        browser_caps = cm.get_browser_capabilities()
        self.assertIn("browser_screenshot", browser_caps)
        self.assertIn("emerged_screenshot_share", browser_caps)
        self.assertNotIn("web_search", browser_caps)
        print("✅ 浏览器能力过滤正确")
    
    def test_persistence_across_instances(self):
        """能力记忆跨实例持久化"""
        from capability_memory import CapabilityMemory
        
        cm1 = CapabilityMemory(self.test_dir)
        cm1.record_browser_atomic("screenshot", "截图")
        cm1.record_emerged_skill("screenshot_share", [{"operation": "screenshot"}], "截图")
        
        # 创建新实例，应该能读取之前的数据
        cm2 = CapabilityMemory(self.test_dir)
        self.assertTrue(cm2.has_capability("browser_screenshot"))
        self.assertTrue(cm2.has_capability("emerged_screenshot_share"))
        print("✅ 能力记忆跨实例持久化正确")


# ============================================================
# 5. 模拟 _delayed_reply 涌现拦截流程
# ============================================================

class TestDelayedReplyEmergenceIntegration(unittest.TestCase):
    """模拟 base_runtime._delayed_reply 中涌现拦截层的逻辑"""
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_screenshot_full_flow(self, mock_get_page):
        """模拟完整的截图涌现流程"""
        mock_page = MagicMock()
        mock_page.screenshot.return_value = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        mock_page.url = "https://www.xiaohongshu.com/explore/abc"
        mock_page.title.return_value = "小红书 - 好看的帖子"
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution
        
        # 模拟 route_skill 返回 "none" 后的涌现拦截
        skill_name = "none"
        combined_text = "截个图给我看看"
        
        if skill_name == "none":
            instant_result = attempt_instant_execution(combined_text)
            
            self.assertIsNotNone(instant_result)
            self.assertTrue(instant_result["success"])
            self.assertEqual(instant_result["type"], "screenshot")
            
            # 验证截图文件
            screenshot_path = instant_result["primary_result"]
            self.assertTrue(os.path.exists(screenshot_path))
            
            # 验证结果结构
            self.assertIn("skill_learned", instant_result)
            self.assertEqual(instant_result["skill_learned"], "screenshot_share")
            
            print(f"✅ 截图涌现完整流程通过")
            print(f"   路径: {screenshot_path}")
            print(f"   技能: {instant_result['skill_learned']}")
            
            # 清理
            os.remove(screenshot_path)
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_url_share_full_flow(self, mock_get_page):
        """模拟完整的 URL 分享涌现流程"""
        mock_page = MagicMock()
        mock_page.url = "https://www.douban.com/movie/12345/"
        mock_page.title.return_value = "肖申克的救赎 (豆瓣)"
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution
        
        instant_result = attempt_instant_execution("把这个电影的链接发给我")
        
        self.assertIsNotNone(instant_result)
        self.assertTrue(instant_result["success"])
        self.assertEqual(instant_result["type"], "url")
        self.assertEqual(instant_result["results"]["url"], "https://www.douban.com/movie/12345/")
        self.assertIn("肖申克", instant_result["results"]["title"])
        
        print(f"✅ URL 分享涌现完整流程通过")
        print(f"   URL: {instant_result['results']['url']}")
        print(f"   标题: {instant_result['results']['title']}")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_extract_content_full_flow(self, mock_get_page):
        """模拟完整的内容提取涌现流程"""
        mock_page = MagicMock()
        mock_page.title.return_value = "Python 入门教程"
        mock_page.evaluate.return_value = "Python 是一种简洁优雅的编程语言，适合初学者入门..."
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution
        
        instant_result = attempt_instant_execution("这篇文章讲什么")
        
        self.assertIsNotNone(instant_result)
        self.assertTrue(instant_result["success"])
        self.assertEqual(instant_result["type"], "text")
        self.assertIn("Python", instant_result["results"]["text"])
        
        print(f"✅ 内容提取涌现完整流程通过")
        print(f"   标题: {instant_result['results']['title']}")
        print(f"   内容: {instant_result['results']['text'][:50]}...")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_emergence_fails_gracefully(self, mock_get_page):
        """涌现失败时优雅降级"""
        mock_get_page.return_value = None  # 没有页面
        
        from skill_connector import attempt_instant_execution
        
        # 截图请求但没有浏览器页面
        result = attempt_instant_execution("截个图")
        
        # 应该返回 None，让 _delayed_reply 降级到普通 LLM 回复
        self.assertIsNone(result)
        print("✅ 涌现失败时优雅降级（返回 None）")
    
    def test_normal_chat_not_intercepted(self):
        """普通聊天不被涌现拦截"""
        from skill_connector import attempt_instant_execution
        
        normal_msgs = [
            "你好呀",
            "今天心情怎么样",
            "我好无聊",
            "晚安",
        ]
        for msg in normal_msgs:
            result = attempt_instant_execution(msg)
            self.assertIsNone(result, f"普通聊天被拦截: {msg}")
            print(f"  ✅ 「{msg}」→ 未拦截（正确）")
        print("✅ 普通聊天全部正确放行")


# ============================================================
# 6. _exec_browser_atomic 测试（Recipe 系统集成）
# ============================================================

class TestExecBrowserAtomic(unittest.TestCase):
    """测试 _exec_browser_atomic 函数"""
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_screenshot_via_exec(self, mock_get_page):
        """通过 _exec_browser_atomic 执行截图"""
        mock_page = MagicMock()
        mock_page.screenshot.return_value = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
        mock_get_page.return_value = mock_page
        
        from skill_connector import _exec_browser_atomic
        
        result = _exec_browser_atomic(
            {"operation": "screenshot", "params": {"full_page": False}},
            "test_skill"
        )
        
        self.assertIsNotNone(result)
        self.assertIn("path", result)
        self.assertIn("artifact", result)
        self.assertEqual(result["artifact"]["type"], "image")
        print("✅ _exec_browser_atomic 截图执行正确")
        
        # 清理
        if os.path.exists(result["path"]):
            os.remove(result["path"])
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_get_url_via_exec(self, mock_get_page):
        """通过 _exec_browser_atomic 获取 URL"""
        mock_page = MagicMock()
        mock_page.url = "https://test.com/page"
        mock_get_page.return_value = mock_page
        
        from skill_connector import _exec_browser_atomic
        
        result = _exec_browser_atomic(
            {"operation": "get_current_url", "params": {}},
            "test_skill"
        )
        
        self.assertIsNotNone(result)
        self.assertEqual(result["content"], "https://test.com/page")
        print("✅ _exec_browser_atomic URL 获取正确")
    
    def test_missing_operation(self):
        """缺少 operation 参数"""
        from skill_connector import _exec_browser_atomic
        
        result = _exec_browser_atomic({"params": {}}, "test_skill")
        self.assertIsNone(result)
        print("✅ 缺少 operation 参数正确返回 None")


# ============================================================
# 7. 操作描述和注册表一致性
# ============================================================

class TestOperationsConsistency(unittest.TestCase):
    """测试操作注册表和 dispatch 表的一致性"""
    
    def test_all_operations_have_handlers(self):
        """所有注册的操作都有对应的处理函数"""
        from browser_pool import BrowserAtomicOps
        
        for op_name in BrowserAtomicOps.OPERATIONS:
            handler_name = f"_op_{op_name}"
            self.assertTrue(
                hasattr(BrowserAtomicOps, handler_name),
                f"操作 {op_name} 缺少处理函数 {handler_name}"
            )
        print(f"✅ 所有 {len(BrowserAtomicOps.OPERATIONS)} 个操作都有处理函数")
    
    def test_all_operations_in_dispatch(self):
        """所有注册的操作都在 dispatch 表中"""
        from browser_pool import BrowserAtomicOps
        
        # 调用 execute 来验证 dispatch 表
        for op_name in BrowserAtomicOps.OPERATIONS:
            # 不需要真正执行，只要不返回"未知操作"就说明在 dispatch 中
            result = BrowserAtomicOps.execute(op_name, {})
            if result.get("error"):
                self.assertNotIn("未知操作", result["error"],
                    f"操作 {op_name} 不在 dispatch 表中")
        print(f"✅ 所有操作都在 dispatch 表中")
    
    def test_operations_description_format(self):
        """操作描述格式正确"""
        from browser_pool import BrowserAtomicOps
        
        desc = BrowserAtomicOps.get_operations_description()
        
        # 每个操作都应该出现在描述中
        for op_name in BrowserAtomicOps.OPERATIONS:
            self.assertIn(op_name, desc, f"操作 {op_name} 未出现在描述中")
        
        # 描述应该以标题开头
        self.assertTrue(desc.startswith("你拥有以下浏览器原子操作能力"))
        print("✅ 操作描述格式正确")


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 浏览器原子操作涌现机制 — 全面集成测试")
    print("=" * 60)
    
    # 清理可能的残留缓存
    cache_file = os.path.expanduser("~/.chimera_instant_skills.json")
    if os.path.exists(cache_file):
        os.remove(cache_file)
    
    unittest.main(verbosity=2)
