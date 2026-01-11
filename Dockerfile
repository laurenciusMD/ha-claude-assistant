ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    bash \
    curl \
    jq \
    ffmpeg

# Install Python dependencies with --break-system-packages for PEP 668
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
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
