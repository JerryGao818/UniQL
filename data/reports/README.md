# Reference revisions and baseline summaries

The full `data/queries/` files and `data/subsets/clean_256/queries/` files use the same current references for shared question IDs. Each full dialect file contains 1,534 aligned intents; each clean-subset file contains the existing 256 selected intents.

The October 2026 revision synchronizes reviewed question/evidence corrections, SQLite references, and target SQL corrections, including fixes for Drill and Teradata. Construction-stage aliases used internally are normalized to the public `annotation_source` vocabulary: `glot`, `LLM-0shot`, `LLM-retry`, `LLM-rule`, and `human`.

The two CSV files summarize the existing model execution traces with these reference revisions applied:

- `full_1534_baseline_results.csv`: execution accuracy over all 1,534 intents per dialect.
- `clean_256_baseline_results.csv`: execution accuracy over the unchanged 256 clean-subset IDs.

Scores are percentages. `Avg.` is the unweighted mean across the 16 dialects, computed before rounding individual scores; `Avg. N` is the number of dialects. These inference-only baselines use their original evaluation protocol and should not be used as the matched base for the direct-SQL SFT experiment. The SFT package generates its own matched base predictions on the held-out 307 intents.

Druid question 520 uses the native-verified reference returning the original SQLite single-row answer (`Anna Pavleeva`, `gladiator`). Saved model prediction outputs were rescored against this reference; model predictions and aggregate correct counts are unchanged.

Question 694 uses the verified comment-author reference. Saved prediction outputs were rescored against that reference in all 16 dialects; the full baseline summaries include these updated outcomes. The unchanged Clean-256 selection does not contain this question.

Question 1021 now follows the updated official BIRD reference and returns `player_name, height`, in that order. Existing saved predictions were rescored using the original dialect-specific EX comparators and verified native reference values; see `gold_1021_revision.json` for evidence and score-count changes. Clean-256 does not contain this question and is unchanged.

Subsequent native execution verified the corrected question 1021 SQL in 13 dialects; Spark, StarRocks, and Teradata were not rerun. SQLite, DuckDB, and Oracle return `Kristof van Hout, 208.28`; the other verified environments return `Kristof van Hout, 208`. Scoring uses the reference value for each experiment's execution snapshot, without coercing fractional reference values to integers. In particular, historical ClickHouse main runs use 208.28 and SFT runs use 208. This verification adds execution evidence and does not change the published scores.
