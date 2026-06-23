---
name: mcsas-analysis
description: |
  使用 McSAS 进行 SAXS 数据的粒径分布分析。
  当用户提到"粒径分析"、"粒径分布"、"McSAS"、"mcsas"、"颗粒尺寸"、"size distribution"时触发。
allowed-tools: Read, Bash, Write
---

# McSAS 粒径分析规则

## 交互规范（必须遵守）

1. **开场概览**：在步骤 1 之前，先向用户展示全部 6 个步骤的概览，让用户知道整体流程包含「自主设定参数 → 迭代拟合优化 → 结果评估」闭环。
2. **步骤开头说明**：每个步骤开始时，用中文交代这一步在做什么、为什么需要做。
3. **用户操作提示**：需要用户确认或选择时，用清晰的中文提示，列出选项和推荐值。
4. **步骤结束进度条**：每个步骤完成后，打印如下格式的进度条：

```
╔══════════════════════════════════════════════════╗
║  ✅ 步骤 1/6 已完成                              ║
║  ✅ 步骤 2/6 已完成（创建工作目录 + 读取数据）        ║
║  🔄 步骤 3-5：迭代优化（第 2/5 轮进行中）          ║
║  ⬜ 步骤 6/6：最终结果汇总                        ║
╚══════════════════════════════════════════════════╝
```

## 六步流程概览

| 步骤 | 名称 | 说明 |
|------|------|------|
| 1 | 选择数据文件 | 列出 `data/` 下可用文件，用户选择 |
| 2 | 创建工作目录 + 读取数据 | 创建运行目录、读取数据绘制 Log-Log 散射曲线 |
| 3 | 自主设定拟合参数 + 写入参数配置文件 | 自动估计 McSAS 初始参数 + 创建/更新参数配置文件；后续轮应用评估结果自动调整 |
| 4 | McSAS 拟合  | 蒙特卡洛拟合  |
| 5 | 拟合结果评估 + 优化决策 |每轮展示拟合曲线和粒径分布直方图，并依据三级评估标准决策下一轮迭代， Tier 1 必须 → 决定去留；Tier 2 建议；Tier 3 加分 |
| 6 | 最终结果汇总 | 迭代历史 + 最终指标 + 完整报告 |

### 迭代闭环

```
步骤 2: 创建工作目录 + 读取数据
    ↓
步骤 3: 拟合参数设定 + 配置文件 ─────┐
    ↓                            │
步骤 4: McSAS 拟合                │ 
    ↓                            │ 回到步骤 3
步骤 5: 结果评估 + 调整参数         │
    ├─ Tier 1 通过 → 步骤 6       │
    ├─ Tier 1 失败 → 展示调整    ──┘
    └─ 致命错误 → 提示用户手动干预
```

- **最大迭代次数**：5 轮（防止无限循环）
- **每轮记录**：参数、评估结果、调整措施 写入 `iteration_history.json`
- **振荡检测**：同一参数上轮调大、本轮需调小（或反之）→ 警告用户，建议接受最优轮次

---

## 步骤 1：选择数据文件

**开场**：首先向用户展示完整流程概览（上表），强调本流程包含自动迭代优化。然后执行步骤 1。

用 `ls data/` 列出 `.txt` 文件，以表格展示：

```
| # | 文件名 | 说明（文件创建日期） |
|---|--------|------|
| 1 | xxx.txt | ... |
| 2 | yyy.txt | ... |
```

用中文提示：「请选择要分析的数据文件，输入数字编号:」

用户选择后，记录文件名，打印进度条进入步骤 2。

---

## 步骤 2：创建工作目录 + 读取数据

**说明**：创建独立运行目录，读取数据并绘制 SAXS Log-Log 散射曲线查看数据质量和 Q 范围，为后续参数估计和拟合做准备。

### 2.1 创建工作目录

```
「将为本次分析创建工作目录： results/{filename}_{YYYYMMDD_HHMMSS}/ 」
```

