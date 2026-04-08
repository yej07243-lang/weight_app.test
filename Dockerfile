FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5000
ENV WEIGHT_DB_PATH=/data/weight_records.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

COPY weight_app.py /app/weight_app.py
COPY wsgi.py /app/wsgi.py

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '5000') + '/healthz').read()"

CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT} wsgi:app"]
