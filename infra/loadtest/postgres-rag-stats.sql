-- Read-only representative transaction for `/rag/stats`. It mirrors the four
-- retrieval-summary query shapes that previously ran for every dashboard
-- refresh. One pgbench transaction executes all four statements.
SELECT count(DISTINCT t.rag_query_id), count(*)
FROM rag_trace AS t
JOIN rag_query AS q ON q.id = t.rag_query_id
WHERE q.created_at >= now() - make_interval(days => 30);

SELECT t.outcome, count(*)
FROM rag_trace AS t
JOIN rag_query AS q ON q.id = t.rag_query_id
WHERE q.created_at >= now() - make_interval(days => 30)
GROUP BY t.outcome
ORDER BY count(*) DESC;

SELECT CASE
           WHEN t.dense_rank IS NOT NULL AND t.sparse_rank IS NOT NULL THEN 'both'
           WHEN t.sparse_rank IS NOT NULL THEN 'sparse_only'
           WHEN t.dense_rank IS NOT NULL THEN 'dense_only'
           ELSE 'unknown'
       END AS channel,
       count(*)
FROM rag_trace AS t
JOIN rag_query AS q ON q.id = t.rag_query_id
WHERE q.created_at >= now() - make_interval(days => 30)
  AND t.outcome = 'cited'
GROUP BY 1;

SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t.fused_rank),
       max(t.fused_rank),
       count(*) FILTER (WHERE t.fused_rank > 10)
FROM rag_trace AS t
JOIN rag_query AS q ON q.id = t.rag_query_id
WHERE q.created_at >= now() - make_interval(days => 30)
  AND t.outcome = 'cited'
  AND t.fused_rank IS NOT NULL;
