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
COPY docker-entrypoint.sh ./docker-entrypoint.sh

# El valor completo incluye LSTM y explicabilidad. Para una imagen liviana de API
# puede usarse --build-arg PRORA_EXTRAS=ml.
ARG PRORA_EXTRAS=ml,lstm,explainability
RUN pip install --upgrade pip \
    && pip install ".[${PRORA_EXTRAS}]" \
    && chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/artifacts/models /app/data/inbox /app/data/raw \
    && chown -R prora:prora /app

USER prora
EXPOSE 8000

# Render y otros PaaS inyectan PORT; en local/compose se usa 8000.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/ready', timeout=3)" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
