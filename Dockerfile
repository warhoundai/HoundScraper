FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY requirements.lock ./
COPY src ./src
ARG HOUNDSCRAPER_EXTRAS=""
RUN pip install -r requirements.lock && pip install --no-deps . && case "$HOUNDSCRAPER_EXTRAS" in "") ;; s3|vertex|s3,vertex) pip install ".[${HOUNDSCRAPER_EXTRAS}]" ;; *) echo "Unsupported optional runtime extras" >&2; exit 1 ;; esac && useradd --uid 10001 --create-home scraper && mkdir /data && chown 10001:10001 /data
USER 10001:10001
ENV HOUNDSCRAPER_STORAGE=/data
EXPOSE 8081
CMD ["houndscraper","serve","--host","0.0.0.0"]
