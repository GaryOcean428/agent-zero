#!/bin/sh
# Docker entrypoint script for gary-zero
# This allows us to use exec form in Dockerfile while still supporting variable expansion

set -e

# Default PORT if not set
PORT=${PORT:-8000}

# Execute the main application
exec uvicorn agent_zero.main:app --host 0.0.0.0 --port "$PORT" "$@"
