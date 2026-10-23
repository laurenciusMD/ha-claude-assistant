-- =====================================================================================
-- Quill – Bereinigung des Personenregisters (PostgreSQL)
--
-- Voraussetzung: scripts/personen-bereinigung-daten.sql wurde eingespielt (Staging-Tabelle
-- persons_cleanup_decisions, erzeugt von scripts/personen-klassifikation.py).
--
-- Ablauf (eine Transaktion, idempotent, nichts wird physisch gelöscht):
--   0. Infrastruktur: persons_quarantine (Kopie-Tabelle), persons_cleanup_log (Änderungsprotokoll
--      für das Rollback), Spalten persons.quarantined_at / quarantine_reason / merged_into
--   1. Alle Nicht-Personen und Dubletten nach persons_quarantine kopieren
--   2. Dubletten verschmelzen: Verweise (person_connections, kg_nodes, dossier_persons,
--      file_persons, material_persons, company_persons, person_tags, alle FK-Tabellen) auf die
--      kanonische ID umhängen, Attribute (Aliase, E-Mails, Partei, Quelle, user_id) in den
--      kanonischen Datensatz übernehmen, Dublette als quarantined markieren
--   3. Nicht-Personen als quarantined markieren; Organisationen -> organizations (falls vorhanden,
--      sonst companies), Ereignisse -> events
--   4. Namen korrigieren (person_korrigieren)
--   5. Entscheidungen als angewendet markieren
--
-- Die Originalzeilen bleiben in persons (mit quarantined_at gesetzt). Die Oberfläche muss
-- quarantined_at IS NULL filtern (siehe scripts/persons-route-quarantine.patch).
--
-- Aufruf:  psql -v ON_ERROR_STOP=1 -f scripts/personen-bereinigung-daten.sql
--          psql -v ON_ERROR_STOP=1 -f scripts/personen-bereinigung.sql
--   oder:  cat scripts/personen-bereinigung-daten.sql scripts/personen-bereinigung.sql \
--            | docker exec -i journalism-postgres psql -U journalism -d journalism -v ON_ERROR_STOP=1
-- Rollback: scripts/personen-bereinigung-rollback.sql
-- =====================================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ------------------------------------------------------------------------------------
-- 0. Infrastruktur
-- ------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS persons_cleanup_decisions (
  run_id         TEXT NOT NULL,
  id             UUID NOT NULL,
  name_alt       TEXT,
  entscheidung   TEXT NOT NULL CHECK (entscheidung IN ('person_ok','person_korrigieren','dublette','keine_person','unklar')),
  name_neu       TEXT,
  kanonische_id  UUID,
  unterkategorie TEXT,
  konfidenz      NUMERIC(3,2),
  begruendung    TEXT,
  applied_at     TIMESTAMPTZ,
  PRIMARY KEY (run_id, id)
);

