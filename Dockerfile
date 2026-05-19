FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ca-certificates \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install torch --index-url https://download.pytorch.org/whl/cu124 \
    && python3 -m pip install -r /app/requirements.txt

COPY . /app

ENV APP_HOST=0.0.0.0 \
    APP_PORT=8080 \
    APP_DEBUG=false

EXPOSE 8080

CMD ["sh", "-c", "python3 -m uvicorn main:app --host 0.0.0.0 --port ${APP_PORT:-8080}"]

