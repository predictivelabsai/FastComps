FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=5063
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5063
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=4 CMD curl --fail --silent http://127.0.0.1:5063/healthz >/dev/null || exit 1
CMD ["sh","-c","uvicorn main:app --host 0.0.0.0 --port ${PORT:-5063}"]
