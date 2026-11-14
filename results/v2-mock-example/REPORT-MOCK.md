# GTM lead-qualification eval - v2 world-state report (MOCK - not a model result)

Generated from a sealed v2 run completed 2026-11-14T05:36:02Z (world database sha256 `9afc86c15e059dba`). Every number below is recomputed offline by `scripts/world_report.py` from the CRM world database, the dataset's own labels and the sealed trial plan; none are typed by hand. The date is the run's recorded completion time, not the day this file was rendered.

**MOCK BACKEND: deterministic test double, not a language model. These numbers check harness math only.**

## What is graded here

- **Effects, not answers.** A lead-run is correct only if the simulated CRM shows it: the lead record carries the true tier, the lead is a member of the true route's queue, and a dispatch event with a valid receipt agrees with that state. The model's JSON, its `reason` text and the runner's log are not evidence of correctness.
- **Failures stay in the denominator.** Unparseable answers, dropped dispatches and inconsistent effects count as wrong; every accuracy below is over all planned lead-runs.
- **Confidence is a self-report.** Calibration compares the confidence the qualifier stated (taken from the decisions log) with what the world shows. It is the one figure here that rests on the log, and it is secondary.
- **Boundary.** The CRM is a local simulator owned by this harness, not a production CRM and not an independent security boundary. The separation that matters is from the model under test, which runs tool-free and never sees the labels, the plan or the database. The hashes below are consistency links; they are not tamperproof against whoever owns the files.

## Setup

- backend: `mock-test-only`
- leads: 120 independent cases (synthetic, seed 20261114)
- runs per arm: 3 -> 360 lead-runs per arm
- arms: treatment, placebo, baseline
- decisions: 1080 planned, of which 720 are model calls (the baseline arm is deterministic rules)
- dataset sha256: `3b40af0733f0b768c04695d60726c295c7e536a320ea69aebd993b49e5b72277`
- trial plan sha256: `e80e33f831fe865a4468980d41937e9b74110f690e45869290c1ecd4d69ae482`

## Preregistration

This run is not preregistered.

## Integrity checks

All of the following passed; the grader refuses to produce a score otherwise.

- sealed artifacts: manifest complete and self-consistent; plan, receipt, world database and decisions log match their sealed sha256
- dataset and plan: dataset sha256 matches; plan regenerated from dataset + design is identical (1080 trial identities)
- world metadata: sealed; bound to this plan, dataset and run receipt
- arm/run worlds: 9 isolated worlds, one per planned arm x run, all closed
- lead inventory: 120 planned leads in each world; no missing, duplicate, extra or unknown ids (1080 lead records)
- queue membership: every lead record is in exactly one known queue; no invalid routes
- event receipts: 1080 events; receipt chain recomputed; at most one event per trial; no cross-arm/run references
- decisions log inventory: 1080 rows, exactly one per planned trial (used for self-reported confidence only)

## Primary outcomes: effect accuracy

| arm | tier effect | route effect | both | delivered | rejected (unparseable) | no effect | inconsistent |
|---|---|---|---|---|---|---|---|
| treatment | 214/360 (59.4%) | 208/360 (57.8%) | 208/360 (57.8%) | 360 | 0 | 0 | 0 |
| placebo | 114/360 (31.7%) | 111/360 (30.8%) | 111/360 (30.8%) | 360 | 0 | 0 | 0 |
| baseline | 321/360 (89.2%) | 315/360 (87.5%) | 315/360 (87.5%) | 360 | 0 | 0 | 0 |

Denominators are all 360 planned lead-runs per arm: 120 leads x 3 runs. They are lead-runs, not 360 independent cases.

## Planned comparisons (paired per lead)

