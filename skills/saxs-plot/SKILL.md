---
name: saxs-plot
description: |
  绘制 SAXS 数据的 Log-Log 散射曲线图。
  当用户提到"画SAXS图"、"绘制散射曲线"、"SAXS可视化"、"log图"时触发。
allowed-tools: Read, Bash, Write
---

# SAXS 数据可视化规则

## 数据格式

`data/` 目录下的 SAXS 数据为三列制表符分隔：
- **Q** — 散射矢量 (nm⁻¹)
- **I** — 散射强度
- **Isigma** — 强度误差

## 绘图类型

### Log-Log 散射曲线
- X 轴：Q (对数坐标)
- Y 轴：I (对数坐标)
- 同时绘制误差棒 (Isigma)
- 用途：展示散射曲线的整体形态

### McSAS 拟合结果图
- X 轴：Q (对数坐标)
- Y 轴：I (对数坐标)
- 原始数据散点 + 误差棒
- 最优 McSAS 模型拟合曲线（χ² 最小的那条，标注 χ² 值）
- **注意**：`modelI` 需用 `x0` 参数缩放（`modelI * x0[0] + x0[1]`），否则与数据不在同一尺度
- 用途：评估拟合质量，直观判断模型与数据的吻合程度

### 粒径分布直方图
- X 轴：Radius (nm)
- Y 轴：Volume-weighted Distribution
- **左图 Mean**：多 repetition 均值 + 标准差误差棒（SAXS 标准做法）
- **右图 Best**：最优单次重复结果（标注 χ²），便于对比
- **峰值（mode）** 标注在图例中，代表体积加权最可几半径——样品中占主导地位的颗粒尺寸
- Y 轴缩放对齐 McSAS 内置逻辑：`counts * x0[0] * 1e-5`，不带 weights
- Nature 期刊风格配色：muted blue (`#4477AA`) + muted rose (`#CC6677`)
- 四周边框完整，DPI 300

## 脚本

- `plot_saxs.py` — 原始数据 Log-Log 散射曲线
- `plot_fit.py` — McSAS 拟合结果可视化（最优拟合 + 数据对比）
- `plot_histogram.py` — 粒径分布直方图（Mean vs Best 双图对比，峰值标注）

## 运行环境

**本项目所有 Python 脚本必须在 `mcsas` conda 环境中运行。** 执行任何命令前，务必先激活环境：

```bash
conda activate mcsas
```

## 使用方式举例

```bash
# 原始数据绘图 — plot_saxs.py 会自动在非绝对路径前加 data/ 前缀
python3 plot_saxs.py A-SiO2-1C-2.txt              # ✅ 只传文件名，自动找到 data/A-SiO2-1C-2.txt
python3 plot_saxs.py /abs/path/to/data/xxx.txt    # ✅ 绝对路径直接使用，不拼接
# python3 plot_saxs.py data/A-SiO2-1C-2.txt       # ❌ 错误！会变成 data/data/A-SiO2-1C-2.txt

# 拟合结果绘图
python3 plot_fit.py results/xxx/mcsas_results/results.nxs images/

# 粒径分布直方图
python3 plot_histogram.py results/xxx/mcsas_results/results.nxs images/ --radius-min 10 --radius-max 80
```

## 注意事项

- **路径陷阱（重要）**：`plot_saxs.py` 第 74 行自动在非绝对路径前拼接 `data/`。只传裸文件名（`SiO2-1C.txt`）或绝对路径，**严禁**传 `data/xxx.txt`，否则变成 `data/data/xxx.txt`
- **必须**先执行 `conda activate mcsas`，否则 numpy/matplotlib/h5py 不可用
- 如果中文无法显示，改为英文标签
- 拟合图仅展示 χ² 最优的那条曲线
- 直方图 Y 轴缩放必须对齐 McSAS 源码：`counts * x0[0] * correctionFactor(1e-5)`
- 直方图**不带 weights**（贡献本身已隐含体积加权），不要画蛇添足做二次 volume weighting
