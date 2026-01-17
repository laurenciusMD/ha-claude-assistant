ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install system dependencies including build tools for npm
RUN apk add --no-cache \
    python3 \
    py3-pip \
    bash \
    curl \
    jq \
    ffmpeg \
    nodejs \
    npm \
    git \
    g++ \
    make \
    python3-dev

# Install Python dependencies with --break-system-packages for PEP 668
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    pyyaml \
    pillow \
    requests

# Install Claude CLI from official npm package
# Using --unsafe-perm for Alpine compatibility
ENV NPM_CONFIG_UNSAFE_PERM=true
RUN npm install -g --unsafe-perm @anthropic-ai/claude-code@latest && \
    chmod -R 755 /usr/lib/node_modules/@anthropic-ai/claude-code && \
    ln -sf /usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude /usr/local/bin/claude

# Verify Claude CLI is accessible
RUN which claude && ls -la /usr/local/bin/claude && claude --version || echo "Claude installed (needs auth)"

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