CREATE TABLE IF NOT EXISTS persons_cleanup_log (
  id          BIGSERIAL PRIMARY KEY,
  run_id      TEXT NOT NULL,
  step        TEXT NOT NULL,          -- quarantine | rehang | merge_canonical_before | mark | insert_entity | rename | run
  table_name  TEXT,
  column_name TEXT,
  row_id      TEXT,
  old_value   TEXT,
  new_value   TEXT,
  row_data    JSONB,
  action      TEXT,                   -- updated | deleted | inserted | snapshot | marked | info
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_persons_cleanup_log_run ON persons_cleanup_log(run_id, id);

ALTER TABLE persons ADD COLUMN IF NOT EXISTS quarantined_at    TIMESTAMPTZ;
ALTER TABLE persons ADD COLUMN IF NOT EXISTS quarantine_reason TEXT;
ALTER TABLE persons ADD COLUMN IF NOT EXISTS merged_into       UUID;
CREATE INDEX IF NOT EXISTS idx_persons_quarantined_at ON persons(quarantined_at) WHERE quarantined_at IS NOT NULL;

-- Quarantäne-Tabelle: gleiche Spalten wie persons plus cleanup_*-Metadaten
CREATE TABLE IF NOT EXISTS persons_quarantine (LIKE persons INCLUDING DEFAULTS);
ALTER TABLE persons_quarantine ADD COLUMN IF NOT EXISTS cleanup_run_id         TEXT;
ALTER TABLE persons_quarantine ADD COLUMN IF NOT EXISTS cleanup_decision       TEXT;
ALTER TABLE persons_quarantine ADD COLUMN IF NOT EXISTS cleanup_subcategory    TEXT;
ALTER TABLE persons_quarantine ADD COLUMN IF NOT EXISTS cleanup_canonical_id   UUID;
ALTER TABLE persons_quarantine ADD COLUMN IF NOT EXISTS cleanup_reason         TEXT;
ALTER TABLE persons_quarantine ADD COLUMN IF NOT EXISTS cleanup_quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now();

DO $$
DECLARE
  c RECORD;
BEGIN
  -- Primärschlüssel, falls noch nicht vorhanden
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'persons_quarantine'::regclass AND contype = 'p') THEN
    ALTER TABLE persons_quarantine ADD PRIMARY KEY (id);
  END IF;
  -- Spalten nachziehen, die persons seit Anlage der Quarantäne-Tabelle bekommen hat
  FOR c IN
    SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS typ
    FROM pg_attribute a
    WHERE a.attrelid = 'persons'::regclass AND a.attnum > 0 AND NOT a.attisdropped
      AND NOT EXISTS (SELECT 1 FROM pg_attribute b
                      WHERE b.attrelid = 'persons_quarantine'::regclass AND b.attnum > 0
                        AND NOT b.attisdropped AND b.attname = a.attname)
  LOOP
    EXECUTE format('ALTER TABLE persons_quarantine ADD COLUMN %I %s', c.attname, c.typ);
  END LOOP;
END $$;

-- ------------------------------------------------------------------------------------
-- Hilfsfunktionen (temporär, verschwinden mit der Sitzung)
-- ------------------------------------------------------------------------------------

-- Hängt alle Zeilen von tbl.col von p_dup auf p_canon um; protokolliert jede Änderung.
-- Zeilen, die durch das Umhängen einen UNIQUE-Konflikt oder eine Selbstreferenz erzeugen würden,
-- werden protokolliert (vollständige Zeile als JSON) und entfernt – Rollback stellt sie wieder her.
CREATE FUNCTION pg_temp.cleanup_rehang(p_run TEXT, p_tbl TEXT, p_col TEXT, p_dup UUID, p_canon UUID)
RETURNS VOID LANGUAGE plpgsql AS $fn$
DECLARE
  v_has_id   BOOLEAN;
  v_idx      RECORD;
  v_other    TEXT;
  v_cols     TEXT[];
  v_sql      TEXT;
  v_coltype  TEXT;
  v_castdup  TEXT;
  v_castcan  TEXT;
