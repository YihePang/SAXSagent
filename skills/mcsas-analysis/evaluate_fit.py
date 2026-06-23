#!/usr/bin/env python3
"""
McSAS 拟合结果评估脚本

评估体系:
  Tier 1（必须满足）: χ²_red 分级评估（通过区间 0.05-10） + 主峰非边界峰
  Tier 2（建议满足）: 改变 radius 后主峰稳定 + 改变 nContrib 后主峰稳定
  Tier 3（加分项）:   主峰在可解析范围内 + nRep > 20
  参考信息:           残差自相关分析（DW + 周期性检测，仅供参考不阻塞）

运行环境: 必须在 mcsas conda 环境中执行
    conda activate mcsas

用法: python3 evaluate_fit.py <nxs_path> <data_file_path> <radius_min> <radius_max> [--history iteration_history.json]
"""

import h5py
import numpy as np
import sys
import os
import json
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auto_params import load_saxs_data

N_HIST_BINS = 50


# ============================================================================
# HDF5 加载
# ============================================================================

def load_nxs_for_evaluation(nxs_path):
    with h5py.File(nxs_path, 'r') as f:
        root = 'analyses/MCResult1'
        nbins = int(f[f'{root}/mcdata/nbins'][()])
        dof = nbins - 2
        n_rep = int(f[f'{root}/optimization/nRep'][()])
        fit_q = f[f'{root}/mcdata/measData/Q'][:].flatten()
        data_i = f[f'{root}/mcdata/measData/I'][:].flatten()
        data_sigma = f[f'{root}/mcdata/measData/ISigma'][:].flatten()

        reps = []
        for r in range(n_rep):
            try:
                gof = float(f[f'{root}/optimization/repetition{r}/gof'][()])
                model_i = f[f'{root}/optimization/repetition{r}/modelI'][:]
                x0 = f[f'{root}/optimization/repetition{r}/x0'][:]
                radii = f[f'{root}/model/repetition{r}/parameterSet/data'][:].flatten()  # nm
                reps.append({
                    'index': r, 'gof': gof, 'chi2_red': gof / dof,
                    'model_i': model_i, 'x0': x0, 'radii': radii,
                })
            except KeyError:
                continue
        if not reps:
            raise ValueError("所有 repetition 数据不完整")

    return {'nbins': nbins, 'dof': dof, 'n_rep': n_rep,
            'fit_q': fit_q, 'data_i': data_i, 'data_sigma': data_sigma, 'reps': reps}


# ============================================================================
# 辅助函数
# ============================================================================

