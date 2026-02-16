FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl && \
    rm -rf /var/lib/apt/lists/*

# 先安装Python依赖（利用Docker缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载 sentence-transformers 模型（避免运行时下载）
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# 复制项目文件
COPY . .

# 排除不需要的大文件
RUN rm -rf wechat_screenshots/ __pycache__/ .git/

# 启动脚本
RUN chmod +x railway_start.sh
CMD ["bash", "railway_start.sh"]
