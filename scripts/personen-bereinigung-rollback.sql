-- =====================================================================================
-- Quill – Rollback der Personenbereinigung (PostgreSQL)
--
-- Macht den zuletzt angewendeten Lauf aus scripts/personen-bereinigung.sql vollständig
-- rückgängig, anhand von persons_cleanup_log (in umgekehrter Reihenfolge):
--   - Namenskorrekturen zurücksetzen
--   - angelegte organizations/companies/events-Zeilen entfernen
--   - Quarantäne-Markierungen (quarantined_at, quarantine_reason, merged_into) löschen
--   - kanonische Datensätze auf den Stand vor der Verschmelzung zurücksetzen
--   - umgehängte Verweise zurückhängen, entfernte Verknüpfungszeilen wieder einfügen
--   - Quarantäne-Kopien und Protokoll des Laufs entfernen, Entscheidungen wieder als offen markieren
--
-- Eine Transaktion. Soll ein bestimmter Lauf statt des letzten zurückgenommen werden:
--   psql -v run_id='personen-bereinigung-2026-10-23' -f scripts/personen-bereinigung-rollback.sql
-- =====================================================================================

\set ON_ERROR_STOP on
\if :{?run_id}
\else
\set run_id ''
\endif

BEGIN;

SELECT set_config('rb.run_id', :'run_id', true);

DO $rb$
DECLARE
  v_run     TEXT := NULLIF(current_setting('rb.run_id', true), '');
  l         RECORD;
  v_cols    TEXT;
  v_sql     TEXT;
  v_newrow  JSONB;
  v_cnt     INT := 0;
BEGIN
  IF v_run IS NULL THEN
    SELECT run_id INTO v_run
    FROM persons_cleanup_decisions WHERE applied_at IS NOT NULL
    GROUP BY run_id ORDER BY max(applied_at) DESC LIMIT 1;
  END IF;
  IF v_run IS NULL THEN
    RAISE NOTICE 'Kein angewendeter Lauf gefunden – nichts zurückzunehmen.';
    RETURN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM persons_cleanup_log WHERE run_id = v_run) THEN
    RAISE EXCEPTION 'Für Lauf % existiert kein Protokoll in persons_cleanup_log', v_run;
  END IF;
  RAISE NOTICE 'Rollback von Lauf %', v_run;

  FOR l IN SELECT * FROM persons_cleanup_log WHERE run_id = v_run ORDER BY id DESC LOOP
    v_cnt := v_cnt + 1;

    IF l.step = 'rename' AND l.action = 'updated' THEN
      UPDATE persons
      SET canonical_name = l.old_value,
          aliases = array_remove(aliases, l.old_value)
      WHERE id = l.row_id::uuid AND canonical_name = l.new_value;

    ELSIF l.step = 'insert_entity' AND l.action = 'inserted' THEN
      IF to_regclass(l.table_name) IS NOT NULL THEN
        EXECUTE format('DELETE FROM %I WHERE id::text = $1', l.table_name) USING l.row_id;
      END IF;

    ELSIF l.step = 'mark' THEN
      UPDATE persons
      SET quarantined_at = NULL, quarantine_reason = NULL, merged_into = NULL
      WHERE id = l.row_id::uuid;

    ELSIF l.step = 'merge_canonical_before' THEN
      -- Kanonischen Datensatz komplett auf den Schnappschuss zurücksetzen (alle noch existierenden Spalten)
      SELECT string_agg(format('%1$I = r.%1$I', a.attname), ', ') INTO v_cols
      FROM pg_attribute a
      WHERE a.attrelid = 'persons'::regclass AND a.attnum > 0 AND NOT a.attisdropped
        AND a.attname <> 'id' AND l.row_data ? a.attname;
      IF v_cols IS NOT NULL THEN
        EXECUTE format('UPDATE persons p SET %s FROM jsonb_populate_record(NULL::persons, $1) r WHERE p.id = $2', v_cols)
        USING l.row_data, l.row_id::uuid;
      END IF;

    ELSIF l.step = 'rehang' AND l.action = 'updated' THEN
      IF to_regclass(l.table_name) IS NOT NULL THEN
        IF l.column_name = 'properties.person_id' THEN
          EXECUTE 'UPDATE kg_nodes SET properties = jsonb_set(properties, ''{person_id}'', to_jsonb($1::text))
                   WHERE id::text = $2 AND properties->>''person_id'' = $3'
          USING l.old_value, l.row_id, l.new_value;
        ELSE
          -- Spaltentyp beachten (uuid oder text)
          EXECUTE format('UPDATE %I SET %I = $1::%s WHERE id::text = $2 AND %I::text = $3',
                         l.table_name, l.column_name,
                         (SELECT format_type(atttypid, atttypmod) FROM pg_attribute
                          WHERE attrelid = l.table_name::regclass AND attname = l.column_name),
                         l.column_name)
          USING l.old_value, l.row_id, l.new_value;
        END IF;
      END IF;

    ELSIF l.step = 'rehang' AND l.action = 'updated_noid' THEN
      -- Tabelle ohne id-Spalte: aktuelle (umgehängte) Zeile entfernen und alte Zeile wieder einfügen
      IF to_regclass(l.table_name) IS NOT NULL THEN
        v_newrow := jsonb_set(l.row_data, ARRAY[l.column_name], to_jsonb(l.new_value));
        EXECUTE format('DELETE FROM %1$I WHERE ctid = (SELECT ctid FROM %1$I t WHERE to_jsonb(t) = $1 LIMIT 1)', l.table_name)
        USING v_newrow;
        EXECUTE format('INSERT INTO %1$I SELECT * FROM jsonb_populate_record(NULL::%1$I, $1) ON CONFLICT DO NOTHING', l.table_name)
        USING l.row_data;
      END IF;

    ELSIF l.step = 'rehang' AND l.action = 'deleted' THEN
      IF to_regclass(l.table_name) IS NOT NULL THEN
        EXECUTE format('INSERT INTO %1$I SELECT * FROM jsonb_populate_record(NULL::%1$I, $1) ON CONFLICT DO NOTHING', l.table_name)
        USING l.row_data;
      END IF;
    END IF;
  END LOOP;

  -- Quarantäne-Kopien und Protokoll dieses Laufs entfernen, Entscheidungen wieder öffnen
  DELETE FROM persons_quarantine WHERE cleanup_run_id = v_run;
  DELETE FROM persons_cleanup_log WHERE run_id = v_run;
  UPDATE persons_cleanup_decisions SET applied_at = NULL WHERE run_id = v_run;

  RAISE NOTICE 'Rollback abgeschlossen: % Protokolleinträge zurückgenommen. Sichtbare Personen: %',
    v_cnt, (SELECT count(*) FROM persons WHERE quarantined_at IS NULL);
END $rb$;

COMMIT;
