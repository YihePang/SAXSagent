#!/usr/bin/env python3
"""
SAXS 数据驱动的 McSAS 参数自动估计脚本

根据实验数据的 Q 范围、信噪比、数据密度，基于 SAXS 物理原理
自动计算 McSAS 拟合参数的推荐初始值。

运行环境: 必须在 mcsas conda 环境中执行
    conda activate mcsas

用法: python3 auto_params.py <datafile>
  datafile: SAXS 数据文件的绝对路径（Q, I, Isigma 三列）

输出:
  stdout:  JSON 格式的推荐参数（供 agent 解析）
  stderr:  人类可读的参数摘要

核心原理:
  - 粒径范围:  R_max = π/Q_min（nm，下限 100 nm）, R_min = π/Q_max（nm，下限 1 nm）
  - nContrib:  按 Q 范围粗粒度分档（200/300/400/500），不敏感参数，无需微调
  - nRep:      初始探索固定为 2
"""

import numpy as np
import sys
import os
import json
import math
import warnings


# ---------------------------------------------------------------------------
# 数据加载（与 plot_saxs.py 保持一致的自动表头检测逻辑）
# ---------------------------------------------------------------------------

def load_saxs_data(filepath):
    """
    自动检测表头并加载 SAXS 数据 (Q, I, Isigma)

    Parameters
    ----------
    filepath : str
        SAXS 数据文件路径

    Returns
    -------
    q, i, isigma : ndarray
    """
    with open(filepath, 'r') as f:
        first_line = f.readline().strip()

    # 检测分隔符：优先 Tab，其次逗号，最后空格
    if '\t' in first_line:
        sep = '\t'
    elif ',' in first_line:
        sep = ','
    else:
        sep = None  # np.loadtxt 默认空格

    parts = first_line.split(sep) if sep else first_line.split()
    try:
        float(parts[0])
        has_header = False
    except ValueError:
        has_header = True

    skiprows = 1 if has_header else 0
    kwargs = {'skiprows': skiprows}
    if sep:
        kwargs['delimiter'] = sep

    data = np.loadtxt(filepath, **kwargs)

    if data.ndim != 2 or data.shape[1] < 3:
        raise ValueError(
            f"数据格式错误: 期望至少 3 列 (Q, I, Isigma)，实际 {data.shape[1] if data.ndim == 2 else 1} 列。"
        )

    q = data[:, 0]
    i = data[:, 1]
    isigma = data[:, 2]
    return q, i, isigma


# ---------------------------------------------------------------------------
# 核心参数估计逻辑
# ---------------------------------------------------------------------------

