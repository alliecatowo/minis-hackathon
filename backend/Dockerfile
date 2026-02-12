FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends gosu libpq-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for caching
COPY pyproject.toml uv.lock* ./

# Install dependencies (all, since uv run needs the full env)
RUN uv sync --no-install-project

# Copy application code
COPY . .

# Create non-root user and give ownership of app dir
RUN useradd --create-home appuser && \
    mkdir -p /data && \
    chown -R appuser:appuser /app /data

# Default DATABASE_URL — override with NEON_DATABASE_URL for Neon
ENV DATABASE_URL="postgresql+asyncpg://localhost:5432/minis"

# Expose port (overridden by $PORT at runtime)
EXPOSE 8000

# Entrypoint: fix volume permissions (mounted as root by Fly.io) then drop to appuser
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
