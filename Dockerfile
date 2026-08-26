# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS web
WORKDIR /src
COPY web-ui/package.json web-ui/package-lock.json ./web-ui/
RUN npm ci --prefix web-ui
COPY web-ui/ ./web-ui/
RUN npm run build --prefix web-ui

FROM python:3.12-slim-bookworm AS app
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY web/ ./web/
COPY --from=web /src/web/dist ./web/dist

RUN uv sync --frozen --extra server --no-dev --no-editable

ENV KYN_HOME=/data
ENV PORT=8765
EXPOSE 8765
VOLUME /data

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health')"

CMD ["sh", "-c", "uv run kyn serve --host 0.0.0.0 --port ${PORT:-8765}"]
