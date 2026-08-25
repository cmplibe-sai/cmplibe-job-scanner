# Multi-stage lightweight Python 3.11 container for cMPLiBe AIScanner
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATA_DIR=/app/data \
    PORT=8000

# Set working directory
WORKDIR /app

# Install system dependencies (curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY job_pulse /app/job_pulse

# Create persistent data directory
RUN mkdir -p /app/data

# Expose server port
EXPOSE 8000

# Healthcheck to ensure server is live and responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/auth/me || exit 1

# Start the FastAPI web application and background radar schedulers
CMD ["sh", "-c", "uvicorn job_pulse.server:app --host 0.0.0.0 --port ${PORT}"]
