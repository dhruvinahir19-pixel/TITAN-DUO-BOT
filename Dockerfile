# TITAN DUO v4.0 APEX - PRODUCTION DOCKER CONTAINER
FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr (ensures instant logs on Render)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

# Install minimal OS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy codebase
COPY . .

# Expose web server port
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ping || exit 1

# Launch main daemon (runs FastAPI web server in background + autonomous trading loop)
CMD ["python", "main.py"]
