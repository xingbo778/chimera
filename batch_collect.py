#!/usr/bin/env python3
"""
批量采集脚本 - 从已保存的console输出中提取所有图片URL并下载
同时也从搜索结果页面的__INITIAL_STATE__中批量获取
"""
import json, re, requests, hashlib, os, glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SAVE_DIR = Path("/home/ubuntu/chimera/wechat_screenshots")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Referer': 'https://www.xiaohongshu.com/',
}

def download_one(url, prefix="img"):
    """下载单张图片"""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    fname = f"{prefix}_{url_hash}.webp"
    save_path = SAVE_DIR / fname
    
    if save_path.exists():
        return str(save_path), True
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 3000:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return str(save_path), True
    except:
        pass
    return None, False

def collect_from_console_outputs():
    """从所有console输出文件中提取图片URL"""
    all_urls = set()
    for f in glob.glob('/home/ubuntu/console_outputs/exec_result_*.txt'):
        with open(f) as fh:
            content = fh.read()
        # 提取所有小红书图片URL
        pattern = r'https?://sns-webpic[^"\\,\s\]\}]+'
        urls = re.findall(pattern, content)
        for url in urls:
            if 'comment/' not in url and 'avatar' not in url and 'emoji' not in url:
                all_urls.add(url)
    return list(all_urls)

def batch_download(urls, prefix="img", max_workers=10):
    """并发下载"""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_one, url, prefix): url for url in urls}
        for future in as_completed(futures):
            path, success = future.result()
            if success:
                results.append(path)
    return results

if __name__ == "__main__":
    # 从console输出中提取
    urls = collect_from_console_outputs()
    print(f"从console输出中提取到 {len(urls)} 个图片URL")
    
    # 从已保存的URL文件中提取
    url_file = Path("/home/ubuntu/chimera/all_image_urls.json")
    if url_file.exists():
        with open(url_file) as f:
            extra_urls = json.load(f)
        urls = list(set(urls + extra_urls))
        print(f"合并后共 {len(urls)} 个URL")
    
    # 批量下载
    downloaded = batch_download(urls, "batch")
    print(f"下载完成: {len(downloaded)} 张")
    
    # 统计总数
    all_files = list(SAVE_DIR.glob('*.webp')) + list(SAVE_DIR.glob('*.jpg'))
    print(f"磁盘总图片: {len(all_files)}")
