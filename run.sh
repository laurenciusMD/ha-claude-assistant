#!/usr/bin/with-contenv bashio

# ============================================================================
# Claude Assistant - CLI Mode (No API Costs!)
# Uses Claude Pro included tokens via CLI authentication
# ============================================================================

# Set HOME to /data so Claude CLI stores credentials there (persistent volume)
export HOME=/data

# Get configuration from Home Assistant
export LOG_LEVEL=$(bashio::config 'log_level')
export ENABLE_IMAGE_ANALYSIS=$(bashio::config 'enable_image_analysis')
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"
export HOMEASSISTANT_URL="http://supervisor/core"

bashio::log.info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bashio::log.info "  Claude Assistant - CLI Mode (No API Costs)"
bashio::log.info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bashio::log.info "Log level: ${LOG_LEVEL}"
bashio::log.info "Image analysis: ${ENABLE_IMAGE_ANALYSIS}"
bashio::log.info "Credentials location: ${HOME}/.claude/"

# ============================================================================
# Setup credentials from config (if provided)
# ============================================================================

mkdir -p "${HOME}/.claude"
CREDENTIALS_FILE="${HOME}/.claude/.credentials.json"

# Check if credentials are provided in config
if bashio::config.has_value 'claude_credentials'; then
    CREDS=$(bashio::config 'claude_credentials')
    if [ -n "$CREDS" ]; then
        bashio::log.info "✓ Using credentials from addon configuration"
        # Write credentials to file WITHOUT trailing newline (echo -n)
        echo -n "$CREDS" > "$CREDENTIALS_FILE"
        chmod 600 "$CREDENTIALS_FILE"

        # Debug: Verify what was written
        WRITTEN_SIZE=$(wc -c < "$CREDENTIALS_FILE")
        WRITTEN_FIRST=$(head -c 60 "$CREDENTIALS_FILE")
        bashio::log.info "DEBUG: Wrote ${WRITTEN_SIZE} bytes to credentials file"
        bashio::log.info "DEBUG: Content starts with: ${WRITTEN_FIRST}..."
    fi
fi

# ============================================================================
# Check Claude CLI Authentication
# ============================================================================

if [ ! -f "$CREDENTIALS_FILE" ]; then
    bashio::log.warning "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bashio::log.warning "  FIRST TIME SETUP - AUTHENTICATION REQUIRED"
    bashio::log.warning "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bashio::log.warning ""
    bashio::log.warning "Claude CLI is not authenticated yet."
    bashio::log.warning ""
    bashio::log.warning "INSTRUCTIONS:"
    bashio::log.warning "1. Watch the logs below for an authentication URL"
    bashio::log.warning "2. Open that URL in your browser"
    bashio::log.warning "3. Log in with your Claude account (needs Claude Pro)"
    bashio::log.warning "4. After successful auth, the addon will start automatically"
    bashio::log.warning ""
    bashio::log.warning "Starting authentication flow..."
    bashio::log.warning "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bashio::log.warning ""

    # Run Claude CLI to trigger OAuth flow
    # The CLI will print the authentication URL to stdout
    # After user authenticates in browser, CLI will store credentials
    # Use echo to provide a simple input to trigger the auth flow
    echo "hello" | claude --print 2>&1 || {
        bashio::log.error "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        bashio::log.error "  AUTHENTICATION FAILED"
        bashio::log.error "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        bashio::log.error "Could not complete authentication."
        bashio::log.error "Please check:"
        bashio::log.error "  - You have a Claude Pro account"
        bashio::log.error "  - The authentication URL was accessible"
        bashio::log.error "  - You completed the OAuth flow"
        bashio::log.error ""
        bashio::log.error "Restart the addon to try again."
        exit 1
    }

    # Verify credentials were created
    if [ ! -f "$CREDENTIALS_FILE" ]; then
        bashio::log.error "Authentication completed but credentials file not found!"
        bashio::log.error "Expected: $CREDENTIALS_FILE"
        exit 1
    fi

    bashio::log.info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bashio::log.info "  AUTHENTICATION SUCCESSFUL! ✓"
    bashio::log.info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bashio::log.info "Credentials saved to: $CREDENTIALS_FILE"
    bashio::log.info "Future addon restarts will use these credentials."
    bashio::log.info ""
else
    bashio::log.info "✓ Claude CLI already authenticated"
    bashio::log.info "✓ Using existing credentials from: $CREDENTIALS_FILE"

    # Debug: Check credentials file content
    if [ -f "$CREDENTIALS_FILE" ]; then
        CREDS_SIZE=$(wc -c < "$CREDENTIALS_FILE")
        CREDS_FIRST=$(head -c 50 "$CREDENTIALS_FILE")
        bashio::log.info "DEBUG: Credentials file size: ${CREDS_SIZE} bytes"
        bashio::log.info "DEBUG: First 50 chars: ${CREDS_FIRST}..."
    fi
fi

# ============================================================================
# Verify Claude CLI is working
# ============================================================================

bashio::log.info "Verifying Claude CLI installation..."

if which claude > /dev/null 2>&1; then
    CLAUDE_PATH=$(which claude)
    CLAUDE_VERSION=$(claude --version 2>&1 || echo "unknown")
    bashio::log.info "✓ Claude CLI found at: $CLAUDE_PATH"
    bashio::log.info "✓ Claude CLI version: $CLAUDE_VERSION"
else
    bashio::log.error "✗ Claude CLI not found in PATH!"
    exit 1
fi

# ============================================================================
# Start the service
# ============================================================================

bashio::log.info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bashio::log.info "  Starting Claude Assistant Service"
bashio::log.info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bashio::log.info "Mode: CLI (No API costs, uses Claude Pro tokens)"
bashio::log.info "Port: 8099"
bashio::log.info ""

exec python3 /usr/local/bin/claude_service.py
