# Memory Roadmap Completion Audit

_Last updated: 2026-07-03_

Baseline: `app/memory/idea.md`. This audit separates the current MVP implementation from longer-term design targets that still need a deliberate follow-up decision.

## Status Summary

| Roadmap area | Current status | Evidence | Remaining risk |
| --- | --- | --- | --- |
| Short-text topic boundaries | MVP implemented | `summary.py`, `signals.py`, `turns.py`, prompt boundary tests | Topic semantics use local hashed similarity and rules, not model embeddings. |
| Dynamic working memory | MVP implemented | `work_memory(..., after_message_count=...)`, prompt manifest fields | Limits are configurable heuristics; not learned from usage yet. |
| JSON to SQLite path | MVP implemented | `StorageBackend`, `JsonStore`, `SqliteStore`, migration script, memory/log projection reads, search tests | State snapshot remains JSON-compatible by design for mutation flows; SQLite is still a backend/projection, not the only source model. |
| FTS and semantic recall | Partially implemented | `memory_fts`, `memory_embeddings`, `semantic.py`, storage search tests | Semantic vectors are deterministic local fallback vectors, not production embeddings or `sqlite-vec`. |
| Parameter centralization | MVP implemented | `MemoryParams`, profiles, file overrides, parameter metadata, centralized topic/follow-up/audit anchors | Defaults are still hand-tuned until broader calibration data exists. |
| Feedback and calibration loop | Partially implemented | `feedback.py`, `calibration.py`, `scripts/analyze_memory_feedback.py`, `scripts/evaluate_memory_calibration.py` | Feedback reports evidence, but there is no automatic optimizer or large labeled dataset. |
| Keyword flexibility and intent | Partially implemented | `StructuredLLMIntentClassifier`, rule fallback, centralized keyword groups and topic aliases | Rule fallback still needs broader phrase coverage; LLM classifier is optional rather than always-on. |
| Prompt/summary observability | MVP implemented | prompt segments, `prompt_manifest`, `system_segments`, summary boundary fixes | Runtime service restart may still be needed after backend edits in local sessions. |
| Runtime fallback safety | MVP implemented | Chat service factory, intent-classifier, and memory-extractor exception tests | Gateway chat failures still surface as chat failures because no assistant reply exists to preserve. |

## Roadmap Notes

### 1. Short Text And Topic Boundaries

- Topic-shift summaries no longer depend only on fixed message counts. `summary.py` checks semantic similarity over the unsummarized segment, and topic-shift summaries only cover the previous topic.
- High-density short messages are handled through `signals.information_density()` and extraction tests, so short messages such as emotional events are not treated as casual filler.
- `turns.py` clusters recent short user fragments into one logical turn for extraction and intent classification, with naive and aware timestamps normalized before window comparisons.
- Working memory now scales down for casual chat, expands for deep or continued topics, and starts after the latest summary boundary.
- Relative and numeric deadline inference validates invalid dates and handles naive datetimes before time-state comparisons.

Remaining risk: this is a practical local semantic layer. It does not yet use external embedding models or learned topic boundaries.

### 2. Storage And Recall

- The storage contract now supports both JSON and SQLite backends through `StorageBackend`.
- SQLite includes FTS and derived embedding tables, plus migration from existing JSON state.
- Chat recall can use backend search candidates instead of relying only on full in-memory scans.
- Read-only memory lists, status profile construction, debug logs, and feedback analysis can use storage projection interfaces instead of reading those collections from the full state snapshot.

Remaining risk: the current semantic search is local and deterministic. Write-side chat mutation still keeps the JSON-compatible snapshot as the source of truth, and the long-term `SQLite + sqlite-vec` target from the roadmap is not fully implemented.

### 3. Parameters, Feedback, And Calibration

- Tunable memory behavior is centralized in `MemoryParams`, with profiles and config-file overrides.
- Feedback signals can detect correction, follow-up resolution, topic shift, confirmation acceptance, and memory-audit outcomes.
- Calibration scripts provide an automation-friendly gate for positive and negative recall/follow-up/feedback/correction expectations.
- Feedback analysis now includes parameter metadata with current values, sensitivity, safe ranges, and expected adjustment effects for high-impact knobs.

Remaining risk: calibration coverage is still small. The labeled baseline now covers twenty-four cases, including correction mutation, disclosure engagement, pattern-label over-disclosure, slang low-motivation, and mixed-language anxiety, but it is still below the 50-100 case target from the roadmap.

### 4. Keyword Flexibility And Intent

- Topic words, topic aliases, invitation words, audit anchors, and signal groups are centralized rather than scattered.
- The structured LLM intent path exists and falls back to deterministic rules when unavailable.
- Chat service initialization and per-turn intent classification fall back to deterministic rules if the configured classifier path raises.
- Rule intent now preserves actual information-density scores instead of flattening them away.
- Rule fallback now covers additional completion/deletion phrases and comma-style corrections such as `不是 X，是 Y`.
- Rule signal coverage now includes slang fatigue/avoidance and mixed-language anxiety expressions such as `摆烂`, `躺平`, and `very anxious`.

Remaining risk: alias coverage is still curated and small; there is no trained classifier or always-on semantic intent model yet.

## Verification Gates

Use these gates for future memory-roadmap iterations:

- `python -m pytest -q`
- `python -m compileall -q app scripts tests`
- `python scripts\evaluate_memory_calibration.py` (exits non-zero when any case fails)
- `python scripts\analyze_memory_feedback.py` when feedback or parameter evidence changes

Latest audited baseline after this pass: full tests pass, compile checks pass, calibration covers twenty-four cases with a perfect score, and chat runtime fallbacks preserve replies when classifier/extractor setup or extraction fails.

## Next Iteration Candidates

1. Continue expanding `data/memory_calibration_cases.json` toward 50-100 labeled cases, especially around subtle over-disclosure, mixed-language intent, repeated follow-up fatigue, and colloquial correction/deletion phrases.
2. Decide whether to integrate real embeddings plus `sqlite-vec`, or keep the deterministic local semantic fallback for the MVP.
3. Broaden the curated synonym/phrase map for topic and intent signals using real chat failures.
4. Continue narrowing full-snapshot reads where mutation semantics do not require the whole JSON-compatible state.
5. Add a local service restart verification step after backend prompt changes when permissions allow it.
