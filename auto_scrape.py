#!/usr/bin/env python3
"""
使用 Playwright MCP 自动化采集小红书微信聊天截图
流程：搜索关键词 → 提取笔记链接 → 逐个打开笔记 → 提取图片+评论 → 下载图片
"""
import subprocess, json, time, os, re, hashlib, urllib.parse
import requests
from pathlib import Path

SAVE_DIR = Path("/home/ubuntu/chimera/wechat_screenshots")
META_FILE = Path("/home/ubuntu/chimera/scraped_notes.json")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

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

def mcp_call(tool_name, input_json):
    """调用 Playwright MCP 工具"""
    cmd = [
        "manus-mcp-cli", "tool", "call", tool_name,
        "--server", "playwright",
        "--input", json.dumps(input_json)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout + result.stderr

def navigate(url):
    """导航到URL"""
    return mcp_call("browser_navigate", {"url": url})

def evaluate_js(expression):
    """执行JS并返回结果"""
    result = mcp_call("browser_evaluate", {"expression": expression})
    return result

def take_screenshot(path=None):
    """截图"""
    args = {}
    if path:
        args["path"] = path
    return mcp_call("browser_take_screenshot", args)

def snapshot():
    """获取页面快照"""
    return mcp_call("browser_snapshot", {})

def download_image(url, save_path):
    """下载图片"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'https://www.xiaohongshu.com/',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
    except Exception as e:
        print(f"    下载失败 {url}: {e}")
    return False

def extract_note_links():
    """从搜索结果页提取笔记链接"""
    js = """
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
    })()
    """
    result = evaluate_js(js)
    # 从结果中提取JSON
    try:
        # 找到JSON数组
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return []

def extract_note_data():
    """从笔记详情页提取图片URL和评论"""
    js = """
    (function() {
        const result = {images: [], title: '', content: '', comments: []};
        
        // 标题
        const t = document.querySelector('#detail-title');
        if (t) result.title = t.textContent.trim().slice(0, 200);
        
        // 正文
        const d = document.querySelector('#detail-desc');
        if (d) result.content = d.textContent.trim().slice(0, 1000);
        
        // 图片
        const imgUrls = new Set();
        document.querySelectorAll('img').forEach(img => {
            const src = img.src || '';
            if (src.startsWith('http') && !src.includes('avatar') && 
                !src.includes('emoji') && !src.includes('logo') && !src.includes('icon') &&
                !src.includes('loading') && !src.includes('default') &&
                (img.width > 100 || img.height > 100 || img.naturalWidth > 100)) {
                imgUrls.add(src.split('?')[0]);
            }
        });
        result.images = Array.from(imgUrls);
        
        // 评论 - 多种选择器
        const seen = new Set();
        document.querySelectorAll('.content, [class*="comment"]').forEach(el => {
            const text = el.textContent.trim();
            if (text.length > 3 && text.length < 200 && !seen.has(text) &&
                !text.includes('回复') && !text.includes('展开') && 
                !text.includes('条评论') && !text.includes('发送')) {
                seen.add(text);
                result.comments.push(text);
            }
        });
        
        return JSON.stringify(result);
    })()
    """
    result = evaluate_js(js)
    try:
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return {"images": [], "title": "", "content": "", "comments": []}

def main():
    all_notes = []
    total_images = 0
    
    # 先用主浏览器的cookie - Playwright MCP用的是独立浏览器
    # 需要先登录
    print("=== 小红书微信聊天截图采集 ===\n")
    
    # 先检查是否已登录（通过导航到首页）
    print("检查登录状态...")
    navigate("https://www.xiaohongshu.com")
    time.sleep(3)
    
    for ki, keyword in enumerate(KEYWORDS):
        print(f"\n[{ki+1}/{len(KEYWORDS)}] 搜索: {keyword}")
        
        # 搜索
        encoded = urllib.parse.quote(keyword)
        url = f"https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_search_result_notes&type=51"
        navigate(url)
        time.sleep(3)
        
        # 提取笔记链接
        note_urls = extract_note_links()
        print(f"  找到 {len(note_urls)} 个笔记")
        
        # 逐个打开笔记（每个关键词取前5个高质量笔记）
        for ni, note_url in enumerate(note_urls[:5]):
            print(f"  [{ni+1}/5] 打开: {note_url}")
            navigate(note_url)
            time.sleep(3)
            
            # 提取数据
            data = extract_note_data()
            data['url'] = note_url
            data['keyword'] = keyword
            
            print(f"    标题: {data.get('title', '无')[:50]}")
            print(f"    图片: {len(data.get('images', []))} 张")
            print(f"    评论: {len(data.get('comments', []))} 条")
            
            # 下载图片
            downloaded = []
            for ii, img_url in enumerate(data.get('images', [])):
                # 用URL的hash作为文件名
                url_hash = hashlib.md5(img_url.encode()).hexdigest()[:10]
                ext = '.webp' if 'webp' in img_url else '.jpg'
                fname = f"{keyword[:4]}_{ki}_{ni}_{ii}_{url_hash}{ext}"
                save_path = SAVE_DIR / fname
                
                if download_image(img_url, str(save_path)):
                    downloaded.append(str(save_path))
                    total_images += 1
            
            data['downloaded_images'] = downloaded
            all_notes.append(data)
            
            print(f"    下载: {len(downloaded)} 张图片")
        
        # 保存进度
        with open(META_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_notes, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 采集完成 ===")
    print(f"总笔记: {len(all_notes)}")
    print(f"总图片: {total_images}")
    print(f"元数据: {META_FILE}")

if __name__ == "__main__":
    main()
