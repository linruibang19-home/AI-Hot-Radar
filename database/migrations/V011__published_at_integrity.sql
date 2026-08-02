-- Enforce plausible publication dates at the database level.
--
-- `sanitize_published_at` in the ingest path already drops impossible dates,
-- but an application-level guard only protects the code paths that call it.
-- Five OpenAlex rows dated 2036-2045 were reintroduced after being cleaned,
-- by a process running an image that predated the guard. A future-dated item
-- gets maximum freshness forever, so it pins itself to the top of every
-- time-ordered view and the hot list — the failure is silent and permanent.
--
-- A CHECK constraint cannot express this: it may only call IMMUTABLE functions
-- and this rule needs `now()`. A trigger can, and it degrades the same way the
-- application guard does — the implausible value is discarded, not rejected —
-- so a bad date from a third-party feed still ingests the rest of the item.
-- observed_at continues to record when we actually saw it, so nothing is lost.

CREATE OR REPLACE FUNCTION drop_implausible_published_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.published_at IS NOT NULL THEN
        -- Clock skew between us and a publisher is minutes, not days.
        IF NEW.published_at > now() + interval '6 hours'
           OR NEW.published_at < timestamptz '1990-01-01' THEN
            NEW.published_at := NULL;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_content_item_published_at ON content_item;
CREATE TRIGGER trg_content_item_published_at
    BEFORE INSERT OR UPDATE OF published_at ON content_item
    FOR EACH ROW
    EXECUTE FUNCTION drop_implausible_published_at();

-- Clean whatever is currently stored.
UPDATE content_item
   SET published_at = NULL
 WHERE published_at > now() + interval '6 hours'
    OR published_at < timestamptz '1990-01-01';

-- The feed orders by publication date but the UI groups by
-- COALESCE(published_at, observed_at). An item with no publication date was
-- therefore grouped under the day it was observed while sorting as though it
-- were the oldest thing in the feed, which is why the timeline read as
-- jumbled. This index supports ordering by the same expression the UI groups by.
CREATE INDEX IF NOT EXISTS idx_item_effective_date
    ON content_item ((COALESCE(published_at, observed_at)) DESC, id DESC)
    WHERE duplicate_of_id IS NULL;
