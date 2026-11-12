# git-contributions

Python scripts measuring authors' contributions to a Git-controlled, multi-file LaTeX
project with long lines (one line = one paragraph), so plain `git blame` is not enough.

## Documents

All in `notes/`, in Org format, committed:

- `notes/spec.org` -- what the scripts do (measures, CLI, report contents).
- `notes/plan.org` -- how they are built (modules, algorithms).
- `notes/tasks.org` -- task list; mark tasks DONE as they land.
- `notes/backlog.org` -- ideas deliberately left out for now.

Keep these in step with the code: a change of behavior updates the spec in the same commit.
Private, uncommitted files (reviews, discussions, scratch) live in `mbork.local/`.

## Workflow

- This repo uses the `human-review` workflow and `/blind-review`.
- Work task by task (`notes/tasks.org`), committing as you go. After each task, run one full
  round of `/blind-review` over the task's commits and fix the findings at your discretion.
- Fold the fixes into the commits they belong to (fixup commits plus
  `git rebase --autosquash`), not as separate fix commits: a clear, linear history matters
  more than an accurate one. This is the one standing exception to the rule below, and it
  applies only to the current task's commits.
- No test suite. Check changes by running the scripts on the throwaway repo built by
  `make_test_repo.py` (committed).

## Commits

- Commit yourself with plain `git commit`; do **not** use the `/commit` skill here.
- Commits are atomic: if in doubt, split a change into more commits rather than fewer.
- **Never rewrite history** (amend, rebase, reset, force-push, filter-repo on this repo)
  unless explicitly asked, or folding review fixes as described above.

## Prose

User-facing prose (docs, `--help`, messages, report texts) is written by Claude in this repo,
in English -- an exception to the global `TRANSLATE` rule.
The one exception to the exception is `README.org`: Claude drafts it in Polish, leaves the
draft uncommitted, and commits it only after mbork has translated it.

## Hard rules for the scripts

- Never modify the measured repo. Anything that rewrites history works on a plain copy
  (not a clone, all remotes removed) in a suffixed sibling directory, kept and reused across
  runs.
- Python standard library only, plus the external `git` and `git-filter-repo` commands.
  No other dependencies without explicit approval.
- Only long CLI options, no positional arguments; `--help` or no arguments prints usage.
- Reports go to a file; stdout/stderr carry only progress, the output file name, timing and
  errors.
