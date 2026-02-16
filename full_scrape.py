#!/usr/bin/env python3
"""
完整的小红书笔记采集脚本
使用 requests + 小红书 web 页面解析
直接请求笔记页面HTML，从中提取图片URL和评论
"""
import json, re, time, hashlib, urllib.parse, os
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

SAVE_DIR = Path("/home/ubuntu/chimera/wechat_screenshots")
META_FILE = Path("/home/ubuntu/chimera/scraped_notes_full.json")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# 所有搜索关键词
KEYWORDS = [
    "和男朋友的聊天记录",
    "和女朋友聊天日常",
    "闺蜜聊天记录搞笑",
    "情侣日常聊天",
    "和对象的沙雕聊天",
    "暧昧期聊天记录",
    "和妈妈的聊天记录",
    "室友群聊天记录",
    "兄弟聊天记录",
    "微信聊天截图搞笑",
]

# 从keyword1已提取的19个笔记
KNOWN_NOTES = json.loads(open("/home/ubuntu/chimera/keyword1_notes.json").read()) if os.path.exists("/home/ubuntu/chimera/keyword1_notes.json") else []

def download_image(url, save_path):
    """下载图片"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'https://www.xiaohongshu.com/',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 3000:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
    except:
        pass
    return False

def extract_images_from_html(html):
    """从笔记页面HTML中提取所有图片URL"""
    images = set()
    
    # 方法1: 从 __INITIAL_STATE__ 中提取
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>', html, re.DOTALL)
    if match:
        try:
            # 这个JSON可能很大，尝试从中提取图片URL
            state_str = match.group(1)
            # 提取所有图片URL
            img_pattern = r'https://[^"\'\\]+(?:\.jpg|\.jpeg|\.png|\.webp|\.gif)'
            for m in re.finditer(img_pattern, state_str):
                url = m.group()
                if 'sns-webpic' in url or 'ci.xiaohongshu' in url:
                    images.add(url.split('?')[0])
        except:
            pass
    
    # 方法2: 从 img 标签中提取
    img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    for m in re.finditer(img_pattern, html):
        url = m.group(1)
        if ('sns-webpic' in url or 'ci.xiaohongshu' in url) and 'avatar' not in url:
            images.add(url.split('?')[0])
    
    # 方法3: 从 data-src 中提取
    datasrc_pattern = r'data-src=["\']([^"\']+)["\']'
    for m in re.finditer(datasrc_pattern, html):
        url = m.group(1)
        if ('sns-webpic' in url or 'ci.xiaohongshu' in url) and 'avatar' not in url:
            images.add(url.split('?')[0])
    
    return list(images)

def extract_comments_from_html(html):
    """从HTML中提取评论"""
    comments = []
    # 从 __INITIAL_STATE__ 中提取评论
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>', html, re.DOTALL)
    if match:
        state_str = match.group(1)
        # 找评论内容
        comment_pattern = r'"content"\s*:\s*"([^"]{3,200})"'
        seen = set()
        for m in re.finditer(comment_pattern, state_str):
            text = m.group(1)
            # 过滤掉非评论内容
            if text not in seen and len(text) > 3 and not text.startswith('http'):
                seen.add(text)
                comments.append(text)
    return comments[:50]  # 最多50条

def fetch_note_page(note_url, session=None):
    """请求笔记页面"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://www.xiaohongshu.com/',
    }
    s = session or requests.Session()
    try:
        resp = s.get(note_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"  请求失败: {e}")
    return None

def main():
    print("=== 小红书微信聊天截图采集 ===\n")
    
    all_results = []
    total_images = 0
    
    # 先处理已知的笔记
    print(f"已有 {len(KNOWN_NOTES)} 个笔记URL")
    
    session = requests.Session()
    
    for i, note in enumerate(KNOWN_NOTES):
        note_url = note['url']
        note_id = note['id']
        title = note.get('title', '')
        
        print(f"\n[{i+1}/{len(KNOWN_NOTES)}] {title[:40]} ({note_url})")
        
        # 请求页面
        html = fetch_note_page(note_url, session)
        if not html:
            print("  页面请求失败，跳过")
            continue
        
        # 提取图片
        images = extract_images_from_html(html)
        comments = extract_comments_from_html(html)
        
        print(f"  图片: {len(images)} 张, 评论: {len(comments)} 条")
        
        # 下载图片
        downloaded = []
        for ii, img_url in enumerate(images):
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
            ext = '.webp' if 'webp' in img_url else '.jpg'
            fname = f"{note_id}_{ii}_{url_hash}{ext}"
            save_path = SAVE_DIR / fname
            
            if save_path.exists():
                downloaded.append(str(save_path))
                continue
            
            if download_image(img_url, str(save_path)):
                downloaded.append(str(save_path))
                total_images += 1
        
        print(f"  下载: {len(downloaded)} 张")
        
        result = {
            'id': note_id,
            'url': note_url,
            'title': title,
            'keyword': note.get('keyword', '和男朋友的聊天记录'),
            'images': images,
            'downloaded': downloaded,
            'comments': comments,
        }
        all_results.append(result)
        
        # 保存进度
        with open(META_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        
        time.sleep(1)  # 避免请求过快
    
    print(f"\n=== 采集完成 ===")
    print(f"笔记: {len(all_results)}")
    print(f"新下载图片: {total_images}")
    print(f"元数据: {META_FILE}")

if __name__ == "__main__":
    main()