```bash
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
RUN_DIR="results/{filename}_{TIMESTAMP}"
mkdir -p "${RUN_DIR}/images"
mkdir -p "${RUN_DIR}/mcsas_results"
```

同时创建空的迭代历史文件：

```json
// {RUN_DIR}/iteration_history.json
{
  "data_file": "{datafile_absolute_path}",
  "max_iterations": 5,
  "started_at": "{ISO timestamp}",
  "iterations": []
}
```

记录变量：`RUN_DIR`、`DATAFILE_PATH`、`ITERATION=0`（进入步骤 3 时递增为 1）。

### 2.2 读取并查看数据（Log-Log散射曲线可视化）

```
「显示 SAXS 数据文件：{filename}」
```

```bash
conda activate mcsas && python3 skills/saxs-plot/plot_saxs.py {datafile_absolute_path} {run_dir}/images
```

> **⚠️ 路径陷阱**：`plot_saxs.py` 内部会自动在非绝对路径前拼接 `data/`。**必须传绝对路径**。

输出：`{run_dir}/images/{filename}_loglog.png`

打印进度条（步骤 2 完成，标注「创建工作目录 + 读取数据」），进入步骤 3。

---

## 步骤 3：自主设定拟合参数 **[循环入口]**

**说明**：McSAS 拟合需要两类配置文件：**数据读取参数**（read_config.yaml，告诉 McSAS 如何读取数据）和 **模型拟合参数**（run_config.yaml，控制粒径拟合模型）。本章节遵循「先告知 → 创建模板副本 → 先数据读取参数，后模型拟合参数」的清晰流程，让用户对每一步在做什么有明确的体验。

---

### 分支 A：首轮（ITERATION = 0，首次进入步骤 3）

#### 3.1 告知用户两类参数

进入步骤 3 时，首先向用户说明两类参数的概念：

```
「McSAS 拟合需要两类配置参数：

  📖 **数据读取参数** (`read_config.yaml`)：告诉 McSAS 如何读取数据文件
     — 分隔符、列名、Q 值范围（dataRange）、统计分辨率（nbins）
  ⚙️ **模型拟合参数** (`run_config.yaml`)：控制粒径拟合模型
     — 半径范围、球模型、蒙特卡洛迭代次数（maxIter）、重复次数（nRep）

下面我先基于 `template/config/` 模板创建两份配置文件，然后逐一与你确认参数值。」
```

#### 3.2 从模板创建两份配置文件

```bash
mkdir -p {run_dir}/config
mkdir -p {run_dir}/iteration_1/config
```

**步骤**：
1. 读取 `template/config/read_config.yaml` 模板，同时读取数据文件前几行确认格式（分隔符、表头、列名），将 csvargs 调整为匹配实际数据后写入 `{run_dir}/config/read_config.yaml`
2. 读取 `template/config/run_config.yaml` 模板，原样写入 `{run_dir}/config/run_config.yaml`

告知用户：

```
「✅ 两份配置模板已从 `template/config/` 创建：
  • {run_dir}/config/read_config.yaml  — 数据读取参数（csvargs 已匹配数据文件格式）
  • {run_dir}/config/run_config.yaml   — 模型拟合参数（待后续参数估计更新）

接下来逐一确定这两份配置中的参数值，先确定「数据读取参数」，再确定「模型拟合参数」。」
```

#### 3.3 确定「数据读取参数」（read_config.yaml）

**说明**：首先确定数据读取参数。告知用户每个参数的含义：

```
「📖 第一步：确定「数据读取参数」

| 参数 | 当前值 | 说明 |
|------|--------|------|
| `nbins` | 100 | 原始数据重新划分的统计区间数。50–200，数据平稳→50 提高速度，数据波动剧烈→200 保留细节 |
| `dataRange` | [0.0, inf] | 指定用于拟合的 Q 值范围。可设上界排除高 Q 噪声（如 [0.0, 0.5]） |

是否需要调整上述数据读取参数？
  • 直接回复 **「不改」** 使用默认值
  • 或指定修改，如 `nbins=150`、`dataRange=[0.0, 0.5]`」
```

