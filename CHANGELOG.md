# Changelog

## 0.2.0 (2026-01-17)

### 🎉 MAJOR UPDATE - 100% CLI Mode (Zero API Costs!)

#### Breaking Changes
- **REMOVED:** `anthropic_api_key` config option - no longer needed!
- Now uses Claude Code CLI with OAuth authentication
- Uses your Claude Pro included tokens (no pay-per-use API costs)

#### New Features
- ✅ Automatic OAuth flow on first start - just click the link in logs!
- ✅ Claude CLI installed automatically in container via npm
- ✅ Persistent credentials stored in `/data/.claude/` (survives restarts)
- ✅ Interactive setup guide in addon logs
- ✅ 30-second timeout protection for all Claude operations
- ✅ Enhanced logging with beautiful status messages

#### Improvements
- 🚀 Simplified config - only `log_level` and `enable_image_analysis`
- 🛡️ Better error handling and timeout protection
- 📦 Cleaner Docker image (removed unnecessary dependencies)
- ⚡ Direct file path references instead of base64 encoding

#### Technical
- Complete service rewrite for CLI-only mode
- Removed all API client code
- Added asyncio timeout handling
- HOME environment set to /data for credential persistence

---

## 0.1.0 (2026-01-11)

### Features
- 🎉 Initial release
- ✅ Claude Code CLI integration
- ✅ Image analysis from Frigate snapshots
- ✅ REST API for chat and analysis
- ✅ Home Assistant services support
- ✅ Direct access to Frigate media

### API Endpoints
- `POST /api/chat` - Chat with Claude
- `POST /api/analyze_image` - Analyze any image
- `POST /api/analyze_snapshot` - Analyze Frigate snapshot
- `GET /api/health` - Health check

### Home Assistant Services
- `claude.chat` - Send message to Claude
- `claude.analyze_snapshot` - Analyze camera snapshot
