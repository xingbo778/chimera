#!/usr/bin/env python3
"""
浏览器自动化采集控制脚本
输出：note_urls.json（所有待采集的笔记URL列表）
"""
import json, urllib.parse

KEYWORDS = [
    "和男朋友的聊天记录",
    "和女朋友聊天日常", 
    "闺蜜聊天记录",
    "兄弟聊天记录搞笑",
    "情侣聊天日常",
    "和对象的沙雕聊天",
    "微信聊天截图搞笑",
    "和妈妈的聊天记录",
    "室友群聊天记录",
    "暧昧期聊天记录",
]

def make_search_url(keyword):
    encoded = urllib.parse.quote(keyword)
    return f"https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_search_result_notes"

# JS: 提取搜索页笔记链接
EXTRACT_LINKS_JS = """
(function() {
    const links = [];
    document.querySelectorAll('a[href*="/explore/"]').forEach(a => {
        const match = a.href.match(/\\/explore\\/([a-f0-9]+)/);
        if (match) {
            const url = 'https://www.xiaohongshu.com/explore/' + match[1];
            if (!links.includes(url)) links.push(url);
        }
    });
    return JSON.stringify(links);
})();
"""

# JS: 从笔记详情页提取图片URL、标题、正文、评论
EXTRACT_NOTE_JS = """
(function() {
    const result = {images: [], title: '', content: '', comments: []};
    
    // 标题
    const t = document.querySelector('#detail-title, [class*="title"]');
    if (t) result.title = t.textContent.trim().slice(0, 200);
    
    // 正文
    const d = document.querySelector('#detail-desc, [class*="desc"], .note-text');
    if (d) result.content = d.textContent.trim().slice(0, 1000);
    
    // 图片 - 获取所有可能的图片
    const imgUrls = new Set();
    document.querySelectorAll('img').forEach(img => {
        const src = img.src || '';
        if (src.startsWith('http') && !src.includes('avatar') && 
            !src.includes('emoji') && !src.includes('logo') && !src.includes('icon') &&
            (img.width > 150 || img.height > 150 || img.naturalWidth > 150)) {
            imgUrls.add(src.split('?')[0]);
        }
    });
    result.images = Array.from(imgUrls);
    
    // 评论
    const commentEls = document.querySelectorAll('.comment-inner-container .content, [class*="comment-content"], [class*="commentContent"]');
    commentEls.forEach(el => {
        const text = el.textContent.trim();
        if (text.length > 2 && text.length < 300) result.comments.push(text);
    });
    
    return JSON.stringify(result);
})();
"""

if __name__ == "__main__":
    for kw in KEYWORDS:
        print(f"搜索URL: {make_search_url(kw)}")
    print(f"\n提取链接JS长度: {len(EXTRACT_LINKS_JS)}")
    print(f"提取笔记JS长度: {len(EXTRACT_NOTE_JS)}")
