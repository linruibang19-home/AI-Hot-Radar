"""RAG evaluation (M4, TASK-M4-001).

AHR-ROADMAP-800 is explicit that the baseline is measured before a reranker is
added, and that "a few subjective examples" do not count as evidence. This
package holds the machinery that makes that possible: the golden set, the
metrics, and the runner that turns a retrieval configuration into a number.
"""
