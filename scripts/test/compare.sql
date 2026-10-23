SELECT 'persons' t, md5(string_agg((to_jsonb(p) - 'quarantined_at' - 'quarantine_reason' - 'merged_into' - 'updated_at')::text, E'\n' ORDER BY id)) FROM persons p
UNION ALL SELECT 'dossier_persons', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM dossier_persons x
UNION ALL SELECT 'person_tags', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM person_tags x
UNION ALL SELECT 'person_connections', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM person_connections x
UNION ALL SELECT 'person_relationships', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM person_relationships x
UNION ALL SELECT 'file_persons', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM file_persons x
UNION ALL SELECT 'companies', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM companies x
UNION ALL SELECT 'company_persons', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM company_persons x
UNION ALL SELECT 'events', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM events x
UNION ALL SELECT 'kg_nodes', md5(string_agg(to_jsonb(x)::text, E'\n' ORDER BY to_jsonb(x)::text)) FROM kg_nodes x;