BEGIN
  SELECT format_type(a.atttypid, a.atttypmod) INTO v_coltype
  FROM pg_attribute a WHERE a.attrelid = p_tbl::regclass AND a.attname = p_col AND NOT a.attisdropped;
  IF v_coltype IS NULL THEN RETURN; END IF;
  -- Spalten können UUID oder (fehlerhaft) INTEGER/TEXT sein; nur UUID/TEXT sind umhängbar
  IF v_coltype NOT IN ('uuid', 'text', 'character varying') AND v_coltype NOT LIKE 'character varying%' THEN
    RETURN;
  END IF;
  v_castdup := CASE WHEN v_coltype = 'uuid' THEN quote_literal(p_dup) || '::uuid' ELSE quote_literal(p_dup::text) END;
  v_castcan := CASE WHEN v_coltype = 'uuid' THEN quote_literal(p_canon) || '::uuid' ELSE quote_literal(p_canon::text) END;

  SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = p_tbl::regclass AND attname = 'id' AND NOT attisdropped)
    INTO v_has_id;

  -- a) Selbstreferenzen: Zeilen, in denen eine andere Personen-Spalte bereits auf p_canon zeigt
  FOR v_other IN
    SELECT a.attname FROM pg_attribute a
    WHERE a.attrelid = p_tbl::regclass AND a.attnum > 0 AND NOT a.attisdropped
      AND a.attname <> p_col AND format_type(a.atttypid, a.atttypmod) = v_coltype
      AND a.attname IN ('person_id','connected_person_id','person_a_id','person_b_id','source_person_id',
                        'target_person_id','related_person_id','matched_person_id','primary_person_id')
  LOOP
    v_sql := format(
      'WITH del AS (DELETE FROM %I t WHERE t.%I = %s AND t.%I = %s RETURNING t.*)
       INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, row_data, action)
       SELECT %L, ''rehang'', %L, %L, NULL, %L, %L, to_jsonb(del), ''deleted'' FROM del',
      p_tbl, p_col, v_castdup, v_other, v_castcan,
      p_run, p_tbl, p_col, p_dup::text, p_canon::text);
    EXECUTE v_sql;
  END LOOP;

  -- b) UNIQUE-Konflikte: für jeden Unique-Index, der p_col enthält, Dubletten-Zeilen entfernen,
  --    zu denen bereits eine gleichartige Zeile des kanonischen Datensatzes existiert
  FOR v_idx IN
    SELECT i.indexrelid
    FROM pg_index i
    WHERE i.indrelid = p_tbl::regclass AND i.indisunique
      AND i.indpred IS NULL AND i.indexprs IS NULL
      AND p_col IN (SELECT a.attname FROM pg_attribute a
                    WHERE a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey))
  LOOP
    SELECT array_agg(a.attname ORDER BY a.attnum) INTO v_cols
    FROM pg_attribute a
    WHERE a.attrelid = p_tbl::regclass AND a.attnum = ANY ((SELECT indkey FROM pg_index WHERE indexrelid = v_idx.indexrelid)::int2[])
      AND a.attname <> p_col;
    IF v_cols IS NULL OR array_length(v_cols, 1) IS NULL THEN
      -- Unique nur auf p_col selbst: Dubletten-Zeile entfernen, falls Kanon-Zeile existiert
      v_sql := format(
        'WITH del AS (DELETE FROM %I t WHERE t.%I = %s AND EXISTS (SELECT 1 FROM %I c WHERE c.%I = %s) RETURNING t.*)
         INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, row_data, action)
         SELECT %L, ''rehang'', %L, %L, NULL, %L, %L, to_jsonb(del), ''deleted'' FROM del',
        p_tbl, p_col, v_castdup, p_tbl, p_col, v_castcan,
        p_run, p_tbl, p_col, p_dup::text, p_canon::text);
    ELSE
      v_sql := format(
        'WITH del AS (DELETE FROM %I t WHERE t.%I = %s AND EXISTS (SELECT 1 FROM %I c WHERE c.%I = %s AND %s) RETURNING t.*)
         INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, row_data, action)
         SELECT %L, ''rehang'', %L, %L, NULL, %L, %L, to_jsonb(del), ''deleted'' FROM del',
        p_tbl, p_col, v_castdup, p_tbl, p_col, v_castcan,
        (SELECT string_agg(format('c.%I IS NOT DISTINCT FROM t.%I', x, x), ' AND ') FROM unnest(v_cols) x),
        p_run, p_tbl, p_col, p_dup::text, p_canon::text);
    END IF;
    EXECUTE v_sql;
  END LOOP;

  -- c) Umhängen der verbleibenden Zeilen
  IF v_has_id THEN
    v_sql := format(
      'WITH upd AS (UPDATE %I t SET %I = %s WHERE t.%I = %s RETURNING t.id)
       INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
       SELECT %L, ''rehang'', %L, %L, upd.id::text, %L, %L, ''updated'' FROM upd',
      p_tbl, p_col, v_castcan, p_col, v_castdup,
      p_run, p_tbl, p_col, p_dup::text, p_canon::text);
  ELSE
    -- ohne id-Spalte: alte Zeile komplett protokollieren, Rollback löscht/re-insertet anhand der Zeilendaten
    v_sql := format(
      'WITH old AS (SELECT to_jsonb(t) AS d FROM %I t WHERE t.%I = %s),
            upd AS (UPDATE %I t SET %I = %s WHERE t.%I = %s)
       INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, row_data, action)
       SELECT %L, ''rehang'', %L, %L, NULL, %L, %L, old.d, ''updated_noid'' FROM old',
      p_tbl, p_col, v_castdup, p_tbl, p_col, v_castcan, p_col, v_castdup,
      p_run, p_tbl, p_col, p_dup::text, p_canon::text);
  END IF;
  EXECUTE v_sql;
