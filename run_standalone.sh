#!/bin/bash
# Claude Assistant - Standalone Docker Container
# Läuft OHNE Home Assistant Addon System

echo "Building Claude Assistant Docker image..."
cd /home/laurencius/ha-claude-addon

docker build -t claude-assistant:latest -f- . <<'DOCKERFILE'
FROM python:3.11-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    curl \
    jq \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI (if available)
# RUN npm install -g @anthropic-ai/claude-code

# Install Python dependencies
RUN pip install --no-cache-dir \
    aiohttp \
    pyyaml \
    pillow \
    requests

# Copy service
COPY claude_service.py /app/claude_service.py
RUN chmod +x /app/claude_service.py

WORKDIR /app

# Environment
ENV ANTHROPIC_API_KEY=""
ENV LOG_LEVEL="info"
ENV ENABLE_IMAGE_ANALYSIS="true"

CMD ["python3", "/app/claude_service.py"]
DOCKERFILE

echo "✅ Image built!"

echo ""
echo "Starting Claude Assistant container..."
docker run -d \
  --name claude-assistant \
  --restart=unless-stopped \
  -p 8099:8099 \
  -v /media/frigate:/media/frigate:ro \
  -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  -e LOG_LEVEL="info" \
  -e ENABLE_IMAGE_ANALYSIS="true" \
  claude-assistant:latest

echo "✅ Container started!"
echo ""
echo "Health check:"
sleep 5
curl http://localhost:8099/api/health

echo ""
echo ""
echo "📝 Usage:"
echo "  Test: curl http://192.168.8.183:8099/api/health"
echo "  Logs: docker logs -f claude-assistant"
echo "  Stop: docker stop claude-assistant"
