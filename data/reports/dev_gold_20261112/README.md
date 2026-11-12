# Dev reference repair — November 12, 2026

Oracle's 1,534 public gold queries now use the exact quoted table and column names in the updated schema. All 1,534 pass native Oracle reference validation (1,521 directly and 13 with reviewed tie-equivalence evidence). This includes questions 514, 1123, 1125 and 1263, previously failing with `ORA-01791`.

After normalizing identifier case and quoting, 1,301 Oracle SQL ASTs retain the previous query shape. The remaining changes include Oracle syntax/type compatibility and audited reference repairs; changing all 1,534 SQL strings does not mean discarding all previous query logic.

The original UniQL question IDs, questions, evidence and difficulty fields are retained. We adopt 26 individually reviewed reference repairs after checking the latest official BIRD dev SQL and available correction material. We do not replace the original tasks with the broader wording/output revisions in newer BIRD releases. The audit does not claim to resolve every BIRD annotation issue.

| Published dialect | Native validation | Target SQL changed |
| --- | --- | --- |
| Oracle | 1,534 / 1,534 | 1,534, primarily identifier binding |
| DuckDB | 26 / 26 | 25 |
| PostgreSQL | 26 / 26 | 21 |
| MySQL | 26 / 26 | 23 |
| SQLite | Reference execution for the repaired queries | 26 |

The other 11 target dialects retain their original published files while their scoped candidates await native validation. Correct existing translations are preserved. The preliminary whole-release drafts are excluded from this release.

Clean-256 retains its 256 IDs. Oracle's full subset is rebound, and the verified dialects' subset files are filtered from their corresponding full files. The subset contains repaired questions 484, 988 and 1135.

## Evidence and comparison

- `reference_repairs.json`: previous/accepted SQLite SQL, original intent, review rationale and source references for each of the 26 repairs.
- `native_validation.json`: per-question SQL hashes, native evidence hashes, comparison outcomes and supplemental semantic proofs.
- `summary.json`: source database hashes, release file hashes, validation counts and pending dialects.

The 11 Oracle databases comprise 75 tables and 3,932,735 rows. Migration uses full typed multiset fingerprints, including NULLs and duplicate multiplicity. Oracle full-strict data verification and the final SQL validation are recorded separately; unchanged successful query evidence can be inherited only with equal Oracle SQL bytes and equivalent normalized SQLite AST. Each inherited evidence file is checked by SHA-256.

Validation uses project EX (`oracle-ex-bag-finite-float-v1`), preserving exact integer/text/binary/NULL identity and applying finite float tolerance (`abs_tol=1e-8`, `rel_tol=1e-9`). Ordered differences require SQL review and evidence for the full eligible multiset, exact source sorting keys and Top-K boundary. Question 1209 orders diagnosis representatives by earliest eligible Birthday; its reference ID tie-breaker only makes equal birthdays deterministic and is not part of the requested order.

RF comparisons follow the reviewed official policy: remove `<` and `>` and compare the boundary number. Censored observations do not establish the actual measurement. U-PRO uses the official SQLite numeric-prefix conversion (`+1(30)` → 1, `+2(100)` → 2). These are explicit benchmark policies, not clinical interpretations.

This validation used no new model calls. Historical prediction outputs and baseline CSV scores have not been rerun or rescored; these results are reference checks, not model leaderboard scores.

## Oracle migration and evaluation

The new schema/gold requires migration with `migration/oracle/insert_to_oracle.py`. The loader rejects CDB root/seed connections, creates ordinary PDB users without `_ORACLE_SCRIPT`, verifies the source database hashes and checks full target content. Existing benchmark users are replaced only when `--recreate` is explicitly supplied.

Configure credentials locally through environment variables; use a writable PDB service such as `localhost:1521/FREEPDB1`:

```bash
export UNIQL_ORACLE_DSN=localhost:1521/FREEPDB1
export UNIQL_ORACLE_ADMIN_USER=SYSTEM
# Set UNIQL_ORACLE_ADMIN_PASSWORD and UNIQL_ORACLE_USER_PASSWORD locally.
python migration/oracle/insert_to_oracle.py --root /path/to/dev_databases
python evaluation/evaluate.py \
  --predicted_sql_path /path/to/oracle_predictions.json \
  --dialect oracle --model your_model \
  --output_dir evaluation_results --num_cpus 1
```

The evaluator executes SQL without uppercasing literals, preserves Decimal and LOB values, compares empty-result column widths and returns structured errors. Two failed queries cannot be graded as a match. Native timeouts/cancellation and session cleanup are handled within the Oracle adapter. Its regression suite passes 66 tests. Serial Oracle Free evaluation was used here; reliable four-worker evaluation has not been established.
