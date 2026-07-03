# Memory Roadmap Completion Audit

_Last updated: 2026-07-03_

Baseline: `app/memory/idea.md`. This audit separates the current MVP implementation from longer-term design targets that still need a deliberate follow-up decision.

## Status Summary

| Roadmap area | Current status | Evidence | Remaining risk |
| --- | --- | --- | --- |
| Short-text topic boundaries | MVP implemented | `summary.py`, `signals.py`, `turns.py`, prompt boundary tests | Topic semantics use local hashed similarity and rules, not model embeddings. |
| Dynamic working memory | MVP implemented | `work_memory(..., after_message_count=...)`, prompt manifest fields | Limits are configurable heuristics; not learned from usage yet. |
| JSON to SQLite path | MVP implemented | `StorageBackend`, `JsonStore`, `SqliteStore`, migration script, search tests | State snapshot remains JSON-compatible by design; SQLite is a backend/projection, not the only source model. |
| FTS and semantic recall | Partially implemented | `memory_fts`, `memory_embeddings`, `semantic.py`, storage search tests | Semantic vectors are deterministic local fallback vectors, not production embeddings or `sqlite-vec`. |
| Parameter centralization | MVP implemented | `MemoryParams`, profiles, file overrides, centralized topic/follow-up/audit anchors | Defaults are still hand-tuned until broader calibration data exists. |
| Feedback and calibration loop | Partially implemented | `feedback.py`, `calibration.py`, `scripts/analyze_memory_feedback.py`, `scripts/evaluate_memory_calibration.py` | Feedback reports evidence, but there is no automatic optimizer or large labeled dataset. |
| Keyword flexibility and intent | Partially implemented | `StructuredLLMIntentClassifier`, rule fallback, centralized keyword groups | Rule fallback is still keyword-heavy; LLM classifier is optional rather than always-on. |
| Prompt/summary observability | MVP implemented | prompt segments, `prompt_manifest`, `system_segments`, summary boundary fixes | Runtime service restart may still be needed after backend edits in local sessions. |

## Roadmap Notes

### 1. Short Text And Topic Boundaries

- Topic-shift summaries no longer depend only on fixed message counts. `summary.py` checks semantic similarity over the unsummarized segment, and topic-shift summaries only cover the previous topic.
- High-density short messages are handled through `signals.information_density()` and extraction tests, so short messages such as emotional events are not treated as casual filler.
- `turns.py` clusters recent short user fragments into one logical turn for extraction and intent classification.
- Working memory now scales down for casual chat, expands for deep or continued topics, and starts after the latest summary boundary.

Remaining risk: this is a practical local semantic layer. It does not yet use external embedding models or learned topic boundaries.

### 2. Storage And Recall

- The storage contract now supports both JSON and SQLite backends through `StorageBackend`.
- SQLite includes FTS and derived embedding tables, plus migration from existing JSON state.
- Chat recall can use backend search candidates instead of relying only on full in-memory scans.

Remaining risk: the current semantic search is local and deterministic. The long-term `SQLite + sqlite-vec` target from the roadmap is not fully implemented.

### 3. Parameters, Feedback, And Calibration

- Tunable memory behavior is centralized in `MemoryParams`, with profiles and config-file overrides.
- Feedback signals can detect correction, follow-up resolution, topic shift, confirmation acceptance, and memory-audit outcomes.
- Calibration scripts provide a repeatable gate for recall/follow-up/feedback expectations.

Remaining risk: calibration coverage is still small. The next serious quality step is expanding labeled cases before trusting parameter changes.

### 4. Keyword Flexibility And Intent

- Topic words, invitation words, audit anchors, and signal groups are centralized rather than scattered.
- The structured LLM intent path exists and falls back to deterministic rules when unavailable.
- Rule intent now preserves actual information-density scores instead of flattening them away.

Remaining risk: there is no synonym expansion pipeline, trained classifier, or always-on semantic intent model yet.

## Verification Gates

Use these gates for future memory-roadmap iterations:

- `python -m pytest -q`
- `python -m compileall -q app scripts tests`
- `python scripts\evaluate_memory_calibration.py`
- `python scripts\analyze_memory_feedback.py` when feedback or parameter evidence changes

Latest audited baseline before this document: full tests were passing, compile checks passed, and calibration reported a perfect score in the previous committed phases.

## Next Iteration Candidates

1. Expand `data/memory_calibration_cases.json` beyond the current small baseline, especially around over-disclosure, missed follow-up, and correction.
2. Decide whether to integrate real embeddings plus `sqlite-vec`, or keep the deterministic local semantic fallback for the MVP.
3. Add a synonym/phrase expansion layer for topic and intent signals.
4. Audit remaining full-snapshot profile reads and decide whether any should use narrower storage projections.
5. Add a local service restart verification step after backend prompt changes when permissions allow it.
