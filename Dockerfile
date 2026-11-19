FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . && rm -rf /app/src /app/build
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin translator \
 && mkdir /data && chown translator:translator /data
ENV TRANSLATOR_DB=/data/translator.db
USER translator
VOLUME /data
EXPOSE 18490
CMD ["python", "-m", "translator"]
