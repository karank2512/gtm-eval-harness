# GTM lead-qualification eval - v2 world-state report

Generated from a sealed v2 run completed 2026-11-14T06:26:06Z (world database sha256 `c810ca8431754123`). Every number below is recomputed offline by `scripts/world_report.py` from the CRM world database, the dataset's own labels and the sealed trial plan; none are typed by hand. The date is the run's recorded completion time, not the day this file was rendered.

## What is graded here

- **Effects, not answers.** A lead-run is correct only if the simulated CRM shows it: the lead record carries the true tier, the lead is a member of the true route's queue, and a dispatch event with a valid receipt agrees with that state. The model's JSON, its `reason` text and the runner's log are not evidence of correctness.
- **Failures stay in the denominator.** Unparseable answers, dropped dispatches and inconsistent effects count as wrong; every accuracy below is over all planned lead-runs.
- **Confidence is a self-report.** Calibration compares the confidence the qualifier stated (taken from the decisions log) with what the world shows. It is the one figure here that rests on the log, and it is secondary.
- **Boundary.** The CRM is a local simulator owned by this harness, not a production CRM and not an independent security boundary. The separation that matters is from the model under test, which runs tool-free and never sees the labels, the plan or the database. The hashes below are consistency links; they are not tamperproof against whoever owns the files.

## Setup

- backend: `claude-code` (model requested: `claude-fable-5-2`)
- runtime: local Claude Code CLI on a Claude subscription - no API key, no usage billing; tool use disabled (`--tools ''`), no session persistence, each call started from an empty scratch directory outside the repository, so each call is a stateless prompt-to-JSON completion
- model identifiers reported back by the CLI (recorded, not enforced): `claude-fable-5-2`
- fail-fast: the run aborts on the first CLI failure, no retries; an aborted run has no manifest and cannot be graded
- leads: 120 independent cases (synthetic, seed 20261114)
- runs per arm: 3 -> 360 lead-runs per arm
- arms: treatment, placebo, baseline
- decisions: 1080 planned, of which 720 are model calls (the baseline arm is deterministic rules)
- dataset sha256: `3b40af0733f0b768c04695d60726c295c7e536a320ea69aebd993b49e5b72277`
- trial plan sha256: `e80e33f831fe865a4468980d41937e9b74110f690e45869290c1ecd4d69ae482`

## Preregistration

- id: `gtm-v2-20261114` (docs/preregistrations/gtm-v2-20261114.md)
- verified before the first model call at git commit `d8d0d9d3404d0a70a6b256f51e91da29b8dbe9d1` (commit time 2026-11-14T05:46:00Z); run started 2026-11-14T05:46:24Z
- manifest sha256 `bee5c5daac153e4bb84e9d3aad1d557bd019b2db049596f6aa6d739c3271e1c8`, document sha256 `128ef27846b38210d7685106e38fadfd8728db3e8cd2018c580e953c1f838212`
- attempt 1; earlier attempts on disk when this one started: none
- This is not held-out confirmatory evidence: the v1 run on the same public synthetic dataset was seen before the preregistration was written. v2 is an engineering replication under stricter grading.

## Integrity checks

All of the following passed; the grader refuses to produce a score otherwise.

- sealed artifacts: manifest complete and self-consistent; plan, receipt, world database and decisions log match their sealed sha256
- dataset and plan: dataset sha256 matches; plan regenerated from dataset + design is identical (1080 trial identities)
- preregistration binding: receipt names the preregistration manifest by sha256 and git commit; the manifest given matches and pins this dataset and plan
- world metadata: sealed; bound to this plan, dataset and run receipt
- arm/run worlds: 9 isolated worlds, one per planned arm x run, all closed
- lead inventory: 120 planned leads in each world; no missing, duplicate, extra or unknown ids (1080 lead records)
- queue membership: every lead record is in exactly one known queue; no invalid routes
- event receipts: 1080 events; receipt chain recomputed; at most one event per trial; no cross-arm/run references
- decisions log inventory: 1080 rows, exactly one per planned trial (used for self-reported confidence only)

## Primary outcomes: effect accuracy

| arm | tier effect | route effect | both | delivered | rejected (unparseable) | no effect | inconsistent |
|---|---|---|---|---|---|---|---|
| treatment | 360/360 (100.0%) | 308/360 (85.6%) | 308/360 (85.6%) | 360 | 0 | 0 | 0 |
| placebo | 99/360 (27.5%) | 89/360 (24.7%) | 75/360 (20.8%) | 360 | 0 | 0 | 0 |
| baseline | 321/360 (89.2%) | 315/360 (87.5%) | 315/360 (87.5%) | 360 | 0 | 0 | 0 |

Denominators are all 360 planned lead-runs per arm: 120 leads x 3 runs. They are lead-runs, not 360 independent cases.

## Planned comparisons (paired per lead)

