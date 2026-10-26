# Multi-arch Dockerfile for DeskOS v2 (ARM64 Raspberry Pi 4 & AMD64)
# Use modern Debian Bookworm (Bullseye is archived/EOL)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install minimal curl for healthcheck (psutil & cryptography install from pre-built wheels on Bookworm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies (wheels exist for aarch64 & x86_64)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

# Ensure data directory exists
RUN mkdir -p /app/data

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8765/health || exit 1

CMD ["python3", "server.py"]