| comparison | effect | leads where first arm is better | worse | tied | mean per-lead difference (points) | lead-run delta |
|---|---|---|---|---|---|---|
| treatment vs baseline | tier | 5/120 | 53/120 | 62/120 | -29.7 | -107 (214 vs 321 of 360) |
| treatment vs baseline | route | 5/120 | 53/120 | 62/120 | -29.7 | -107 (208 vs 315 of 360) |
| treatment vs placebo | tier | 59/120 | 22/120 | 39/120 | +27.8 | +100 (214 vs 114 of 360) |
| treatment vs placebo | route | 58/120 | 22/120 | 40/120 | +26.9 | +97 (208 vs 111 of 360) |

Each lead's share of correct runs in the first arm minus its share in the second; the unit is the lead. Descriptive only: no significance test, no p-value, no superiority claim.

## Prespecified criteria

Source: preregistration `gtm-v2-20261114`. FORMAT DEMONSTRATION ONLY: this run is not preregistered; the criteria are applied to show what the report will contain, and test nothing.

### H1: Placebo control (validity gate) - MET

- tier effect accuracy, placebo <= 0.50: observed 114/360 - met
- tier effect accuracy diff, treatment vs placebo >= 0.25: observed 214/360 vs 114/360 (+27.8 points) - met
- reading fixed in advance: The measurement responds to the leads' own signals; the treatment figures are interpretable.

### H2: Tier effect near ceiling and above rules (v1 replication) - NOT MET

- tier effect accuracy, treatment >= 0.95: observed 214/360 - NOT met
- tier effect accuracy diff, treatment vs baseline > 0: observed 214/360 vs 321/360 (-29.7 points) - NOT met
- reading fixed in advance: v1's tier result did not replicate under world-state grading; reported as a non-replication with the observed counts.

### H3: No practically meaningful routing advantage over rules (v1 replication) - NOT MET

- abs route effect accuracy diff, treatment vs baseline <= 0.05: observed 208/360 vs 315/360 (+29.7 points) - NOT met
- reading fixed in advance: Does not replicate v1's routing finding; the direction and size are reported as observed, with no superiority claim in either direction.

### H4: Every planned decision is delivered - MET

- undelivered trials == 0: observed 0 of 1080 planned - met
- reading fixed in advance: Every planned decision produced a consistent CRM effect (tier, queue and dispatch receipt).

## Arm: treatment

- planned lead-runs: 360 (120 leads); delivered with a consistent effect: 360; rejected as unparseable: 0; no effect recorded: 0; inconsistent: 0

### Tier effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 55/87 | 63.2% |
| personal_dev | 102/111 | 91.9% |
| team | 57/162 | 35.2% |
| **all** | 214/360 | 59.4% |

### Route effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 55/87 | 63.2% |
| sales_assist | 51/153 | 33.3% |
| self_serve | 102/120 | 85.0% |
| **all** | 208/360 | 57.8% |

Clean vs tricky (tier effect): clean 173/264 (65.5%), tricky 41/96 (42.7%).

### Tier in the CRM vs true tier, most frequent first

| true | in CRM | n |
|---|---|---|
| personal_dev | personal_dev | 102 |
| team | enterprise | 93 |
| team | team | 57 |
| enterprise | enterprise | 55 |
| enterprise | personal_dev | 26 |
| team | personal_dev | 12 |
| personal_dev | team | 7 |
| enterprise | team | 6 |
| personal_dev | enterprise | 2 |

### Queue in the CRM vs true route, most frequent first

| true | in CRM | n |
|---|---|---|
| self_serve | self_serve | 102 |
| sales_assist | sales | 90 |
| sales | sales | 55 |
| sales_assist | sales_assist | 51 |
| sales | self_serve | 26 |
| self_serve | sales_assist | 13 |
| sales_assist | self_serve | 12 |
| sales | sales_assist | 6 |
| self_serve | sales | 5 |

## Arm: placebo

- planned lead-runs: 360 (120 leads); delivered with a consistent effect: 360; rejected as unparseable: 0; no effect recorded: 0; inconsistent: 0

### Tier effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 39/87 | 44.8% |
| personal_dev | 43/111 | 38.7% |
| team | 32/162 | 19.8% |
| **all** | 114/360 | 31.7% |

