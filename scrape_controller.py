#!/usr/bin/env python3
"""
采集控制器 - 生成浏览器操作指令序列
输出：一系列需要在浏览器中执行的URL和JS命令
"""
import json, urllib.parse
from pathlib import Path

KEYWORDS = [
    "和男朋友的聊天记录",
    "和女朋友聊天日常",
    "闺蜜聊天记录搞笑",
    "情侣日常聊天",
    "和对象的沙雕聊天",
    "暧昧期聊天记录",
    "和妈妈的聊天记录搞笑",
    "室友群聊天记录",
    "兄弟聊天记录搞笑",
    "微信聊天截图搞笑",
]

# JS: 提取搜索页笔记链接
EXTRACT_LINKS_JS = """
(function() {
    const links = [];
    document.querySelectorAll('a[href*="/explore/"]').forEach(a => {
        const match = a.href.match(/\\/explore\\/([a-f0-9]+)/);
        if (match) {
            const url = a.href;
            if (!links.find(l => l.url === url)) {
                // 获取标题
                const parent = a.closest('[class*="note"]') || a.parentElement;
                const titleEl = parent ? parent.querySelector('[class*="title"]') : null;
                links.push({
                    id: match[1],
                    url: url,
                    title: titleEl ? titleEl.textContent.trim() : a.textContent.trim().slice(0, 50)
                });
            }
        }
    });
    return JSON.stringify(links);
})();
"""

# JS: 从笔记弹窗提取图片和评论
EXTRACT_NOTE_JS = """
(function() {
    const result = {images: [], title: '', content: '', comments: []};
    const modal = document.querySelector('[class*="note-detail"], [class*="noteDetail"]') || document;
    
    const titleEl = modal.querySelector('#detail-title, [class*="title"]');
    if (titleEl) result.title = titleEl.textContent.trim().slice(0, 200);
    
    const descEl = modal.querySelector('#detail-desc, [class*="desc"]');
    if (descEl) result.content = descEl.textContent.trim().slice(0, 1000);
    
    const imgUrls = new Set();
    modal.querySelectorAll('img').forEach(img => {
        const src = img.src || '';
        if (src.startsWith('http') && 
            (src.includes('sns-webpic') || src.includes('xhscdn')) &&
            !src.includes('avatar') && !src.includes('emoji') && 
            !src.includes('logo') && !src.includes('icon')) {
            imgUrls.add(src);
        }
    });
    result.images = Array.from(imgUrls);
    
    const seen = new Set();
    modal.querySelectorAll('.content, [class*="comment-content"]').forEach(el => {
        const text = el.textContent.trim();
        if (text.length > 2 && text.length < 300 && !seen.has(text) &&
            !text.includes('发送') && !text.includes('取消') && !text.includes('说点什么')) {
            seen.add(text);
            result.comments.push(text);
        }
    });
    
    return JSON.stringify(result);
})();
"""

def generate_search_urls():
    """生成所有搜索URL"""
    urls = []
    for kw in KEYWORDS:
        encoded = urllib.parse.quote(kw)
        url = f"https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_search_result_notes&type=51"
        urls.append({"keyword": kw, "url": url})
    return urls

if __name__ == "__main__":
    urls = generate_search_urls()
    print(f"共 {len(urls)} 个搜索关键词:")
    for u in urls:
        print(f"  {u['keyword']}: {u['url']}")
    
    # 保存
    with open('/home/ubuntu/chimera/search_urls.json', 'w') as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)
    
    print(f"\nJS脚本:")
    print(f"  提取链接: {len(EXTRACT_LINKS_JS)} chars")
    print(f"  提取笔记: {len(EXTRACT_NOTE_JS)} chars")
