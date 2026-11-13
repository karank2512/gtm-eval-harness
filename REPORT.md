# GTM lead-qualification eval - report

Generated 2026-11-14 from `results/results.jsonl`. Every number below is recomputed from that file by `scripts/report.py`; none are typed by hand.

## Setup

- backend: `claude-code` (model: `claude-fable-5-2`)
- leads: 120 (synthetic, seed 20261114)
- runs per arm: 3
- arms: baseline, placebo, treatment

## Headline

1. The pipeline routes 99.2% of leads to the right tier (357/360).
2. On leads designed to fool it, accuracy is 100.0% (96/96) vs 98.9% on clean leads (261/264).
3. Confidence is calibrated to ECE 0.137 over 360 scored calls
4. Re-running the same leads flips the tier call on 0.0% of lead-runs (120 leads x repeated runs).

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

## How to reproduce

```sh
python3 run_eval.py --backend claude-code --runs 3 --out results/results.jsonl
python3 scripts/report.py --results results/results.jsonl --out REPORT.md
```