用户确认后：
- 更新 `{run_dir}/config/read_config.yaml`（如有修改）
- 复制到 `{run_dir}/iteration_1/config/read_config.yaml` 存档
- 告知：「✅ 数据读取参数已确定」

#### 3.4 确定「模型拟合参数」（run_config.yaml）— 自动参数估计

**说明**：数据读取参数确定后，进入模型拟合参数。基于 SAXS 物理原理从实验数据自动计算推荐值。

**核心原理**：
- **粒径范围**：`R_max = π/Q_min`（nm，下限 100 nm），`R_min = π/Q_max`（nm，下限 1 nm）
- **nContrib**：按 Q 范围 decade 数粗粒度分档（<1→200, 1-2→300, 2-3→400, ≥3→500）
- **nRep**：初始探索固定为 2

```bash
conda activate mcsas && python3 skills/mcsas-analysis/auto_params.py {datafile_absolute_path}
```

展示自动估计结果：

```
「⚙️ 第二步：确定「模型拟合参数」

根据你的实验数据，自动估计的推荐参数如下：

| 参数 | 推荐值 | 含义 | 计算依据 |
|------|--------|------|----------|
| `modelName` | `”sphere”` | 散射模型 | 球模型（默认） |
| `nContrib` | **{auto_nContrib}** | 粒子贡献数 | Q 范围 {q_decades} decades → 粗粒度分档 |
| `fitParameterLimits.radius` | **[{auto_Rmin}, {auto_Rmax}]** | 半径范围 (nm) | R_max=π/Q_min (下限100nm), R_min=π/Q_max (下限1nm) |
| `maxIter` | `100000` | 单次 MC 最大迭代步数 | 标准值 |
| `nRep` | `2` | 独立重复次数 | 初始测试固定 |

📐 **自动估计说明**：
  • 半径范围：R_max = π/{q_min} ≈ {R_max_raw} nm（下限 100 nm），R_min = π/{q_max} ≈ {R_min_raw} nm（下限 1 nm）
  • nContrib：按 Q 范围分档（<1 decade→200, 1-2→300, 2-3→400, ≥3→500）
  • 数据质量：**{data_quality}**（中位 S/N = {median_snr}，数据点数 = {n_points}）
  {如有 warnings，在此展示}

⚠️ **参数设置提醒**：`maxIter` 和 `nRep` 直接影响拟合总耗时。`nRep=2, maxIter=100000` 适合快速测试。

直接回复 **「不改」** 使用自动估计值，或告诉我需要修改的参数。例如：`nContrib=400` 或 `radius=[5, 80]`」
```

用户确认后：
- 将确认的参数值写入 `{run_dir}/config/run_config.yaml`：
  - `nContrib` → `{AUTO_PARAMS.n_contrib}`
  - `fitParameterLimits.radius` → `[{AUTO_PARAMS.radius_min}, {AUTO_PARAMS.radius_max}]`
  - `nRep` → `2`
- 复制到 `{run_dir}/iteration_1/config/run_config.yaml` 存档
- 告知：「✅ 模型拟合参数已确定」

#### 3.5 参数设定完成汇总

```
「✅ 步骤 3 参数设定完成！

  📖 数据读取参数：nbins={nbins}, dataRange={dataRange}
  ⚙️ 模型拟合参数：radius=[{rmin}, {rmax}], nContrib={ncontrib}, nRep={nrep}, maxIter={maxIter}

准备进入步骤 4：McSAS 蒙特卡洛拟合...」
```

记录本轮参数到 `iteration_history.json` 的 `iterations[0].params`，打印进度条，进入步骤 4。

