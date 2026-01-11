# Claude Assistant - Home Assistant Addon

Claude Code CLI Integration für Home Assistant mit Bildanalyse.

## Features

- ✅ **Claude Code CLI** Integration
- ✅ **Bildanalyse** von Frigate Snapshots
- ✅ **Chat Interface** über REST API
- ✅ **Home Assistant Services** für Automatisierungen
- ✅ **Direkter Zugriff** auf Frigate Media

## Installation

1. **Addon Repository hinzufügen:**
   - Gehe zu Supervisor → Add-on Store → ⋮ → Repositories
   - Füge hinzu: `/addons/claude-assistant` (lokal)

2. **Addon installieren:**
   - Suche "Claude Assistant" im Add-on Store
   - Klicke "Install"

3. **Konfiguration:**
   ```yaml
   anthropic_api_key: "sk-ant-..."
   log_level: "info"
   enable_image_analysis: true
   ```

4. **Starten:**
   - Start on boot: aktivieren
   - Start

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
