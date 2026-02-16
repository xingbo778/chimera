"""
测试浏览器原子操作涌现机制的端到端流程。
不需要真实浏览器，通过 mock 验证逻辑正确性。
"""

import os
import sys
import json
import time
import unittest
from unittest.mock import patch, MagicMock

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(__file__))


class TestBrowserAtomicOps(unittest.TestCase):
    """测试 BrowserAtomicOps 类的基本功能"""
    
    def test_operations_description(self):
        """测试操作描述生成"""
        from browser_pool import BrowserAtomicOps
        desc = BrowserAtomicOps.get_operations_description()
        self.assertIn("screenshot", desc)
        self.assertIn("get_current_url", desc)
        self.assertIn("navigate", desc)
        print(f"✅ 操作描述生成正确 ({len(desc)} chars)")
    
    def test_operations_registry(self):
        """测试操作注册表完整性"""
        from browser_pool import BrowserAtomicOps
        expected_ops = ["screenshot", "get_current_url", "get_page_title", 
                       "extract_text", "navigate", "click", "type_text", "scroll"]
        for op in expected_ops:
            self.assertIn(op, BrowserAtomicOps.OPERATIONS)
        print(f"✅ 所有 {len(expected_ops)} 个原子操作已注册")
    
    def test_execute_unknown_operation(self):
        """测试执行未知操作"""
        from browser_pool import BrowserAtomicOps
        result = BrowserAtomicOps.execute("nonexistent_op")
        self.assertFalse(result["success"])
        self.assertIn("未知操作", result["error"])
        print("✅ 未知操作正确返回错误")


class TestIntentClassification(unittest.TestCase):
    """测试意图分类"""
    
    def test_screenshot_intent(self):
        """测试截图意图识别"""
        from skill_connector import _classify_user_intent
        
        test_cases = [
            "截个图给我看看",
            "你在看什么呀，截图看看",
            "发个截图",
            "看下屏幕",
        ]
        for msg in test_cases:
            intent = _classify_user_intent(msg)
            self.assertIsNotNone(intent, f"未识别截图意图: {msg}")
            self.assertEqual(intent["type"], "screenshot_share", f"意图类型错误: {msg} -> {intent}")
            print(f"  ✅ 「{msg}」→ screenshot_share")
        print("✅ 截图意图识别全部通过")
    
    def test_url_intent(self):
        """测试 URL 分享意图识别"""
        from skill_connector import _classify_user_intent
        
        test_cases = [
            "把链接发给我",
            "分享一下网址",
            "发个链接",
        ]
        for msg in test_cases:
            intent = _classify_user_intent(msg)
            self.assertIsNotNone(intent, f"未识别URL意图: {msg}")
            self.assertEqual(intent["type"], "share_url", f"意图类型错误: {msg} -> {intent}")
            print(f"  ✅ 「{msg}」→ share_url")
        print("✅ URL 分享意图识别全部通过")
    
    def test_extract_content_intent(self):
        """测试内容提取意图识别"""
        from skill_connector import _classify_user_intent
        
        test_cases = [
            "这页写了什么",
            "这个页面说了啥",
            "帮我看看这个",
        ]
        for msg in test_cases:
            intent = _classify_user_intent(msg)
            self.assertIsNotNone(intent, f"未识别内容提取意图: {msg}")
            self.assertEqual(intent["type"], "extract_content", f"意图类型错误: {msg} -> {intent}")
            print(f"  ✅ 「{msg}」→ extract_content")
        print("✅ 内容提取意图识别全部通过")
    
    def test_normal_chat_no_intent(self):
        """测试普通聊天不触发涌现"""
        from skill_connector import _classify_user_intent
        
        test_cases = [
            "你好呀",
            "今天天气怎么样",
            "我好无聊",
        ]
        for msg in test_cases:
            intent = _classify_user_intent(msg)
            is_none = intent is None or intent.get("type") == "none"
            self.assertTrue(is_none, f"普通聊天误触发涌现: {msg} -> {intent}")
            print(f"  ✅ 「{msg}」→ None (正确)")
        print("✅ 普通聊天不触发涌现")


