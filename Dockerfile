FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY trendbot ./trendbot
RUN pip install --no-cache-dir .

# Persistent volume for the halt sentinel and candle cache. A logical HALT must
# survive `restart: always`, so the sentinel lives here (see PRD EE-6).
RUN mkdir -p /data
VOLUME ["/data"]

# Safe by default: dry-run + testnet. Override explicitly to go live.
ENV DRY_RUN=true \
    BYBIT_TESTNET=true \
    TRENDBOT_HALT_FILE=/data/trendbot.halt \
    TRENDBOT_DATA_DIR=/data/candles

ENTRYPOINT ["trendbot"]
CMD ["run"]
