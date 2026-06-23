#!/usr/bin/env python3
"""
SAXS 数据可视化脚本
绘制 Log-Log 散射曲线

运行环境: 必须在 mcsas conda 环境中执行
    conda activate mcsas

用法: python3 plot_saxs.py <datafile> [output_dir]
  output_dir: 默认 images/
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import sys
import os

# ---- 中文字体设置 ----
matplotlib.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

# ---- 数据加载 ----
def load_saxs_data(filepath):
    """自动检测表头并加载 SAXS 数据 (Q, I, Isigma)"""
    with open(filepath, 'r') as f:
        first_line = f.readline().strip()
    parts = first_line.split('\t')
    try:
        float(parts[0])
        has_header = False
    except ValueError:
        has_header = True

    skiprows = 1 if has_header else 0
    data = np.loadtxt(filepath, skiprows=skiprows)
    q = data[:, 0]
    i = data[:, 1]
    isigma = data[:, 2]
    return q, i, isigma

# ---- 绘图函数 ----
def plot_loglog(q, i, isigma, sample_name, output_path):
    """Log-Log 散射曲线"""
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax.errorbar(q, i, yerr=isigma, fmt='o', markersize=2,
                capsize=1.5, elinewidth=0.5, label=sample_name, color='#1f77b4')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('Q (nm⁻¹)')
    ax.set_ylabel('I (a.u.)')
    ax.set_title(f'SAXS Scattering Curve — {sample_name}')
    ax.legend()
    ax.grid(True, which='both', linestyle='--', alpha=0.4)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f'[OK] Log-log plot saved to: {output_path}')
    if sys.platform == 'darwin':
        os.system(f'open "{output_path}"')
        # 将 Preview 窗口移到屏幕右下角
        os.system(
            'osascript -e "delay 0.5" '
            '-e "tell application \\"Finder\\" to set sb to bounds of window of desktop" '
            '-e "set sw to item 3 of sb" '
            '-e "set sh to item 4 of sb" '
            '-e "tell application \\"Preview\\" to set bounds of front window to {sw-520, sh-390, sw-20, sh-30}"'
        )
    else:
        plt.show()

# ---- 主程序 ----
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 plot_saxs.py <datafile> [output_dir]')
        print('  datafile:   path to SAXS data file (or filename in data/)')
        print('  output_dir: output directory (default: images/)')
        sys.exit(1)

    sample_file = sys.argv[1]
    filepath = sample_file if os.path.isabs(sample_file) else os.path.join('data', sample_file)

    if not os.path.exists(filepath):
        print(f'Error: file not found: {filepath}')
        sys.exit(1)

    sample_name = os.path.splitext(os.path.basename(sample_file))[0]

    q, i, isigma = load_saxs_data(filepath)
    print(f'Loaded {len(q)} data points from {filepath}')
    print(f'  Q range: {q.min():.4f} ~ {q.max():.4f} nm⁻¹')

    output_dir = sys.argv[2] if len(sys.argv) > 2 else 'images'
    os.makedirs(output_dir, exist_ok=True)
    plot_loglog(q, i, isigma, sample_name, f'{output_dir}/{sample_name}_loglog.png')
    print('Done.')
