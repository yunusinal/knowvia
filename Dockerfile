# Knowvia: API (FastAPI) + arayüz (Streamlit) tek konteynerde. ARM64 (Oracle Ampere) ve x86_64 için derlenir.
# Ayrıntı: docs/adr/12-public-demo-deployment.md, kurulum: docs/deploy-oracle.md
FROM ghcr.io/astral-sh/uv:0.11.14 AS uv

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

# Bağımlılıklar ayrı katmanda: kod değişince yeniden kurulmaz. Sürümler uv.lock'tan; test/ölçüm grupları alınmaz.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-default-groups

COPY app ./app
COPY frontend ./frontend
COPY scripts ./scripts
COPY data/demo_docs ./data/demo_docs
COPY .streamlit ./.streamlit
COPY docker/entrypoint.sh /usr/local/bin/knowvia-entrypoint

# Çalışma verisi (SQLite, Qdrant, ~2.3 GB model önbelleği) kalıcı birimde; konteyner silinse de korunur.
ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_URL=sqlite:////data/app.db \
    QDRANT_PATH=/data/qdrant \
    MODEL_CACHE_DIR=/data/models \
    KNOWVIA_API_URL=http://127.0.0.1:8000

RUN useradd --create-home --uid 10001 knowvia \
    && mkdir /data && chown knowvia:knowvia /data \
    && chmod 0755 /usr/local/bin/knowvia-entrypoint
USER knowvia
VOLUME /data

# Yalnız arayüz dışarı açılır; API konteyner içinde 127.0.0.1'de kalır.
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

ENTRYPOINT ["knowvia-entrypoint"]
