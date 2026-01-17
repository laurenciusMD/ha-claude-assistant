#!/bin/bash
# Claude Assistant Addon - Update Script
# Verwendung: Wenn ich Änderungen am Addon mache, führe ich das aus

cd /home/laurencius/ha-claude-addon

echo "=== Updating Claude Assistant Addon ==="
echo ""

# Zeige Änderungen
echo "Changed files:"
git status --short

echo ""
echo "Adding changes..."
git add -A

echo ""
read -p "Commit message: " COMMIT_MSG

if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="Update addon configuration and features"
fi

# Commit
git commit -m "$COMMIT_MSG

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# Push to GitHub
echo ""
echo "Pushing to GitHub..."
git push origin main

echo ""
echo "✅ Update pushed to GitHub!"
echo ""
echo "Home Assistant wird das Update automatisch sehen."
echo "Benutzer können dann auf 'Update' klicken im Add-on."
