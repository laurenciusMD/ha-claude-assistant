ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    nodejs \
    npm \
    bash \
    curl \
    jq \
    git \
    ffmpeg

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    aiohttp \
    asyncio \
    pyyaml \
    pillow \
    requests

# Copy service files
COPY run.sh /
COPY claude_service.py /usr/local/bin/
RUN chmod a+x /run.sh /usr/local/bin/claude_service.py

# Set working directory
WORKDIR /data

# Run startup script
CMD ["/run.sh"]
