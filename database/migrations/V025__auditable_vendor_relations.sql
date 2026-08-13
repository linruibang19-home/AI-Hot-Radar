-- TASK-M5-015: vendor navigation is about the subject of an item, not every
-- entity that happened to be mentioned in its body (ADR-0030).

CREATE TABLE item_vendor_relation (
    content_item_id    UUID NOT NULL REFERENCES content_item(id) ON DELETE CASCADE,
    vendor_slug        TEXT NOT NULL REFERENCES vendor(slug) ON DELETE CASCADE,
    relation_level     VARCHAR(16) NOT NULL,
    score              NUMERIC(5,4) NOT NULL,
    matched_entity_slug TEXT NOT NULL,
    matched_role       VARCHAR(16) NOT NULL,
    confidence         NUMERIC(4,3) NOT NULL,
    reason_code        VARCHAR(40) NOT NULL,
    classifier_version VARCHAR(40) NOT NULL,
    evaluated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (content_item_id, vendor_slug),
    CONSTRAINT ck_item_vendor_relation_level
        CHECK (relation_level IN ('primary', 'related', 'mention')),
    CONSTRAINT ck_item_vendor_relation_role
        CHECK (matched_role IN ('subject', 'object', 'mention')),
    CONSTRAINT ck_item_vendor_relation_score CHECK (score BETWEEN 0 AND 1),
    CONSTRAINT ck_item_vendor_relation_confidence CHECK (confidence BETWEEN 0 AND 1)
);

CREATE INDEX item_vendor_relation_feed_idx
    ON item_vendor_relation (vendor_slug, relation_level, score DESC, content_item_id);

COMMENT ON TABLE item_vendor_relation IS
    'Versioned, explainable projection from item_entity into public vendor navigation.';

-- Keep every extraction label for RAG and analysis, but expose only the three
-- strongest sufficiently confident topics in public navigation.
CREATE VIEW public_item_topic AS
SELECT content_item_id, topic_id, confidence
  FROM (
        SELECT it.*,
               row_number() OVER (
                   PARTITION BY it.content_item_id
                   ORDER BY it.confidence DESC NULLS LAST, it.topic_id
               ) AS topic_rank
          FROM item_topic it
         WHERE COALESCE(it.confidence, 0) >= 0.60
       ) ranked
 WHERE topic_rank <= 3;

COMMENT ON VIEW public_item_topic IS
    'Public topic projection: top three labels per item with confidence >= 0.60.';

CREATE OR REPLACE FUNCTION refresh_item_vendor_relations(target_item_id UUID)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM item_vendor_relation WHERE content_item_id = target_item_id;

    INSERT INTO item_vendor_relation (
        content_item_id, vendor_slug, relation_level, score,
        matched_entity_slug, matched_role, confidence, reason_code,
        classifier_version, evaluated_at
    )
    WITH candidates AS (
        SELECT ie.content_item_id,
               ve.vendor_slug,
               e.slug AS entity_slug,
               ie.role,
               COALESCE(ie.confidence, 0.5)::numeric AS confidence,
               position(lower(e.name) in lower(COALESCE(ci.zh_title, '') || ' ' || ci.title)) > 0
                   AS title_match,
               position(lower(e.name) in lower(left(COALESCE(ci.summary_zh, ''), 180))) > 0
                   AS summary_lead_match
          FROM item_entity ie
          JOIN entity e ON e.id = ie.entity_id
          JOIN vendor_entity ve ON ve.entity_slug = e.slug
          JOIN content_item ci ON ci.id = ie.content_item_id
         WHERE ie.content_item_id = target_item_id
    ), classified AS (
        SELECT *,
               CASE
                   WHEN role = 'subject' AND confidence >= 0.75
                        AND (title_match OR summary_lead_match) THEN 'primary'
                   WHEN role = 'subject' AND confidence >= 0.85 THEN 'related'
                   WHEN role = 'object' AND confidence >= 0.65 THEN 'related'
                   WHEN role = 'mention' AND confidence >= 0.75 AND title_match THEN 'related'
                   ELSE 'mention'
               END AS relation_level,
               CASE
                   WHEN role = 'subject' AND title_match THEN 'subject_in_title'
                   WHEN role = 'subject' AND summary_lead_match THEN 'subject_in_summary_lead'
                   WHEN role = 'subject' THEN 'subject_context'
                   WHEN role = 'object' THEN 'comparison_or_object'
                   WHEN title_match THEN 'title_mention'
                   ELSE 'passing_mention'
               END AS reason_code
          FROM candidates
    ), scored AS (
        SELECT *,
               LEAST(1.0,
                   CASE relation_level
                       WHEN 'primary' THEN 0.78
                       WHEN 'related' THEN 0.48
                       ELSE 0.12
                   END
                   + confidence * 0.17
                   + CASE WHEN title_match THEN 0.05 ELSE 0 END
               )::numeric(5,4) AS score
          FROM classified
    ), strongest AS (
        SELECT DISTINCT ON (vendor_slug) *
          FROM scored
         ORDER BY vendor_slug,
                  CASE relation_level WHEN 'primary' THEN 3 WHEN 'related' THEN 2 ELSE 1 END DESC,
                  score DESC,
                  entity_slug
    )
    SELECT content_item_id, vendor_slug, relation_level, score,
           entity_slug, role, confidence, reason_code,
           'vendor-relation-v1', now()
      FROM strongest;
END;
$$;

-- The same deterministic rule serves historical and future content. The
-- function deletes only its derived rows; item_entity remains the extraction
-- fact used by search and RAG.
DO $$
DECLARE
    target_id UUID;
BEGIN
    FOR target_id IN
        SELECT DISTINCT ie.content_item_id FROM item_entity ie
    LOOP
        PERFORM refresh_item_vendor_relations(target_id);
    END LOOP;
END $$;
