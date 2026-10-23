# Quill – Bereinigung des Personenregisters

Stand: 2026-10-23. Dieses Verzeichnis gehört logisch zum Quill-Repo (`laurenciusMD/journalism-dashboard`);
die Skripte liegen hier, weil die Sitzung an dieses Repo gebunden war.

## Status

**Die Exporte `exports/personen-export.csv` und `exports/person_connections_counts.csv` liegen in keinem
Branch von `journalism-dashboard` und auch nicht in diesem Repo.** Ohne die Daten kann keine Entscheidungs-
liste erzeugt werden. Alles andere ist fertig und getestet:

| Datei | Zweck |
|---|---|
| `scripts/personen-klassifikation.py` | Regelwerk + Dubletten-Abgleich; erzeugt `exports/personen-entscheidungen.csv`, `exports/personen-restmenge.csv`, `exports/personen-zusammenfassung.md` und `scripts/personen-bereinigung-daten.sql` |
| `scripts/personen-bereinigung.sql` | Idempotentes Postgres-Skript (eine Transaktion): Quarantäne-Kopie, Verschmelzen, Überführen in `organizations`/`companies` und `events`, Namenskorrektur |
| `scripts/personen-bereinigung-rollback.sql` | Nimmt den letzten Lauf anhand des Protokolls vollständig zurück |
| `scripts/persons-route-quarantine.patch` | Filter `quarantined_at IS NULL` für Liste, Suche und Dubletten-Erkennung in `backend/src/routes/persons.js` |
| `scripts/test/run-test.sh` | End-to-End-Test gegen ein Mini-Schema (Lauf, Idempotenz, Rollback, erneuter Lauf) |

## Ablauf, sobald die Exporte vorliegen

```bash
# 1. Exporte ablegen
#    exports/personen-export.csv           (id, name, aliases, emails, party, source, created_at, created_by[, birth_date])
#    exports/person_connections_counts.csv (person_id, anzahl_verbindungen)

# 2. Regelbasierte Klassifikation + Dubletten
python3 -I scripts/personen-klassifikation.py
#    -> exports/personen-entscheidungen.csv, exports/personen-restmenge.csv (unklar),
#       exports/personen-zusammenfassung.md, scripts/personen-bereinigung-daten.sql

# 3. Einzelbewertung der Restmenge (unklar): Spalte entscheidung_neu (+ name_neu/kanonische_id/unterkategorie)
#    in exports/personen-restmenge.csv ausfüllen (oder von Claude bewerten lassen) und zurückspielen:
python3 -I scripts/personen-klassifikation.py --einzelbewertung exports/personen-restmenge.csv

# 4. Backup, dann anwenden (Server, Docker-Container journalism-postgres)
cat scripts/personen-bereinigung-daten.sql scripts/personen-bereinigung.sql \
  | docker exec -i journalism-postgres psql -U journalism -d journalism -v ON_ERROR_STOP=1

# 5. Oberfläche: Patch einspielen und Backend neu starten
cd /pfad/zu/journalism-dashboard && git apply scripts/persons-route-quarantine.patch

# Rollback bei Bedarf
docker exec -i journalism-postgres psql -U journalism -d journalism -v ON_ERROR_STOP=1 \
  < scripts/personen-bereinigung-rollback.sql
```

## Entscheidungsregeln (Kurzfassung)

1. **keine_person** (Unterkategorie): `email` (Regex), `fragment` (nur Zahlen/Zeichen, ≤ 2 Zeichen, Zahl + Einheit
   wie „30 Tagen“, Datum, kleingeschriebener Satzanfang, Artikel/Präposition, nur Vorname, Initial, > 6 Wörter),
   `ereignis` (Parteitag, Konvent, Wahl, Demo, Kongress, Sitzung …), `organisation` (Rechtsformen, Partei-,
   Behörden-, Medien-, Firmen-Schlüsselwörter, „&“), `sonstiges` (URLs, Sendungen/Medienformate, Service-Adressen).
   Zweiteilige Namen mit bekanntem Vornamen („Peter Bank“) bleiben Personen; Moderatorennamen („Markus Lanz“) ebenso.
2. **person_korrigieren**: Präfix „A- “, „Nachname, Vorname“, „NACHNAME Vorname“, „Nachname Vorname“ (per
   Vornamenlexikon), Titel (Dr., Prof., MdB, Rechtsanwalt …), Klammer- und Trennzeichen-Zusätze, Versalien,
   Sonderzeichen. Der alte Name wandert in `aliases`.
3. **dublette**: Schlüssel = normalisierter Name (Umlaute/ß transliteriert, Titel/Zusätze entfernt, Reihenfolge
   gedreht). Gruppiert wird bei identischem Schlüssel, gleichen Namensbestandteilen in anderer Reihenfolge,
   Alias = Name eines anderen Datensatzes, oder Vor- **und** Nachname gleich mit Zwischenname nur auf einer Seite.
   **Nicht** zusammengelegt wird bei widersprüchlicher Partei, widersprüchlichem Geburtsdatum, widersprüchlichen
   E-Mails oder zwei verschiedenen `created_by`-Benutzern (Testuser-Kopien). Kanonisch wird der Datensatz mit dem
   höchsten Score (Quelle +3, Partei +2, Geburtsdatum +2, E-Mails, Aliase, `created_by` gesetzt +1, bereits
   korrekte Schreibweise +1, 2·ln(1+Verbindungen)); für den Namen wird die Schreibweise mit Umlaut/ß bevorzugt.
