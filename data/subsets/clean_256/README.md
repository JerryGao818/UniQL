# UniQL-Clean-256

This directory contains a 256-question clean-annotation subset for UniQL leaderboard evaluation.

The subset is selected in response to known annotation issues in the original BIRD development data. We use publicly released correction metadata and existing UniQL evaluation artifacts to identify original examples suitable for clean-subset reporting.

The full UniQL-1534 benchmark remains the primary evaluation track. UniQL-Clean-256 is a supplementary track for users
who want to report results on a smaller set of cleaner original annotations.

Files:

- `question_ids.txt`: selected original BIRD question IDs.
- `question_ids.json`: same IDs in JSON format.
- `queries/`: per-dialect query files filtered to the 256 retained questions.
- `subset_metadata.json`: machine-readable subset description.

Use the full files under `data/queries/` for the standard UniQL-1534 leaderboard, or these filtered files for the UniQL-Clean-256 leaderboard.

## Background

Recent work has documented annotation noise in BIRD-style text-to-SQL data and motivated reporting on verified or cleaner
subsets in addition to full benchmark results:

- Zhu Y, Jin T, Choi Y, et al. ReViSQL: Achieving Human-Level Text-to-SQL[J]. arXiv preprint arXiv:2603.20004, 2026.
- Wretblad N, Riseby F, Biswas R, et al. Understanding the effects of noise in text-to-sql: An examination of the bird-bench benchmark[C]//Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (Volume 2: Short Papers). 2024: 356-369.
