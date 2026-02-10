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

# Expose port (overridden by $PORT at runtime)
EXPOSE 8000

CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
