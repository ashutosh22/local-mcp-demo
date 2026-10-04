# Stage 1: Build stage to compile wheels and download dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build essentials for python package compilation safely
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install packages into a local user directory to make copying clean
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Final ultra-slim execution stage
FROM python:3.11-slim AS runner

WORKDIR /app

# Copy only the compiled binaries from the builder stage
COPY --from=builder /root/.local /root/.local
COPY server.py .

# Add local path to environment variables
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Open port 8000 for the FastAPI application stream
EXPOSE 8000

CMD ["python", "server.py"]
