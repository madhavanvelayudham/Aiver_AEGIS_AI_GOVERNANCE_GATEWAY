# Production Dockerfile for AEGIS AI Agent Governance Gateway
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend

# Set working directory to root /app
WORKDIR /app

# Copy dependency definition first for caching layer
COPY backend/requirements.txt /app/backend/requirements.txt

# Install dependencies without cache files
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend application files
COPY backend/ /app/backend/

# Copy policies directory
COPY policies/ /app/policies/

# Set working directory to backend for app runtime
WORKDIR /app/backend

# Expose port 8000 by default
EXPOSE 8000

# Production uvicorn startup command
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