---

### 分支 B：后续迭代（ITERATION > 1）

**说明**：后续迭代中，**数据读取参数**（read_config.yaml）通常保持不变；调整主要针对 **模型拟合参数**（run_config.yaml）。根据评估引擎的输出自动生成调整方案，并交由用户确认。

#### 3.B.1 告知用户本轮为参数调整

```
「📋 第 {N} 轮参数设定（基于第 {N-1} 轮评估结果）

数据读取参数（read_config.yaml）保持不变。
模型拟合参数（run_config.yaml）根据评估结果自动调整如下：」
```

#### 3.B.2 应用评估调整

从步骤 5 评估结果的 `adjustments` 字段中获取调整建议，自动应用到 `{run_dir}/config/run_config.yaml`：

| adjustment.action | 修改的配置文件 | 修改的键 | 规则 |
|---|---|---|---|
| `increase_maxIter` | `run_config.yaml` | `maxIter` | 替换为新值（×2） |
| `expand_radius_max` | `run_config.yaml` | `fitParameterLimits.radius[1]` | 替换为新值（×1.5，取整到 5） |
| `lower_radius_min` | `run_config.yaml` | `fitParameterLimits.radius[0]` | 替换为新值（×0.5，下限 1） |
| `increase_nRep` | `run_config.yaml` | `nRep` | 替换为新值（×2，上限 100） |
| `increase_nContrib` | `run_config.yaml` | `nContrib` | 替换为新值（+100，上限 1000） |
| `warn_only` / `warn_model` | 不修改配置 | — | 仅展示警告信息 |

#### 3.B.3 展示调整摘要并确认

```
「第 {N-1} 轮拟合评估发现以下问题，已自动调整模型拟合参数：

| 问题 | 判定依据 | 调整措施 | 参数变更 |
|------|----------|----------|----------|
| χ²_red 过高 | χ²_red=1.45 > 1.0 | 增大 maxIter | 100000 → 200000 |
| 主峰触碰 R_max 边界 | Peak=200 nm at upper bound | 扩大半径上限 | radius_max: 200 → 300 |

📖 数据读取参数（read_config.yaml）：保持不变
⚙️ 模型拟合参数（run_config.yaml）：以上调整 + 用户额外修改

将使用以上调整后的参数进行第 {N} 轮拟合。

直接回复 **「开始」** 继续，或告诉我你想额外修改的参数（如 `nContrib=400`、`dataRange=[0.0, 0.5]`）。」
```

#### 3.B.4 用户确认后

- `mkdir -p {run_dir}/iteration_{N}/config/`
- 复制当前 config 文件到 `{run_dir}/iteration_{N}/config/` 存档
- 更新 `iteration_history.json`

#### 振荡检测（每次进入分支 B 时执行）

在执行调整前，对比本轮 `adjustments` 与上一轮 `iteration_history.json` 中已应用的调整：

- 如果某参数在上轮被**调大**，本轮评估又建议**调小**（或反之）→ **触发振荡警告**：
  ```
  「⚠️ 检测到参数振荡：{参数} 在第 {N-1} 轮被调大/调小，本轮又需要反向调整。
  这表明拟合可能已接近最优，继续迭代可能不会显著改善。

  建议：接受第 {best_iteration} 轮的结果（χ²_red = {best_chi2}）。
  是否仍要继续调整？（回复「继续」或「接受最优结果」）」
  ```

#### 参数上限（防止失控增长）

调整时检查以下上限，达到上限时在调整说明中标注「已达到上限」：

| 参数 | 上限 | 说明 |
|------|------|------|
| `maxIter` | 1,000,000 | 超出后建议调整 dataRange 或其他参数 |
| `nContrib` | 1,000 | 超出后不再增加 |
| `nRep` | 100 | 已为发表级标准 |
| `radius_max` | 500 nm | 已超出典型 SAXS 量程 |
| `radius_min` | 0.1 nm | 原子尺度下限 |

