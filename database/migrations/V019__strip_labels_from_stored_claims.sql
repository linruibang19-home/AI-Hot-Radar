-- Clean the model's own evidence labels out of claims already stored.
--
-- `bind_citations` cleaned the answer body from the start, `limitations` was
-- fixed after `[E1]` was seen on the page, and `claim_text` was never cleaned at
-- all. It renders as 「支撑：DeepSeek 计划上调 API 定价[E1]」 under a card that
-- already shows the number — a marker pointing at the thing it is printed on.
--
-- The code fix only helps answers generated after it. Permalinks are meant to be
-- shared and quoted, so the rows already written have to be cleaned too;
-- otherwise the defect stays visible on exactly the copies most likely to be
-- read by someone else.
--
-- Bracketed form only, matching the code: a bare `E5` in model prose can be a
-- model name. Measured before writing this — all 22 affected rows are bracketed.
UPDATE rag_citation
   SET claim_text = btrim(regexp_replace(claim_text, '\[E[0-9]+\]', '', 'g'), ' 、,，')
 WHERE claim_text ~ '\[E[0-9]+\]';
