#!/usr/bin/env python3
"""
SAXS 粒径分布直方图脚本
从 McSAS results.nxs 中提取粒径分布，绘制带误差棒的直方图。

实现逻辑对齐 McSAS 自带的 mc_model_histogrammer.py：
  - 每个 repetition 独立直方图（count-based，不带 weights）
  - Y 轴缩放：counts * x0[0] * correctionFactor (1e-5)
  - 误差棒：各 repetition 之间的标准差
  - 最优 repetition 单独高亮

直方图范围：
  优先级: CLI --radius-min/--radius-max > 自动从数据检测（加 10% 边距）

运行环境: 必须在 mcsas conda 环境中执行
    conda activate mcsas

用法: python3 plot_histogram.py <results.nxs> [output_dir] [--radius-min R_MIN] [--radius-max R_MAX]
"""

import h5py
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import sys
import os

# ---- 中文字体设置 ----
matplotlib.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

# ---- 直方图默认参数 ----
HIST_PARAMS = {
    "parameter": "radius",
    "nBin": 50,
    "binScale": "linear",
    "binWeighting": "vol",
    "autoRange": False,
}
# presetRangeMin/presetRangeMax 由 CLI 参数 --radius-min/--radius-max 指定，
# 或自动从数据中检测（无 CLI 参数时的回退方案）。

# McSAS 单位转换因子（SasModel 单位 → 绝对单位）
CORRECTION_FACTOR = 1e-5


def load_all_repetitions(nxs_path, hist_params, radius_min=None, radius_max=None):
    """从 results.nxs 提取所有 repetition 的半径数据和 x0 缩放因子

    Parameters
    ----------
    radius_min, radius_max : float or None
        直方图范围 (nm)。如为 None，自动从数据中检测（加 10% 边距）。
    """
    with h5py.File(nxs_path, 'r') as f:
        n_rep = f['analyses/MCResult1/optimization/nRep'][()]
        nbins = f['analyses/MCResult1/mcdata/nbins'][()]
        dof = nbins - 2  # scale + background

        rep_data = []  # list of (radii, x0, gof, reduced_chi2)
        for r in range(n_rep):
            ps = f[f'analyses/MCResult1/model/repetition{r}/parameterSet']
            radii = ps['data'][:].flatten()  # nm（McSAS Q 单位为 nm⁻¹）
            x0 = f[f'analyses/MCResult1/optimization/repetition{r}/x0'][:]
            gof = f[f'analyses/MCResult1/optimization/repetition{r}/gof'][()]
            reduced = gof / dof
            rep_data.append((radii, x0, gof, reduced))

        filename = f['analyses/MCResult1/mcdata/filename'][()]
        if isinstance(filename, bytes):
            filename = filename.decode('utf-8')
        sample_name = os.path.splitext(os.path.basename(filename))[0]

    # 找最优
    best_idx = int(np.argmin([d[2] for d in rep_data]))

    # ---- 确定直方图范围 ----
    if radius_min is None or radius_max is None:
        # 自动检测：收集所有 rep 的半径，取 min/max + 10% 边距
        all_radii = np.concatenate([d[0] for d in rep_data])
        data_min = float(np.min(all_radii))
        data_max = float(np.max(all_radii))
        margin = (data_max - data_min) * 0.1
        auto_min = max(0.1, data_min - margin)
        auto_max = data_max + margin
        if radius_min is None:
            radius_min = auto_min
        if radius_max is None:
            radius_max = auto_max

    # 四舍五入到合理精度
    p_min = float(np.floor(radius_min))
    p_max = float(np.ceil(radius_max))
    n_bin = hist_params["nBin"]
    bin_edges = np.linspace(p_min, p_max, n_bin + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    all_hists = []  # shape (nRep, nBin)
    all_reduced = []
    for radii, x0, gof, reduced in rep_data:
        counts, _ = np.histogram(radii, bins=bin_edges)
        # McSAS 标准缩放：counts * x0[0] * correctionFactor
        scaled = counts.astype(np.float64) * x0[0] * CORRECTION_FACTOR
        all_hists.append(scaled)
        all_reduced.append(reduced)
    all_hists = np.array(all_hists)

    # 均值和标准差
    mean_hist = all_hists.mean(axis=0)
    std_hist = all_hists.std(axis=0, ddof=1) if n_rep > 1 else np.zeros_like(mean_hist)

    # 最优
    best_hist = all_hists[best_idx]
    best_reduced = all_reduced[best_idx]

    return bin_centers, bin_edges, mean_hist, std_hist, best_hist, best_reduced, best_idx, n_rep, sample_name, dof


def plot_histogram(bin_centers, bin_edges, mean_hist, std_hist, best_hist,
                   best_reduced, best_idx, n_rep, sample_name, hist_params, output_path):
    """绘制粒径分布直方图 — 左：均值+误差棒，右：最优单次"""
    # Nature 期刊风格配色
    C_MEAN = '#4477AA'     #  muted blue
    C_MEAN_EDGE = '#2B5580'
    C_BEST = '#CC6677'     #  muted rose
    C_BEST_EDGE = '#994455'

    plt.rcParams.update({
        'font.size': 11,
        'axes.titlesize': 12,
        'axes.labelsize': 11,
        'legend.fontsize': 10,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
    })

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.2))

    bar_width = bin_edges[1] - bin_edges[0]

    # 找峰值
    mean_peak_idx = np.argmax(mean_hist)
    mean_peak_r = bin_centers[mean_peak_idx]
    best_peak_idx = np.argmax(best_hist)
    best_peak_r = bin_centers[best_peak_idx]

    # ---- 左图：多 repetition 均值 + 误差棒 ----
    ax1.bar(bin_centers, mean_hist, width=bar_width,
            yerr=std_hist, capsize=2, error_kw={'linewidth': 0.6},
            color=C_MEAN, edgecolor=C_MEAN_EDGE, linewidth=0.3, alpha=0.9,
            label=f'Mean  (peak: {mean_peak_r:.1f} nm)')
    ax1.set_xlabel('Radius (nm)')
    ax1.set_ylabel('Volume-weighted Distribution')
    ax1.set_title(f'Mean of {n_rep} repetitions (±1σ)')
    ax1.legend(fontsize=10, loc='upper right', frameon=True, fancybox=False,
               edgecolor='#cccccc')
    ax1.grid(True, axis='y', linestyle='--', alpha=0.3, linewidth=0.5)
    for sp in ax1.spines.values():
        sp.set_visible(True)
        sp.set_linewidth(0.8)
        sp.set_color('#333333')

    # ---- 右图：最优 repetition ----
    ax2.bar(bin_centers, best_hist, width=bar_width,
            color=C_BEST, edgecolor=C_BEST_EDGE, linewidth=0.3, alpha=0.9,
            label=f'Best  (peak: {best_peak_r:.1f} nm)')
    ax2.set_xlabel('Radius (nm)')
    ax2.set_ylabel('Volume-weighted Distribution')
    ax2.set_title(f'Best fit — rep{best_idx} (χ²$_{{\\mathrm{{red}}}}$={best_reduced:.3f})')
    ax2.legend(fontsize=10, loc='upper right', frameon=True, fancybox=False,
               edgecolor='#cccccc')
    ax2.grid(True, axis='y', linestyle='--', alpha=0.3, linewidth=0.5)
    for sp in ax2.spines.values():
        sp.set_visible(True)
        sp.set_linewidth(0.8)
        sp.set_color('#333333')

    fig.suptitle(f'Particle Size Distribution — {sample_name}', fontsize=13, y=1.02)
    plt.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f'[OK] Histogram saved to: {output_path}')
    if sys.platform == 'darwin':
        os.system(f'open "{output_path}"')
        os.system(
            'osascript -e "delay 0.5" '
            '-e "tell application \\"Finder\\" to set sb to bounds of window of desktop" '
            '-e "set sw to item 3 of sb" '
            '-e "set sh to item 4 of sb" '
            '-e "tell application \\"Preview\\" to set bounds of front window to {sw-820, sh-350, sw-20, sh-30}"'
        )


