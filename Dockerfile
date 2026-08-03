# ── Stage 1: build the React frontend ───────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python/Flask runtime ───────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# System deps for mysqlclient-style builds (PyMySQL is pure-python, but
# Pillow/reportlab need these to compile their wheels on some platforms)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Bring in the compiled frontend from stage 1 — this is what app.py's
# /login route and /assets/<path> serve directly.
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Uploaded files / instance DB need to persist across container restarts —
# mount a volume at these paths in Dokploy if you want uploads to survive
# redeploys (see DOKPLOY_DEPLOY.md).
RUN mkdir -p static/uploads instance

EXPOSE 8000

CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:8000", "app:app"]
