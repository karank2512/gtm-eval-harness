# gtm-eval-harness

Does your LLM lead-qualification pipeline actually work?

PLG companies now run language models inside the funnel: qualifying signups,
scoring fit, routing leads to sales. Almost nobody measures whether those
calls are right. This harness does, the way you'd test a drug: a treatment
arm, a placebo arm, denominators on every number, and negative results
reported as findings.

There are two grading modes. They are kept separate on purpose.

| | v1 legacy grading | v2 world-state grading |
|---|---|---|
| what is graded | the qualifier's parsed answer | the effect in a simulated CRM: tier on the lead record, queue membership, dispatch receipt |
| evidence | the runner's own results log | a persisted CRM world database, read offline |
| unparseable answers | counted separately | failures inside every denominator |
| planned in advance | no | preregistration, checked before any model call |
| entry points | `run_eval.py`, `scripts/report.py` | `run_world_eval.py`, `scripts/grade_world.py`, `scripts/world_report.py` |
| status in this repo | real measured run (`REPORT.md`) | harness built and tested; registered real run not yet executed |

## What it measures

Given a lead-qualification prompt (yours, or the included example) and a set
of labeled leads, the harness reports:

- **Tier and routing accuracy** by true segment, with `correct/n` on every
  line - no bare percentages.
- **Confusion pairs**, most frequent first - e.g. enterprises misrouted as
  personal developers, buying-intent teams marked low-fit.
