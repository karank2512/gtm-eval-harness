# gtm-eval-harness

Does your LLM lead-qualification pipeline actually work?

PLG companies now run language models inside the funnel: qualifying signups,
scoring fit, routing leads to sales. Almost nobody measures whether those
calls are right. This harness does, the way you'd test a drug: a treatment
arm, a placebo arm, denominators on every number, and negative results
reported as findings.

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

## Quickstart

No dependencies beyond Python 3.10+ and, for real runs, an authenticated
Claude Code CLI.

```sh
# 1. generate the example dataset (synthetic PLG leads, seeded)
python3 scripts/generate_leads.py --n 120 --out data/leads.jsonl

# 2. run the eval through Claude Code (subscription - no API key, no usage billing)
python3 run_eval.py --backend claude-code --runs 3 --out results/results.jsonl

# 3. regenerate REPORT.md from the results (all figures recomputed)
python3 scripts/report.py --results results/results.jsonl --out REPORT.md
```

A smoke run first is cheap and catches prompt/parse problems:

```sh
python3 run_eval.py --backend claude-code --runs 1 --limit 12 \
    --out results/smoke.jsonl
```

## Execution method and cost

Real runs call `claude -p` (the Claude Code CLI) once per lead per arm per
run, so they execute on the machine's Claude subscription. **No API key is
used and no usage billing is involved.** The published run pinned the model
explicitly (`--model claude-fable-5-2`). Two flags are baked into the
backend as defaults so a fresh checkout reproduces published numbers
exactly: `--tools ''` (tool use disabled - every call is a stateless
prompt-to-JSON completion) and `--no-session-persistence`. The runner is
fail-fast: a CLI failure (signed out, timeout, nonzero exit, or an
`is_error` envelope) aborts the run on the FIRST failure with no retries,
the partial output is preserved at `<out>.partial`, and any previous
complete results file is left untouched - so a broken setup can never
masquerade as a completed run. Unparseable model answers are recorded as
metric rows, never aborts. Pass any extra flags your CLI setup needs via
`--extra-args`.
With the default dataset: 120 leads x 3 arms x 3 runs = 1080 calls, of
which 720 hit the model (the baseline arm is deterministic). Use `--limit`
and `--runs` to size a run to your session.

## The example dataset

`data/leads.jsonl` is fully synthetic (seeded generator, no real company
data) and shaped like a PLG free-to-paid motion: personal developers, teams,
and enterprises, with the signals a qualifier would actually see - seats,
devices, features used, pricing questions, domain claims. ~25% of leads are
deliberately tricky, with the label reasoning documented in each record.
Point the harness at your own labeled leads by writing the same JSONL schema.

## Honesty rules this repo follows

- Every number in REPORT.md is recomputed from results JSONL by
  `scripts/report.py`. Nothing is typed by hand.
- The placebo arm ships on by default; a harness that can't fail isn't a
  measurement.
- The `mock` backend is a deterministic test double for CI. Its numbers check
  harness math only and are labeled as such wherever they appear. They are
  not model results.

## Development

```sh
python3 -m unittest discover -s tests -v
```

## Status of the numbers in this repo

`REPORT.md` and `results/results.jsonl` are a real measured run: 120
synthetic leads x 3 repeats x 3 arms through Claude (model pinned in the
report), executed via the local Claude Code CLI on a subscription - no API
spend. Headline: tier calls land at 99.2% (357/360 lead-runs) with zero
flips across repeats, but routing (89.2%, 321/360) beats the deterministic
rules baseline (87.5%, 315/360) by only 6 lead-runs, and every routing miss
over-routes the lead toward sales. Confidence is underconfident on this set
(mean 0.85 vs 99.2% actual, ECE 0.137). The placebo arm sits at 27.5%,
near chance, so the measurement responds to the inputs.

Read the Limits section of the report before reusing any number: 120 leads
with 3 repeats are 360 rows but only 120 independent cases, the labels are
hand-designed, and the dataset is synthetic. `results/EXAMPLE-REPORT-mock.md`
is a mock-backend run kept only to show the report format; it is labeled as
such and is not a model result.