---

## 步骤 4：McSAS 拟合 

**说明**：调用 McSAS 的蒙特卡洛优化引擎，对 SAXS 数据进行粒径分布拟合。这是整个分析最核心、最耗时的步骤。

```
「开始第 {N} 轮 McSAS 蒙特卡洛拟合（共最多 5 轮），预计需要数分钟。托管给我，如遇到异常自动排查解决。」
```

```bash
conda activate mcsas && mcsas3-runner \
  -f {datafile_absolute_path} \
  -F {run_dir}/config/read_config.yaml \
  -R {run_dir}/config/run_config.yaml \
  -r {run_dir}/mcsas_results/results_iter{N}.nxs
```

> **结果文件命名规则**：每轮迭代的结果文件按迭代轮数命名（`results_iter1.nxs`, `results_iter2.nxs`, ...），**不覆盖**之前轮次的结果。便于追溯每轮拟合的完整输出。

**确认完成**：检查 `results_iter{N}.nxs` 是否生成，展示拟合耗时。


## 步骤 5：拟合结果评估 + 优化决策

### 5.1 拟合结果展示

**说明**：每轮拟合完成后，立即展示拟合曲线和粒径分布直方图，让用户在评估前直观了解拟合质量。

```
「第 {N} 轮拟合完成，展示拟合结果：」
```

**拟合曲线图**：

```bash
conda activate mcsas && python3 skills/saxs-plot/plot_fit.py {run_dir}/mcsas_results/results_iter{N}.nxs {run_dir}/images
```

**粒径分布直方图**：

```bash
conda activate mcsas && python3 skills/saxs-plot/plot_histogram.py \
  {run_dir}/mcsas_results/results_iter{N}.nxs \
  {run_dir}/images \
  --radius-min {radius_min} --radius-max {radius_max}
```

两个脚本输出文件覆盖到 `{run_dir}/images/{filename}_fit.png` 和 `{run_dir}/images/{filename}_histogram.png`（每轮覆盖更新，始终展示最新一轮结果）。

展示拟合指标摘要：
```
「本轮拟合指标：」

| 指标 | 值 |
|------|-----|
| 最优 χ²_red | {value} |
| 主峰位置 | {peak} Å |
| 主峰 CV | {cv}% |
| 拟合耗时 | {elapsed}s |
```

「接下来进行拟合结果评估...」

### 5.2 拟合结果评估

**说明**：对拟合结果进行三级分级评估。**Tier 1 决定去留，Tier 2 提供优化方向，Tier 3 仅供参考。**

```bash
conda activate mcsas && python3 skills/mcsas-analysis/evaluate_fit.py \
  {run_dir}/mcsas_results/results_iter{N}.nxs \
  {datafile_absolute_path} \
  {radius_min} \
  {radius_max} \
  --history {run_dir}/iteration_history.json
```

> `--history` 参数用于 Tier 2 跨迭代比较。首轮迭代如尚无 history 文件，可省略该参数。

**该脚本自动完成**：
- 逐 repetition 提取 χ²、模型曲线、半径分布
- 按三级体系逐项判定
- Tier 1 失败 → 生成调整建议（blocking=true）
- stdout 输出 JSON（供 agent 解析），stderr 输出人类可读摘要

**你必须**：捕获 stdout JSON，解析 `verdict`, `blocking`, `tiers`, `adjustments`, `best_chi2_red`, `peaks`, `summary` 等字段。

### 5.3 三级评估体系

#### 🔴 Tier 1：必须满足（blocking）

| # | 准则 | 判定方法 | 通过条件 | 不通过条件 |
|---|------|----------|----------|------------|
| 1.1 | χ²_red 合理 | 最优 rep 的 gof / (nbins-2) | **0.05 < χ²_red ≤ 10** | χ²_red ≤ 0.05 或 χ²_red > 10 |

