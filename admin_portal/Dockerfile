# Build frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY admin_portal/frontend/package*.json ./
RUN npm install
COPY admin_portal/frontend/ ./
RUN npm run build

# Build backend
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python project
COPY pyproject.toml ./
COPY app/ ./app/
COPY admin_portal/backend/ ./admin_portal/backend/

# Install Python dependencies
RUN pip install --no-cache-dir .

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist ./admin_portal/frontend/dist

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1

CMD ["uvicorn", "admin_portal.backend.main:app", "--host", "0.0.0.0", "--port", "8005"]
