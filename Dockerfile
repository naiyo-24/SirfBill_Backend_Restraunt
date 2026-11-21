# ========================================================
# SirfBill Restaurant Platform - Production Dockerfile
# Python 3.11 Slim with WeasyPrint & PostgreSQL client
# ========================================================
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered streaming logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8033

WORKDIR /app

# Install system dependencies:
# - postgresql-client: for pg_isready database readiness checks
# - curl: for container healthcheck
# - libcairo2, libpango, libgdk-pixbuf, fonts: for WeasyPrint PDF receipt & invoice printing
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    build-essential \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure entrypoint script is executable
RUN chmod +x ./entrypoint.sh

# Expose backend service port 8033
EXPOSE 8033

# Container Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8033/ || exit 1

# Start service via entrypoint (runs auto-migration then starts Uvicorn)
ENTRYPOINT ["./entrypoint.sh"]
CMD []
