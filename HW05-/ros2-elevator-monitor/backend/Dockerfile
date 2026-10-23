# =====================================================================
# web-backend : Python FastAPI
# 職責：業務邏輯、樓層資訊/地圖路徑管理、歷史巡檢紀錄 API
# =====================================================================
FROM python:3.11-slim-bookworm

LABEL maintainer="SE-HW05" \
      description="FastAPI backend for ROS 2 elevator inspection monitor"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Taipei

WORKDIR /app

# 系統相依：libpq (psycopg) 與 curl（healthcheck）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# 先安裝依賴，變更 requirements.txt 時可利用 layer cache
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# 複製程式碼
COPY app /app/app

# 以非 root 權限執行
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]