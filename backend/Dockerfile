FROM python:3.13-slim

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for caching
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home appuser && \
    mkdir -p /data && chown appuser:appuser /data
USER appuser

# Default DATABASE_URL points to the Fly.io persistent volume mount
ENV DATABASE_URL="sqlite+aiosqlite:////data/minis.db"

# Expose port (overridden by $PORT at runtime)
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
