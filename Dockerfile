# Build arguments for metadata (passed by Docker Hub hooks)
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=dev
ARG DOCKER_TAG=latest

# ========== Builder Stage ==========
FROM python:3.11-slim AS builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PYTHONPATH=/app

# Install system dependencies and uv in one layer to reduce image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# Set working directory
WORKDIR /app

# Copy dependency files first to leverage Docker cache
COPY pyproject.toml README.md ./
COPY src/agent_zero ./src/agent_zero

# Install Python dependencies using pip in development mode
RUN pip install --no-cache-dir -e ".[dev]"

# ========== Production Stage ==========
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    PATH="/home/appuser/.local/bin:${PATH}"

# Set default application environment variables (non-sensitive)
ENV WEB_UI_PORT=50001 \
    USE_CLOUDFLARE=false \
    TOKENIZERS_PARALLELISM=true \
    PYDEVD_DISABLE_FILE_VALIDATION=1 \
    OLLAMA_BASE_URL="http://127.0.0.1:11434" \
    LM_STUDIO_BASE_URL="http://127.0.0.1:1234/v1" \
    OPEN_ROUTER_BASE_URL="https://openrouter.ai/api/v1" \
    SAMBANOVA_BASE_URL="https://fast-api.snova.ai/v1"

# Install system dependencies and create non-root user in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos '' appuser

# Set working directory and ensure it's writable by appuser
WORKDIR /app
RUN chown -R appuser:appuser /app

# Copy from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /app/src/agent_zero ./src/agent_zero
COPY --from=builder /app/agent_zero.egg-link /usr/local/lib/python3.11/site-packages/

# Copy the rest of the application as appuser
USER appuser
COPY --chown=appuser:appuser . .

# Ensure entrypoint script is executable
USER root
RUN chmod +x /app/docker-entrypoint.sh
USER appuser

# Expose the port the app runs on
EXPOSE ${PORT}

# Health check with proper variable expansion
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f "http://localhost:${PORT}/health" || exit 1

# Use exec form with entrypoint script for proper signal handling
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "agent_zero.main:app", "--host", "0.0.0.0", "--port", "$PORT"]