def _histogram_peaks(reps, radius_min, radius_max):
    """计算所有 rep 的直方图和主峰位置"""
    bin_edges = np.linspace(radius_min, radius_max, N_HIST_BINS + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    all_hists = []
    peak_radii = []
    for r in reps:
        radii = r['radii']
        if len(radii) == 0:
            continue
        counts, _ = np.histogram(radii, bins=bin_edges)
        all_hists.append(counts.astype(np.float64))
        peak_radii.append(bin_centers[int(np.argmax(counts))])

    if not all_hists:
        return None, None, None, bin_centers

    mean_hist = np.mean(all_hists, axis=0)
    main_bin = int(np.argmax(mean_hist))
    main_peak = float(bin_centers[main_bin])

    peak_arr = np.array(peak_radii)
    cv_pct = float(np.std(peak_arr, ddof=1) / np.mean(peak_arr) * 100) if len(peak_arr) > 1 and np.mean(peak_arr) > 0 else 0.0

    return mean_hist, main_peak, main_bin, bin_centers, peak_arr, cv_pct, all_hists


def _autocorrelation_check(residuals):
    """检查残差自相关（多滞后），检测周期性"""
    n = len(residuals)
    if n < 20:
        return None, "残差点不足，跳过自相关检验"

    max_lag = min(n // 4, 20)
    acf = []
    for lag in range(1, max_lag + 1):
        r1 = residuals[:-lag]
        r2 = residuals[lag:]
        corr = np.corrcoef(r1, r2)[0, 1]
        if np.isfinite(corr):
            acf.append(corr)

    if not acf:
        return None, "无法计算自相关"

    acf = np.array(acf)

    # 检查是否有显著的周期性峰值（lag > 1 处 |ACF| > 0.3）
    significant_lags = []
    for i, val in enumerate(acf):
        lag = i + 1
        if lag > 1 and abs(val) > 0.3:
            significant_lags.append({'lag': lag, 'acf': round(float(val), 3)})

    has_periodicity = len(significant_lags) > 0
    dw = float(np.sum((residuals[1:] - residuals[:-1])**2) / np.sum(residuals**2)) if np.sum(residuals**2) > 0 else 2.0

    return {
        'dw': round(dw, 3),
        'acf_lag1': round(float(acf[0]), 3) if len(acf) > 0 else None,
        'significant_lags': significant_lags,
        'has_periodicity': has_periodicity,
        'max_lag_checked': max_lag,
    }, None


# ============================================================================
# Tier 1 准则（必须满足）
# ============================================================================

def tier1_chi2(reps, dof):
    """Tier 1-A: χ²_red 分级评估

    分级阈值:
      < 0.05      → ❌ 不通过（严重过拟合或误差估计严重偏大）
      0.05 – 0.2  → ⚠️ 良好，建议检查误差估计
      0.2 – 2.0   → ✅ 正常
      2.0 – 5.0   → ⚠️ 可接受，需结合残差判断
      5.0 – 10.0  → ⚠️ 较差，需检查数据
      > 10.0      → ❌ 不通过（拟合失败）
    """
    best = min(reps, key=lambda r: r['gof'])
    val = best['chi2_red']

    if val <= 0.05:
        passed = False
        quality = 'reject_low'
        quality_label = '不通过（过低）'
    elif val <= 0.2:
        passed = True
        quality = 'good_low'
        quality_label = '良好，建议检查误差估计'
    elif val <= 2.0:
        passed = True
        quality = 'normal'
        quality_label = '正常'
    elif val <= 5.0:
        passed = True
        quality = 'acceptable'
        quality_label = '可接受，需结合残差判断'
    elif val <= 10.0:
        passed = True
        quality = 'poor'
        quality_label = '较差，需检查数据'
    else:
        passed = False
        quality = 'reject_high'
        quality_label = '不通过（过高）'

    return {
        'pass': passed,
        'value': round(val, 4),
        'threshold': '0.05 < χ²_red ≤ 10',
        'quality': quality,
        'quality_label': quality_label,
        'detail': f"Best rep #{best['index']}: raw_χ²={best['gof']:.2f}, doF={dof}, χ²_red={val:.4f} → {quality_label}",
        'best_rep': best['index'],
    }


def tier1_residuals(reps, fit_q, data_i, data_sigma):
    """Tier 1-B: 残差随机无明显周期性"""
    best = min(reps, key=lambda r: r['gof'])
    model_scaled = best['model_i'] * best['x0'][0] + best['x0'][1]

    n = min(len(data_i), len(model_scaled))
    with np.errstate(divide='ignore', invalid='ignore'):
        residuals = np.where(
            (data_sigma[:n] > 0) & np.isfinite(data_sigma[:n]),
            (data_i[:n] - model_scaled[:n]) / data_sigma[:n],
            np.nan
        )
    finite_res = residuals[np.isfinite(residuals)]

    if len(finite_res) < 20:
        return {'pass': True, 'value': None, 'threshold': 'DW≈2, no periodicity',
                'detail': "有效残差点不足，跳过残差检验"}

    ac_result, ac_error = _autocorrelation_check(finite_res)
    if ac_error:
        return {'pass': True, 'value': None, 'threshold': 'DW≈2, no periodicity',
                'detail': ac_error}

    dw = ac_result['dw']
    has_period = ac_result['has_periodicity']
    dw_ok = 1.2 < dw < 2.5
    passed = dw_ok and not has_period

    issues = []
    if not dw_ok:
        if dw <= 1.0:
            issues.append("正自相关（残差系统性结构）")
        elif dw <= 1.2:
            issues.append("轻微正自相关")
        elif dw >= 3.0:
            issues.append("负自相关（可能过拟合）")
        else:
            issues.append("轻微负自相关")
    if has_period:
        issues.append(f"检测到周期性（lag={[s['lag'] for s in ac_result['significant_lags']]}）")

    return {
        'pass': passed,
        'value': dw,
        'threshold': 'DW∈(1.2,2.5) 且无周期性',
        'detail': f"DW={dw:.3f}" + (f", {'; '.join(issues)}" if issues else ", 残差随机"),
        'dw': dw,
        'has_periodicity': has_period,
        'acf_lag1': ac_result['acf_lag1'],
    }


def tier1_boundary(reps, radius_min, radius_max):
    """Tier 1-C: 主峰不是边界峰"""
    result = _histogram_peaks(reps, radius_min, radius_max)
    if result[0] is None:
        return {'pass': False, 'value': None, 'threshold': '不在边界',
                'detail': "无法计算直方图"}

    mean_hist, main_peak, main_bin, bin_centers, *_ = result
    is_lower = (main_bin == 0)
    is_upper = (main_bin == N_HIST_BINS - 1)
    passed = not (is_lower or is_upper)

    if is_lower:
        problem = f"主峰位于 R_min 边界 ({radius_min} nm)"
    elif is_upper:
        problem = f"主峰位于 R_max 边界 ({radius_max} nm)"
    else:
        problem = None

    return {
        'pass': passed,
        'value': round(main_peak, 1),
        'threshold': f'不在 [{radius_min}, {radius_max}] 边缘',
        'detail': f"主峰 {main_peak:.1f} nm (bin {main_bin+1}/{N_HIST_BINS})" + (f" — ⚠ {problem}" if problem else " — OK"),
        'is_at_lower': is_lower,
        'is_at_upper': is_upper,
        'main_peak': round(main_peak, 1),
    }


# ============================================================================
# Tier 2 准则（建议满足，需要跨迭代历史）
# ============================================================================

def tier2_radius_stability(reps, radius_min, radius_max, history=None):
    """Tier 2-A: 改变 radius 范围后主峰稳定（变化 < 5%）"""
    result = _histogram_peaks(reps, radius_min, radius_max)
    if result[0] is None:
        return {'pass': True, 'value': None, 'threshold': '< 5%',
                'detail': "无法计算（无直方图数据）", 'n/a': True}

    current_peak = result[1]

    if history is None:
        return {'pass': True, 'value': None, 'threshold': '< 5%',
                'detail': "首轮迭代，尚无历史数据可比较。后续改变 radius 范围后将自动检测峰位稳定性。",
                'pending': True}

    # 查找历史中 radius 范围不同的迭代
    comparisons = []
    for it in history.get('iterations', []):
        p = it.get('params', {})
        hist_rmin = p.get('radius_min')
        hist_rmax = p.get('radius_max')
        if hist_rmin is None or hist_rmax is None:
            continue
        if (hist_rmin != radius_min or hist_rmax != radius_max):
            hist_peak = it.get('evaluation', {}).get('peaks', {}).get('main')
            if hist_peak is not None:
                shift_pct = abs(current_peak - hist_peak) / hist_peak * 100
                comparisons.append({
                    'iter': it['iteration'],
                    'radius': [hist_rmin, hist_rmax],
                    'peak': hist_peak,
                    'shift_pct': round(shift_pct, 1),
                    'stable': shift_pct < 5.0,
                })

    if not comparisons:
        return {'pass': True, 'value': None, 'threshold': '< 5%',
                'detail': "尚无不同 radius 范围的迭代可比较。",
                'pending': True}

    all_stable = all(c['stable'] for c in comparisons)
    max_shift = max(c['shift_pct'] for c in comparisons)

    return {
        'pass': all_stable,
        'value': round(max_shift, 1),
        'threshold': '< 5%',
        'detail': (
            f"与 {len(comparisons)} 个不同 radius 范围的迭代比较，"
            f"最大主峰偏移 {max_shift:.1f}% → "
            f"{'稳定' if all_stable else '不稳定'}"
        ),
        'comparisons': comparisons,
        'all_stable': all_stable,
    }


def tier2_ncontrib_stability(reps, radius_min, radius_max, history=None):
    """Tier 2-B: 改变 nContrib 后主峰稳定（变化 < 5%）"""
    result = _histogram_peaks(reps, radius_min, radius_max)
    if result[0] is None:
        return {'pass': True, 'value': None, 'threshold': '< 5%',
                'detail': "无法计算", 'n/a': True}

    current_peak = result[1]

    if history is None:
        return {'pass': True, 'value': None, 'threshold': '< 5%',
                'detail': "首轮迭代，尚无历史数据可比较。后续改变 nContrib 后将自动检测峰位稳定性。",
                'pending': True}

    comparisons = []
    for it in history.get('iterations', []):
        p = it.get('params', {})
        hist_nc = p.get('nContrib')
        if hist_nc is None or hist_nc == p.get('nContrib', 'unknown'):
            continue
        if hist_nc != p.get('nContrib'):
            # Wait, we need to know what the CURRENT nContrib is. It's not in evaluate_fit.py arguments.
            # We compare ALL previous iterations regardless.
            pass

    # Actually, we don't have current nContrib as a CLI arg. Let's compare against all
    # previous iterations that have different evaluation results, and infer nContrib from params.
    # Simpler: just compare current peak against all previous iterations' peaks.
    if not history.get('iterations'):
        return {'pass': True, 'value': None, 'threshold': '< 5%',
                'detail': "尚无历史迭代可比较。", 'pending': True}

    # Find iterations with different nContrib
    # We need current nContrib — let's get it from the most recent iteration's params
    # Actually, we don't have current nContrib passed in. Let me rethink.

    # For now, if we have history, compare against ALL previous iterations.
    # If the peak is stable across ALL of them, it certainly includes nContrib changes.
    comparisons = []
    current_peak_val = float(current_peak)
    for it in history.get('iterations', []):
        hist_peak = it.get('evaluation', {}).get('peaks', {}).get('main')
        if hist_peak is not None and hist_peak != current_peak_val:
            shift_pct = abs(current_peak_val - hist_peak) / hist_peak * 100
            comparisons.append({
                'iter': it['iteration'],
                'peak': hist_peak,
                'shift_pct': round(shift_pct, 1),
                'stable': shift_pct < 5.0,
            })

    if not comparisons:
        return {'pass': True, 'value': None, 'threshold': '< 5%',
                'detail': "无历史数据可比较，后续迭代将自动检测。", 'pending': True}

    all_stable = all(c['stable'] for c in comparisons)
    max_shift = max(c['shift_pct'] for c in comparisons)

    return {
        'pass': all_stable,
        'value': round(max_shift, 1),
        'threshold': '< 5%',
        'detail': (
            f"与 {len(comparisons)} 个历史迭代比较，"
            f"最大主峰偏移 {max_shift:.1f}% → "
            f"{'稳定' if all_stable else '不稳定'}"
        ),
        'comparisons': comparisons,
        'all_stable': all_stable,
    }


# ============================================================================
# Tier 3 准则（加分项）
# ============================================================================

def tier3_resolvable_range(reps, radius_min, radius_max, data_file_path):
    """Tier 3-A: 主峰在 Q 范围可解析尺寸内"""
    result = _histogram_peaks(reps, radius_min, radius_max)
    if result[0] is None:
        return {'pass': True, 'value': None, 'threshold': 'ℹ 加分项',
                'detail': "无法计算直方图"}

    main_peak = result[1]
    try:
        q, _, _ = load_saxs_data(data_file_path)
        q_valid = q[q > 0]
        q_min, q_max = float(np.min(q_valid)), float(np.max(q_valid))
        # Q 的单位是 nm⁻¹（McSAS 默认），R = π/Q 直接得到 nm
        R_lo = math.pi / q_max   # nm
        R_hi = 2.0 * math.pi / q_min  # nm
    except Exception:
        return {'pass': True, 'value': round(main_peak, 1),
                'threshold': f'ℹ [{R_lo:.1f}, {R_hi:.1f}]',
                'detail': "无法读取 Q 范围"}

    in_range = R_lo < main_peak < R_hi
    return {
        'pass': in_range,
        'value': round(main_peak, 1),
        'threshold': f'[{R_lo:.1f}, {R_hi:.1f}]',
        'detail': f"主峰 {main_peak:.1f} nm {'在' if in_range else '超出'}可解析范围 [{R_lo:.1f}, {R_hi:.1f}] nm",
    }


def tier3_nrep(n_rep):
    """Tier 3-B: nRep > 20"""
    passed = n_rep > 20
    return {
        'pass': passed,
        'value': n_rep,
        'threshold': '> 20（发表级）',
        'detail': f"nRep={n_rep}" + (" ✓ 发表级" if passed else "（建议≥20用于发表）"),
    }


# ============================================================================
# 编排
# ============================================================================

def evaluate(nxs_path, data_file_path, radius_min, radius_max, history=None, current_params=None):
    """
    三级评估。

    Returns dict with:
      tiers: {tier1_must, tier2_should, tier3_bonus}
      verdict: 'pass' | 'tier1_fail' | 'tier2_partial'
      blocking: bool — True if Tier 1 failures require adjustment
    """
    try:
        data = load_nxs_for_evaluation(nxs_path)
    except (OSError, KeyError, ValueError) as e:
        return {
            'verdict': 'fatal',
            'blocking': True,
            'fatal': True,
            'error': str(e),
            'summary': f"无法读取 results.nxs: {e}",
        }

    reps = data['reps']
    dof = data['dof']

    # 致命检查
    all_gof = [r['gof'] for r in reps]
    if all(np.isnan(g) or np.isinf(g) for g in all_gof):
        return {
            'verdict': 'fatal', 'blocking': True, 'fatal': True,
            'error': 'degenerate_fit',
            'detail': "所有 repetition χ² = NaN/Inf",
            'summary': "拟合完全失败",
        }

    # ===== Tier 1: 必须满足 =====
    t1_chi2 = tier1_chi2(reps, dof)
    t1_boundary = tier1_boundary(reps, radius_min, radius_max)

    # ===== 参考信息：残差分析（不参与通过/失败判定）=====
    t1_residuals = tier1_residuals(reps, data['fit_q'], data['data_i'], data['data_sigma'])

    tier1_all_pass = t1_chi2['pass'] and t1_boundary['pass']
    t1_failed = [k for k, c in [('chi2', t1_chi2), ('boundary', t1_boundary)] if not c['pass']]

    # ===== Tier 2: 建议满足 =====
    t2_radius_stab = tier2_radius_stability(reps, radius_min, radius_max, history)
    t2_nc_stab = tier2_ncontrib_stability(reps, radius_min, radius_max, history)

    tier2_all_pass = t2_radius_stab['pass'] and t2_nc_stab['pass']

    # ===== Tier 3: 加分项 =====
    t3_resolvable = tier3_resolvable_range(reps, radius_min, radius_max, data_file_path)
    t3_nrep = tier3_nrep(data['n_rep'])

    # ===== 综合判定 =====
    if tier1_all_pass:
        if tier2_all_pass:
            verdict = 'pass'
        else:
            verdict = 'tier2_partial'
        blocking = False
    else:
        verdict = 'tier1_fail'
        blocking = True

    # 调整建议
    adjustments = []
    chi2_quality = t1_chi2.get('quality', 'unknown')
    chi2_val = t1_chi2['value']

    if not t1_chi2['pass']:
        # blocking 级别不通过
        if chi2_quality == 'reject_low':
            suggestions = ['检查 Isigma 是否合理（误差估计可能严重偏大）',
                          '检查 dataRange 是否过窄导致过拟合',
                          '检查 nRep 是否太少导致偶然低 χ²']
        else:  # reject_high
            suggestions = ['增大 maxIter 改善收敛',
                          '检查 modelName 是否匹配粒子形状',
                          '检查数据质量（噪声、异常点）']
        adjustments.append({
            'tier': 1, 'criterion': 'chi2',
            'problem': 'chi2_out_of_range',
            'action': 'adjust_fit_params',
            'reason': f"χ²_red={chi2_val:.4f} — {t1_chi2['quality_label']}",
            'suggestions': suggestions,
        })
    elif chi2_quality in ('good_low', 'acceptable', 'poor'):
        # 非 blocking 但有建议
        if chi2_quality == 'good_low':
            suggestions = ['检查 Isigma 是否合理（误差估计可能偏大）']
        elif chi2_quality == 'acceptable':
            suggestions = ['建议增大 maxIter 改善收敛', '结合残差结果综合判断']
        else:  # poor
            suggestions = ['检查数据质量', '检查 modelName 是否匹配', '考虑调整 dataRange']
        adjustments.append({
            'tier': 1, 'criterion': 'chi2',
            'problem': f'chi2_{chi2_quality}',
            'action': 'warn_only',
            'reason': f"χ²_red={chi2_val:.4f} — {t1_chi2['quality_label']}",
            'suggestions': suggestions,
        })

    if not t1_residuals['pass']:
        suggestions = []
        if t1_residuals.get('dw', 2.0) < 1.2:
            suggestions.append('DW 偏低，残差可能有系统性趋势（SAXS 中常见，不一定表示拟合失败）')
        if t1_residuals.get('has_periodicity'):
            suggestions.append('残差有周期性，可尝试调整 dataRange 截断高 Q 噪声区')
        adjustments.append({
            'tier': 0, 'criterion': 'residuals',
            'problem': 'systematic_residuals',
            'action': 'warn_only',  # 参考信息，不阻塞
            'reason': f"DW={t1_residuals.get('dw', '?')}（仅供参考，不阻塞）",
            'suggestions': suggestions or ['DW 偏离理想值，但不作为必须调整条件'],
        })
    if not t1_boundary['pass']:
        if t1_boundary.get('is_at_upper'):
            new_rmax = min(int(math.ceil(radius_max * 1.5 / 5) * 5), 500)
            adjustments.append({
                'tier': 1, 'criterion': 'boundary',
                'problem': 'boundary_at_rmax',
                'action': 'expand_radius_max',
                'reason': f"主峰触碰 R_max={radius_max} nm，扩大至 {new_rmax} nm",
                'changes': {'radius_max': new_rmax},
            })
        elif t1_boundary.get('is_at_lower'):
            new_rmin = max(int(math.floor(radius_min * 0.5)), 0)
            adjustments.append({
                'tier': 1, 'criterion': 'boundary',
                'problem': 'boundary_at_rmin',
                'action': 'lower_radius_min',
                'reason': f"主峰触碰 R_min={radius_min} nm，降低至 {new_rmin} nm",
                'changes': {'radius_min': new_rmin},
            })

    # Tier 2 建议（不阻塞）
    tier2_suggestions = []
    if not t2_radius_stab.get('pass') and not t2_radius_stab.get('pending'):
        tier2_suggestions.append({
            'tier': 2, 'criterion': 'radius_stability',
            'detail': t2_radius_stab['detail'],
            'suggestion': '峰位随 radius 范围变化，建议增大 nRep 确认稳定性',
        })
    if not t2_nc_stab.get('pass') and not t2_nc_stab.get('pending'):
        tier2_suggestions.append({
            'tier': 2, 'criterion': 'ncontrib_stability',
            'detail': t2_nc_stab['detail'],
            'suggestion': '峰位随 nContrib 变化，建议增大 nRep 确认稳定性',
        })

    # 主峰信息
    peaks_info = {'main': t1_boundary.get('main_peak')}
    best = min(reps, key=lambda r: r['gof'])

    return {
        'verdict': verdict,
        'blocking': blocking,
        'fatal': False,
        'best_rep': best['index'],
        'dof': dof,
        'n_rep': data['n_rep'],
        'best_chi2_red': round(best['chi2_red'], 4),
        'peaks': peaks_info,
        'tiers': {
            'tier1_must': {
                'label': '必须满足',
                'all_pass': tier1_all_pass,
                'failed': t1_failed,
                'criteria': {
                    'chi2': {'label': 'χ²_red ∈ (0.05, 10]', **t1_chi2},
                    'boundary': {'label': '主峰非边界峰', **t1_boundary},
                },
            },
            'tier2_should': {
                'label': '建议满足',
                'all_pass': tier2_all_pass,
                'criteria': {
                    'radius_stability': {'label': '改变radius后主峰稳定(<5%)', **t2_radius_stab},
                    'ncontrib_stability': {'label': '改变nContrib后主峰稳定(<5%)', **t2_nc_stab},
                },
                'suggestions': tier2_suggestions,
            },
            'tier3_bonus': {
                'label': '加分项',
                'criteria': {
                    'resolvable_range': {'label': '主峰在可解析范围内', **t3_resolvable},
                    'nrep_sufficient': {'label': 'nRep > 20', **t3_nrep},
                },
            },
        },
        'residuals': {
            'label': '残差分析（参考信息，不参与通过/失败判定）',
            **t1_residuals,
        },
        'adjustments': adjustments,
        'summary': (
            "✅ 核心条件满足，拟合可靠。" if verdict == 'pass'
            else "⚠️ 核心条件满足，建议进一步优化。" if verdict == 'tier2_partial'
            else f"❌ {len(t1_failed)} 项核心条件不满足，必须调整: {', '.join(t1_failed)}"
        ),
    }


# ============================================================================
# stderr 摘要
# ============================================================================

def print_human_summary(result):
    lines = []
    verdict = result['verdict']
    if verdict == 'fatal':
        lines.append("[evaluate_fit] 💀 FATAL")
        lines.append(f"[evaluate_fit] {result.get('summary', '')}")
    else:
        icon = '✅' if verdict == 'pass' else '⚠️' if verdict == 'tier2_partial' else '❌'
        lines.append(f"[evaluate_fit] {icon} VERDICT: {verdict} | blocking={result['blocking']}")

        for tier_key in ['tier1_must', 'tier2_should', 'tier3_bonus']:
            tier = result['tiers'][tier_key]
            lines.append(f"[evaluate_fit]")
            lines.append(f"[evaluate_fit] ── {tier['label']} ──")
            for key, c in tier['criteria'].items():
                icon = '✅' if c['pass'] else '⬜' if c.get('pending') else '❌'
                lines.append(f"[evaluate_fit]   {icon} {c['label']}: {c['detail']}")

        # 参考信息：残差分析
        if result.get('residuals'):
            res = result['residuals']
            lines.append(f"[evaluate_fit]")
            lines.append(f"[evaluate_fit] ── {res['label']} ──")
            icon = 'ℹ️'
            lines.append(f"[evaluate_fit]   {icon} {res.get('label', '残差分析')}: {res.get('detail', '')}")

        if result.get('adjustments'):
            blocking_adjs = [a for a in result['adjustments'] if a['tier'] == 1]
            ref_adjs = [a for a in result['adjustments'] if a['tier'] == 0]
            if blocking_adjs:
                lines.append(f"[evaluate_fit]")
                lines.append(f"[evaluate_fit] Tier 1 调整建议 ({len(blocking_adjs)}):")
                for adj in blocking_adjs:
                    lines.append(f"[evaluate_fit]   → {adj['reason']}")
            if ref_adjs:
                lines.append(f"[evaluate_fit] 参考信息:")
                for adj in ref_adjs:
                    lines.append(f"[evaluate_fit]   ℹ️ {adj['reason']}")

    for line in lines:
        print(line, file=sys.stderr)


# ============================================================================
# CLI
# ============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='McSAS 拟合结果评估')
    parser.add_argument('nxs_path', help='results.nxs 路径')
    parser.add_argument('data_file_path', help='原始数据文件路径')
    parser.add_argument('radius_min', type=float, help='半径下限 (nm)')
    parser.add_argument('radius_max', type=float, help='半径上限 (nm)')
    parser.add_argument('--history', default=None, help='iteration_history.json 路径（用于 Tier 2 跨迭代比较）')

    args = parser.parse_args()

    if not os.path.exists(args.nxs_path):
        print(f"Error: results.nxs not found: {args.nxs_path}", file=sys.stderr)
        sys.exit(1)

    history = None
    if args.history and os.path.exists(args.history):
        try:
            with open(args.history) as f:
                history = json.load(f)
        except Exception:
            pass

    result = evaluate(args.nxs_path, args.data_file_path,
                      args.radius_min, args.radius_max, history=history)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print_human_summary(result)
