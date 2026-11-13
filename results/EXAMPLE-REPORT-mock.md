# GTM lead-qualification eval - report

Generated 2026-11-14 from `results/example-mock.jsonl`. Every number below is recomputed from that file by `scripts/report.py`; none are typed by hand.

## Setup

- backend: `mock-test-only`
- leads: 120 (synthetic, seed 20261114)
- runs per arm: 3
- arms: baseline, placebo, treatment
- **MOCK BACKEND: deterministic test double, not a language model. These numbers check harness math only.**

## Headline

1. The pipeline routes 59.4% of leads to the right tier (214/360).
2. On leads designed to fool it, accuracy is 42.7% (41/96) vs 65.5% on clean leads (173/264).
3. Confidence is calibrated to ECE 0.231 over 360 scored calls
4. Re-running the same leads flips the tier call on 11.9% of lead-runs (120 leads x repeated runs).

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
| enterprise | 39/87 | 44.8% |
| personal_dev | 43/111 | 38.7% |
| team | 32/162 | 19.8% |
| **all** | 114/360 | 31.7% |

### Route accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 39/87 | 44.8% |
| sales_assist | 29/153 | 19.0% |
| self_serve | 43/120 | 35.8% |
| **all** | 111/360 | 30.8% |

### Confusions (tier), most frequent first

| true | predicted | n |
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

### Calibration (ECE 0.383, Brier 0.394, n=360)

| confidence bin | n | mean conf | accuracy |
|---|---|---|---|
| 0.2-0.4 | 5 | 0.30 | 60.0% |
| 0.4-0.6 | 74 | 0.51 | 41.9% |
| 0.6-0.8 | 147 | 0.68 | 36.7% |
| 0.8-1.0 | 134 | 0.82 | 19.4% |

### Run-to-run stability

| run | correct/n | accuracy |
|---|---|---|
| 0 | 36/120 | 30.0% |
| 1 | 42/120 | 35.0% |
| 2 | 36/120 | 30.0% |

Mean per-lead flip rate: 11.9% across 120 leads; accuracy spread across runs: 5.0%.

## Arm: treatment

- scored rows: 360/360 (unparseable: 0)

### Tier accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| enterprise | 55/87 | 63.2% |
| personal_dev | 102/111 | 91.9% |
| team | 57/162 | 35.2% |
| **all** | 214/360 | 59.4% |

### Route accuracy by true segment

| true segment | correct/n | accuracy |
|---|---|---|
| sales | 55/87 | 63.2% |
| sales_assist | 51/153 | 33.3% |
| self_serve | 102/120 | 85.0% |
| **all** | 208/360 | 57.8% |

### Confusions (tier), most frequent first

| true | predicted | n |
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

### Calibration (ECE 0.231, Brier 0.214, n=360)

| confidence bin | n | mean conf | accuracy |
|---|---|---|---|
| 0.2-0.4 | 5 | 0.30 | 20.0% |
| 0.4-0.6 | 74 | 0.51 | 41.9% |
| 0.6-0.8 | 147 | 0.68 | 32.7% |
| 0.8-1.0 | 134 | 0.82 | 100.0% |

### Run-to-run stability

| run | correct/n | accuracy |
|---|---|---|
| 0 | 70/120 | 58.3% |
| 1 | 74/120 | 61.7% |
| 2 | 70/120 | 58.3% |

Mean per-lead flip rate: 11.9% across 120 leads; accuracy spread across runs: 3.3%.

## How to reproduce

```sh
python3 run_eval.py --backend mock --runs 3 --out results/results.jsonl
python3 scripts/report.py --results results/results.jsonl --out REPORT.md
```