class TestOperationPlanning(unittest.TestCase):
    """测试操作序列规划"""
    
    def test_screenshot_plan(self):
        """测试截图操作序列"""
        from skill_connector import _plan_instant_operations
        
        intent = {"type": "screenshot_share", "key": "screenshot_share", "params": {}}
        ops = _plan_instant_operations(intent)
        self.assertIsNotNone(ops)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["operation"], "screenshot")
        print("✅ 截图操作序列正确: [screenshot]")
    
    def test_share_url_plan(self):
        """测试 URL 分享操作序列"""
        from skill_connector import _plan_instant_operations
        
        intent = {"type": "share_url", "key": "share_url", "params": {}}
        ops = _plan_instant_operations(intent)
        self.assertIsNotNone(ops)
        self.assertEqual(len(ops), 2)
        op_names = [op["operation"] for op in ops]
        self.assertIn("get_current_url", op_names)
        self.assertIn("get_page_title", op_names)
        print("✅ URL 分享操作序列正确: [get_current_url, get_page_title]")
    
    def test_extract_content_plan(self):
        """测试内容提取操作序列"""
        from skill_connector import _plan_instant_operations
        
        intent = {"type": "extract_content", "key": "extract_content", "params": {}}
        ops = _plan_instant_operations(intent)
        self.assertIsNotNone(ops)
        op_names = [op["operation"] for op in ops]
        self.assertIn("extract_text", op_names)
        print("✅ 内容提取操作序列正确")


class TestCapabilityMemory(unittest.TestCase):
    """测试能力记忆系统"""
    
    def setUp(self):
        """创建临时目录"""
        self.test_dir = "/tmp/test_capability_memory"
        os.makedirs(self.test_dir, exist_ok=True)
    
    def test_record_browser_atomic(self):
        """测试记录浏览器原子操作"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        cm.record_browser_atomic("screenshot", "用户请求截图")
        
        self.assertTrue(cm.has_capability("browser_screenshot"))
        self.assertEqual(cm.capabilities["browser_screenshot"]["use_count"], 1)
        print("✅ 浏览器原子操作记录正确")
    
    def test_record_emerged_skill(self):
        """测试记录涌现技能"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        operations = [
            {"operation": "screenshot", "params": {}},
        ]
        cm.record_emerged_skill("screenshot_share", operations, "截个图看看")
        
        self.assertTrue(cm.has_capability("emerged_screenshot_share"))
        print("✅ 涌现技能记录正确")
    
    def test_emerged_skills_summary(self):
        """测试涌现技能摘要"""
        from capability_memory import CapabilityMemory
        
        cm = CapabilityMemory(self.test_dir)
        cm.record_emerged_skill("screenshot_share", [{"operation": "screenshot"}], "截图")
        cm.record_emerged_skill("share_url", [{"operation": "get_current_url"}], "分享链接")
        
        summary = cm.get_emerged_skills_summary()
        self.assertIn("screenshot_share", summary)
        self.assertIn("share_url", summary)
        print(f"✅ 涌现技能摘要正确:\n{summary}")
    
    def tearDown(self):
        """清理临时文件"""
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)


class TestInstantSkillCache(unittest.TestCase):
    """测试即时技能缓存持久化"""
    
    def test_cache_save_and_load(self):
        """测试缓存保存和加载"""
        from skill_connector import _instant_skill_cache, _save_instant_cache, _load_instant_cache, _INSTANT_CACHE_FILE
        
        # 写入测试数据
        _instant_skill_cache["test_skill"] = {
            "operations": [{"operation": "screenshot", "params": {}}],
            "last_success": time.time(),
            "description": "测试技能",
        }
        _save_instant_cache()
        
        # 验证文件存在
        self.assertTrue(os.path.exists(_INSTANT_CACHE_FILE))
        
        # 清空内存缓存
        _instant_skill_cache.clear()
        self.assertEqual(len(_instant_skill_cache), 0)
        
        # 重新加载
        _load_instant_cache()
        self.assertIn("test_skill", _instant_skill_cache)
        print("✅ 即时技能缓存持久化正确")
        
        # 清理
        if os.path.exists(_INSTANT_CACHE_FILE):
            os.remove(_INSTANT_CACHE_FILE)


