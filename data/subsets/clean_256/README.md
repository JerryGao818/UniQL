# UniQL-Clean-256

This directory contains a 256-question clean-annotation subset for UniQL leaderboard evaluation.

The subset is selected in response to known annotation issues in the original BIRD development data. We use publicly released correction metadata and existing UniQL evaluation artifacts to identify original examples suitable for clean-subset reporting.

Files:

- `question_ids.txt`: selected original BIRD question IDs.
- `question_ids.json`: same IDs in JSON format.
- `queries/`: per-dialect query files filtered to the 256 retained questions.
- `subset_metadata.json`: machine-readable subset description.

Use the full files under `data/queries/` for the standard UniQL-1534 leaderboard, or these filtered files for the UniQL-Clean-256 leaderboard.
