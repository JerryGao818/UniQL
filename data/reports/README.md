# Reference revisions and baseline summaries

The full `data/queries/` files and `data/subsets/clean_256/queries/` files use the same current references for shared question IDs. Each full dialect file contains 1,534 aligned intents; each clean-subset file contains the existing 256 selected intents.

The October 2026 revision synchronizes reviewed question/evidence corrections, SQLite references, and target SQL corrections, including fixes for Drill and Teradata. Construction-stage aliases used internally are normalized to the public `annotation_source` vocabulary: `glot`, `LLM-0shot`, `LLM-retry`, `LLM-rule`, and `human`.

The two CSV files summarize the existing model execution traces with these reference revisions applied:

- `full_1534_baseline_results.csv`: execution accuracy over all 1,534 intents per dialect.
- `clean_256_baseline_results.csv`: execution accuracy over the unchanged 256 clean-subset IDs.

Scores are percentages. `Avg.` is the unweighted mean across the 16 dialects, computed before rounding individual scores; `Avg. N` is the number of dialects. These inference-only baselines use their original evaluation protocol and should not be used as the matched base for the direct-SQL SFT experiment. The SFT package generates its own matched base predictions on the held-out 307 intents.

Druid question 520 uses the native-verified reference returning the original SQLite single-row answer (`Anna Pavleeva`, `gladiator`). Saved model prediction outputs were rescored against this reference; model predictions and aggregate correct counts are unchanged.
