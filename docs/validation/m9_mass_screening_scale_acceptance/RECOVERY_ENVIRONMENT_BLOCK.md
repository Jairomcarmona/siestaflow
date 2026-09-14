# M9 Recovery Environment Block

The recovery acceptance uses 500 candidates with two real canonical DAG nodes
per candidate: `EVAL_i → SCORE_i`. The deterministic first-invocation failure
set is `i % 20 == 7` (25 EVAL nodes).

Observed canonical behavior before the environment block:

- 950 unaffected task nodes completed during the first invocation.
- The 25 selected EVAL nodes failed technically and their SCORE descendants
  blocked; unrelated branches continued.
- The next invocation reused completed work and retried failed/blocked work.
- Original attempt directories remained immutable.

Native Windows then raised `PermissionError [WinError 5]` while
`RealFileSystem.atomic_write_json` replaced the canonical
`state/workflow_runtime.json`. In the fresh clean-equivalent comparison the
persisted affected tasks were:

- `EVAL-candidate-0484`: `INCOMPLETE`, attempt 1.
- `SCORE-candidate-0445`: `INCOMPLETE`, attempt 1.
- `SCORE-candidate-0484`: `PENDING` because its EVAL parent was incomplete.

Both errors name temporary state files in the external, untracked M9
workspace. No candidate scientific result, capability parser, artifact
identity, source file, or test expectation was changed to conceal this
condition. The clean-equivalent summary hash cannot be certified from this
run, so it is deliberately omitted from the authoritative corrected result.
