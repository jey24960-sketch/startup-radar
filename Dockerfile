# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY web ./web
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY requirements-v2.lock.txt ./
RUN pip install --no-cache-dir -r requirements-v2.lock.txt
RUN groupadd --gid 10001 radar && useradd --uid 10001 --gid radar --no-create-home radar
COPY radar ./radar
COPY core ./core
COPY sources.json ./
COPY --from=frontend /build/web/static ./web/static
USER radar
EXPOSE 8000
CMD ["python", "-m", "radar.deployment", "--serve"]
