FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SYNOLOGY_HOT_FOLDER=/data/hot_folder \
    WORKING_DIRECTORY=/data/working_dir \
    EXPORT_DIRECTORY=/data/export_dir \
    DATABASE_URL=sqlite:////data/editorial.db \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    tesseract-ocr-cat \
    tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements_api.txt requirements_remote.txt requirements_watcher.txt /app/

RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt -r requirements_api.txt -r requirements_remote.txt -r requirements_watcher.txt

COPY . /app

RUN mkdir -p /data/hot_folder /data/working_dir /data/export_dir && \
    useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
