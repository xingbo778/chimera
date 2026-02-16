"""
批量下载指定话题的图片
从已保存的URL列表下载，按话题分目录
"""
import json
import os
import requests
import hashlib
import sys

def download_urls(urls, topic_dir):
    os.makedirs(topic_dir, exist_ok=True)
    count = 0
    for url in urls:
        try:
            fname = hashlib.md5(url.encode()).hexdigest()[:12] + ".webp"
            fpath = os.path.join(topic_dir, fname)
            if os.path.exists(fpath):
                count += 1
                continue
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 5000:
                with open(fpath, 'wb') as f:
                    f.write(resp.content)
                count += 1
        except:
            pass
    return count

if __name__ == "__main__":
    url_file = sys.argv[1]
    topic = sys.argv[2]
    
    with open(url_file) as f:
        urls = json.load(f)
    
    topic_dir = f"wechat_screenshots/topic_{topic}"
    n = download_urls(urls, topic_dir)
    print(f"[{topic}] 下载了 {n}/{len(urls)} 张图片到 {topic_dir}")
