FROM node:26-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------
# Install Python + FFmpeg + Git
# ---------------------------------------------------------

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-dev \
        ffmpeg \
        ca-certificates \
        git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------
# Install Python dependencies
# ---------------------------------------------------------

COPY requirements.txt .

RUN python3 -m pip install --break-system-packages --upgrade pip && \
    python3 -m pip install --break-system-packages -r requirements.txt

# ---------------------------------------------------------
# Install BgUtils PO-token HTTP provider 2.0.0
# ---------------------------------------------------------

RUN git clone \
        --depth 1 \
        --branch 2.0.0 \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
        /opt/bgutil-ytdlp-pot-provider && \
    cd /opt/bgutil-ytdlp-pot-provider/server && \
    npm ci --no-audit --no-fund && \
    npx tsc

# ---------------------------------------------------------
# Copy bot
# ---------------------------------------------------------

COPY . .

# ---------------------------------------------------------
# Start:
#   1. BgUtils PO-token server
#   2. Telegram music bot
# ---------------------------------------------------------

CMD ["sh", "-c", "cd /opt/bgutil-ytdlp-pot-provider/server && node build/main.js --host 127.0.0.1 --port 4416 & exec python3 bot.py"]
