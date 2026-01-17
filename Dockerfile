ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    bash \
    curl \
    jq \
    ffmpeg \
    nodejs \
    npm

# Install Python dependencies with --break-system-packages for PEP 668
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    pyyaml \
    pillow \
    requests

# Install Claude CLI globally via npm
# This installs the official Claude Code CLI without API costs
RUN npm install -g @anthropic-ai/claude-code && \
    ln -sf /usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude /usr/local/bin/claude

# Copy service files
COPY run.sh /
COPY claude_service.py /usr/local/bin/
RUN chmod a+x /run.sh /usr/local/bin/claude_service.py

# Create directory for Claude credentials (will be mounted as volume)
RUN mkdir -p /data/.claude

# Set working directory
WORKDIR /data

# Run startup script
CMD ["/run.sh"]
