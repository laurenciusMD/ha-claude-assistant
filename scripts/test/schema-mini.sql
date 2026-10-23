CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TABLE users (id SERIAL PRIMARY KEY, username TEXT);
INSERT INTO users (username) VALUES ('laurencius'), ('testuser');
CREATE TABLE dossiers (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), title TEXT, created_by INTEGER);
INSERT INTO dossiers (title, created_by) VALUES ('Recherche A', 1);
CREATE TABLE persons (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  dossier_id UUID REFERENCES dossiers(id) ON DELETE CASCADE,
  canonical_name TEXT NOT NULL, aliases TEXT[], description TEXT,
  confidence_score FLOAT DEFAULT 0.5, merged_from UUID[],
  created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW(),
  birth_date DATE, emails JSONB DEFAULT '[]'::jsonb, parties TEXT[], organizations TEXT[],
  party TEXT, source TEXT, user_id INTEGER, slug VARCHAR(100) UNIQUE, osint_data JSONB, photo_url TEXT
);
CREATE TABLE dossier_persons (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), dossier_id UUID NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
  person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE, role TEXT, CONSTRAINT unique_dossier_person UNIQUE (dossier_id, person_id));
CREATE TABLE person_tags (person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE, tag_name TEXT NOT NULL, PRIMARY KEY (person_id, tag_name));
CREATE TABLE person_connections (id SERIAL PRIMARY KEY, person_id UUID, connected_person_id UUID, connected_person_name TEXT, relation_type TEXT, relation_context TEXT, confidence INTEGER DEFAULT 50);
CREATE TABLE person_relationships (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), person_a_id UUID REFERENCES persons(id) ON DELETE CASCADE, person_b_id UUID REFERENCES persons(id) ON DELETE CASCADE, relationship_type TEXT NOT NULL);
CREATE TABLE file_persons (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), file_id UUID NOT NULL, person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE, UNIQUE (file_id, person_id));
CREATE TABLE companies (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name TEXT NOT NULL, description TEXT, dossier_id UUID, created_by INTEGER);
CREATE TABLE company_persons (company_id UUID REFERENCES companies(id), person_id UUID REFERENCES persons(id), role TEXT, PRIMARY KEY (company_id, person_id));
CREATE TABLE events (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), dossier_id UUID REFERENCES dossiers(id), title TEXT NOT NULL, description TEXT, event_date DATE,
  confidence TEXT CHECK (confidence IN ('confirmed','alleged','disputed')), created_at TIMESTAMP DEFAULT NOW());
CREATE TABLE kg_nodes (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id INTEGER, node_type TEXT NOT NULL, name TEXT NOT NULL, properties JSONB DEFAULT '{}', source_id UUID);
CREATE TABLE smart_quotes (id SERIAL PRIMARY KEY, speaker_person_id INTEGER REFERENCES users(id), quote TEXT); -- falsch typisierte Spalte wie in Migration 042