### Route effect accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 39/87 | 44.8% |
| sales_assist | 29/153 | 19.0% |
| self_serve | 43/120 | 35.8% |
| **all** | 111/360 | 30.8% |

Clean vs tricky (tier effect): clean 73/264 (27.7%), tricky 41/96 (42.7%).

### Tier in the CRM vs true tier, most frequent first

| true | in CRM | n |
|---|---|---|
| team | personal_dev | 72 |
| team | enterprise | 58 |
| personal_dev | enterprise | 53 |
| personal_dev | personal_dev | 43 |
| enterprise | enterprise | 39 |
| team | team | 32 |
| enterprise | personal_dev | 25 |
| enterprise | team | 23 |
| personal_dev | team | 15 |

### Queue in the CRM vs true route, most frequent first

| true | in CRM | n |
|---|---|---|
| sales_assist | self_serve | 72 |
| self_serve | sales | 59 |
| sales_assist | sales | 52 |
| self_serve | self_serve | 43 |
| sales | sales | 39 |
| sales_assist | sales_assist | 29 |
| sales | self_serve | 25 |
| sales | sales_assist | 23 |
| self_serve | sales_assist | 18 |

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

- treatment: overconfident on this set: mean self-reported confidence 0.69 vs tier effect accuracy 59.4% over the 360 lead-runs that reported a confidence (ECE 0.231, Brier 0.214); 0 lead-runs reported none and are not scored here (they are still failures above).

| confidence bin | n | mean conf | tier effect accuracy |
|---|---|---|---|
| 0.2-0.4 | 5 | 0.30 | 20.0% |
| 0.4-0.6 | 74 | 0.51 | 41.9% |
| 0.6-0.8 | 147 | 0.68 | 32.7% |
| 0.8-1.0 | 134 | 0.82 | 100.0% |

- placebo: overconfident on this set: mean self-reported confidence 0.69 vs tier effect accuracy 31.7% over the 360 lead-runs that reported a confidence (ECE 0.383, Brier 0.394); 0 lead-runs reported none and are not scored here (they are still failures above).

| confidence bin | n | mean conf | tier effect accuracy |
|---|---|---|---|
| 0.2-0.4 | 5 | 0.30 | 60.0% |
| 0.4-0.6 | 74 | 0.51 | 41.9% |
| 0.6-0.8 | 147 | 0.68 | 36.7% |
| 0.8-1.0 | 134 | 0.82 | 19.4% |

- baseline: overconfident on this set: mean self-reported confidence 1.00 vs tier effect accuracy 89.2% over the 360 lead-runs that reported a confidence (ECE 0.108, Brier 0.108); 0 lead-runs reported none and are not scored here (they are still failures above).

| confidence bin | n | mean conf | tier effect accuracy |
|---|---|---|---|
| 0.8-1.0 | 360 | 1.00 | 89.2% |

## Secondary: run-to-run stability

### treatment

| run | tier effect | route effect |
|---|---|---|
| 0 | 70/120 (58.3%) | 68/120 (56.7%) |
| 1 | 74/120 (61.7%) | 72/120 (60.0%) |
| 2 | 70/120 (58.3%) | 68/120 (56.7%) |

The tier in the CRM differs between runs for 41/120 leads (mean per-lead flip rate 11.9%); tier effect accuracy spread across runs: 3.3%.

### placebo

| run | tier effect | route effect |
|---|---|---|
| 0 | 36/120 (30.0%) | 35/120 (29.2%) |
| 1 | 42/120 (35.0%) | 41/120 (34.2%) |
| 2 | 36/120 (30.0%) | 35/120 (29.2%) |

The tier in the CRM differs between runs for 41/120 leads (mean per-lead flip rate 11.9%); tier effect accuracy spread across runs: 5.0%.

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
python3 scripts/grade_world.py --run-dir <run-dir> --data data/leads.jsonl --criteria-demo <prereg-manifest>
python3 scripts/world_report.py --run-dir <run-dir> --data data/leads.jsonl --criteria-demo <prereg-manifest> --out <report.md>
```