> **χ²_red 分级解读**：
> | 区间 | 质量 | 说明 |
> |------|------|------|
> | < 0.05 | ❌ 不通过 | 严重过拟合或误差估计严重偏大 |
> | 0.05 – 0.2 | ⚠️ 良好 | 建议检查数据的误差估计（Isigma）是否合理 |
> | 0.2 – 2.0 | ✅ 正常 | 拟合质量正常 |
> | 2.0 – 5.0 | ⚠️ 可接受 | 需要结合残差判断，建议增大 maxIter |
> | 5.0 – 10.0 | ⚠️ 较差 | 需要检查数据质量、模型适用性 |
> | > 10.0 | ❌ 不通过 | 拟合失败，需排查数据或模型 |

| # | 准则 | 判定方法 | 通过条件 |
|---|------|----------|----------|
| 1.2 | 残差随机无周期性 | Durbin-Watson + 多滞后自相关检验 | **DW ∈ (1.2, 2.5) 且无显著周期性** |
| 1.3 | 主峰非边界峰 | mean 直方图主峰不在首/末 bin | **不在半径边界** |

> **任一项不通过（❌）→ 必须调整参数重新拟合，不可直接接受。**

#### 🟡 Tier 2：建议满足（advisory）

| # | 准则 | 判定方法 | 通过条件 |
|---|------|----------|----------|
| 2.1 | 改变 radius 后主峰稳定 | 与历史迭代中不同 radius 范围的峰位比较 | **偏移 < 5%** |
| 2.2 | 改变 nContrib 后主峰稳定 | 与历史迭代中不同 nContrib 的峰位比较 | **偏移 < 5%** |

> 首轮迭代无历史数据 → 标记为 `pending`（待后续轮次检测）。
> 失败不阻塞，但建议增大 nRep 或确认峰位可靠性。

#### 🟢 Tier 3：加分项（bonus）

| # | 准则 | 通过条件 |
|---|------|----------|
| 3.1 | 主峰在可解析范围内 | π/Q_max < R_peak < 2π/Q_min |
| 3.2 | nRep 达到发表级 | nRep > 20 |

> 仅供参考，不纳入通过/失败判定。

### 5.4 向用户展示评估结果

```
「第 {N} 轮三级可靠性评估：」

🔴 Tier 1 — 必须满足：
| 准则 | 状态 | 值 | 阈值 |
|------|------|-----|------|
| χ²_red ∈ (0.05, 10] | ✅/❌ | {value} | 0.05 < χ²_red ≤ 10 |
| 残差随机无周期性 | ✅/❌ | DW={dw} | DW∈(1.2, 2.5) |
| 主峰非边界峰 | ✅/❌ | {peak} nm | 不在边界 |

🟡 Tier 2 — 建议满足：
| 准则 | 状态 | 值 | 阈值 |
|------|------|-----|------|
| radius 稳定性 | ✅/❌/⏳ | 偏移 {pct}% | < 5% |
| nContrib 稳定性 | ✅/❌/⏳ | 偏移 {pct}% | < 5% |

🟢 Tier 3 — 加分项：
| 准则 | 状态 | 值 |
|------|------|-----|
| 可解析范围 | ✅/❌ | {peak} nm ∈ [{Rlo}, {Rhi}] |
| nRep > 20 | ✅/❌ | nRep={nrep} |

判定：{verdict}
```

### 5.5 优化决策分支

#### ✅ Tier 1 全部通过（verdict = 'pass' 或 'tier2_partial'）

```
「🎉 核心条件（Tier 1）全部满足！拟合结果可靠。

{如有 Tier 2 未通过，列出建议}
{如有调整建议，列出}

是否接受本轮结果并进入最终汇总？
  - 回复「接受」或「是」→ 进入步骤 6：最终结果汇总
  - 回复具体参数调整 → 如 `radius=[20,80]`，应用后进入下一轮」
```

