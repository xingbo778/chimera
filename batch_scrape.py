#!/usr/bin/env python3
"""
批量采集小红书笔记图片和评论
方案：利用已登录浏览器的cookie，通过小红书web API获取笔记详情
"""
import json, os, re, time, hashlib, urllib.parse
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

SAVE_DIR = Path("/home/ubuntu/chimera/wechat_screenshots")
META_FILE = Path("/home/ubuntu/chimera/scraped_notes_all.json")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

# 从keyword1_notes.json读取已提取的笔记列表
def load_note_urls():
    """加载所有已提取的笔记URL"""
    notes = []
    f = Path("/home/ubuntu/chimera/keyword1_notes.json")
    if f.exists():
        with open(f) as fh:
            notes.extend(json.load(fh))
    return notes

def download_image(url, save_path):
    """下载图片"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.xiaohongshu.com/',
        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
    except Exception as e:
        pass
    return False

def main():
    notes = load_note_urls()
    print(f"共 {len(notes)} 个笔记待下载封面图")
    
    total = 0
    for i, note in enumerate(notes):
        cover_url = note.get('cover', '')
        if not cover_url:
            continue
        
        note_id = note.get('id', f'unknown_{i}')
        title = note.get('title', '')[:20]
        
        # 生成文件名
        ext = '.webp'
        fname = f"note_{note_id}_cover{ext}"
        save_path = SAVE_DIR / fname
        
        if save_path.exists():
            print(f"  [{i+1}] 已存在: {fname}")
            total += 1
            continue
        
        if download_image(cover_url, str(save_path)):
            total += 1
            print(f"  [{i+1}] 下载成功: {title} -> {fname}")
        else:
            print(f"  [{i+1}] 下载失败: {title}")
    
    print(f"\n共下载 {total} 张封面图")
    print("注意：这只是封面图，每个笔记可能有多张图片")
    print("需要逐个打开笔记获取所有图片")

if __name__ == "__main__":
    main()