def compute_auto_params(q, i, isigma):
    """
    根据 SAXS 数据自动估计 McSAS 拟合参数

    Parameters
    ----------
    q : ndarray
        散射矢量 Q (A^-1)
    i : ndarray
        散射强度 I
    isigma : ndarray
        不确定度

    Returns
    -------
    result : dict
    """
    warnings_list = []

    # --- 过滤无效数据点 ---
    valid_mask = (q > 0) & (i > 0) & (isigma >= 0) & np.isfinite(q) & np.isfinite(i) & np.isfinite(isigma)

    n_removed = np.sum(~valid_mask)
    if n_removed > 0:
        q = q[valid_mask]
        i = i[valid_mask]
        isigma = isigma[valid_mask]
        warnings_list.append(
            f"移除了 {n_removed} 个无效数据点 (Q<=0, I<=0, 或非有限值)"
        )

    n_points = len(q)
    if n_points < 3:
        raise ValueError(
            f"有效数据点不足: {n_points} 个（至少需要 3 个点）。请检查数据文件。"
        )

    q_min = float(np.min(q))
    q_max = float(np.max(q))
    q_ratio = q_max / q_min
    q_decades = math.log10(q_ratio)

    # --- 信噪比估计 ---
    # SAXS 强度随 Q 增大急剧下降（数个量级），全 Q 范围的中位 S/N 会被
    # 高 Q 低信号区域拉低，因此仅使用前 20% 数据点（Guinier 区 + 第一振荡）
    # 评估数据质量。
    n_low_q = max(10, len(q) // 5)
    i_low = i[:n_low_q]
    isigma_low = isigma[:n_low_q]

    # 检测恒定 Isigma（实验人员未提供真实不确定度）
    isigma_std = float(np.std(isigma))
    isigma_constant = (isigma_std < 1e-12 and len(isigma) > 1)

    with np.errstate(divide='ignore', invalid='ignore'):
        snr_low = np.where(
            (isigma_low > 0) & np.isfinite(isigma_low),
            i_low / isigma_low,
            np.nan
        )

    finite_snr_low = snr_low[np.isfinite(snr_low)]
    if len(finite_snr_low) == 0:
        snr = 1.0
        warnings_list.append("无法计算信噪比（所有 Isigma 为零或无穷），使用保守估计")
    else:
        snr = float(np.median(finite_snr_low))

    # --- 数据质量评估（仅用于信息展示，不影响 nContrib 粗粒度分档） ---
    if n_points < 50:
        quality_label = "sparse"
    elif isigma_constant:
        quality_label = "acceptable"
        warnings_list.append(
            "不确定度 Isigma 为恒定值（通常为占位符），无法据其判断信噪比。"
            "McSAS 结果对误差估计敏感，如拟合不理想，请确认不确定度是否可靠。"
        )
    elif snr < 5:
        quality_label = "noisy"
    elif snr > 30:
        quality_label = "good"
    else:
        quality_label = "acceptable"

    # --- 半径范围估计（单位：nm）---
    # Q 的单位是 nm⁻¹（McSAS 默认），R = π / Q 直接得到 nm
    # R_min = π / Q_max（最小可检测粒径，下限 1 nm）
    # R_max = π / Q_min（最大可检测粒径，下限 100 nm）
    R_max_raw = math.pi / q_min           # nm
    R_min_raw = math.pi / q_max           # nm

    # 窄 Q 范围补偿：Q 跨度不足时扩大估计范围
    if q_ratio < 3:
        range_expansion = 3.0
        warnings_list.append(
            f"Q 范围过窄 (Q_max/Q_min = {q_ratio:.1f} < 3)，"
            f"已将估计半径范围扩展 {range_expansion:.0f} 倍以保证覆盖。"
            "建议获取更宽 Q 范围的数据以获得可靠粒径分布。"
        )
    else:
        range_expansion = 1.0

    # 应用范围扩展（窄 Q 时），无额外裕度
    R_max_est = R_max_raw * range_expansion
    R_min_est = R_min_raw / range_expansion

    # R_max: 向上取整到 5 的倍数，下限 100 nm
    R_max = max(100, int(math.ceil(R_max_est / 5.0)) * 5)

    # R_min: 向下取整到整数，下限 1 nm
    R_min = max(1, int(math.floor(R_min_est)))

    # 确保 R_max > R_min
    if R_max <= R_min:
        R_max = R_min + 5
        warnings_list.append(
            f"估计的半径范围无效，已调整为 [{R_min}, {R_max}]"
        )

    # Q_min 极小 → 限制 R_max 上限（避免不合理的巨大粒径，单位 nm）
    if q_min < 0.001:
        uncapped_R_max = R_max
        R_max = min(R_max, 500)
        if uncapped_R_max > 500:
            warnings_list.append(
                f"Q_min = {q_min:.6f} A^-1 非常小，R_max 已从 {uncapped_R_max} nm 截断至 500 nm"
            )

    # --- nContrib 估计（粗粒度分档） ---
    # McSAS 结果对 nContrib=200 vs 300 不敏感，按 Q 范围 decade 数粗分即可：
    #   < 1 decade   → 200
    #   1-2 decades  → 300
    #   2-3 decades  → 400
    #   ≥ 3 decades  → 500
    # 稀疏数据降一档（最少 200）
    if q_decades < 1.0:
        n_contrib = 200
    elif q_decades < 2.0:
        n_contrib = 300
    elif q_decades < 3.0:
        n_contrib = 400
    else:
        n_contrib = 500

    if n_points < 50:
        n_contrib = max(200, n_contrib - 100)

    # --- nRep ---
    n_rep = 2  # 初始探索固定值

    # ========== 组装结果 ==========
    result = {
        "q_min": round(q_min, 4),
        "q_max": round(q_max, 4),
        "q_ratio": round(q_ratio, 2),
        "q_decades": round(q_decades, 2),
        "n_points": n_points,
        "median_snr": round(snr, 2),
        "data_quality": quality_label,
        "parameters": {
            "radius_min": R_min,
            "radius_max": R_max,
            "n_contrib": n_contrib,
            "n_rep": n_rep,
        },
        "diagnostics": {
            "R_min_raw": round(R_min_raw, 2),
            "R_max_raw": round(R_max_raw, 2),
            "R_min_formula": "pi / Q_max (nm, floor 1 nm)",
            "R_max_formula": "pi / Q_min (nm, floor 100 nm)",
            "R_min_margin": 1.0,
            "R_max_margin": round(range_expansion, 2),
            "range_expansion": round(range_expansion, 2),
        },
        "warnings": warnings_list,
    }

    return result


# ---------------------------------------------------------------------------
# 人类可读摘要（stderr）
# ---------------------------------------------------------------------------

def print_human_summary(result, filename):
    """打印格式化的参数摘要到 stderr"""
    p = result["parameters"]
    d = result["diagnostics"]
    q = result

    lines = [
        f"[auto_params] Loaded {q['n_points']} data points from {filename}",
        f"[auto_params] Q range: {q['q_min']:.4f} ~ {q['q_max']:.4f} nm⁻¹ "
        f"(ratio: {q['q_ratio']:.1f}x, {q['q_decades']:.2f} decades)",
        f"[auto_params] Median S/N: {q['median_snr']:.1f}  |  Data quality: {q['data_quality']}",
        f"[auto_params]",
        f"[auto_params] Recommended parameters:",
        f"[auto_params]   radius:     [{p['radius_min']}, {p['radius_max']}] nm",
        f"[auto_params]     R_max = π/Q_min = {d['R_max_raw']:.1f} nm (floor 100 nm)",
        f"[auto_params]     R_min = π/Q_max = {d['R_min_raw']:.1f} nm (floor 1 nm)",
        f"[auto_params]     range_expansion: {d['range_expansion']:.1f}x",
        f"[auto_params]   nContrib:   {p['n_contrib']}",
        f"[auto_params]   nRep:       {p['n_rep']} (initial test)",
    ]

    if result["warnings"]:
        lines.append(f"[auto_params]")
        lines.append(f"[auto_params] Warnings ({len(result['warnings'])}):")
        for w in result["warnings"]:
            lines.append(f"[auto_params]   [!] {w}")

    for line in lines:
        print(line, file=sys.stderr)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 auto_params.py <datafile>", file=sys.stderr)
        print("  datafile: path to SAXS data file (Q, I, Isigma columns)")
        sys.exit(1)

    filepath = sys.argv[1]

    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    # 加载数据
    q, i, isigma = load_saxs_data(filepath)

    # 计算参数
    result = compute_auto_params(q, i, isigma)

    # 输出
    print(json.dumps(result, ensure_ascii=False, indent=2))          # stdout → agent
    print_human_summary(result, os.path.basename(filepath))          # stderr → human
