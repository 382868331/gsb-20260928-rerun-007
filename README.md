# 实验数据清洗工作台（CleanBench）

本地数据 → 可配置清洗流水线 → 执行前预览影响 → 执行后生成不可变新版本，
每条结果都能追溯到原始记录。后端 Python 标准库实现，前端 React 19 + Vite。

## 核心设计

- **原件保留，只生成新版本**：导入 CSV 时为每行分配稳定身份 `r0001…`，
  `v0` 是不可变原始快照；每次执行只追加 `v1/v2/…`，旧版本永远可读。
- **逐行血缘**：每个处理步骤返回局部来源映射，流水线串联成全局血缘；
  合并产生的行记录所有被吸收行，点开结果即可看到它来自哪些原记录。
- **先预览，后发布**：`preview` 在内存中跑完整流水线并返回行数变化与
  逐步统计，不写任何文件；只有显式执行才提交新版本。
- **失败不发半成品**：所有步骤在内存中全部成功后，才把新版本文件原子写盘，
  再原子替换 manifest（临时文件 + `os.replace` + fsync）。任何一步报错，
  最新版本保持不变。
- **可扩展步骤**：`backend/steps/` 中每个步骤是纯函数
  `apply(rows, params) -> (rows, lineage, stats)`，在注册表登记即可，
  不重建已有数据身份。
- **重开工程**：工程数据就是磁盘上的 JSON（`manifest.json` + `versions/`），
  重启服务后版本历史和血缘照常查看。

内置四步：缺失值处理（删行/常量/均值/中位数/众数）、数值有效性检查、
单位换算（支持 `factor + offset`，如华氏度 → 摄氏度；未知单位报错中止）、
重复记录合并（按主键分组，数值冲突可均值/首条/末条，可选择冲突即中止）。

**按来源分别决策**：数值检查和单位换算都支持 `source_column`（如 `lab`、
`batch` 列）。策略可写全局规则，再在 `policies.by_source[来源值]` 下为
每个来源单独覆盖。因此同一列中来自两个来源的同类非法文字（如都是
`ERR`）可以一个排除该行、另一个替换为明确数值或留待核对；统计按
「异常 × 来源」分别汇总，预览的逐行明细标注 `decision_scope`
（`global` / `source:<来源>` / `manual`），发布结果与预览完全一致。

**追加实验批次**：`POST /api/projects/{name}/batches` 在不改动任何已发布
版本的前提下，把新批次 CSV 并入工作数据集（`working.json` 代际递增、
新行续号 `rNNNN`）。再预览时逐行标注「旧记录 / 新批次」，并分别统计
受影响的旧记录与新记录；执行只追加新版本，旧版本文件永不被覆盖。

**人工例外**：可对单条记录的单个异常设置人工决定（保留/排除/替代），
保存在工程的 `exceptions.json` 中并附带保存时的规则指纹。之后修改规则，
预览与发布会列出与新规则冲突的例外，用户必须逐条选择「保留」或
「撤回」才能发布；撤回后该单元格恢复按规则处理，但审计记录保留。
保存重开工程后例外仍在，原值、单位换算结果和排除原因都逐条对应。

**版本比较**：`POST /api/projects/{name}/compare/{a}/{b}` 把两个已发布
版本间每条记录的差异归为三类之一：数据新增（按批次代际判断，被规则
排除的新行也算新增）、规则变化、人工决定。

数值有效性把每类单元格严格区分为：**缺失**（空/NA）、**非法文字**
（如 `ERR`）、**非有限数值**（`Infinity`/`inf`/`NaN` 或实际的非有限浮点）、
**超出有限范围**（超出显式配置的 `min_value/max_value`）。单位换算分别在
**换算前（原值）和换算后（结果）**检查：有限原值经缩放也可能溢出或越界。
每种异常来源可单独配置策略：

- `error`：中止，预览和执行都不发布（非法类默认）；
- `flag`：保留原值待核对，在结果行写入 `_review` 标记，不当成正常数值；
- `drop`：排除该行，预览与血缘保留行号和原始值；
- `replace`：仅在明确给出**有限数值**替代值时使用，永远不会悄悄替换成 0。

