# SAXS Agent

> **Claude Code-powered agent for iterative Small Angle X-ray Scattering (SAXS) particle size distribution analysis.**

SAXS Agent is a specialized [Claude Code](https://claude.ai/code) agent that automates the full SAXS data analysis workflow: from raw scattering data to reliable particle size distributions via McSAS Monte Carlo fitting, guided by a 3-tier reliability evaluation system with automatic parameter optimization.

---

## Table of Contents

- [Why SAXS Agent?](#why-saxs-agent)
- [How It Works](#how-it-works)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Skills](#skills)
  - [`saxs-plot` — Visualization](#saxs-plot--visualization)
  - [`mcsas-analysis` — Full Analysis Pipeline](#mcsas-analysis--full-analysis-pipeline)
- [3-Tier Reliability Evaluation](#3-tier-reliability-evaluation)
- [Parameter Estimation](#parameter-estimation)
- [Configuration Templates](#configuration-templates)
- [Data Format](#data-format)
- [Output Structure](#output-structure)
- [Key Rules](#key-rules)
- [License](#license)

---

## Why SAXS Agent?

Manual SAXS analysis with McSAS involves a tedious trial-and-error cycle:

1. Guess initial parameters (radius range, nContrib, maxIter...)
2. Run McSAS fitting (minutes of waiting)
3. Eyeball the fit and histogram
4. Tweak parameters and repeat
5. Hope you converge before losing patience

**SAXS Agent replaces this with an intelligent, autonomous loop:**

- **Auto-estimates** physically-grounded initial parameters from your data (Q range → radius range via π/Q_min, S/N → data quality)
- **Runs** McSAS Monte Carlo fitting autonomously
- **Evaluates** results with a rigorous 3-tier system (χ²_red grading, Durbin-Watson residuals, boundary detection, cross-iteration stability)
- **Adjusts** parameters automatically based on diagnostic signals
- **Converges** within ≤5 iterations or warns you if convergence is impossible

The agent doesn't just run commands — it **reasons about the physics**, explains each decision in natural language (Chinese), and asks for your input at key decision points.

---

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  Step 1  →  Select data file from data/              │
│  Step 2  →  Create run directory + visualize raw data│
│  Step 3  →  Auto-estimate parameters + write configs │◄──────┐
│  Step 4  →  Run McSAS Monte Carlo fitting            │       │
│  Step 5  →  3-tier evaluation + optimization decision│       │
│              ├─ Tier 1 PASS → Step 6                  │       │
│              └─ Tier 1 FAIL → Adjust params ─────────┘       │
│  Step 6  →  Final summary + report                          │
└─────────────────────────────────────────────────────┘
                                     Max 5 iterations
```

The **iteration loop** (Steps 3→4→5→3) is the core innovation: each round evaluates the fit quality with quantitative metrics, identifies root causes (e.g., χ² too high → increase maxIter; peak at R_max boundary → expand radius range), and applies targeted fixes. The loop stops when Tier 1 criteria are met, or after 5 iterations with a shake detection mechanism to catch parameter oscillations.

---

## Repository Structure

```
SAXS_agent/
├── data/                          # SAXS experimental data files
│   ├── SiO2-0C.txt                #   SiO2 sample (no header)
│   └── SiO2-1C.txt                #   SiO2 sample (no header)
├── template/                      # Configuration file templates
│   └── config/
│       ├── read_config.yaml       #   Data reading parameters (nbins, dataRange, csvargs)
│       └── run_config.yaml        #   Model & fitting parameters (radius, nContrib, maxIter...)
├── skills/                        # Claude Code skill implementations
│   ├── saxs-plot/                 #   Visualization skill
│   │   ├── SKILL.md               #     Skill definition + rules
│   │   ├── plot_saxs.py           #     Raw data Log-Log scatter plot
│   │   ├── plot_fit.py            #     McSAS fit result overlay
│   │   └── plot_histogram.py      #     Particle size distribution histogram
│   └── mcsas-analysis/            #   McSAS analysis pipeline skill
│       ├── SKILL.md               #     Detailed 6-step iterative workflow rules
│       ├── auto_params.py         #     Auto-estimate initial McSAS parameters
│       └── evaluate_fit.py        #     3-tier reliability evaluation engine
├── results/                       # Analysis run directories (auto-generated)
│   └── {filename}_{timestamp}/
│       ├── images/                #   Plot outputs (loglog, fit, histogram)
│       ├── config/                #   Active configs (latest iteration)
│       ├── iteration_N/           #   Per-iteration config snapshots
│       ├── iteration_history.json #   Full iteration tracking log
│       └── mcsas_results/         #   McSAS results (.nxs per iteration)
├── .claude/
│   └── skills/                    #   → symlink to ../skills/
├── CLAUDE.md                      # Agent instructions (loaded by Claude Code)
└── README.md
```

---

## Prerequisites

### 1. Claude Code

Install Claude Code from [claude.ai/code](https://claude.ai/code).

### 2. McSAS + Conda Environment

All Python scripts and McSAS commands run inside the `mcsas` conda environment:

```bash
# Create and activate the environment
conda create -n mcsas python=3.10
conda activate mcsas

# Install dependencies
pip install numpy matplotlib h5py

# Install McSAS3
# Follow instructions at: https://github.com/McSAS/McSAS3
```

The environment must provide:
- `numpy`, `matplotlib`, `h5py` — for data processing and visualization
- `mcsas3` / `mcsas3-runner` — the McSAS Monte Carlo fitting CLI

---

## Quick Start

### Option 1: Interactive Chat (Recommended)

Open this repository in Claude Code and simply say:

```
帮我做粒径分析
```

The agent will:
1. List available data files in `data/`
2. Ask you to pick one
3. Walk you through the full 6-step pipeline with Chinese-language prompts
4. Show progress bars, fit plots, and histograms at each iteration
5. Deliver a final summary with all metrics

### Option 2: Individual Scripts

You can also run the analysis scripts directly:

```bash
conda activate mcsas

# 1. Visualize raw SAXS data
python3 skills/saxs-plot/plot_saxs.py data/SiO2-1C.txt images/

# 2. Auto-estimate parameters
python3 skills/mcsas-analysis/auto_params.py /absolute/path/to/data/SiO2-1C.txt

# 3. Run McSAS fitting
mcsas3-runner \
  -f data/SiO2-1C.txt \
  -F template/config/read_config.yaml \
  -R template/config/run_config.yaml \
  -r output/results.nxs

# 4. Plot fit + histogram
python3 skills/saxs-plot/plot_fit.py output/results.nxs images/
python3 skills/saxs-plot/plot_histogram.py output/results.nxs images/ \
  --radius-min 1 --radius-max 100

# 5. Evaluate fit quality
python3 skills/mcsas-analysis/evaluate_fit.py \
  output/results.nxs data/SiO2-1C.txt 1 100 \
  --history iteration_history.json
```

---

## Skills

### `saxs-plot` — Visualization

Triggered when the user mentions: "画SAXS图", "绘制散射曲线", "SAXS可视化", "log图"

| Script | What It Does |
|--------|-------------|
| `plot_saxs.py` | Log-Log scatter plot of raw SAXS data (Q vs I with error bars) |
| `plot_fit.py` | McSAS fit overlay — data points + best-fit model curve (scaled by `x0`) with χ² annotation |
| `plot_histogram.py` | Particle size distribution — **Left:** mean of all repetitions with ±1σ error bars; **Right:** best single repetition. Peak (mode) in legend. Nature-style color scheme. |

All plots: DPI 300, auto-positioned Preview on macOS.

### `mcsas-analysis` — Full Analysis Pipeline

Triggered when the user mentions: "粒径分析", "粒径分布", "McSAS", "mcsas", "颗粒尺寸", "size distribution"

| Step | Name | Description |
|:---:|------|-------------|
| 1 | Select data file | Lists `data/*.txt` files, user picks one |
| 2 | Create workspace + visualize | Creates `results/{filename}_{timestamp}/`, plots Log-Log scattering curve |
| 3 | **[Loop entry]** Parameter setup | Auto-estimates radius range from π/Q, writes configs; subsequent rounds apply evaluation-driven adjustments |
| 4 | McSAS fitting | Monte Carlo optimization via `mcsas3-runner` |
| 5 | Evaluate + decide | Plots fit/histogram, runs 3-tier evaluation → converge / adjust / fatal |
| 6 | Final summary | Iteration history, best metrics, complete report |

**Iteration safety:** Max 5 rounds, oscillation detection, parameter caps, fatal error handling.

---

## 3-Tier Reliability Evaluation

The evaluation engine (`evaluate_fit.py`) applies a structured, quantitative assessment:

### 🔴 Tier 1 — Must Satisfy (Blocking)

| Criterion | Method | Pass Condition |
|-----------|--------|---------------|
| χ²_red reasonable | `best_χ² / (nbins - 2)` | **0.05 < χ²_red ≤ 10** |
| Residual randomness | Durbin-Watson + multi-lag autocorrelation | DW ∈ (1.2, 2.5) with no significant periodicity |
| Main peak not at boundary | Histogram peak bin check | Peak not at first or last bin of [R_min, R_max] |

> **χ²_red grading scale:**
> - `< 0.05` — ❌ Reject (severe overfitting / inflated errors)
> - `0.05–0.2` — ⚠️ Good, check error estimates
> - `0.2–2.0` — ✅ Normal
> - `2.0–5.0` — ⚠️ Acceptable, check residuals
> - `5.0–10.0` — ⚠️ Poor, review data / model
> - `> 10.0` — ❌ Reject (fit failure)

**Any Tier 1 failure → must adjust and re-fit.** (Residual analysis is informative only, not blocking.)

### 🟡 Tier 2 — Should Satisfy (Advisory)

| Criterion | Method | Pass Condition |
|-----------|--------|---------------|
| Peak stability vs radius changes | Cross-iteration comparison with different `radius` ranges | Peak shift < 5% |
| Peak stability vs nContrib changes | Cross-iteration comparison with different `nContrib` values | Peak shift < 5% |

### 🟢 Tier 3 — Bonus (Informational)

| Criterion | Pass Condition |
|-----------|---------------|
| Peak in resolvable range | `π/Q_max < R_peak < 2π/Q_min` |
| Publication-grade repetitions | `nRep > 20` |

---

## Parameter Estimation

The `auto_params.py` script computes physically-grounded initial parameters from the experimental data:

| Parameter | Formula | Notes |
|-----------|---------|-------|
| **R_max** | `max(100, ceil(π/Q_min / 5) × 5)` nm | Lower bound 100 nm; capped at 500 nm for extremely small Q_min |
| **R_min** | `max(1, floor(π/Q_max))` nm | Lower bound 1 nm |
| **nContrib** | Q-range decade-based: `<1→200, 1-2→300, 2-3→400, ≥3→500` | Coarse-grained; McSAS is insensitive to this parameter |
| **nRep** | `2` (initial exploration) | Increased in later iterations as needed |

**Narrow Q-range compensation:** If Q_max/Q_min < 3, the estimated radius range is expanded by 3× to ensure coverage.

**Sensitivity ranking:** `radius range ≈ error estimation ≈ q_min >> nContrib`

---

## Configuration Templates

Two YAML configs control McSAS behavior. The agent copies from `template/config/` and modifies only parameter **values** (never adds/removes fields).

### `read_config.yaml` — Data Reading

```yaml
nbins: 100              # Rebinning resolution (50–200)
dataRange:
  - 0.0                 # Q lower bound
  - .inf                # Q upper bound (.inf = no cutoff)
csvargs:
  sep: "\t"             # Column separator
  header: null          # null = no header row; 0 = first row is header
  names:                # Column names (must match data file exactly)
    - "Q"
    - "I"
    - "ISigma"
```

### `run_config.yaml` — Model & Fitting

```yaml
modelName: "sphere"          # Scattering model
nContrib: 300                # Number of particle contributions (100–1000)
fitParameterLimits:
  radius: [1, 100]           # Radius range in nm
staticParameters:
  sld: 33.4                  # Particle scattering length density
  sld_solvent: 9.4           # Solvent SLD
maxIter: 100000              # Max MC iterations per run
convCrit: 1                  # Convergence criterion
nRep: 2                      # Independent repetitions
nCores: 5                    # CPU cores
```

---

## Data Format

SAXS data files are **tab-separated** with three columns:

| Column | Name | Unit |
|--------|------|------|
| 1 | **Q** | nm⁻¹ (scattering vector magnitude) |
| 2 | **I** | a.u. (scattering intensity) |
| 3 | **ISigma** (or error) | a.u. (estimated uncertainty on I) |

- Files may or may not have a header row (auto-detected)
- Negative or non-finite values are automatically filtered
- The `csvargs.names` in `read_config.yaml` must match the header/column names **exactly** (case-sensitive)

---

## Output Structure

Each analysis run creates a timestamped directory:

```
results/{filename}_{YYYYMMDD_HHMMSS}/
├── images/
│   ├── {filename}_loglog.png       # Log-Log scattering curve (Step 2)
│   ├── {filename}_fit.png          # McSAS fit overlay (Step 5, per iteration)
│   └── {filename}_histogram.png    # Particle size distribution (Step 5, per iteration)
├── config/                         # Active configs (latest iteration)
│   ├── read_config.yaml
│   └── run_config.yaml
├── iteration_1/config/             # Snapshot: iteration 1
│   ├── read_config.yaml
│   └── run_config.yaml
├── iteration_N/config/             # Snapshot: iteration N
│   ├── read_config.yaml
│   └── run_config.yaml
├── iteration_history.json          # Complete iteration log (params + full evaluation per round)
└── mcsas_results/
    ├── results_iter1.nxs           # McSAS HDF5 results (iteration 1)
    ├── results_iter2.nxs           # McSAS HDF5 results (iteration 2)
    └── ...                         # Each iteration preserved independently
```

---

## Key Rules

- **Conda first:** Always `conda activate mcsas` before any Python or McSAS command
- **Absolute paths:** `plot_saxs.py` and `auto_params.py` prepend `data/` to relative paths — always pass absolute paths to avoid path duplication
- **Template integrity:** When copying from `template/config/`, modify only parameter **values**, never add or remove fields
- **Case sensitivity:** `csvargs.names` must match the data file's column headers exactly (e.g., `Isigma` vs `ISigma`)
- **Histogram scaling:** Aligns with McSAS source — `counts * x0[0] * 1e-5` — contributions are inherently volume-weighted; do not apply secondary weighting
- **Fit curves:** Only the best repetition (lowest χ²) is shown; `modelI` is scaled by `x0[0]` before comparison with data
- **Iteration cap:** Maximum 5 iterations to prevent infinite loops; parameter adjustments are capped at defined upper limits
- **Fatal errors:** When `evaluate_fit.py` returns `fatal: true`, the agent stops and waits for manual intervention
- **Oscillation detection:** If the same parameter oscillates (up→down or down→up across consecutive iterations), the agent warns and suggests accepting the best round

---

## License

This project is provided for academic and research use. McSAS3 is developed by the McSAS community — see [McSAS/McSAS3](https://github.com/McSAS/McSAS3) for its license terms.

---

<p align="center">
  <sub>Built with <a href="https://claude.ai/code">Claude Code</a> — an AI agent for SAXS data analysis</sub>
</p>

![](https://komarev.com/ghpvc/?username=YihePang&abbreviated=true&base=3592&label=Repository_visits:)