更新 `iteration_history.json`。如用户接受，进入步骤 6。

#### ❌ Tier 1 有失败（verdict = 'tier1_fail'）

```
「⚠️ Tier 1 核心条件不满足（{failed_criteria}），不建议直接接受。

自动调整建议：」

| 失败准则 | 问题 | 建议 |
|----------|------|------|
| {criterion} | {problem} | {suggestions} |

「是否应用建议调整并重新拟合？
  - 回复「是」或「继续」→ 应用调整，进入第 {N+1} 轮
  - 回复具体参数 → 如 `maxIter=50000, R_min=10`，合并后继续
  - 回复「接受」→ 忽略警告，强制接受本轮并进入步骤 6（标注 Tier 1 未通过）」
```

更新 `iteration_history.json`，如用户同意继续，`ITERATION += 1`，回到步骤 3 分支 B。

#### ⚠️ 达到最大迭代次数（ITERATION = 5）

```
「⚠️ 已达到最大迭代次数（5 轮）。

当前状态：Tier 1 {passed_count}/3 通过（{failed_names}）。

选项：
  A. 接受第 {best_iteration} 轮最优结果（χ²_red = {best_chi2}），进入步骤 6
  B. 手动调整参数后再试一轮（仅限 1 次）
  C. 放弃本次分析」
```

#### 💀 致命错误（fatal = true）

```
「❌ 拟合致命错误：{error}

{detail}

无法自动恢复。建议：
  1. 检查 read_config.yaml 的 dataRange 是否合理
  2. 检查 run_config.yaml 的 fitParameterLimits.radius 是否过窄
  3. 确认 modelName 是否匹配粒子形状

请手动调整后重新触发分析。」
```

**不自动循环**。

### 5.6 更新 iteration_history.json

每轮评估结束后（无论结果如何），追加完整记录。**关键：必须存储完整的 evaluate_fit.py JSON 输出**，以便后续轮次的 Tier 2 跨迭代比较：

```json
{
  "iteration": N,
  "timestamp": "{ISO timestamp}",
  "params": {
    "radius_min": 10,
    "radius_max": 80,
    "nContrib": 300,
    "nRep": 2,
    "maxIter": 10000
  },
  "evaluation": { /* ← 完整的 evaluate_fit.py JSON 输出（含 peaks.main 等） */ },
  "verdict": "tier1_fail",
  "user_action": "continued"
}
```

---

## 步骤 6：最终结果汇总

**说明**：基于最优轮次（或用户选定的轮次），汇总全部迭代历史和分析结论。

> **到达本步骤的路径**：
> - ✅ 用户接受某轮结果 → 「Tier 1 通过，结果可靠」
> - ⚠️ 用户强制接受（Tier 1 有失败）→ 「核心条件未完全满足，结果仅供参考」
> - ⏰ 达到最大迭代次数 → 「迭代终止，选取最优轮次」

### 6.1 确定最优轮次

- 如果用户明确接受了某轮：使用该轮
- 如果达到最大迭代次数：从 `iteration_history.json` 中找到 `best_chi2_red` 最小的那轮
- 如果未收敛，开头加警告：
  ```
  「⚠️ 注意：拟合未完全满足 Tier 1 核心条件。以下结果请审慎解读。」
  ```

### 6.2 最终指标汇总

向用户展示最终结果摘要：

| 指标 | 值 | 说明 |
|------|-----|------|
| 最优 χ²_red | {value} | 0.5-2.0 为合理范围 |
| 主峰位置 | {peak} nm | 主导粒径 |
| 主峰 CV | {cv}% | < 5% 非常稳定 |
| 总迭代轮数 | {N} | — |
| Tier 1 评估 | {passed}/3 通过 | 3/3 表示核心条件满足 |
| 最终判定 | {verdict} | — |

### 6.3 迭代历史总览

