FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system prora \
    && useradd --system --gid prora --home-dir /app prora

COPY pyproject.toml alembic.ini README.md ./
COPY alembic ./alembic
COPY app ./app

# El valor completo incluye LSTM y explicabilidad. Para una imagen liviana de API
# puede usarse --build-arg PRORA_EXTRAS=ml.
ARG PRORA_EXTRAS=ml,lstm,explainability
RUN pip install --upgrade pip \
    && pip install ".[${PRORA_EXTRAS}]" \
    && mkdir -p /app/artifacts/models /app/data/inbox /app/data/raw \
    && chown -R prora:prora /app

USER prora
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