END $fn$;

-- Liefert alle (Tabelle, Spalte), die auf persons.id verweisen: echte Fremdschlüssel plus
-- bekannte Tabellen ohne FK (person_connections, kg_nodes, company_persons ...)
CREATE FUNCTION pg_temp.cleanup_ref_columns()
RETURNS TABLE (tbl TEXT, col TEXT) LANGUAGE sql AS $fn$
  WITH fk AS (
    SELECT c.conrelid::regclass::text AS tbl, a.attname::text AS col
    FROM pg_constraint c
    JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ord) ON TRUE
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
    WHERE c.contype = 'f' AND c.confrelid = 'persons'::regclass
  ),
  known(tbl, col) AS (
    VALUES ('person_connections','person_id'), ('person_connections','connected_person_id'),
           ('kg_nodes','source_id'),
           ('company_persons','person_id'), ('dossier_persons','person_id'), ('file_persons','person_id'),
           ('material_persons','person_id'), ('person_tags','person_id'), ('person_links','person_id'),
           ('discovered_emails','person_id'), ('social_media_profiles','person_id'), ('osint_scans','person_id'),
           ('person_relationships','person_a_id'), ('person_relationships','person_b_id'),
           ('person_attributes','person_id'), ('person_media','person_id'), ('face_annotations','person_id'),
           ('person_photos','person_id'), ('face_embeddings','person_id'), ('face_scan_matches','person_id'),
           ('linguistic_profiles','person_id'), ('analysis_sources','person_id'), ('interviews','interviewee_person_id'),
           ('research_activity_log','person_id'), ('person_suggestions','matched_person_id'),
           ('osint_findings','suggested_person_id'), ('person_merge_log','primary_person_id'),
           ('wall_items','person_id'), ('wiki_entries','person_id'), ('timeline_events','person_id'),
           ('event_entities','person_id'), ('document_persons','person_id'), ('article_persons','person_id'),
           ('dossier_person_roles','person_id'), ('smart_quotes','speaker_person_id'), ('fact_checks','related_person_id')
  )
  SELECT DISTINCT x.tbl, x.col
  FROM (SELECT * FROM fk UNION SELECT * FROM known) x
  WHERE to_regclass(x.tbl) IS NOT NULL
    AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = x.tbl::regclass AND a.attname = x.col AND NOT a.attisdropped)
    AND x.tbl <> 'persons_quarantine'
  ORDER BY 1, 2
$fn$;

-- ------------------------------------------------------------------------------------
-- Hauptlauf
-- ------------------------------------------------------------------------------------
DO $main$
DECLARE
  v_run        TEXT;
  v_cols       TEXT;          -- gemeinsame Spaltenliste persons/persons_quarantine
  v_n          INT;
  v_total      INT := 0;
  d            RECORD;
  r            RECORD;
  v_set        TEXT;
  v_org_table  TEXT;
  v_org_cols   TEXT;
  v_org_vals   TEXT;
  v_new_id     TEXT;
  v_has        BOOLEAN;
  v_name       TEXT;
  v_dossier    UUID;
  v_cnt_q      INT := 0;
  v_cnt_merge  INT := 0;
  v_cnt_np     INT := 0;
  v_cnt_org    INT := 0;
  v_cnt_evt    INT := 0;
  v_cnt_ren    INT := 0;
  v_cnt_skip   INT := 0;
