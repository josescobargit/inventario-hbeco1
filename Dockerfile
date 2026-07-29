FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY database /app/database

RUN useradd --create-home --uid 10001 inventario \
    && chown -R inventario:inventario /app
USER inventario

CMD ["sh", "-c", "PYTHONPATH=backend alembic -c database/alembic.ini upgrade head && PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
