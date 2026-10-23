#!/usr/bin/env bash
# End-to-End-Test der Personenbereinigung gegen eine leere PostgreSQL-Datenbank mit Mini-Schema.
#
# Prüft: Klassifikation -> Staging-SQL -> Bereinigung -> Idempotenz (zweiter Lauf ändert nichts)
#        -> Rollback stellt den Ausgangszustand exakt wieder her -> erneuter Lauf funktioniert.
#
# Aufruf (aus dem Repo-Wurzelverzeichnis), Verbindungsparameter über PG*-Umgebungsvariablen:
#   PGHOST=/run/pgtest PGPORT=5499 PGUSER=postgres scripts/test/run-test.sh
# Die Datenbank "quill_cleanup_test" wird angelegt und am Ende wieder gelöscht.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DB=${TEST_DB:-quill_cleanup_test}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PSQL="psql -q -v ON_ERROR_STOP=1"

mkdir -p "$WORK/exports" "$WORK/scripts"
cp "$ROOT/scripts/test/personen-export.beispiel.csv" "$WORK/exports/personen-export.csv"
cp "$ROOT/scripts/test/person_connections_counts.beispiel.csv" "$WORK/exports/person_connections_counts.csv"

echo "1) Klassifikation"
(cd "$WORK" && python3 -I "$ROOT/scripts/personen-klassifikation.py" --run-id test-lauf | tail -3)

echo "2) Testdatenbank $DB"
psql -q -c "DROP DATABASE IF EXISTS $DB" -c "CREATE DATABASE $DB" postgres
$PSQL -d "$DB" -f "$ROOT/scripts/test/schema-mini.sql"
python3 -I "$ROOT/scripts/test/make-seed.py" "$WORK/exports/personen-export.csv" > "$WORK/seed.sql"
$PSQL -d "$DB" -f "$WORK/seed.sql"
psql -tA -d "$DB" -f "$ROOT/scripts/test/compare.sql" > "$WORK/h_before.txt"

echo "3) Bereinigung"
$PSQL -d "$DB" -f "$WORK/scripts/personen-bereinigung-daten.sql"
psql -v ON_ERROR_STOP=1 -d "$DB" -f "$ROOT/scripts/personen-bereinigung.sql" 2>&1 | grep NOTICE | grep -v "already exists" | sed 's/.*NOTICE:  /   /'
psql -tA -d "$DB" -f "$ROOT/scripts/test/compare.sql" > "$WORK/h_applied.txt"
SICHTBAR=$(psql -tA -d "$DB" -c "SELECT count(*) FROM persons WHERE quarantined_at IS NULL")
QUAR=$(psql -tA -d "$DB" -c "SELECT count(*) FROM persons_quarantine")
[ "$SICHTBAR" = "18" ] && [ "$QUAR" = "29" ] || { echo "FEHLER: erwartet 18 sichtbar / 29 Quarantäne, bekommen $SICHTBAR / $QUAR"; exit 1; }

echo "4) Idempotenz (zweiter Lauf)"
$PSQL -d "$DB" -f "$WORK/scripts/personen-bereinigung-daten.sql"
$PSQL -d "$DB" -f "$ROOT/scripts/personen-bereinigung.sql" >/dev/null 2>&1
psql -tA -d "$DB" -f "$ROOT/scripts/test/compare.sql" > "$WORK/h_applied2.txt"
diff -q "$WORK/h_applied.txt" "$WORK/h_applied2.txt" >/dev/null || { echo "FEHLER: zweiter Lauf hat Daten verändert"; exit 1; }

echo "5) Rollback"
$PSQL -d "$DB" -f "$ROOT/scripts/personen-bereinigung-rollback.sql" >/dev/null 2>&1
psql -tA -d "$DB" -f "$ROOT/scripts/test/compare.sql" > "$WORK/h_after.txt"
diff -q "$WORK/h_before.txt" "$WORK/h_after.txt" >/dev/null || { echo "FEHLER: Zustand nach Rollback weicht vom Ausgangszustand ab"; diff "$WORK/h_before.txt" "$WORK/h_after.txt"; exit 1; }

echo "6) Erneuter Lauf nach Rollback"
$PSQL -d "$DB" -f "$WORK/scripts/personen-bereinigung-daten.sql"
$PSQL -d "$DB" -f "$ROOT/scripts/personen-bereinigung.sql" >/dev/null 2>&1
SICHTBAR=$(psql -tA -d "$DB" -c "SELECT count(*) FROM persons WHERE quarantined_at IS NULL")
[ "$SICHTBAR" = "18" ] || { echo "FEHLER: erneuter Lauf liefert $SICHTBAR sichtbare Personen"; exit 1; }

psql -q -c "DROP DATABASE $DB" postgres
echo "OK – alle Prüfungen bestanden."
