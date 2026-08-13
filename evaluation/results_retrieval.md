# Retrieval evaluation

Ground truth: topic tags assigned during enrichment, which the ranker never sees — so the labels are independent of the signal being measured. Scored per source work (not per chunk) over 33 hand-written PM questions.

| strategy | hit-rate@5 | hit-rate@3 | MRR | questions |
|---|---|---|---|---|
| dense only | 91% | 67% | 0.593 | 33 |
| hybrid (dense+BM25, RRF) | 79% | 79% | 0.712 | 33 |
| hybrid + cross-encoder rerank | 91% | 82% | 0.629 | 33 |

**SC-006 (hit-rate@5 >= 80%): PASS** — the shipped pipeline (*hybrid + cross-encoder rerank*) reaches 91%.

## Reading these numbers honestly

Adding BM25 *lowers* hit-rate@5 against dense-only retrieval while raising hit-rate@3 and MRR: fusion promotes keyword matches that sometimes displace a relevant work from the top five, but ranks its hits higher when it does find them. Reranking then recovers hit@5 and gives the best hit@3 of the three.

Since only five or six passages ever reach the prompt, hit@3 is the number that matters most, and that is where the full pipeline wins. The margin over plain dense search is real but modest — worth stating plainly rather than presenting the pipeline as an unambiguous improvement.