```
「📊 分析完成！

数据文件：{filename}
总迭代轮数：{total_iterations}
最终判定：{verdict}

各轮评估总览：
| 轮次 | radius | nContrib | maxIter | χ²_red | Tier1 | Tier2 | 判定 |
|------|--------|:---:|:---:|--------|:-----:|:-----:|------|
| 1    | [1,80] | 300 | 10k   | 0.08   | 2/3   | ⏳    | 调整 |
| 2    | [1,80] | 400 | 50k   | 0.11   | 2/3   | —     | 调整 |
| 3    | [10,80]| 300 | 10k   | 0.53   | 2/3   | ⏳    | ✅ 最优 |

结果图表：
  • 拟合曲线：{run_dir}/images/{filename}_fit.png
  • 粒径分布：{run_dir}/images/{filename}_histogram.png
  • Log-Log 图：{run_dir}/images/{filename}_loglog.png
  • 迭代记录：{run_dir}/iteration_history.json
```

---

## 目录结构

```
results/{filename}_{YYYYMMDD_HHMMSS}/
├── images/
│   ├── {filename}_loglog.png         # Log-Log 散射曲线
│   ├── {filename}_fit.png            # McSAS 拟合结果图
│   └── {filename}_histogram.png      # 粒径分布直方图
├── config/                           # 当前活跃配置（最新一轮）
│   ├── read_config.yaml
│   └── run_config.yaml
├── iteration_1/config/               # 第 1 轮配置快照
│   ├── read_config.yaml
│   └── run_config.yaml
├── iteration_2/config/               # 第 2 轮配置快照（如有）
│   ├── read_config.yaml
│   └── run_config.yaml
├── iteration_history.json            # 完整迭代追踪日志
└── mcsas_results/
    ├── results_iter1.nxs             # 第 1 轮 McSAS 结果
    ├── results_iter2.nxs             # 第 2 轮 McSAS 结果（如有）
    └── ...                           # 每轮独立保存，不覆盖
```

---

## 关键规则

- **环境**：所有 Python 和 McSAS 命令必须在 `mcsas` conda 环境下执行，先 `conda activate mcsas`
- **路径陷阱**：`plot_saxs.py` 和 `auto_params.py` 均需传数据文件的**绝对路径**
- **自动参数估计**：步骤 3.4 运行 `auto_params.py` 后，必须捕获 stdout JSON，将解析出的参数值替换到步骤 3.3 创建的 `run_config.yaml` 模板中
- **每轮展示结果**：步骤 4 拟合完成后，进入步骤 5.1 必须运行 `plot_fit.py` + `plot_histogram.py` 展示本轮拟合图和直方图，再进行步骤 5.2 评估
- **三级评估**：步骤 5 运行 `evaluate_fit.py` 时传入 `--history {run_dir}/iteration_history.json`。Tier 1 失败 → blocking=true，必须调整；Tier 2 失败 → 建议，不阻塞；Tier 3 → 仅供参考
- **评估 JSON 必须完整存储**：`iteration_history.json` 中每轮的 `evaluation` 字段必须存储完整的 `evaluate_fit.py` JSON 输出（含 `peaks.main`），否则 Tier 2 跨迭代比较无法工作
- **模板复制原则**：从 `template/config/` 复制配置文件时，严格保持模板结构，**仅修改参数值**，不增删任何字段或注释
- **大小写敏感**：`csvargs.names` 列名必须与数据文件表头大小写完全一致
- **迭代上限**：最多 5 轮迭代优化，达到上限后必须提示用户并进入步骤 6
- **敏感度排序**：McSAS 结果对 radius 范围、误差估计、q_min 的敏感性远高于 nContrib。调整参数时优先关注前三者
- **配置归档**：每轮迭代的配置文件必须复制到 `iteration_{N}/config/` 存档，确保可追溯
- **致命错误不自动循环**：评估返回 `fatal: true` 时，必须等待用户手动干预，不可自动重新拟合
