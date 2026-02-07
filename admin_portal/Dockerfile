# Multi-stage Dockerfile for Admin Portal
# Builds React frontend and packages with FastAPI backend
#
# Build context should be the project root directory:
#   docker build -f admin_portal/Dockerfile -t admin-portal .

# Stage 1: Build Frontend
FROM node:20-slim AS frontend-builder

WORKDIR /build

# Copy frontend package files
COPY admin_portal/frontend/package.json ./

# Install dependencies (use npm install since we may not have lock file)
RUN npm install

# Copy frontend source
COPY admin_portal/frontend/ ./

# Build frontend for production with /admin/ base path
ENV VITE_BASE_PATH=/admin/
RUN npm run build

# Stage 2: Python Backend
FROM python:3.11-slim

WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files and install dependencies
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY admin_portal/backend ./admin_portal/backend
RUN pip install --no-cache-dir .

# Copy built frontend from frontend-builder
COPY --from=frontend-builder /build/dist /app/admin_portal/frontend/dist

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose port
EXPOSE 8005

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1

# Run admin portal
CMD ["python", "-m", "uvicorn", "admin_portal.backend.main:app", "--host", "0.0.0.0", "--port", "8005"]