BEGIN
  -- Neuester, noch nicht angewendeter Lauf
  SELECT run_id INTO v_run
  FROM persons_cleanup_decisions WHERE applied_at IS NULL
  GROUP BY run_id ORDER BY run_id DESC LIMIT 1;

  IF v_run IS NULL THEN
    RAISE NOTICE 'Keine offenen Entscheidungen in persons_cleanup_decisions – nichts zu tun (bereits angewendet?).';
    RETURN;
  END IF;
  RAISE NOTICE 'Lauf %: % Entscheidungen', v_run, (SELECT count(*) FROM persons_cleanup_decisions WHERE run_id = v_run);

  -- Validierung: Dubletten müssen auf einen Datensatz zeigen, der selbst bleibt
  SELECT count(*) INTO v_n
  FROM persons_cleanup_decisions dd
  LEFT JOIN persons_cleanup_decisions cc ON cc.run_id = dd.run_id AND cc.id = dd.kanonische_id
  WHERE dd.run_id = v_run AND dd.entscheidung = 'dublette'
    AND (dd.kanonische_id IS NULL OR dd.kanonische_id = dd.id
         OR cc.id IS NULL OR cc.entscheidung NOT IN ('person_ok', 'person_korrigieren'));
  IF v_n > 0 THEN
    RAISE EXCEPTION '% Dubletten-Entscheidungen zeigen auf keinen gültigen kanonischen Datensatz', v_n;
  END IF;
  SELECT count(*) INTO v_n
  FROM persons_cleanup_decisions dd
  WHERE dd.run_id = v_run AND dd.entscheidung = 'dublette'
    AND NOT EXISTS (SELECT 1 FROM persons p WHERE p.id = dd.kanonische_id);
  IF v_n > 0 THEN
    RAISE EXCEPTION '% kanonische Datensätze existieren nicht (mehr) in persons', v_n;
  END IF;
  SELECT count(*) INTO v_n
  FROM persons_cleanup_decisions dd WHERE dd.run_id = v_run
    AND NOT EXISTS (SELECT 1 FROM persons p WHERE p.id = dd.id);
  IF v_n > 0 THEN
    RAISE NOTICE '% Entscheidungen betreffen IDs, die nicht mehr in persons existieren – werden übersprungen', v_n;
  END IF;

  INSERT INTO persons_cleanup_log (run_id, step, action, new_value)
  VALUES (v_run, 'run', 'info', 'start ' || now()::text);

  -- ----------------------------------------------------------------------------------
  -- 1. Kopie nach persons_quarantine (Nicht-Personen und Dubletten)
  -- ----------------------------------------------------------------------------------
  SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) INTO v_cols
  FROM pg_attribute a
  WHERE a.attrelid = 'persons'::regclass AND a.attnum > 0 AND NOT a.attisdropped
    AND EXISTS (SELECT 1 FROM pg_attribute b WHERE b.attrelid = 'persons_quarantine'::regclass
                  AND b.attname = a.attname AND NOT b.attisdropped);

  EXECUTE format(
    'INSERT INTO persons_quarantine (%s, cleanup_run_id, cleanup_decision, cleanup_subcategory, cleanup_canonical_id, cleanup_reason)
     SELECT %s, d.run_id, d.entscheidung, d.unterkategorie, d.kanonische_id, d.begruendung
     FROM persons p JOIN persons_cleanup_decisions d ON d.id = p.id
     WHERE d.run_id = $1 AND d.entscheidung IN (''keine_person'', ''dublette'')
     ON CONFLICT (id) DO NOTHING',
    v_cols, regexp_replace(v_cols, '(^|, )', '\1p.', 'g'))
  USING v_run;
  GET DIAGNOSTICS v_cnt_q = ROW_COUNT;
  RAISE NOTICE '1. % Zeilen nach persons_quarantine kopiert', v_cnt_q;

  -- ----------------------------------------------------------------------------------
  -- 2. Dubletten verschmelzen
  -- ----------------------------------------------------------------------------------
  FOR d IN
    SELECT dd.id AS dup_id, dd.kanonische_id AS canon_id, dd.begruendung
    FROM persons_cleanup_decisions dd
    JOIN persons p ON p.id = dd.id
    WHERE dd.run_id = v_run AND dd.entscheidung = 'dublette'
      AND p.quarantined_at IS NULL            -- noch nicht verarbeitet (Idempotenz)
    ORDER BY dd.kanonische_id, dd.id
  LOOP
    -- a) Schnappschuss des kanonischen Datensatzes (einmal je Lauf)
    IF NOT EXISTS (SELECT 1 FROM persons_cleanup_log
                   WHERE run_id = v_run AND step = 'merge_canonical_before' AND row_id = d.canon_id::text) THEN
      INSERT INTO persons_cleanup_log (run_id, step, table_name, row_id, row_data, action)
      SELECT v_run, 'merge_canonical_before', 'persons', p.id::text, to_jsonb(p), 'snapshot'
      FROM persons p WHERE p.id = d.canon_id;
    END IF;

    -- b) Verweise umhängen
    FOR r IN SELECT * FROM pg_temp.cleanup_ref_columns() LOOP
      IF r.tbl = 'kg_nodes' THEN
        -- nur Personen-Knoten, deren source_id auf die Dublette zeigt
        EXECUTE format(
          'WITH upd AS (UPDATE kg_nodes SET source_id = $2 WHERE source_id = $1 AND node_type = ''person'' RETURNING id)
           INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
           SELECT %L, ''rehang'', ''kg_nodes'', ''source_id'', upd.id::text, %L, %L, ''updated'' FROM upd',
          v_run, d.dup_id::text, d.canon_id::text)
        USING d.dup_id, d.canon_id;
      ELSE
        PERFORM pg_temp.cleanup_rehang(v_run, r.tbl, r.col, d.dup_id, d.canon_id);
      END IF;
    END LOOP;
    -- kg_nodes.properties->>'person_id'
    IF to_regclass('kg_nodes') IS NOT NULL THEN
      EXECUTE format(
        'WITH upd AS (UPDATE kg_nodes SET properties = jsonb_set(properties, ''{person_id}'', to_jsonb($2::text))
                      WHERE properties->>''person_id'' = $1::text RETURNING id)
         INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
         SELECT %L, ''rehang'', ''kg_nodes'', ''properties.person_id'', upd.id::text, %L, %L, ''updated'' FROM upd',
        v_run, d.dup_id::text, d.canon_id::text)
      USING d.dup_id, d.canon_id;
    END IF;

    -- c) Attribute in den kanonischen Datensatz übernehmen (nur vorhandene Spalten)
    v_set := 'aliases = (SELECT array_agg(DISTINCT x) FROM unnest(COALESCE(c.aliases, ''{}'') || ARRAY[dp.canonical_name] || COALESCE(dp.aliases, ''{}'')) x WHERE x IS NOT NULL AND x <> '''' AND x <> c.canonical_name)';
    IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'persons'::regclass AND attname = 'emails' AND NOT attisdropped) THEN
      v_set := v_set || ', emails = (SELECT COALESCE(jsonb_agg(e), ''[]''::jsonb) FROM (SELECT DISTINCT e FROM jsonb_array_elements(COALESCE(c.emails, ''[]''::jsonb) || COALESCE(dp.emails, ''[]''::jsonb)) e) s)';
    END IF;
    FOR r IN
      SELECT attname FROM pg_attribute
      WHERE attrelid = 'persons'::regclass AND NOT attisdropped
        AND attname IN ('party', 'source', 'user_id', 'birth_date', 'birth_place', 'description', 'profession',
                        'nationality', 'gender', 'photo_url', 'profile_image_url', 'dossier_id', 'location')
    LOOP
      v_set := v_set || format(', %1$I = COALESCE(c.%1$I, dp.%1$I)', r.attname);
    END LOOP;
    FOR r IN
      SELECT attname FROM pg_attribute
      WHERE attrelid = 'persons'::regclass AND NOT attisdropped
        AND attname IN ('parties', 'organizations', 'clubs', 'locations', 'family_connections')
        AND format_type(atttypid, atttypmod) = 'text[]'
    LOOP
      v_set := v_set || format(', %1$I = (SELECT array_agg(DISTINCT x) FROM unnest(COALESCE(c.%1$I, ''{}'') || COALESCE(dp.%1$I, ''{}'')) x WHERE x IS NOT NULL AND x <> '''')', r.attname);
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'persons'::regclass AND attname = 'merged_from' AND NOT attisdropped) THEN
      v_set := v_set || ', merged_from = (SELECT array_agg(DISTINCT x) FROM unnest(COALESCE(c.merged_from, ''{}'') || ARRAY[dp.id]) x)';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'persons'::regclass AND attname = 'updated_at' AND NOT attisdropped) THEN
      v_set := v_set || ', updated_at = now()';
    END IF;

    EXECUTE format('UPDATE persons c SET %s FROM persons dp WHERE c.id = $1 AND dp.id = $2', v_set)
    USING d.canon_id, d.dup_id;

    -- d) Dublette markieren (bleibt physisch erhalten)
    UPDATE persons
    SET quarantined_at = now(),
        quarantine_reason = 'dublette -> ' || d.canon_id::text || ' (' || v_run || ')',
        merged_into = d.canon_id
    WHERE id = d.dup_id;
    INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
    VALUES (v_run, 'mark', 'persons', 'quarantined_at', d.dup_id::text, NULL, d.canon_id::text, 'marked');
    v_cnt_merge := v_cnt_merge + 1;
  END LOOP;
  RAISE NOTICE '2. % Dubletten verschmolzen', v_cnt_merge;

  -- ----------------------------------------------------------------------------------
  -- 3. Nicht-Personen markieren und Organisationen/Ereignisse überführen
  -- ----------------------------------------------------------------------------------
  v_org_table := CASE WHEN to_regclass('organizations') IS NOT NULL THEN 'organizations'
                      WHEN to_regclass('companies') IS NOT NULL THEN 'companies' END;

  FOR d IN
    SELECT dd.id, dd.name_alt, dd.unterkategorie, dd.begruendung, p.canonical_name, p.description, p.dossier_id
    FROM persons_cleanup_decisions dd
    JOIN persons p ON p.id = dd.id
    WHERE dd.run_id = v_run AND dd.entscheidung = 'keine_person' AND p.quarantined_at IS NULL
    ORDER BY dd.id
  LOOP
    v_name := NULLIF(btrim(regexp_replace(d.canonical_name, '\s+', ' ', 'g')), '');

    IF d.unterkategorie = 'organisation' AND v_org_table IS NOT NULL AND v_name IS NOT NULL THEN
      EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE lower(name) = lower($1))', v_org_table) INTO v_has USING v_name;
      IF NOT v_has THEN
        v_org_cols := 'name'; v_org_vals := quote_literal(v_name);
        IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = v_org_table::regclass AND attname = 'description' AND NOT attisdropped) THEN
          v_org_cols := v_org_cols || ', description';
          v_org_vals := v_org_vals || ', ' || quote_literal(COALESCE(d.description, '') ||
                        CASE WHEN d.description IS NULL OR d.description = '' THEN '' ELSE E'\n' END ||
                        'Aus Personenregister überführt (persons.id=' || d.id::text || ', Lauf ' || v_run || ')');
        END IF;
        IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = v_org_table::regclass AND attname = 'dossier_id' AND NOT attisdropped) THEN
          v_org_cols := v_org_cols || ', dossier_id';
          v_org_vals := v_org_vals || ', ' || COALESCE(quote_literal(d.dossier_id::text) || '::uuid', 'NULL');
        END IF;
        IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = v_org_table::regclass AND attname = 'source' AND NOT attisdropped) THEN
          v_org_cols := v_org_cols || ', source';
          v_org_vals := v_org_vals || ', ' || quote_literal('personen-bereinigung');
        END IF;
        EXECUTE format('INSERT INTO %I (%s) VALUES (%s) RETURNING id::text', v_org_table, v_org_cols, v_org_vals) INTO v_new_id;
        INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
        VALUES (v_run, 'insert_entity', v_org_table, 'name', v_new_id, d.id::text, v_name, 'inserted');
        v_cnt_org := v_cnt_org + 1;
      END IF;
    ELSIF d.unterkategorie = 'ereignis' AND to_regclass('events') IS NOT NULL AND v_name IS NOT NULL THEN
      SELECT EXISTS (SELECT 1 FROM events WHERE lower(title) = lower(v_name)) INTO v_has;
      IF NOT v_has THEN
        INSERT INTO events (dossier_id, title, description)
        VALUES (d.dossier_id, v_name,
                COALESCE(d.description, '') || CASE WHEN d.description IS NULL OR d.description = '' THEN '' ELSE E'\n' END ||
                'Aus Personenregister überführt (persons.id=' || d.id::text || ', Lauf ' || v_run || ')')
        RETURNING id::text INTO v_new_id;
        INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
        VALUES (v_run, 'insert_entity', 'events', 'title', v_new_id, d.id::text, v_name, 'inserted');
        v_cnt_evt := v_cnt_evt + 1;
      END IF;
    END IF;

    UPDATE persons
    SET quarantined_at = now(),
        quarantine_reason = 'keine_person/' || COALESCE(d.unterkategorie, 'sonstiges') || ' (' || v_run || ')'
    WHERE id = d.id;
    INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
    VALUES (v_run, 'mark', 'persons', 'quarantined_at', d.id::text, NULL, 'keine_person/' || COALESCE(d.unterkategorie, 'sonstiges'), 'marked');
    v_cnt_np := v_cnt_np + 1;
  END LOOP;
  RAISE NOTICE '3. % Nicht-Personen markiert (% -> %, % -> events)', v_cnt_np, v_cnt_org, COALESCE(v_org_table, '-'), v_cnt_evt;

  -- ----------------------------------------------------------------------------------
  -- 4. Namen korrigieren
  -- ----------------------------------------------------------------------------------
  FOR d IN
    SELECT dd.id, dd.name_alt, dd.name_neu, p.canonical_name
    FROM persons_cleanup_decisions dd
    JOIN persons p ON p.id = dd.id
    WHERE dd.run_id = v_run AND dd.entscheidung = 'person_korrigieren'
      AND dd.name_neu IS NOT NULL AND btrim(dd.name_neu) <> ''
      AND p.canonical_name IS DISTINCT FROM dd.name_neu
    ORDER BY dd.id
  LOOP
    IF d.canonical_name IS DISTINCT FROM d.name_alt THEN
      -- Name wurde seit dem Export bereits von Hand geändert: nicht überschreiben
      v_cnt_skip := v_cnt_skip + 1;
      INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
      VALUES (v_run, 'rename', 'persons', 'canonical_name', d.id::text, d.canonical_name, d.name_neu, 'skipped_changed');
      CONTINUE;
    END IF;
    UPDATE persons
    SET canonical_name = d.name_neu,
        aliases = CASE WHEN d.canonical_name = ANY (COALESCE(aliases, '{}')) THEN aliases
                       ELSE array_append(COALESCE(aliases, '{}'), d.canonical_name) END
    WHERE id = d.id;
    INSERT INTO persons_cleanup_log (run_id, step, table_name, column_name, row_id, old_value, new_value, action)
    VALUES (v_run, 'rename', 'persons', 'canonical_name', d.id::text, d.canonical_name, d.name_neu, 'updated');
    v_cnt_ren := v_cnt_ren + 1;
  END LOOP;
  RAISE NOTICE '4. % Namen korrigiert, % übersprungen (seit Export geändert)', v_cnt_ren, v_cnt_skip;

  -- ----------------------------------------------------------------------------------
  -- 5. Abschluss
  -- ----------------------------------------------------------------------------------
  UPDATE persons_cleanup_decisions SET applied_at = now() WHERE run_id = v_run;
  INSERT INTO persons_cleanup_log (run_id, step, action, new_value)
  VALUES (v_run, 'run', 'info', format('ende %s: quarantaene=%s, verschmolzen=%s, nicht_personen=%s, orgs=%s, events=%s, umbenannt=%s',
                                        now()::text, v_cnt_q, v_cnt_merge, v_cnt_np, v_cnt_org, v_cnt_evt, v_cnt_ren));
  RAISE NOTICE 'Fertig. Sichtbare Personen (quarantined_at IS NULL): %', (SELECT count(*) FROM persons WHERE quarantined_at IS NULL);
END $main$;

COMMIT;
