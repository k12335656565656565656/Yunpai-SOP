FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOP_DB_PATH=/data/sop_knowledge.sqlite3 \
    SOP_LIBREOFFICE_PATH=/usr/bin/libreoffice

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir .

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/ready', timeout=4)" || exit 1

CMD ["uvicorn", "cad_ai.sop_knowledge.web:create_server_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--workers", "1", "--timeout-keep-alive", "180"]
