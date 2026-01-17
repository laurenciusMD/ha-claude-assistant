# Claude Assistant - Home Assistant Addon

**Claude Code CLI Integration für Home Assistant - Keine API-Kosten!**

Nutzt deine Claude Pro inkludierten Tokens statt pay-per-use API.

## ✨ Hauptfeatures

- ✅ **Keine API-Kosten** - Nutzt Claude CLI mit deinem Pro-Account
- ✅ **Einfache OAuth-Setup** - Link klicken, anmelden, fertig!
- ✅ **Bildanalyse** von Frigate Snapshots
- ✅ **Chat Interface** über REST API
- ✅ **Home Assistant Services** für Automatisierungen
- ✅ **Direkter Zugriff** auf Frigate Media

## 🚀 Installation

### 1. Addon Repository hinzufügen

- Gehe zu **Supervisor → Add-on Store → ⋮ → Repositories**
- Füge hinzu: `https://github.com/yourusername/ha-claude-addon`

### 2. Addon installieren

- Suche "Claude Assistant" im Add-on Store
- Klicke **Install**

### 3. Konfiguration

**Wichtig:** Version 0.2.0+ benötigt **KEINEN API-Key mehr!**

```yaml
log_level: "info"              # debug, info, warning, error
enable_image_analysis: true    # Bildanalyse aktivieren
```

### 4. Erster Start - OAuth Setup

1. **Addon starten** (Start-Button klicken)
2. **Logs öffnen** (Log-Tab im Addon)
3. **Du siehst einen Link** wie: `https://claude.ai/auth/...`
4. **Link im Browser öffnen**
5. **Mit deinem Claude Pro Account anmelden**
6. **Fertig!** - Credentials werden gespeichert, bei jedem Neustart wiederverwendet

**Beispiel Log-Output:**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FIRST TIME SETUP - AUTHENTICATION REQUIRED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Claude CLI is not authenticated yet.

INSTRUCTIONS:
1. Watch the logs below for an authentication URL
2. Open that URL in your browser
3. Log in with your Claude account (needs Claude Pro)
4. After successful auth, the addon will start automatically

Starting authentication flow...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[OAuth URL wird hier angezeigt...]
```

### 5. Fertig!

- **Start on boot:** aktivieren (optional)
- Service läuft auf Port **8099**

## Verwendung

### Service: claude.chat

Chat mit Claude:

```yaml
service: claude.chat
data:
  message: "Was ist das Wetter heute?"
```

### Service: claude.analyze_snapshot

Frigate Snapshot analysieren:

```yaml
service: claude.analyze_snapshot
data:
  camera: "okam_cam1"
  question: "Siehst du Personen oder Fahrzeuge?"
```

### REST API

**Chat:**
```bash
curl -X POST http://homeassistant.local:8099/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hallo Claude!"}'
```

**Snapshot analysieren:**
```bash
curl -X POST http://homeassistant.local:8099/api/analyze_snapshot \
  -H "Content-Type: application/json" \
  -d '{"camera": "okam_cam1", "question": "Was siehst du?"}'
```

## Automatisierung Beispiel

```yaml
automation:
  - alias: "Analyse bei Personen-Erkennung"
    trigger:
      - platform: state
        entity_id: binary_sensor.okam_cam1_person_detected
        to: "on"
    action:
      - service: claude.analyze_snapshot
        data:
          camera: "okam_cam1"
          question: "Wer ist das? Beschreibe die Person."
      - service: notify.mobile_app
        data:
          message: "{{ state_attr('sensor.claude_last_analysis', 'response') }}"
```

## Troubleshooting

**Addon startet nicht:**
- Prüfe ob Anthropic API Key konfiguriert ist
- Schaue in die Logs: Supervisor → Claude Assistant → Log

**Keine Snapshots gefunden:**
- Prüfe ob Frigate läuft
- Prüfe ob `/media/frigate` gemountet ist

**Claude CLI fehlt:**
- Rebuild das Addon Image

## Entwicklung

Lokale Entwicklung:
```bash
cd /home/laurencius/ha-claude-addon
docker build -t claude-assistant:dev .
docker run -p 8099:8099 claude-assistant:dev
```

## Support

- GitHub: https://github.com/anthropics/claude-code
- Home Assistant Forum: https://community.home-assistant.io/
