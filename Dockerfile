FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RADAR_HOST=0.0.0.0 \
    RADAR_DATA_DIR=/var/data \
    RADAR_ENV=production \
    RADAR_ALLOW_REGISTRATION=0 \
    RADAR_SERPRO_AUTO_MONITOR=0

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py README.md ./
COPY integrations ./integrations
COPY static ./static

RUN mkdir -p /var/data/sync-cache

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT','10000') + '/healthz', timeout=4)"

CMD ["python", "app.py"]
