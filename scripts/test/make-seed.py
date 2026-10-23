#!/usr/bin/env python3
"""Erzeugt aus personen-export.beispiel.csv ein Seed-SQL für das Mini-Schema (schema-mini.sql),
inklusive Verknüpfungszeilen, die Konfliktfälle beim Verschmelzen abdecken (UNIQUE-Konflikte,
Selbstreferenzen, Tabellen ohne id-Spalte, kg_nodes-Properties).

Aufruf: python3 -I scripts/test/make-seed.py scripts/test/personen-export.beispiel.csv > seed.sql
"""
import csv
import sys


def q(v: str) -> str:
    return "NULL" if v == "" else "'" + v.replace("'", "''") + "'"


def main() -> None:
    rows = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
    out = []
    for r in rows:
        out.append(
            "INSERT INTO persons (id, canonical_name, aliases, emails, party, source, created_at, user_id, slug, dossier_id) "
            f"VALUES ('{r['id']}', {q(r['name']) if r['name'] else chr(39)*2}, {q(r['aliases'] or '{}')}::text[], "
            f"{q(r['emails'] or '[]')}::jsonb, {q(r['party'])}, {q(r['source'])}, {q(r['created_at'])}::timestamp, "
            f"{q(r['created_by'])}::int, 'slug-{r['id'][:8]}', (SELECT id FROM dossiers LIMIT 1));")
    by: dict[str, str] = {}
    for r in rows:
        by.setdefault(r["name"], r["id"])  # erste Zeile gewinnt
    cb, ab, dr = by["Christina Baum"], by["A- Baum, Christina"], by["Dr. Christina Baum (MdB)"]
    hm, hmu, ma = by["Müller, Hans"], by["Hans Mueller"], by["MERKEL Angela"]
    d = "(SELECT id FROM dossiers LIMIT 1)"
    out += [
        f"INSERT INTO dossier_persons (dossier_id, person_id, role) VALUES ({d}, '{cb}', 'Hauptperson'), ({d}, '{ab}', 'Migriert'), ({d}, '{dr}', 'Erwähnt'), ({d}, '{hm}', 'Erwähnt');",
        f"INSERT INTO person_tags VALUES ('{ab}','afd'), ('{cb}','afd'), ('{ab}','mdb');",
        f"INSERT INTO person_connections (person_id, connected_person_id, connected_person_name, relation_type) VALUES ('{ab}', '{hm}', 'Hans Müller', 'Kollege'), ('{hmu}', '{ab}', 'Christina Baum', 'Kollegin'), ('{ab}', '{cb}', 'Christina Baum', 'self-dup'), ('{ma}', NULL, 'Olaf Scholz', 'Nachfolger');",
        f"INSERT INTO person_relationships (person_a_id, person_b_id, relationship_type) VALUES ('{ab}', '{hm}', 'colleague'), ('{dr}', '{cb}', 'same');",
        f"INSERT INTO file_persons (file_id, person_id) VALUES ('11111111-1111-1111-1111-111111111111', '{cb}'), ('11111111-1111-1111-1111-111111111111', '{ab}'), ('22222222-2222-2222-2222-222222222222', '{ab}');",
        "INSERT INTO companies (name) VALUES ('Antaios Verlag');",
        f"INSERT INTO company_persons SELECT id, '{ab}', 'Autorin' FROM companies; INSERT INTO company_persons SELECT id, '{cb}', 'Autorin' FROM companies;",
        f"INSERT INTO kg_nodes (node_type, name, source_id, properties) VALUES ('person', 'Christina Baum', '{ab}', '{{\"person_id\": \"{ab}\"}}'), ('document', 'Doc', '{ab}', '{{}}');",
        "INSERT INTO events (title) VALUES ('Sommerinterview 2025');",
    ]
    print("\n".join(out))


if __name__ == "__main__":
    main()
