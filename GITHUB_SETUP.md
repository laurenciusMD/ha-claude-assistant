# GitHub Repository Setup

## Schritt 1: Repository auf GitHub erstellen

1. Gehe zu: https://github.com/new
2. **Repository name:** `ha-claude-assistant`
3. **Description:** `Claude Code CLI Integration für Home Assistant mit Bildanalyse`
4. **Public** auswählen
5. ❌ **NICHT** "Initialize this repository with a README" anklicken
6. Klick **"Create repository"**

## Schritt 2: Repository verbinden und pushen

```bash
cd /home/laurencius/ha-claude-addon

# Ersetze USERNAME mit deinem GitHub Username
git remote add origin git@github.com:USERNAME/ha-claude-assistant.git

# Pushen
git branch -M main
git push -u origin main
```

## Schritt 3: In Home Assistant hinzufügen

1. **Home Assistant öffnen:** http://192.168.8.183:8123
2. **Einstellungen → Add-ons → Add-on Store**
3. **⋮ (oben rechts) → Repositories**
4. **Repository hinzufügen:**
   ```
   https://github.com/USERNAME/ha-claude-assistant
   ```
5. **Klick "Add"**
6. **Refresh** - dann siehst du "Claude Assistant" im Store!

---

## Alternative: Ich mache es automatisch

**Gib mir deinen GitHub Username, dann pushe ich es direkt!**
