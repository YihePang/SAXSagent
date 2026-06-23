#!/usr/bin/env python3
"""
SAXS 拟合结果可视化脚本
读取 McSAS results.nxs，在同一张 Log-Log 图上绘制：
  - 原始 SAXS 数据（散点 + 误差棒）
  - 最优 McSAS 模型拟合曲线（χ² 最小的那条）

模型强度需要按 x0 参数缩放：modelI_scaled = modelI * x0[0] + x0[1]

运行环境: 必须在 mcsas conda 环境中执行
    conda activate mcsas

用法: python3 plot_fit.py <results.nxs> [output_dir]
  output_dir: 默认与 nxs 同目录
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


def load_nxs_data(nxs_path):
    """从 results.nxs 提取原始数据和最优拟合曲线"""
    with h5py.File(nxs_path, 'r') as f:
        # 原始数据（分箱前，用于展示）
        raw = f['analyses/MCResult1/mcdata/rawData']
        raw_q = raw['Q'][:]
        raw_i = raw['I'][:]
        raw_err = raw['ISigma'][:]

        # 拟合 Q 网格（分箱后）
        fit_q = f['analyses/MCResult1/mcdata/measData/Q'][:].flatten()

        # 样品名称
        filename = f['analyses/MCResult1/mcdata/filename'][()]
        if isinstance(filename, bytes):
            filename = filename.decode('utf-8')
        sample_name = os.path.splitext(os.path.basename(filename))[0]

        # 计算 Reduced χ² = raw χ² / DoF, DoF = nbins - 2 (scale + background)
        nbins = f['analyses/MCResult1/mcdata/nbins'][()]
        dof = nbins - 2

        # 找最优重复（Reduced χ² 最小）
        n_rep = f['analyses/MCResult1/optimization/nRep'][()]
        best_gof = float('inf')
        best_idx = 0
        best_model_i = None
        best_x0 = None
        best_reduced = float('inf')

        for r in range(n_rep):
            rep = f[f'analyses/MCResult1/optimization/repetition{r}']
            gof = rep['gof'][()]
            reduced = gof / dof
            if gof < best_gof:
                best_gof = gof
                best_reduced = reduced
                best_idx = r
                best_model_i = rep['modelI'][:]
                best_x0 = rep['x0'][:]

        # 用 x0 参数缩放模型强度到与数据同一尺度
        # modelI_scaled = modelI * scale + background
        scaled_model_i = best_model_i * best_x0[0] + best_x0[1]

    return raw_q, raw_i, raw_err, fit_q, scaled_model_i, best_reduced, best_idx, sample_name


def plot_fit(raw_q, raw_i, raw_err, fit_q, model_i, reduced_chi2, best_idx, sample_name, output_path):
    """Log-Log 散射曲线 + 最优 McSAS 拟合"""
    fig, ax = plt.subplots(figsize=(6, 4))

    # 原始数据散点 + 误差棒
    ax.errorbar(raw_q, raw_i, yerr=raw_err,
                fmt='o', markersize=2.5, capsize=1.5, elinewidth=0.5,
                color='#1f77b4', alpha=0.5, label=f'{sample_name} (data)')

    # 最优拟合曲线
    ax.plot(fit_q, model_i, '-', color='#d62728', linewidth=2.0,
            label=f'SAXS fit rep{best_idx} ($\\chi^2_\\mathrm{{red}}$={reduced_chi2:.3f})')

    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('Q (nm⁻¹)')
    ax.set_ylabel('I (a.u.)')
    ax.set_title(f'SAXS Fit — {sample_name}')
    ax.legend(fontsize=10)
    ax.grid(True, which='both', linestyle='--', alpha=0.4)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f'[OK] Fit plot saved to: {output_path}')
    if sys.platform == 'darwin':
        os.system(f'open "{output_path}"')
        os.system(
            'osascript -e "delay 0.5" '
            '-e "tell application \\"Finder\\" to set sb to bounds of window of desktop" '
            '-e "set sw to item 3 of sb" '
            '-e "set sh to item 4 of sb" '
            '-e "tell application \\"Preview\\" to set bounds of front window to {sw-620, sh-430, sw-20, sh-30}"'
        )
    else:
        plt.show()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 plot_fit.py <results.nxs> [output_dir]')
        print('  results.nxs: path to McSAS results file')
        print('  output_dir:  output directory (default: same dir as nxs)')
        sys.exit(1)

    nxs_path = sys.argv[1]
    if not os.path.exists(nxs_path):
        print(f'Error: file not found: {nxs_path}')
        sys.exit(1)

    raw_q, raw_i, raw_err, fit_q, model_i, reduced_chi2, best_idx, sample_name = load_nxs_data(nxs_path)
    print(f'Loaded results from {nxs_path}')
    print(f'  Raw data: {len(raw_q)} points, Q={raw_q.min():.4f}~{raw_q.max():.4f}')
    print(f'  Fit grid: {len(fit_q)} points')
    print(f'  Best fit: rep{best_idx}, χ²_red={reduced_chi2:.4f}')

    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(nxs_path)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{sample_name}_fit.png')
    plot_fit(raw_q, raw_i, raw_err, fit_q, model_i, reduced_chi2, best_idx, sample_name, output_path)
    print('Done.')
