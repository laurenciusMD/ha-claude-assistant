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
# The package has a 'bin: claude' field that automatically creates /usr/local/bin/claude
# Force reinstall to get latest version (2.1.19+)
ENV NPM_CONFIG_UNSAFE_PERM=true
RUN npm cache clean --force && \
    npm install -g --force @anthropic-ai/claude-code@latest

# Verify Claude CLI installation
RUN which claude && ls -la $(which claude)

# Cache buster to force rebuild of following layers
ARG CACHEBUST=1

# Copy service files (v0.3.7 - debug logging added)
COPY run.sh /
COPY claude_service.py /usr/local/bin/
COPY www /usr/local/bin/www
RUN chmod a+x /run.sh /usr/local/bin/claude_service.py && \
    echo "Build time: $(date)" && \
    head -5 /run.sh

# Create directory for Claude credentials (will be mounted as volume)
RUN mkdir -p /data/.claude

# Set working directory
WORKDIR /data

# Run startup script
CMD ["/run.sh"]