| comparison | effect | leads where first arm is better | worse | tied | mean per-lead difference (points) | lead-run delta |
|---|---|---|---|---|---|---|
| treatment vs baseline | tier | 13/120 | 0/120 | 107/120 | +10.8 | +39 (360 vs 321 of 360) |
| treatment vs baseline | route | 6/120 | 9/120 | 105/120 | -1.9 | -7 (308 vs 315 of 360) |
| treatment vs placebo | tier | 87/120 | 0/120 | 33/120 | +72.5 | +261 (360 vs 99 of 360) |
| treatment vs placebo | route | 78/120 | 3/120 | 39/120 | +60.8 | +219 (308 vs 89 of 360) |

Each lead's share of correct runs in the first arm minus its share in the second; the unit is the lead. Descriptive only: no significance test, no p-value, no superiority claim.

## Prespecified criteria

Source: preregistration `gtm-v2-20261114`. Criteria fixed in the preregistration before the run; descriptive thresholds, not significance tests.

### H1: Placebo control (validity gate) - MET

- tier effect accuracy, placebo <= 0.50: observed 99/360 - met
- tier effect accuracy diff, treatment vs placebo >= 0.25: observed 360/360 vs 99/360 (+72.5 points) - met
- reading fixed in advance: The measurement responds to the leads' own signals; the treatment figures are interpretable.

### H2: Tier effect near ceiling and above rules (v1 replication) - MET

- tier effect accuracy, treatment >= 0.95: observed 360/360 - met
- tier effect accuracy diff, treatment vs baseline > 0: observed 360/360 vs 321/360 (+10.8 points) - met
- reading fixed in advance: Replicates v1 under world-state grading: tier effects are near ceiling on this dataset and above the rules baseline.

### H3: No practically meaningful routing advantage over rules (v1 replication) - MET

- abs route effect accuracy diff, treatment vs baseline <= 0.05: observed 308/360 vs 315/360 (+1.9 points) - met
- reading fixed in advance: Replicates v1: the model's routing effect is within 5 points of the free rules baseline on this dataset.

### H4: Every planned decision is delivered - MET

- undelivered trials == 0: observed 0 of 1080 planned - met
- reading fixed in advance: Every planned decision produced a consistent CRM effect (tier, queue and dispatch receipt).

## Arm: treatment

- planned lead-runs: 360 (120 leads); delivered with a consistent effect: 360; rejected as unparseable: 0; no effect recorded: 0; inconsistent: 0

### Tier effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 87/87 | 100.0% |
| personal_dev | 111/111 | 100.0% |
| team | 162/162 | 100.0% |
| **all** | 360/360 | 100.0% |

### Route effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 87/87 | 100.0% |
| sales_assist | 110/153 | 71.9% |
| self_serve | 111/120 | 92.5% |
| **all** | 308/360 | 85.6% |

Clean vs tricky (tier effect): clean 264/264 (100.0%), tricky 96/96 (100.0%).

### Tier in the CRM vs true tier, most frequent first

| true | in CRM | n |
|---|---|---|
| team | team | 162 |
| personal_dev | personal_dev | 111 |
| enterprise | enterprise | 87 |

### Queue in the CRM vs true route, most frequent first

| true | in CRM | n |
|---|---|---|
| self_serve | self_serve | 111 |
| sales_assist | sales_assist | 110 |
| sales | sales | 87 |
| sales_assist | sales | 43 |
| self_serve | sales_assist | 9 |

## Arm: placebo

- planned lead-runs: 360 (120 leads); delivered with a consistent effect: 360; rejected as unparseable: 0; no effect recorded: 0; inconsistent: 0

### Tier effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 9/87 | 10.3% |
| personal_dev | 30/111 | 27.0% |
| team | 60/162 | 37.0% |
| **all** | 99/360 | 27.5% |

### Route effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 23/87 | 26.4% |
| sales_assist | 36/153 | 23.5% |
| self_serve | 30/120 | 25.0% |
| **all** | 89/360 | 24.7% |

Clean vs tricky (tier effect): clean 84/264 (31.8%), tricky 15/96 (15.6%).

### Tier in the CRM vs true tier, most frequent first

| true | in CRM | n |
|---|---|---|
| team | personal_dev | 60 |
| team | team | 60 |
| enterprise | team | 57 |
| personal_dev | team | 45 |
| team | enterprise | 42 |
| personal_dev | enterprise | 36 |
| personal_dev | personal_dev | 30 |
| enterprise | personal_dev | 21 |
| enterprise | enterprise | 9 |

### Queue in the CRM vs true route, most frequent first

| true | in CRM | n |
|---|---|---|
| sales_assist | self_serve | 60 |
| sales_assist | sales | 57 |
| self_serve | sales | 51 |
| sales | sales_assist | 43 |
| self_serve | sales_assist | 39 |
| sales_assist | sales_assist | 36 |
| self_serve | self_serve | 30 |
| sales | sales | 23 |
| sales | self_serve | 21 |

## Arm: baseline

- planned lead-runs: 360 (120 leads); delivered with a consistent effect: 360; rejected as unparseable: 0; no effect recorded: 0; inconsistent: 0

### Tier effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 87/87 | 100.0% |
| personal_dev | 111/111 | 100.0% |
| team | 123/162 | 75.9% |
| **all** | 321/360 | 89.2% |

