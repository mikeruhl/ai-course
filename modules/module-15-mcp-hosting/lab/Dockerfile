# Multi-stage Dockerfile for the MCP server
# Stage 1: build — installs dependencies using uv
# Stage 2: runtime — lean image without build tools

# ---------------------------------------------------------------------------
# Stage 1: Builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv — fast Python package manager used by the course
RUN pip install --no-cache-dir uv

# Copy dependency manifest first (layer cache: deps only reinstall if pyproject.toml changes)
COPY pyproject.toml .

# TODO (Task 2): Add a uv.lock file to your lab directory and copy it here:
# COPY uv.lock .

# Install runtime dependencies only (skip pytest, rich, etc.)
# --frozen: fail if lock file is out of sync (good practice for reproducible builds)
# --no-dev: exclude dev dependencies
RUN uv sync --no-dev

# ---------------------------------------------------------------------------
# Stage 2: Runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY src/ src/

# Copy knowledge base content (Task 2 Resources)
# In production, you might mount this as a volume or read from Azure Blob Storage
COPY knowledge_base/ knowledge_base/

# Activate the virtual environment by putting it first on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Document the port — Container Apps ingress config must match this
EXPOSE 8080

# Default environment variables
# These are overridden at runtime via Container Apps env vars or Key Vault references
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080
ENV KB_PATH=/app/knowledge_base

# Health check — Container Apps can use this for liveness probes
# Pings /sse (the SSE endpoint) and expects an HTTP 200
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/sse')" || exit 1

# Run the MCP server
CMD ["python", "src/server.py"]