4. **unklar**: mehrere Personen in einem Eintrag („X und Y“), einzelnes Wort mit Verbindungen/Attributen
   (Nachname allein?), untypische Namensbestandteile. Geht in `exports/personen-restmenge.csv`.

## Was das SQL genau tut

- legt `persons_quarantine` (Spalten wie `persons` + `cleanup_*`), `persons_cleanup_decisions` (Staging) und
  `persons_cleanup_log` (Änderungsprotokoll) an; ergänzt `persons.quarantined_at`, `quarantine_reason`, `merged_into`
- kopiert alle Nicht-Personen und Dubletten nach `persons_quarantine`
- je Dublette: Schnappschuss des kanonischen Datensatzes; alle Verweise umhängen (alle Fremdschlüssel auf `persons`
  plus `person_connections.person_id/connected_person_id`, `kg_nodes.source_id` und `kg_nodes.properties.person_id`,
  `company_persons`, `dossier_persons`, `file_persons`, `material_persons`, `person_tags` …). Zeilen, die dabei einen
  UNIQUE/PK-Konflikt oder eine Selbstverbindung erzeugen würden, werden als JSON protokolliert und entfernt
  (Rollback fügt sie wieder ein). Aliase, E-Mails, Partei, Quelle, `user_id`, Geburtsdatum werden in den
  kanonischen Datensatz übernommen (`COALESCE` bzw. Vereinigung), `merged_from` ergänzt. Die Dublette bleibt in
  `persons`, bekommt `quarantined_at` und `merged_into`.
- Nicht-Personen: `quarantined_at` setzen; `organisation` → `organizations` (falls vorhanden, sonst `companies`),
  `ereignis` → `events`, jeweils nur wenn noch kein gleichnamiger Eintrag existiert
- Namen korrigieren, nur wenn der Name seit dem Export unverändert ist; alter Name → `aliases`
- Entscheidungen als angewendet markieren. Zweiter Lauf: keine Änderung. Physisch gelöscht wird nichts.

## Warum die Oberfläche nur 8.915 Personen zeigt

`GET /api/persons` in `backend/src/routes/persons.js` (Zeile 71) filtert hart auf den angemeldeten Benutzer:

```js
const conditions = [`p.user_id = $1`];
const params = [req.session.userId];
```

Es gibt kein deleted-Flag. Von allen Pfaden, die Personen anlegen, setzt **nur** `postgresService.createPerson`
(Anlegen über die Oberfläche) die Spalte `user_id`. Alle Importe lassen sie leer:

| Pfad | Datei | `user_id` |
|---|---|---|
| Personen-Formular (`POST /api/persons`) | `backend/src/services/postgresService.js:198` | gesetzt |
| NorthData/OSINT-Import (`source` = NorthData, Sherlock …) | `backend/src/routes/osint.js:1547, 3069, 3466` | NULL |
| Personen aus Dokumenten | `backend/src/routes/filePersons.js:467` | NULL |
| Quick-Add im Dossier | `backend/src/routes/dossiers.js:1823` | NULL |
| CLI `quill.js` (Anlegen, Quick-Add, Massenimport) | `cli/quill.js:98, 756, 1120` | NULL |
| `scripts/safe-person-import.sh` | – | NULL |

Die 8.915 sichtbaren Einträge sind also die Datensätze mit `user_id` = angemeldeter Benutzer; die übrigen
rund 18.000 haben `user_id IS NULL` (Importe) oder gehören einem anderen Benutzer (`create_testuser.sql`
kopiert alle Personen des Hauptbenutzers für „Testuser“, was zusätzlich echte Dubletten mit anderem
`created_by` erzeugt). Die Suche (`/api/persons/search`) und die Dubletten-Erkennung filtern dagegen nicht
nach Benutzer, deshalb tauchen dort Einträge auf, die in der Liste fehlen.

Das Verschmelzen hilft hier doppelt: der kanonische Datensatz erbt `user_id` aus der Dublette, wenn er selbst
keinen hat. Für importierte Personen ohne Dublette bleibt es bei `user_id IS NULL`; wenn sie sichtbar werden
sollen, ist entweder ein `UPDATE persons SET user_id = <id> WHERE user_id IS NULL AND quarantined_at IS NULL`
oder die Entfernung des Benutzerfilters in der Route nötig. Das ist eine Produktentscheidung, nicht Teil
dieses Skripts.

## Test

```bash
PGHOST=... PGPORT=... PGUSER=... scripts/test/run-test.sh
```

Auf einem 47-zeiligen Beispiel (`scripts/test/personen-export.beispiel.csv`) ergab der Lauf:
11 person_ok, 4 person_korrigieren, 10 dublette, 19 keine_person (1 email, 3 organisation, 3 ereignis,
8 fragment, 4 sonstiges), 3 unklar; 29 Zeilen in Quarantäne, 3 Organisationen nach `companies`, 2 Ereignisse
nach `events`; zweiter Lauf ohne Änderung; Rollback stellt den Ausgangszustand spaltengenau wieder her.