流水线可基于任意历史版本预览并发布：版本号始终追加（如基于 `v0` 比较
两套策略会得到 `v1`、`v2`），新版本记录 `created_from`，原数据和已有成功
版本都保持原样。修改任何步骤参数或退回步骤都会立即清空旧预览，重新计算后
才显示与当前设置一致的统计和结果，不会混入下游旧报告。

## 运行

```bash
# 1. 后端（无第三方依赖）
python3 -m backend.server --port 8000

# 2. 前端开发服务器（已构建过也可直接访问 http://127.0.0.1:8000）
cd frontend && node node_modules/vite/bin/vite.js   # http://127.0.0.1:5173

# 生产构建（后端自动托管 frontend/dist）
cd frontend && node node_modules/vite/bin/vite.js build
```

数据目录默认 `./data/projects`，可用 `--data` 或环境变量 `CLEANBENCH_DATA` 覆盖。

## 快速体验

1. 首页粘贴 CSV，或点「载入示例」（`examples/mixed_units_duplicates.csv`：
   摄氏度/华氏度混用、空值、同一样本的重复且冲突记录、一个非法数值）。
2. 先添加「数值有效性检查」（或直接在单位换算中配置策略）：把 `temperature` 的
   非法文字/无穷设为「中止」或按需要选择排除、替代；也可将 S6 设为待核对。
3. 添加「单位换算」：数值列 `temperature`，单位列 `temp_unit`，标准单位 `C`，
   规则 `C = factor 1`、`F = factor 0.5555556, offset -17.777778`，并可设置
   换算后范围（如结果上限）。
4. 添加「缺失值处理」：中位数填充 `temperature`、均值填充 `pressure`。
5. 添加「重复记录合并」：主键 `sample_id`，数值列取均值。
6. 「预览影响」后逐步查看每一步会动到哪些行（受影响行高亮与原值→新值），
   逐一点「接受这一步」；某一步不想要就「退回这一步」，该步被移除后
   需重新计算预览，下游不会再显示旧结果。全部步骤接受后才能执行发布。
   默认情况下，示例中的非法数值（S6 = `ERR`）会让检查/换算报错、预览与
   执行都不发布；切换为排除或明确替代值后可生成新版本，被处理的行仍可追溯
   到原值。想比较两套策略时，把「基于版本」选回同一个版本（如 `v0`），
   分别执行即可得到两个追加版本。
7. 在新版本表格点任意行的来源图标，查看合并它的原始行以及它在每一步中
   采用的处理（如 S1 ← r0001, r0004，并列出单位换算/缺失填充/合并说明）。

## HTTP API

- `GET  /api/projects` 工程列表
- `POST /api/projects` 以 `{name, csv}` 导入并创建工程
- `GET  /api/projects/{name}` manifest 与列信息
- `GET  /api/projects/{name}/versions/{n}` 某版本数据与步骤报告
- `GET  /api/projects/{name}/versions/{n}/lineage/{row_id}` 结果行的原始来源
- `POST /api/projects/{name}/preview` 基于最新版本，或请求体指定的
  `source_version`（任意历史版本）内存试跑，返回逐步 `affected_rows`
  受影响行明细，不写盘
- `POST /api/projects/{name}/apply` 全部步骤成功后原子提交新版本，可带
  `source_version` 从任意历史版本分叉，版本仍只追加、不变更旧版本
- `POST /api/projects/{name}/batches` 追加新实验批次到工作数据集，不触碰
  任何已发布版本；返回新代际、新行与旧记录数
- `POST /api/projects/{name}/exceptions` 为单条记录添加人工例外（带当前
  规则指纹）；`POST …/exceptions/{id}/withdraw` 撤回；
  `GET …/versions/0/exceptions` 读取含已撤回记录的完整审计
- `POST /api/projects/{name}/compare/{a}/{b}` 比较两个已发布版本，差异按
  数据新增/规则变化/人工决定归因；预览与执行返回 `conflicts`，执行可带
  `conflict_resolutions`（例外 id 映射为 keep 或 withdraw），未解决
  冲突时返回 409

预览/执行报告中每步都带 `stats.affected_rows`（行级影响：转换前后值、
填充、删除、被合并的行），版本文件另存 `step_actions`，血缘接口在
`timeline` 字段返回该结果行经历的每步处理描述。

## 测试

```bash
python3 -m unittest discover -s tests        # 流水线/血缘/原子性/API
cd frontend && node node_modules/vitest/vitest.mjs run   # 前端组件
```
