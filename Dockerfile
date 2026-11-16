FROM python:3.12-slim

# Optional build-time proxy (e.g. for building behind a corporate/sandbox
# proxy); empty and unused on a normal build.
ARG HTTP_PROXY
ARG HTTPS_PROXY

WORKDIR /app

# libatomic1: pedalboard's native extension dlopen()s it at import time.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY skeleton/ skeleton/
COPY PROTOCOL.md .

RUN useradd --create-home --shell /bin/false skeleton \
    && mkdir -p /data \
    && chown -R skeleton:skeleton /app /data
USER skeleton

ENV GREETINGS_DIR=/data/greetings \
    PHOTOS_DIR=/data/photos \
    MODE_FILE=/data/mode.txt \
    AMBIENT_DIR=/data/ambient \
    SETTINGS_FILE=/data/settings.json

EXPOSE 8765 8080

CMD ["python", "-m", "skeleton.server"]
