#!/usr/bin/env python3
"""
小红书微信聊天截图批量采集脚本
- 多个搜索关键词覆盖不同话题
- 自动提取笔记中所有图片URL并下载
- 提取评论区文字
- 保存元数据（标题、关键词、评论等）
"""
import json, os, time, re, requests, hashlib
from pathlib import Path

# ---- 配置 ----
SAVE_DIR = Path("/home/ubuntu/chimera/wechat_screenshots")
META_FILE = Path("/home/ubuntu/chimera/scraped_notes.json")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# 搜索关键词列表 - 覆盖不同类型的聊天截图
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

def get_note_urls_from_search(keyword):
    """通过浏览器console获取搜索结果中的笔记URL"""
    # 这个函数需要在浏览器中执行，这里只返回JS代码
    js_code = """
    const links = [];
    document.querySelectorAll('a[href*="/explore/"]').forEach(a => {
        const href = a.href;
        if (href.includes('/explore/') && !links.includes(href)) {
            // 只保留 /explore/xxx 格式的链接（笔记详情）
            const match = href.match(/\\/explore\\/([a-f0-9]+)/);
            if (match) {
                const cleanUrl = 'https://www.xiaohongshu.com/explore/' + match[1];
                if (!links.includes(cleanUrl)) links.push(cleanUrl);
            }
        }
    });
    JSON.stringify(links);
    """
    return js_code

def get_note_images_and_comments():
    """从笔记详情页提取所有图片URL和评论"""
    js_code = """
    (function() {
        const result = {images: [], title: '', content: '', comments: []};
        
        // 提取标题
        const titleEl = document.querySelector('#detail-title');
        if (titleEl) result.title = titleEl.textContent.trim();
        
        // 提取正文
        const descEl = document.querySelector('#detail-desc, .note-text');
        if (descEl) result.content = descEl.textContent.trim();
        
        // 提取所有图片 - 多种选择器
        const imgSelectors = [
            '.swiper-slide img',
            '.note-slider img', 
            '.carousel img',
            '[class*="slide"] img',
            '.note-image img',
            '.note-content img',
        ];
        const imgUrls = new Set();
        
        // 方法1: 从 swiper/carousel 中提取
        imgSelectors.forEach(sel => {
            document.querySelectorAll(sel).forEach(img => {
                let src = img.src || img.dataset.src || img.getAttribute('data-src');
                if (src && src.startsWith('http') && !src.includes('avatar') && !src.includes('emoji')) {
                    // 获取高清版本
                    src = src.split('?')[0];
                    imgUrls.add(src);
                }
            });
        });
        
        // 方法2: 从背景图中提取
        document.querySelectorAll('[style*="background-image"]').forEach(el => {
            const style = el.style.backgroundImage;
            const match = style.match(/url\\(["']?([^"')]+)["']?\\)/);
            if (match && match[1].startsWith('http') && !match[1].includes('avatar')) {
                imgUrls.add(match[1].split('?')[0]);
            }
        });
        
        // 方法3: 直接找所有大图
        document.querySelectorAll('img').forEach(img => {
            const src = img.src || '';
            const w = img.naturalWidth || img.width || 0;
            const h = img.naturalHeight || img.height || 0;
            if (src.startsWith('http') && (w > 200 || h > 200) && 
                !src.includes('avatar') && !src.includes('emoji') && 
                !src.includes('logo') && !src.includes('icon')) {
                imgUrls.add(src.split('?')[0]);
            }
        });
        
        result.images = Array.from(imgUrls);
        
        // 提取评论
        document.querySelectorAll('[class*="comment"] [class*="content"], .comment-item .content').forEach(el => {
            const text = el.textContent.trim();
            if (text && text.length > 2 && text.length < 200) {
                result.comments.push(text);
            }
        });
        
        return JSON.stringify(result);
    })();
    """
    return js_code

def download_image(url, save_path):
    """下载图片"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'https://www.xiaohongshu.com/',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 5000:  # 过滤太小的图
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
    except Exception as e:
        print(f"下载失败: {e}")
    return False

if __name__ == "__main__":
    print("此脚本需要配合浏览器使用，请运行 scrape_xhs_browser.py")
