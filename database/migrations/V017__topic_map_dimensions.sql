-- Retire the merged topics, carrying their historical tags with them.
--
-- The topic map had one dimension and four near-empty cards in it: measured,
-- `java_ai` 1 tag, `spring_ai` 1, `python_ai` 0, `cloud_ai` 0, `reranker` 0.
-- Those four occupied a quarter of a section while `agent` carried 459.
--
-- **The tags are not deleted, they are moved.** An item was judged to be about
-- Spring AI by a step that read its full text; throwing that judgement away
-- because the label was retired would lose information that cannot be
-- recovered without paying for the enrichment again. Every merge below is to
-- the nearest surviving leaf, and the mapping is the one written down in
-- `config/taxonomy.yaml` under `topic_merges` so the two cannot drift.
--
-- `business` is the interesting one. It is a *group* name, not a topic, and it
-- had 23 tags — `known_slugs()` was offering group keys to the extraction step,
-- so items were being filed into a bucket the page renders as a section
-- heading rather than a card. Those items were reachable from nowhere. The code
-- path is closed in `topics.py`; this moves the rows that already exist.

-- --- move the tags ----------------------------------------------------------
--
-- ON CONFLICT DO NOTHING because an item may already carry the destination
-- topic: something tagged both `embedding` and `rag` must end up with one `rag`
-- row, not a duplicate-key failure.
INSERT INTO item_topic (content_item_id, topic_id, confidence)
SELECT it.content_item_id, dst.id, it.confidence
  FROM item_topic it
  JOIN topic src ON src.id = it.topic_id
  JOIN topic dst ON dst.slug = CASE src.slug
                                   WHEN 'java_ai'       THEN 'ai_coding'
                                   WHEN 'spring_ai'     THEN 'ai_coding'
                                   WHEN 'python_ai'     THEN 'ai_coding'
                                   WHEN 'cloud_ai'      THEN 'inference'
                                   WHEN 'observability' THEN 'inference'
                                   WHEN 'embedding'     THEN 'rag'
                                   WHEN 'reranker'      THEN 'rag'
                                   WHEN 'business'      THEN 'enterprise'
                               END
 WHERE src.slug IN ('java_ai', 'spring_ai', 'python_ai', 'cloud_ai',
                    'observability', 'embedding', 'reranker', 'business')
ON CONFLICT DO NOTHING;

-- --- then remove the retired topics -----------------------------------------
--
-- Delete the tags first: item_topic references topic, and leaving the rows
-- would keep the old cards alive with counts.
DELETE FROM item_topic
 WHERE topic_id IN (
    SELECT id FROM topic
     WHERE slug IN ('java_ai', 'spring_ai', 'python_ai', 'cloud_ai',
                    'observability', 'embedding', 'reranker', 'business',
                    'models', 'engineering', 'ecosystems')
 );

-- The three group rows go too. `models`, `engineering` and `ecosystems` were
-- seeded as parent topics and the groups are now `tech` and `industry`; the
-- re-seed creates those, and leaving the old ones behind would show two
-- generations of section headings at once.
DELETE FROM topic
 WHERE slug IN ('java_ai', 'spring_ai', 'python_ai', 'cloud_ai',
                'observability', 'embedding', 'reranker', 'business',
                'models', 'engineering', 'ecosystems');

-- --- the two dimensions that were never surfaced ----------------------------
--
-- Both read from data the pipeline has been writing since M2. Neither adds a
-- vocabulary: `vendor` groups rows that already exist in `entity`, and
-- `content_type_meta` only names values `content_item.content_type` already
-- holds. Seeded from `config/taxonomy.yaml` by `ahr.cli seed-topics`, the same
-- way `topic` is, so core-api can read them without needing the YAML.

CREATE TABLE vendor (
    slug          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    display_order INT NOT NULL DEFAULT 100
);

COMMENT ON TABLE vendor IS
    'Curated company/model-family cards for the topic map. Groups entity rows; not a topic vocabulary.';

-- Which entities belong to a vendor. Many-to-one and curated, because entities
-- are extracted under whatever name appeared: `deepseek` and `deepseek-v4` are
-- separate rows, as are `gpt-5.6`, `gpt-5.5` and `gpt-5.6-sol`. Ranking
-- entities directly would produce a wall of version numbers.
CREATE TABLE vendor_entity (
    vendor_slug TEXT NOT NULL REFERENCES vendor(slug) ON DELETE CASCADE,
    entity_slug TEXT NOT NULL,
    PRIMARY KEY (vendor_slug, entity_slug)
);

-- Deliberately no FK to `entity`: the curated list names slugs that may not
-- have been seen in the corpus yet, and a vendor card showing 0 is a true
-- statement about coverage. A foreign key would make the seed fail instead.
CREATE INDEX vendor_entity_entity_idx ON vendor_entity (entity_slug);

CREATE TABLE content_type_meta (
    content_type  TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    display_order INT NOT NULL DEFAULT 100
);

COMMENT ON TABLE content_type_meta IS
    'Display names for content_item.content_type. The allowed values stay in config/taxonomy.yaml.';

-- --- reporting --------------------------------------------------------------
--
-- The counts the topic map needs are `count(DISTINCT content_item_id)` per
-- topic, per vendor entity, and per content_type. The first two have indexes
-- already; content_type does not, and it is about to be a page section.
CREATE INDEX IF NOT EXISTS content_item_content_type_idx
    ON content_item (content_type)
    WHERE content_type IS NOT NULL;
