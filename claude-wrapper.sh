#!/bin/sh
# Wrapper for Claude CLI
exec node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js "$@"
