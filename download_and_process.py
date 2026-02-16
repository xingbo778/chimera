#!/usr/bin/env python3
"""
下载图片和处理采集到的数据
从console_outputs中读取JS执行结果，解析并下载图片
"""
import json, re, requests, hashlib, os, sys, glob
from pathlib import Path

SAVE_DIR = Path("/home/ubuntu/chimera/wechat_screenshots")
ALL_NOTES_FILE = Path("/home/ubuntu/chimera/all_scraped_notes.json")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

def parse_js_result(filepath):
    """解析JS执行结果文件"""
    with open(filepath) as f:
        raw = f.read()
    
    json_str = raw.strip().strip('"').replace('\\"', '"').replace('\\\\', '\\')
    try:
        return json.loads(json_str)
    except:
        # 截断了，尝试提取图片URL
        img_pattern = r'https://sns-webpic[^"\\,\s]+'
        images = list(set(re.findall(img_pattern, json_str)))
        return {"images": images, "title": "", "comments": []}

def download_images(images, note_id, keyword_prefix=""):
    """下载图片列表"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'https://www.xiaohongshu.com/',
    }
    
    downloaded = []
    for i, url in enumerate(images):
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        prefix = keyword_prefix[:4] if keyword_prefix else "note"
        fname = f"{prefix}_{note_id}_{i}_{url_hash}.webp"
        save_path = SAVE_DIR / fname
        
        if save_path.exists():
            downloaded.append(str(save_path))
            continue
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 3000:
                with open(save_path, 'wb') as f:
                    f.write(resp.content)
                downloaded.append(str(save_path))
        except:
            pass
    
    return downloaded

def load_all_notes():
    """加载已有的所有笔记数据"""
    if ALL_NOTES_FILE.exists():
        with open(ALL_NOTES_FILE) as f:
            return json.load(f)
    return []

def save_all_notes(notes):
    """保存所有笔记数据"""
    with open(ALL_NOTES_FILE, 'w') as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

def process_note_result(result_file, keyword="", note_id=""):
    """处理单个笔记的JS执行结果"""
    data = parse_js_result(result_file)
    
    images = data.get('images', [])
    title = data.get('title', '')
    comments = data.get('comments', [])
    content = data.get('content', '')
    
    # 下载图片
    downloaded = download_images(images, note_id, keyword)
    
    note = {
        'id': note_id,
        'keyword': keyword,
        'title': title,
        'content': content,
        'images': images,
        'downloaded': downloaded,
        'comments': comments,
    }
    
    # 追加到总数据
    all_notes = load_all_notes()
    # 检查是否已存在
    if not any(n['id'] == note_id for n in all_notes):
        all_notes.append(note)
        save_all_notes(all_notes)
    
    return note

def stats():
    """统计采集数据"""
    all_notes = load_all_notes()
    total_images = sum(len(n.get('downloaded', [])) for n in all_notes)
    total_comments = sum(len(n.get('comments', [])) for n in all_notes)
    
    print(f"=== 采集统计 ===")
    print(f"笔记数: {len(all_notes)}")
    print(f"图片数: {total_images}")
    print(f"评论数: {total_comments}")
    
    # 按关键词统计
    by_kw = {}
    for n in all_notes:
        kw = n.get('keyword', '未知')
        if kw not in by_kw:
            by_kw[kw] = {'notes': 0, 'images': 0, 'comments': 0}
        by_kw[kw]['notes'] += 1
        by_kw[kw]['images'] += len(n.get('downloaded', []))
        by_kw[kw]['comments'] += len(n.get('comments', []))
    
    print(f"\n按关键词:")
    for kw, stats in by_kw.items():
        print(f"  {kw}: {stats['notes']}笔记, {stats['images']}图片, {stats['comments']}评论")
    
    # 磁盘上的图片
    img_files = list(SAVE_DIR.glob('*.webp')) + list(SAVE_DIR.glob('*.jpg'))
    print(f"\n磁盘图片: {len(img_files)} 个文件")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == 'stats':
        stats()
    else:
        print("用法:")
        print("  python3 download_and_process.py stats  # 查看统计")
        print("  在Python中导入 process_note_result() 处理单个笔记")
