-- Remove the JSON envelope the model appended to three stored answers.
--
-- The model wrote the answer as prose and then repeated it as the JSON it was
-- asked for. `json.loads` rejected the leading prose, and the prose-recovery
-- guard only rejects text that *starts* with `{`, so the whole reply — braces,
-- escaped newlines and all — became the answer body. The reader sees the answer
-- twice, the second time as machine output.
--
-- Same argument as V019: the code fix only helps answers generated after it,
-- and a permalink is meant to be shared, so the defect would stay visible on
-- exactly the copies most likely to be read by someone else.
--
-- Only where the envelope starts after the prose. If a row ever has it at
-- position 1, the prose came second and cutting there would empty the answer —
-- that variant now parses correctly rather than needing repair, and no such row
-- exists (measured: 3 rows, envelope at 363, 306 and 884).
UPDATE rag_query
   SET answer_markdown = btrim(
           substring(answer_markdown FROM 1 FOR position('{"answer_markdown"' IN answer_markdown) - 1)
       )
 WHERE position('{"answer_markdown"' IN answer_markdown) > 1;

-- **What this does not repair, stated rather than implied.** Those answers were
-- parsed without a `claims` array, so every one of their citations carries the
-- question as its claim text and was support-scored as (question × passage)
-- instead of (claim × passage). Recovering that needs the claims re-bound and
-- the cross-encoder re-run per citation — a provider call, which is not
-- something a migration should do. The rows keep their 「模型未按约定输出 JSON」
-- limitation, which is the honest record that they were degraded.
