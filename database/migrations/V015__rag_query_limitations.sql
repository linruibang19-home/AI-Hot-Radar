-- The caveats an answer shipped with, kept with the answer.
--
-- `limitations` is what the model said it could *not* establish — "证据只来自
-- 一篇论文报道，未提供原文", "证据中未提及具体许可证类型" — plus the server's own
-- disclosures, such as an answer whose citations were recovered because the
-- model did not follow the output contract.
--
-- It was returned by the live endpoint and rendered by the page, but never
-- stored, so `_as_conversation` had no column to read and returned `[]`. The
-- permalink is the shareable, quotable artifact; it was showing the same
-- answer with its qualifications removed. That is the more confident version
-- of the answer, which is exactly the wrong direction to drift.
--
-- Rows written before this migration keep `[]` — an honest "we do not know
-- what it said", not a claim that it said nothing.
ALTER TABLE rag_query
    ADD COLUMN limitations jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN rag_query.limitations IS
    'What the answer stated it could not establish, plus server-side disclosures. Rendered with the answer.';
