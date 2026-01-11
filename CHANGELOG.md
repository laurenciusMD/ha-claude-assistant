# Changelog

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