class TestEndToEndEmergence(unittest.TestCase):
    """端到端测试：模拟完整的涌现流程"""
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_screenshot_emergence_flow(self, mock_get_page):
        """测试截图涌现的完整流程（mock 浏览器）"""
        # Mock 页面对象
        mock_page = MagicMock()
        mock_page.screenshot.return_value = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100  # fake PNG
        mock_page.url = "https://example.com/test"
        mock_page.title.return_value = "Test Page"
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution
        from capability_memory import CapabilityMemory
        
        # 创建临时能力记忆
        test_dir = "/tmp/test_e2e_emergence"
        os.makedirs(test_dir, exist_ok=True)
        cap_mem = CapabilityMemory(test_dir)
        
        # 执行涌现
        result = attempt_instant_execution("截个图给我看看", capability_memory=cap_mem)
        
        # 验证结果
        self.assertIsNotNone(result, "涌现应该成功")
        self.assertTrue(result["success"])
        self.assertEqual(result["type"], "screenshot")
        self.assertIn("skill_learned", result)
        
        # 验证截图文件存在
        screenshot_path = result["primary_result"]
        self.assertTrue(os.path.exists(screenshot_path))
        
        print(f"✅ 截图涌现端到端测试通过！")
        print(f"   截图路径: {screenshot_path}")
        print(f"   学会技能: {result['skill_learned']}")
        
        # 清理
        import shutil
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_share_url_emergence_flow(self, mock_get_page):
        """测试 URL 分享涌现的完整流程"""
        mock_page = MagicMock()
        mock_page.url = "https://www.xiaohongshu.com/explore/abc123"
        mock_page.title.return_value = "小红书 - 超好吃的蛋糕推荐"
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution
        
        result = attempt_instant_execution("把这个链接发给我")
        
        self.assertIsNotNone(result, "URL 分享涌现应该成功")
        self.assertTrue(result["success"])
        self.assertEqual(result["type"], "url")
        self.assertIn("url", result["results"])
        self.assertEqual(result["results"]["url"], "https://www.xiaohongshu.com/explore/abc123")
        
        print(f"✅ URL 分享涌现端到端测试通过！")
        print(f"   URL: {result['results']['url']}")
        print(f"   标题: {result['results']['title']}")
    
    @patch('browser_pool.BrowserAtomicOps._get_active_page')
    def test_second_call_uses_cache(self, mock_get_page):
        """测试第二次调用使用缓存"""
        mock_page = MagicMock()
        mock_page.screenshot.return_value = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        mock_page.url = "https://example.com"
        mock_page.title.return_value = "Example"
        mock_get_page.return_value = mock_page
        
        from skill_connector import attempt_instant_execution, _instant_skill_cache
        
        # 第一次调用
        result1 = attempt_instant_execution("截图看看")
        self.assertIsNotNone(result1)
        
        # 验证缓存已写入
        self.assertIn("screenshot_share", _instant_skill_cache)
        
        # 第二次调用（应该走缓存）
        result2 = attempt_instant_execution("再截个图")
        self.assertIsNotNone(result2)
        self.assertTrue(result2["success"])
        
        print("✅ 缓存复用测试通过！第二次调用使用了已学会的技能")
        
        # 清理截图文件
        for r in [result1, result2]:
            if r and r.get("primary_result") and os.path.exists(r["primary_result"]):
                os.remove(r["primary_result"])


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 浏览器原子操作涌现机制 — 端到端测试")
    print("=" * 60)
    
    unittest.main(verbosity=2)
