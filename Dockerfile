FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.6 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
COPY --from=build /opt/venv /opt/venv
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin translator \
 && mkdir /data && chown translator:translator /data
ENV TRANSLATOR_DB=/data/translator.db
USER translator
VOLUME /data
EXPOSE 18490
CMD ["python", "-m", "translator"]
