#!/usr/bin/with-contenv bashio

# Get configuration
export ANTHROPIC_API_KEY=$(bashio::config 'anthropic_api_key')
export LOG_LEVEL=$(bashio::config 'log_level')
export ENABLE_IMAGE_ANALYSIS=$(bashio::config 'enable_image_analysis')
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"
export HOMEASSISTANT_URL="http://supervisor/core"

bashio::log.info "Starting Claude Assistant..."
bashio::log.info "Log level: ${LOG_LEVEL}"
bashio::log.info "Image analysis: ${ENABLE_IMAGE_ANALYSIS}"

# Check if API key is set
if bashio::config.is_empty 'anthropic_api_key'; then
    bashio::log.warning "No Anthropic API key configured! Some features may not work."
fi

# Start the Python service
bashio::log.info "Starting Claude service..."
exec python3 /usr/local/bin/claude_service.py
