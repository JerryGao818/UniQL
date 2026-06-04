# UniQL-Hard-256

This directory contains a harder 256-question subset for UniQL leaderboard evaluation.

It starts from the original-clean BIRD Mini-Dev subset identified via Arcwise/UIUC correction metadata, then removes the 37 questions with the highest aggregate correctness across saved UniQL model-dialect traces.

Files:

- `question_ids.txt`: retained original BIRD question IDs.
- `question_ids.json`: same IDs in JSON format.
- `queries/`: per-dialect query files filtered to the 256 retained questions.
- `subset_metadata.json`: machine-readable subset description.

Use the full files under `data/queries/` for the standard UniQL-1534 leaderboard, or these filtered files for the UniQL-Hard-256 leaderboard.