def print_stats(bin_centers, best_hist, best_reduced, best_idx):
    """打印统计信息"""
    total = best_hist.sum()
    if total > 0:
        mean_r = np.average(bin_centers, weights=best_hist)
        variance = np.average((bin_centers - mean_r)**2, weights=best_hist)
        std_r = np.sqrt(variance)
        peak_idx = np.argmax(best_hist)
        peak_r = bin_centers[peak_idx]
        cumsum = np.cumsum(best_hist)
        d50_idx = np.searchsorted(cumsum, total / 2)
        d50 = bin_centers[min(d50_idx, len(bin_centers) - 1)]

        print(f'  Best rep: {best_idx}, χ²_red={best_reduced:.4f}')
        print(f'  Mean radius:  {mean_r:.2f} nm')
        print(f'  Std radius:   {std_r:.2f} nm')
        print(f'  Peak radius:  {peak_r:.2f} nm')
        print(f'  D50 (median): {d50:.2f} nm')
        print(f'  Y max (best): {best_hist.max():.2e}')
    else:
        print('  (no data in histogram range)')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='从 McSAS results.nxs 绘制粒径分布直方图')
    parser.add_argument('nxs_path', help='results.nxs 路径')
    parser.add_argument('output_dir', nargs='?', default=None,
                        help='输出目录（默认与 nxs 同目录）')
    parser.add_argument('--radius-min', type=float, default=None,
                        help='直方图半径下限 (nm)，默认自动检测')
    parser.add_argument('--radius-max', type=float, default=None,
                        help='直方图半径上限 (nm)，默认自动检测')

    args = parser.parse_args()

    if not os.path.exists(args.nxs_path):
        print(f'Error: file not found: {args.nxs_path}')
        sys.exit(1)

    hist_params = HIST_PARAMS

    (bin_centers, bin_edges, mean_hist, std_hist, best_hist,
     best_reduced, best_idx, n_rep, sample_name, dof) = load_all_repetitions(
        args.nxs_path, hist_params,
        radius_min=args.radius_min, radius_max=args.radius_max)

    p_min, p_max = bin_edges[0], bin_edges[-1]
    source = '用户指定' if (args.radius_min or args.radius_max) else '自动检测'
    print(f'Loaded results from {args.nxs_path}')
    print(f'  Repetitions: {n_rep}, Bins: {hist_params["nBin"]}, DoF={dof}')
    print(f'  Histogram range: {p_min:.1f} ~ {p_max:.1f} nm ({source})')
    print_stats(bin_centers, best_hist, best_reduced, best_idx)

    output_dir = args.output_dir if args.output_dir else os.path.dirname(args.nxs_path)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{sample_name}_histogram.png')
    plot_histogram(bin_centers, bin_edges, mean_hist, std_hist, best_hist,
                   best_reduced, best_idx, n_rep, sample_name, hist_params, output_path)
    print('Done.')
