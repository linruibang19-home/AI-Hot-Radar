-- Align entity types with config/taxonomy.yaml (ADR-0014).
--
-- V004 encoded the five types listed in docs/spec/03 §7. The taxonomy config
-- lists eight, and real AI-industry content needs the extra three: universities
-- and standards bodies are organizations rather than companies, MCP is a
-- protocol, and LangChain is a framework. Forcing those into `company` writes a
-- wrong fact at the data layer, which then propagates into M3 clustering and M4
-- entity filtering.

ALTER TABLE entity DROP CONSTRAINT IF EXISTS ck_entity_type;

ALTER TABLE entity ADD CONSTRAINT ck_entity_type CHECK (
    entity_type IN (
        'company',
        'organization',
        'product',
        'model',
        'technology',
        'protocol',
        'framework',
        'person'
    )
);
