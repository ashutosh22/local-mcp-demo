#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

# --- CONFIGURATION VARIABLES ---
CONTAINER_NAME="weather-mcp-service"
IMAGE_NAME="mcp-weather-v2"
HOST_PORT="8081"
CONTAINER_PORT="8081"

echo "=================================================="
echo "🚀 Initiating MCP Server Production Deployment Workflow"
echo "=================================================="

# 1. Stop and move existing container if it exists
if [ "$(docker ps -aq -f name=^${CONTAINER_NAME}$)" ]; then
    echo "🛑 Found running/stale container [${CONTAINER_NAME}]. Stopping and removing..."
    docker rm -f ${CONTAINER_NAME} >/dev/null
    echo "✅ Old container cleared."
else
    echo "ℹ️ No existing container found named [${CONTAINER_NAME}]. Skipping teardown."
fi

# 2. Build the optimized Docker image
echo "📦 Building production Docker image [${IMAGE_NAME}]..."
docker build -t ${IMAGE_NAME} .
echo "✅ Docker image built successfully."

# 3. Clean up dangling images to save disk space
if [ "$(docker images -f "dangling=true" -q)" ]; then
re    echo "🧹 Cleaning up intermediate build layers..."
    docker rmi $(docker images -f "dangling=true" -q) >/dev/null || true
fi

# 4. Launch the new container
echo "🌐 Starting new background container container on port ${HOST_PORT}..."
docker run -d \
    -p ${HOST_PORT}:${CONTAINER_PORT} \
    --name ${CONTAINER_NAME} \
    --restart unless-stopped \
    ${IMAGE_NAME}

echo "=================================================="
echo "🎉 DEPLOYMENT SUCCESSFUL!"
echo "=================================================="
echo "Your server is streaming at: http://localhost:${HOST_PORT}/mcp"
echo "To tail the logs, run: docker logs -f ${CONTAINER_NAME}"
echo "=================================================="
