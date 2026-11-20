# Leaderboard data

The website defaults to the overall view and also provides a view for each of the 16 dialects, for both UniQL-1534 and UniQL-Clean-256. Dialect rankings use that dialect's EX. Overall rankings require results for all 16 dialects.

Each dialect has one table containing the paper baselines and submitted systems, sorted by that dialect's EX. The submission date appears beneath a submitted system's name. Paper baselines have no date or description beneath their names. There is no separate submission-date column.

The 13 UniQL-1534 baseline rows reproduce Table 2 of the [OpenReview paper](https://openreview.net/pdf?id=pEJoB0CyX3), including its printed averages. The paper does not report Clean-256 results; that track retains its existing baseline CSV.

Systems may use target-database error messages to retry SQL during inference. Gold SQL, gold results, and evaluator correctness feedback must not be used to generate or repair predictions. Record the inference setup and gold/evaluator commits with each submission.

Add submitted results to `assets/data/dialect_submissions.js`, one record per model/system, track and dialect. `correct` and `total` determine EX; `total` must cover all 1,534 or 256 questions in the selected track. API failures remain in the denominator. Missing dialect scores are never inferred from another dialect or entered as zero.

Required fields are `model`, `track`, `dialect`, `reference_version`, `gold_commit`, `evaluator_commit`, `correct`, `total`, `submitted_date`, and `gold_correctness_feedback: false`. Version metadata records which release was used for evaluation. `model_url` links the model/system name directly to its project page. Optional fields include `inference_setup`, `source_url`, `results_url`, and per-difficulty counts.

The latest submission is displayed when the same model/system has multiple runs for the same track and dialect. Equal EX scores share a rank. A single-dialect submission appears only in that dialect's table and does not receive an overall rank.

The accepted schemagate + Gemini 3.8 Flash Oracle run scores 996/1,534 (64.93%), including Oracle error feedback repair. Its predictions, logs and verdicts were checked against the original GitHub Actions artifact. The model name links to the schemagate project. The reported 63.69% excludes recorded execution-error repairs but includes generation re-prompts, so it is not presented as a separate single-generation result.

The baseline CSV files and their embedded fallbacks in `assets/js/site.js` must stay synchronized when baseline data is updated. New dialect submissions have one data source, `assets/data/dialect_submissions.js`, loaded by the page before `site.js`; it also works when opening the page locally without a server.
