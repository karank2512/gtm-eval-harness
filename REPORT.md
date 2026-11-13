# GTM lead-qualification eval - report

Generated 2026-11-14 from `results/results.jsonl`. Every number below is recomputed from that file by `scripts/report.py`; none are typed by hand.

## Setup

- backend: `claude-code` (model: `claude-fable-5-2`)
- runtime: local Claude Code CLI on a Claude subscription - no API key, no usage billing; qualification calls run with tool use disabled
- leads: 120 (synthetic, seed 20261114)
- runs per arm: 3
- arms: baseline, placebo, treatment

## Headline

1. Tier calls are near ceiling on this dataset: 99.2% of lead-runs tiered correctly (357/360).
2. Routing is not: 89.2% of lead-runs routed correctly (321/360) - +6 lead-runs vs the deterministic rules baseline (315/360, 87.5%), so on this dataset the model's routing buys almost nothing over free rules.
3. The leads designed to fool the qualifier did not: 96/96 tricky lead-runs tiered correctly vs 261/264 clean. The traps were calibrated for weaker qualifiers - a negative result, reported as one.
4. Confidence is underconfident on this set: mean confidence 0.85 vs actual tier accuracy 99.2% (ECE 0.137), Brier 0.031 over 360 scored calls.
5. Re-running the same leads flips the tier call on 0.0% of lead-runs (120 leads x repeated runs).

## Arm: baseline

- scored rows: 360/360 (unparseable: 0)

### Tier accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 87/87 | 100.0% |
| personal_dev | 111/111 | 100.0% |
| team | 123/162 | 75.9% |
| **all** | 321/360 | 89.2% |

### Route accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 87/87 | 100.0% |
| sales_assist | 117/153 | 76.5% |
| self_serve | 111/120 | 92.5% |
| **all** | 315/360 | 87.5% |

### Confusions (tier), most frequent first

| true | predicted | n |
|---|---|---|
| team | team | 123 |
| personal_dev | personal_dev | 111 |
| enterprise | enterprise | 87 |
| team | enterprise | 39 |

### Calibration (ECE 0.108, Brier 0.108, n=360)

| confidence bin | n | mean conf | accuracy |
|---|---|---|---|
| 0.8-1.0 | 360 | 1.00 | 89.2% |

### Run-to-run stability

| run | correct/n | accuracy |
|---|---|---|
| 0 | 107/120 | 89.2% |
| 1 | 107/120 | 89.2% |
| 2 | 107/120 | 89.2% |

Mean per-lead flip rate: 0.0% across 120 leads; accuracy spread across runs: 0.0%.

## Arm: placebo

- scored rows: 360/360 (unparseable: 0)

### Tier accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 9/87 | 10.3% |
| personal_dev | 30/111 | 27.0% |
| team | 60/162 | 37.0% |
| **all** | 99/360 | 27.5% |

### Route accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 19/87 | 21.8% |
| sales_assist | 41/153 | 26.8% |
| self_serve | 30/120 | 25.0% |
| **all** | 90/360 | 25.0% |

### Confusions (tier), most frequent first

| true | predicted | n |
|---|---|---|
| team | personal_dev | 60 |
| team | team | 60 |
| enterprise | team | 57 |
| personal_dev | team | 42 |
| team | enterprise | 42 |
| personal_dev | enterprise | 39 |
| personal_dev | personal_dev | 30 |
| enterprise | personal_dev | 21 |
| enterprise | enterprise | 9 |

### Calibration (ECE 0.580, Brier 0.550, n=360)

| confidence bin | n | mean conf | accuracy |
|---|---|---|---|
| 0.6-0.8 | 63 | 0.70 | 34.9% |
| 0.8-1.0 | 297 | 0.89 | 25.9% |

### Run-to-run stability

| run | correct/n | accuracy |
|---|---|---|
| 0 | 33/120 | 27.5% |
| 1 | 33/120 | 27.5% |
| 2 | 33/120 | 27.5% |

Mean per-lead flip rate: 0.0% across 120 leads; accuracy spread across runs: 0.0%.

## Arm: treatment

- scored rows: 360/360 (unparseable: 0)

### Tier accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 87/87 | 100.0% |
| personal_dev | 111/111 | 100.0% |
| team | 159/162 | 98.1% |
| **all** | 357/360 | 99.2% |

### Route accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 87/87 | 100.0% |
| sales_assist | 123/153 | 80.4% |
| self_serve | 111/120 | 92.5% |
| **all** | 321/360 | 89.2% |

### Confusions (tier), most frequent first

| true | predicted | n |
|---|---|---|
| team | team | 159 |
| personal_dev | personal_dev | 111 |
| enterprise | enterprise | 87 |
| team | enterprise | 3 |

### Calibration (ECE 0.137, Brier 0.031, n=360)

| confidence bin | n | mean conf | accuracy |
|---|---|---|---|
| 0.6-0.8 | 63 | 0.70 | 95.2% |
| 0.8-1.0 | 297 | 0.89 | 100.0% |

### Run-to-run stability

| run | correct/n | accuracy |
|---|---|---|
| 0 | 119/120 | 99.2% |
| 1 | 119/120 | 99.2% |
| 2 | 119/120 | 99.2% |

Mean per-lead flip rate: 0.0% across 120 leads; accuracy spread across runs: 0.0%.

## Limits

- 120 synthetic leads x 3 repeats each: the per-arm row counts are lead-runs, not independent leads. Repeated runs of one lead share its label and its signals.
- The placebo arm uses one fixed seeded derangement. A different permutation gives a different placebo number; treat it as a sanity floor, not a precise estimate.
- Labels are hand-designed and unambiguous by construction. Real funnel data has contested labels, missing signals and drift; accuracy here is an upper bound, not a promise.
- The dataset is synthetic and shaped like a generic PLG free-to-paid motion. It is not any company's production data.
- Every claim is about this prompt + this model + this dataset. Change any of the three and re-run before reusing a number.

## How to reproduce

```sh
python3 run_eval.py --backend claude-code --model claude-fable-5-2 --runs 3 --out results/results.jsonl
python3 scripts/report.py --results results/results.jsonl --out REPORT.md
```

Runs execute through the local Claude Code CLI on a Claude subscription; no API key is used and no usage billing is involved. Pin the model explicitly as shown so a report always names the model its numbers came from.
