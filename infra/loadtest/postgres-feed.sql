-- Read-only representative query for the public feed.  One pgbench
-- transaction equals one feed-page lookup; it does not mutate production data.
SELECT ci.id, ci.title, ci.published_at, ci.quality_score
FROM content_item AS ci
WHERE ci.duplicate_of_id IS NULL
  AND ci.published_at IS NOT NULL
ORDER BY ci.published_at DESC, ci.id DESC
LIMIT 20;
