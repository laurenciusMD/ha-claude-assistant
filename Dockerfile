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
    ca-certificates

# Install Python dependencies with --break-system-packages for PEP 668
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    pyyaml \
    pillow \
    requests

# Install Claude CLI
COPY install-claude.sh /tmp/
RUN chmod +x /tmp/install-claude.sh && \
    /tmp/install-claude.sh && \
    rm /tmp/install-claude.sh

# Verify installation
RUN which claude && (claude --version 2>&1 || echo "Claude CLI ready (needs auth)")

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
