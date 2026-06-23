# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SAXS_agent is a Claude Code-based agent specialized in **Small Angle X-ray Scattering (SAXS)** data analysis. It provides a complete iterative pipeline: from raw data visualization through McSAS Monte Carlo fitting, 3-tier reliability evaluation, and automatic parameter optimization — converging to reliable particle size distributions.

## Repository Structure

```
SAXS_agent/
├── data/                     # SAXS experimental data files
│   ├── A-SiO2-1C-2.txt      # SiO2 with header (Q, I, Isigma)
│   └── SiO2-1C.txt          # SiO2 without header (Q, I, error)
├── template/                 # Configuration file templates
│   └── config/
│       ├── read_config.yaml  # McSAS data reading parameters
│       └── run_config.yaml   # McSAS model & fitting parameters
├── skills/                   # Custom skill implementations
│   ├── saxs-plot/            # Visualization skill (3 scripts)
│   │   ├── plot_saxs.py      #   Raw data Log-Log scatter plot
│   │   ├── plot_fit.py       #   McSAS fit result overlay
│   │   └── plot_histogram.py #   Particle size distribution histogram
│   └── mcsas-analysis/       # McSAS analysis pipeline skill
│       ├── SKILL.md          #   6-step iterative analysis workflow
│       ├── auto_params.py    #   Auto-estimate initial McSAS parameters from data
│       └── evaluate_fit.py   #   3-tier reliability evaluation engine
├── results/                  # Analysis run directories (generated)
│   └── {filename}_{timestamp}/
│       ├── images/           # Plot outputs (loglog, fit, histogram)
│       ├── config/           # Active configs (latest iteration)
│       ├── iteration_N/      # Per-iteration config snapshots
│       ├── iteration_history.json  # Full iteration tracking log
│       └── mcsas_results/    # McSAS results.nxs
├── .claude/
│   └── skills/               # → symlink to ../skills/
└── CLAUDE.md
```

## SAXS Data Format

SAXS data files are tab-separated with three columns:
- **Q** — scattering vector magnitude (nm⁻¹)
- **I** — scattering intensity
- **Isigma** (or error) — estimated uncertainty on I

Data may or may not have a header row (auto-detected).

## Available Skills

| Skill | Directory | Description |
|---|---|---|
| `saxs-plot` | `skills/saxs-plot/` | SAXS visualization: Log-Log scatter, McSAS fit overlay, particle size histogram |
| `mcsas-analysis` | `skills/mcsas-analysis/` | Full McSAS iterative pipeline: file selection → visualize → auto-estimate params → fitting → 3-tier evaluate → optimize |

### mcsas-analysis — 6-Step Iterative Workflow

> **权威指令在 `skills/mcsas-analysis/SKILL.md`**。执行分析时以 SKILL.md 的详细规则为准，包括交互规范（中文提示、进度条格式、用户确认流程）和参数调整规则。CLAUDE.md 仅为快速参考。

| 步骤 | 名称 | 说明 |
|:---:|------|------|
| 1 | 选择数据文件 | 列出 `data/` 下可用文件 |
| 2 | 创建工作目录 + 读取数据 | 创建运行目录、绘制 Log-Log 散射曲线 |
| 3 | **[循环入口]** 参数估计 + 配置文件 | 首轮自动估计 McSAS 参数；后续轮根据评估结果调整 |
| 4 | McSAS 拟合 | 蒙特卡洛优化 |
| 5 | 拟合结果评估 + 优化决策 | 展示拟合图/直方图 + 三级评估 → 收敛/调整/致命错误 |
| 6 | 最终结果汇总 | 迭代历史 + 最终指标 + 完整报告 |

**迭代闭环**: 步骤 3 → 4 → 5 → (Tier 1 失败) → 3 → 4 → 5 → ... → 收敛 → 步骤 6。最大 5 轮。

### 三级评估体系

