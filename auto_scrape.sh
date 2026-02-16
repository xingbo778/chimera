#!/bin/bash
# 自动化采集小红书微信聊天截图
# 使用 Playwright MCP 浏览器自动化

set -e
cd /home/ubuntu/chimera

SAVE_DIR="/home/ubuntu/chimera/wechat_screenshots"
META_DIR="/home/ubuntu/chimera/scraped_meta"
mkdir -p "$SAVE_DIR" "$META_DIR"

# 搜索关键词
KEYWORDS=(
    "和男朋友的聊天记录"
    "和女朋友聊天日常"
    "闺蜜聊天记录搞笑"
    "情侣日常聊天"
    "和对象的沙雕聊天"
    "暧昧期聊天记录"
    "和妈妈的聊天记录"
    "室友群聊天记录"
    "兄弟聊天记录"
    "微信聊天截图搞笑"
)

echo "=== 开始采集 ==="

for keyword in "${KEYWORDS[@]}"; do
    echo ""
    echo ">>> 搜索关键词: $keyword"
    
    # URL编码
    encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$keyword'))")
    url="https://www.xiaohongshu.com/search_result?keyword=${encoded}&source=web_search_result_notes&type=51"
    
    # 导航到搜索页
    echo "  导航到: $url"
    manus-mcp-cli tool call browser_navigate --server playwright --input "{\"url\": \"$url\"}" 2>&1 | tail -3
    
    sleep 3
    
    # 提取笔记链接
    echo "  提取笔记链接..."
    RESULT=$(manus-mcp-cli tool call browser_evaluate --server playwright --input '{
        "expression": "(function() { const links = []; document.querySelectorAll(\"a[href*=\\\"/explore/\\\"]\").forEach(a => { const match = a.href.match(/\\/explore\\/([a-f0-9]+)/); if (match) { const url = \"https://www.xiaohongshu.com/explore/\" + match[1]; if (!links.includes(url)) links.push(url); } }); return JSON.stringify(links); })()"
    }' --server playwright 2>&1)
    
    # 保存结果
    echo "$RESULT" > "$META_DIR/search_${encoded}.txt"
    echo "  完成"
done

echo ""
echo "=== 搜索阶段完成 ==="