### Route effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 87/87 | 100.0% |
| sales_assist | 117/153 | 76.5% |
| self_serve | 111/120 | 92.5% |
| **all** | 315/360 | 87.5% |

Clean vs tricky (tier effect): clean 240/264 (90.9%), tricky 81/96 (84.4%).

### Tier in the CRM vs true tier, most frequent first

| true | in CRM | n |
|---|---|---|
| team | team | 123 |
| personal_dev | personal_dev | 111 |
| enterprise | enterprise | 87 |
| team | enterprise | 39 |

### Queue in the CRM vs true route, most frequent first

| true | in CRM | n |
|---|---|---|
| sales_assist | sales_assist | 117 |
| self_serve | self_serve | 111 |
| sales | sales | 87 |
| sales_assist | sales | 36 |
| self_serve | sales_assist | 6 |
| self_serve | sales | 3 |

## Secondary: calibration of self-reported confidence

Confidence comes from the decisions log (the qualifier's own statement); correctness comes from the world. The baseline arm always states 1.0.

- treatment: underconfident on this set: mean self-reported confidence 0.85 vs tier effect accuracy 100.0% over the 360 lead-runs that reported a confidence (ECE 0.152, Brier 0.032); 0 lead-runs reported none and are not scored here (they are still failures above).

| confidence bin | n | mean conf | tier effect accuracy |
|---|---|---|---|
| 0.6-0.8 | 66 | 0.69 | 100.0% |
| 0.8-1.0 | 294 | 0.88 | 100.0% |

- placebo: overconfident on this set: mean self-reported confidence 0.85 vs tier effect accuracy 27.5% over the 360 lead-runs that reported a confidence (ECE 0.572, Brier 0.540); 0 lead-runs reported none and are not scored here (they are still failures above).

| confidence bin | n | mean conf | tier effect accuracy |
|---|---|---|---|
| 0.6-0.8 | 65 | 0.69 | 33.8% |
| 0.8-1.0 | 295 | 0.88 | 26.1% |

- baseline: overconfident on this set: mean self-reported confidence 1.00 vs tier effect accuracy 89.2% over the 360 lead-runs that reported a confidence (ECE 0.108, Brier 0.108); 0 lead-runs reported none and are not scored here (they are still failures above).

| confidence bin | n | mean conf | tier effect accuracy |
|---|---|---|---|
| 0.8-1.0 | 360 | 1.00 | 89.2% |

## Secondary: run-to-run stability

### treatment

| run | tier effect | route effect |
|---|---|---|
| 0 | 120/120 (100.0%) | 103/120 (85.8%) |
| 1 | 120/120 (100.0%) | 102/120 (85.0%) |
| 2 | 120/120 (100.0%) | 103/120 (85.8%) |

The tier in the CRM differs between runs for 0/120 leads (mean per-lead flip rate 0.0%); tier effect accuracy spread across runs: 0.0%.

### placebo

| run | tier effect | route effect |
|---|---|---|
| 0 | 33/120 (27.5%) | 28/120 (23.3%) |
| 1 | 33/120 (27.5%) | 31/120 (25.8%) |
| 2 | 33/120 (27.5%) | 30/120 (25.0%) |

The tier in the CRM differs between runs for 0/120 leads (mean per-lead flip rate 0.0%); tier effect accuracy spread across runs: 0.0%.

### baseline

| run | tier effect | route effect |
|---|---|---|
| 0 | 107/120 (89.2%) | 105/120 (87.5%) |
| 1 | 107/120 (89.2%) | 105/120 (87.5%) |
| 2 | 107/120 (89.2%) | 105/120 (87.5%) |

The tier in the CRM differs between runs for 0/120 leads (mean per-lead flip rate 0.0%); tier effect accuracy spread across runs: 0.0%.

## Self-report log vs world

Of 1080 planned decisions: 0 logged as unparseable; 0 logged as decided but with no consistent effect in the world; 0 delivered differently from what the log claims. Informational: wherever the two disagree, the grade follows the world.

## Limits

- 120 synthetic leads x 3 repeats: repeated runs of one lead share its label and signals. Comparisons between arms are paired per lead for that reason.
- World-state grading checks that a decision was actually applied and where the lead ended up. In this harness the simulator applies accepted decisions faithfully, so it guards the measurement path (dropped, misapplied or misreported decisions); it does not make the dataset harder or the labels more realistic.
- The placebo arm uses one fixed seeded derangement. A different permutation gives a different placebo number; treat it as a sanity floor, not a precise estimate.
- Labels are hand-designed and unambiguous by construction. Real funnel data has contested labels, missing signals and drift; accuracy here is an upper bound, not a promise.
- The dataset is synthetic and shaped like a generic PLG free-to-paid motion. It is not any company's production data.
- Integrity checks and hashes are consistency checks on local files. They do not protect against the owner of those files.
- Every claim is about this prompt + this model + this dataset. Change any of the three and re-run before reusing a number.

## How to reproduce this report (offline, no model calls)

```sh
python3 scripts/grade_world.py --run-dir <run-dir> --data data/leads.jsonl
python3 scripts/world_report.py --run-dir <run-dir> --data data/leads.jsonl --out <report.md>
```