- **Clean vs tricky gap** - the dataset includes leads designed to fool a
  qualifier (an enterprise employee's personal project; an enterprise with
  tiny usage mid-evaluation; a heavy team that isn't enterprise).
- **Calibration** - ECE and Brier score of the model's own confidence vs how
  often it's right.
- **Run-to-run stability** - how often re-running the same lead flips the
  call, and the accuracy spread across runs.
- **Parse failures** as a first-class metric, not silently dropped rows.

Three arms, run side by side:

| arm | what it is | what it tells you |
|---|---|---|
| `treatment` | your qualification prompt on the real leads | the number you care about |
| `placebo` | same prompts, each lead's signals swapped with another lead's | if accuracy survives this, the measurement is broken, not the model |
| `baseline` | deterministic rules, no model | what you already get for free |

## v2: world-state grading

In v1 the qualifier returns a tier, a route and a confidence, and the
harness grades that answer. Nothing checks that the decision was ever
applied. v2 adds the missing step:

1. **A simulated CRM world** (`harness/world.py`, stdlib SQLite) owned by
   the evaluator. One isolated world per arm x run, seeded with that run's
   lead roster just before it starts - every lead unqualified, in the
   `unrouted` queue.
2. **The runner applies each accepted decision through a narrow API**:
   assign the tier, move the lead into the route's queue, record a
   dispatch event with a receipt - one transaction, all or nothing. An
   unparseable answer is recorded as a rejection and leaves the lead
   unqualified and unrouted.
3. **An offline grader** (`scripts/grade_world.py`) reads the persisted
   world, the dataset's own labels and a sealed plan of every expected
   trial. A lead-run is correct only if the world shows it: right tier on
   the lead record, lead in the right queue, and a dispatch receipt that
   agrees. A decision that was claimed but dropped, applied to the wrong
   queue, or never written is a failure, whatever the model's JSON said.

What the grader does **not** use to decide correctness: the model's
answer, its `reason` text, or any correctness or label field in the
runner's log. The one thing taken from the log is the model's
self-reported confidence, for calibration - reported as a self-report and
kept apart from effect evidence.

The runner never holds the labels either: it works from a model-facing
view of the dataset (id, company, contact, signals) and the model itself
runs tool-free and stateless, from an empty scratch directory, so it
cannot read the labels, the plan or the database.

Before scoring, the grader checks, and refuses to score (exit 2) on any
failure:

- the run completed: a manifest exists, there is no `ABORTED.json`, and
  the plan, receipt, world database and decisions log match their sealed
  sha256;
- the dataset file is the one the run was planned on (sha256), and the
  sealed plan is exactly what that dataset and design regenerate;
- trial inventory: exact count, no missing, duplicate, extra or unknown
  trial or lead ids, in the world and in the log;
- arm/run isolation: one world per planned arm x run, no event that
  references another arm's or run's trial;
- no invalid tier or route values, every lead in exactly one queue;
- the event receipt chain recomputes.

A run directory is never overwritten. An aborted run stays at
`<run-dir>.partial` with an `ABORTED.json` and no manifest, so it cannot
be graded or mistaken for a completed run.

### What these guarantees are, and are not

- The CRM is a **local simulator that the harness itself owns**. It is
  not a production CRM and not an independent security boundary. The
  separation that means something is between the harness and the
  tool-free model under test.
- The hashes, receipts and read-only file modes are **consistency
  checks**. They catch partial runs, mismatched files and careless edits.
  They are not tamperproof: whoever controls the files can rewrite them
  and recompute every hash.
- The simulator applies accepted decisions faithfully, so world-state
  grading guards the *measurement path* - dropped, misapplied or
  misreported decisions. It does not make the dataset harder or its
  labels more realistic.

## Preregistration (v2)

The v2 real run is preregistered in
[`docs/preregistrations/gtm-v2-20261114.md`](docs/preregistrations/gtm-v2-20261114.md),
with a generated machine-readable manifest next to it. Fixed in advance:
arms, model (`claude-fable-5-2`, tool-free), dataset and its hash, seed,
3 runs, 360 lead-runs per arm over 120 independent leads, 720 model
calls, 1080 decisions, the expected trial inventory, the metrics and
their denominators, per-lead paired comparisons, descriptive criteria,
and the stopping rule (abort on the first CLI failure, no retries, no
optional stopping).

Read its first section before quoting it: **v1 was seen before the
preregistration was written.** v2 is an engineering replication on the
same public synthetic dataset, not held-out confirmatory evidence. The
analysis is descriptive: no significance tests, no p-values, no
superiority claims.

The runner enforces commit-before-run. It refuses to make a single model
call unless the manifest regenerates byte-identically from the working
tree (dataset, source, prompt, scorer, configuration and plan hashes) and
the manifest, the document, the dataset and every pinned source file are
committed and unmodified. The run receipt records the commit and the
hashes of the committed manifest and document.

## Running the registered v2 run

> **Do not run step 2 unless the preregistration and code are committed
> and unmodified.** Step 1 tells you. If it refuses, do not work around
> it: commit first, or - if a pinned input really has to change - the
> preregistration is void for the changed code and needs a new id.
> Publishing (pushing) the commit before the run is what gives the
> ordering an outside witness; the harness cannot check that for you.

```sh
# 1. preregistration gate (no model calls): committed, unmodified, hashes match
python3 scripts/prereg.py verify

# 2. the registered run: 720 model calls via the Claude Code CLI (subscription).
#    Re-runs the same gate first. Writes results/v2/gtm-v2-20261114/attempt-01/.
#    Add --command /path/to/claude if the CLI is not `claude` on PATH.
python3 run_world_eval.py --prereg docs/preregistrations/gtm-v2-20261114.manifest.json

# 3. offline world-state grade (no model calls); exits 2 instead of scoring
#    if any integrity check fails
python3 scripts/grade_world.py --run-dir results/v2/gtm-v2-20261114/attempt-01 \
    --out results/v2/gtm-v2-20261114/attempt-01/grade.json

# 4. report, regenerated from the world (re-grades; never trusts grade.json)
python3 scripts/world_report.py --run-dir results/v2/gtm-v2-20261114/attempt-01 \
    --out REPORT-v2.md
```

Optional, before step 2: the registered 12-lead smoke run (24 model
calls, same gates, written to `results/v2/gtm-v2-20261114/smoke-01/`).
Its numbers are outside the primary counts and are never pooled.

```sh
python3 run_world_eval.py --prereg docs/preregistrations/gtm-v2-20261114.manifest.json --smoke
```

If an attempt aborts on a CLI failure, its `attempt-NN.partial`
directory is kept and the next invocation starts `attempt-NN+1` from
scratch, listing the earlier attempt in its receipt. The first complete
attempt is final; the runner refuses another.

Other world-mode runs:

```sh
# mock backend: deterministic test double, NOT a model, no model calls
python3 run_world_eval.py --backend mock --run-dir /tmp/world-mock
python3 scripts/world_report.py --run-dir /tmp/world-mock --out /tmp/WORLD-MOCK.md

# your own data or model, explicitly not preregistered
python3 run_world_eval.py --backend claude-code --exploratory-unregistered \
    --model <model> --data <your-leads.jsonl> --run-dir <new-dir>
```

## v1 legacy mode

Kept unchanged in behavior so the published v1 numbers stay reproducible.
Reports from this mode are labeled `v1 legacy grading` and say plainly
that there is no world-state evidence behind them.

```sh
# 1. generate the example dataset (synthetic PLG leads, seeded)
python3 scripts/generate_leads.py --n 120 --out data/leads.jsonl

# 2. run the eval through Claude Code (subscription - no API key, no usage billing)
python3 run_eval.py --backend claude-code --runs 3 --out results/results.jsonl

# 3. regenerate REPORT.md from the results (all figures recomputed)
python3 scripts/report.py --results results/results.jsonl --out REPORT.md
```

A v1 smoke run is cheap and catches prompt/parse problems:

```sh
python3 run_eval.py --backend claude-code --runs 1 --limit 12 \
    --out results/smoke.jsonl
```

## Execution method and cost

Real runs call `claude -p` (the Claude Code CLI) once per lead per arm per
run, so they execute on the machine's Claude subscription. **No API key is
used and no usage billing is involved.** The model is pinned explicitly
(`--model claude-fable-5-2`). Two flags are baked into the backend as
defaults: `--tools ''` (tool use disabled - every call is a stateless
prompt-to-JSON completion) and `--no-session-persistence`. The runner is
fail-fast: a CLI failure (signed out, timeout, nonzero exit, or an
`is_error` envelope) aborts the run on the FIRST failure with no retries,
partial output is preserved (`<out>.partial` in v1, `<run-dir>.partial`
in v2), and any previous complete output is left untouched - so a broken
setup can never masquerade as a completed run. Unparseable model answers
are recorded and counted, never aborts.
With the default dataset: 120 leads x 3 arms x 3 runs = 1080 decisions, of
which 720 hit the model (the baseline arm is deterministic).

## The example dataset

`data/leads.jsonl` is fully synthetic (seeded generator, no real company
data) and shaped like a PLG free-to-paid motion: personal developers, teams,
and enterprises, with the signals a qualifier would actually see - seats,
devices, features used, pricing questions, domain claims. ~25% of leads are
deliberately tricky, with the label reasoning documented in each record.
Point the harness at your own labeled leads by writing the same JSONL schema.

## Honesty rules this repo follows

- Every number in a report is recomputed from data by a script. Nothing is
  typed by hand, and CI regenerates every tracked report from its tracked
  data and fails on any difference (`python3 scripts/check_freshness.py`).
- Report dates come from the run's own metadata, not the wall clock, so a
  report regenerates to the same bytes on any day. The v1 run predates
  that field; its report says the date was not recorded rather than
  inventing one.
- The placebo arm ships on by default; a harness that can't fail isn't a
  measurement.
- The `mock` backend is a deterministic test double for CI. Its numbers check
  harness math only and are labeled as such wherever they appear. They are
  not model results.
- v1 data is never presented as having world-state evidence, and v2 was
  not preregistered blind: both are stated where the numbers are.

## Development

```sh
python3 -m unittest discover -s tests -v   # unit + integration, no model calls
python3 scripts/check_freshness.py         # tracked reports match their data
python3 scripts/prereg.py check            # manifest matches the working tree
```

Python 3.10+, standard library only. Tests cover the CRM write API, the
runner's failure handling, and the grader under mutation: a CRM that
drops dispatches or uses the wrong queue, logs edited to claim success,
labels planted where the runner could see them, missing/duplicate/extra
rows, cross-arm references, corrupt or partial artifacts, and the
preregistration gates in throwaway git repositories. A fake CLI script
stands in for `claude` where the real-backend code path is exercised.

Tracked reports are only ever regenerated, never edited:

```sh
# v1 legacy reports, from the retained results files
python3 scripts/report.py --results results/results.jsonl --out REPORT.md
python3 scripts/report.py --results results/example-mock.jsonl \
    --out results/EXAMPLE-REPORT-mock.md

# v2 MOCK example: offline grade and report from its sealed world
M=docs/preregistrations/gtm-v2-20261114.manifest.json
python3 scripts/grade_world.py --run-dir results/v2-mock-example \
    --criteria-demo $M --out results/v2-mock-example/grade.json
python3 scripts/world_report.py --run-dir results/v2-mock-example \
    --criteria-demo $M --out results/v2-mock-example/REPORT-MOCK.md
```

(The mock run directory itself was produced once with
`python3 run_world_eval.py --backend mock --run-dir results/v2-mock-example`;
a run directory is never overwritten, so recreating it means removing the
old one first.)

Changing any pinned source file before the registered run makes
`scripts/prereg.py check` (and CI) fail until the manifest is rebuilt with
`python3 scripts/prereg.py build` and recommitted - by design. After the
registered run is recorded, CI stops comparing the pins with the source
and re-grades the recorded run instead.

## Status of the numbers in this repo

`REPORT.md` and `results/results.jsonl` are a real measured run under
**v1 legacy grading**: 120 synthetic leads x 3 repeats x 3 arms through
Claude (model pinned in the report), executed via the local Claude Code
CLI on a subscription - no API spend. Headline: tier calls land at 99.2%
(357/360 lead-runs) with zero flips across repeats, but routing (89.2%,
321/360) beats the deterministic rules baseline (87.5%, 315/360) by only
6 lead-runs, and every routing miss over-routes the lead toward sales.
Confidence is underconfident on this set (mean 0.85 vs 99.2% actual, ECE
0.137). The placebo arm sits at 27.5%, near chance, so the measurement
responds to the inputs. Those figures grade the model's answers from the
results log; no CRM effect was recorded for that run.

Read the Limits section of the report before reusing any number: 120 leads
with 3 repeats are 360 rows but only 120 independent cases, the labels are
hand-designed, and the dataset is synthetic.

**No v2 real result exists yet.** Two mock artifacts are tracked to show
report formats and to keep the freshness check honest; both are labeled
MOCK and neither is a model result:

- `results/EXAMPLE-REPORT-mock.md` - v1 legacy format, from
  `results/example-mock.jsonl`.
- `results/v2-mock-example/` - a complete v2 run directory from the mock
  backend (plan, receipt, world database, decisions log, manifest), its
  offline grade and `REPORT-MOCK.md`. It has the registered design's
  shape (1080 decisions) and applies the preregistered criteria as a
  labeled format demonstration.