| 级别 | 准则 | 作用 |
|------|------|------|
| 🔴 **Tier 1** | χ²_red 分级评估（0.05-10 通过，≤0.05或>10 不通过）、残差随机 DW∈(1.2,2.5) 无周期性、主峰非边界峰 | **blocking 项失败 → 必须调整** |
| 🟡 **Tier 2** | 改变 radius 后主峰稳定(<5%)、改变 nContrib 后主峰稳定 | 建议满足，不阻塞 |
| 🟢 **Tier 3** | 主峰在可解析范围内、nRep > 20 | 加分项，仅供参考 |

### 参数估计公式

| 参数 | 公式 | 说明 |
|------|------|------|
| `R_max` | `max(100, ceil(π/Q_min / 5) × 5)` nm | 下限 100 nm |
| `R_min` | `max(1, floor(π/Q_max))` nm | 下限 1 nm |
| `nContrib` | Q 范围粗分档：<1→200, 1-2→300, 2-3→400, ≥3→500 | 不敏感参数，无需微调 |
| `nRep` | 2（初始测试） | — |

**敏感度排序**: `radius 范围 ≈ 误差估计 ≈ q_min >> nContrib`

## Runtime Environment

**All Python/McSAS commands must run inside the `mcsas` conda environment:**

```bash
conda activate mcsas
```

This environment provides: `numpy`, `matplotlib`, `h5py`, `mcsas3` (CLI tools + Python API).

## Key Commands

```bash
# Raw data plot — MUST use absolute path
conda activate mcsas && python3 skills/saxs-plot/plot_saxs.py /absolute/path/to/data/xxx.txt output_dir/

# Auto-estimate initial McSAS parameters from data
conda activate mcsas && python3 skills/mcsas-analysis/auto_params.py /absolute/path/to/data/xxx.txt

# McSAS fitting
conda activate mcsas && mcsas3-runner -f /absolute/path/to/data/xxx.txt -F config/read_config.yaml -R config/run_config.yaml -r output/results.nxs

# 3-tier reliability evaluation
conda activate mcsas && python3 skills/mcsas-analysis/evaluate_fit.py results.nxs /path/to/data.txt radius_min radius_max --history iteration_history.json

# Fit result plot
conda activate mcsas && python3 skills/saxs-plot/plot_fit.py results.nxs output_dir/

# Size distribution histogram
conda activate mcsas && python3 skills/saxs-plot/plot_histogram.py results.nxs output_dir/
```

## Key Rules

- **Conda first**: always `conda activate mcsas` before any Python/McSAS command
- **Absolute paths required**: `plot_saxs.py` and `auto_params.py` both auto-prepend `data/` to non-absolute paths. **Always pass the absolute path** (e.g., `/path/to/data/SiO2-1C.txt`)
- **Template copy principle**: when copying from `template/config/`, modify only parameter **values**, never add/remove fields
- **Case sensitivity**: `csvargs.names` must exactly match the data file's header (e.g., `Isigma` vs `ISigma`)
- **Reduced χ²**: `χ²_red = raw_χ² / (nbins - 2)`, where 2 accounts for scale + background free parameters. Acceptable range: 0.5–2.0
- **Histogram scaling**: align with McSAS source — `counts * x0[0] * 1e-5`, no explicit volume weights (contributions are inherently volume-weighted)
- **Fit curves**: only the best repetition (lowest χ²) is shown; `modelI` must be scaled by `x0` before comparing to data
- **Histogram**: shows mean of all repetitions with ±1σ error bars (left) + best single repetition (right), peak (mode) in legend
- **Iteration tracking**: every iteration's config must be archived to `iteration_{N}/config/`; full evaluation JSON must be stored in `iteration_history.json` for Tier 2 cross-iteration comparison
- **Max 5 iterations**: to prevent infinite loops; parameter adjustments are capped (see SKILL.md for caps)
- **Fatal errors stop the loop**: when `evaluate_fit.py` returns `fatal: true`, do NOT auto-loop — wait for manual user intervention
- **Plot windows**: all plot scripts auto-position Preview window at screen bottom-right on macOS
