FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY api/requirements-online.txt api/requirements-online.txt
RUN pip install --no-cache-dir -r api/requirements-online.txt

COPY api api
COPY Frontend Frontend
COPY powerbi/AI_SafeSight_CHV.pdf powerbi/AI_SafeSight_CHV.pdf
RUN rm -f api/seed_users.example.json api/seed_users.json api/*.db

ENV PYTHONUNBUFFERED=1 \
    SAFESIGHT_DB=/app/data/safesight.db \
    SAFESIGHT_SNAPSHOTS=/app/data/snapshots \
    SAFESIGHT_FONT_DIR=/usr/share/fonts/truetype/dejavu \
    SAFESIGHT_FONT=DejaVuSans.ttf \
    SAFESIGHT_FONT_BOLD=DejaVuSans-Bold.ttf \
    SAFESIGHT_SERVE_FRONTEND=1 \
    SAFESIGHT_DETECT=0 \
    SAFESIGHT_TRANSLATE=0

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
