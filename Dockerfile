# ─── Stage 1: Build frontend ─────────────────────────────────────────────────
FROM node:20-alpine AS frontend

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts

COPY web/ ./
RUN npm run build


# ─── Stage 2: Python runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: non-root user
RUN groupadd -r momboard && useradd -r -g momboard -d /app -s /usr/sbin/nologin momboard

WORKDIR /app

# System dependencies (sqlite3 CLI for backup verification, curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (pinned in pyproject.toml)
COPY pyproject.toml ./
RUN pip install --no-cache-dir . && pip cache purge

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Copy built frontend from stage 1
COPY --from=frontend /build/web/dist ./web/dist/

# Copy entrypoint
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Create /data volume mount point with correct permissions
RUN mkdir -p /data/backups && chown -R momboard:momboard /data

# Switch to non-root user
USER momboard

# The application reads DATABASE_URL which defaults to sqlite+aiosqlite:///data/momboard.db
ENV DATABASE_URL="sqlite+aiosqlite:///data/momboard.db" \
    ENV="production" \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

ENTRYPOINT ["./entrypoint.sh"]
