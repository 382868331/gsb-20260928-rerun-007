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

数值有效性把每类单元格严格区分为：**缺失**（空/NA）、**非法文字**
（如 `ERR`）、**非有限数值**（`Infinity`/`inf`/`NaN` 或实际的非有限浮点）、
**超出有限范围**（超出显式配置的 `min_value/max_value`）。单位换算分别在
**换算前（原值）和换算后（结果）**检查：有限原值经缩放也可能溢出或越界。
每种异常来源可单独配置策略：

- `error`：中止，预览和执行都不发布（非法类默认）；
- `flag`：保留原值待核对，在结果行写入 `_review` 标记，不当成正常数值；
- `drop`：排除该行，预览与血缘保留行号和原始值；
- `replace`：仅在明确给出**有限数值**替代值时使用，永远不会悄悄替换成 0。

同一列、同一类异常可以再按**来源**分别决定：在步骤参数 `policies` 中以列名给出
规则列表，每条规则可带 `value_matches`（命中的原始文字，如 `ERR`）、
`source_column` 与 `sources`（来源列名及取值，如 `source=lab-A`），按顺序匹配、
第一条命中生效，最后可用不带来源/文字的规则兜底。于是同样是 `ERR`，来自 A 实验室的
一行可以替换为数值、来自 B 实验室的一行被排除、其余留待核对；预览受影响行、统计、
血缘与最终发布结果由同一份内存计算产生，保证一致。

## 追加实验批次与人工例外

### 结构变化批次与测量对应

当追加批次出现旧批次没有的列时，系统不会按同名列直接套用规则，而是把该批次作为
**结构变化批次**保存原件，并生成测量对应提案：

- **可沿用**：用户确认测量及单位对应后，已有规则才可继承；
- **需补充对应关系**：如 `temperature_value + temperature_unit` 对应旧的
  `temperature + temp_unit`，需明确目标测量与逐条单位列；
- **存在矛盾/多解**：多个旧测量都合理时只列候选，不自动选择。

用户可逐条确认部分测量并立即预览：已确认部分按规则清洗，未确认部分保留在原始批次文件中，
结果行以 `_unresolved_measurements` 标明且规则步骤跳过这些测量。发布版本记录
`adopted_scope`（本次采用范围）和 `structure_actions`（从原列、原文、单位解释到目标测量的说明），
血缘时间线也包含结构对应步骤。撤回某个对应会把依赖它的人工例外标记为 `needs_recheck`，
例外只按原始行 id、批次和 mapping id 生效，不会漂移到同名列或另一个测量。

结构方案比较接口分别返回 `structure_interpretation`（结构解释差异）、
`cleaning_rule_differences`（规则将作用到哪些行的差异）以及 `data_added/value_changes`
（数据新增或值变化）。所有已发布旧版本及统计继续保持原样。

- **追加批次**：`POST /api/projects/{name}/batches/append` 追加列结构一致的新批次。
  新行写入 `workspace.json` 与 `batches/batch-N.json`，v0 与所有已发布版本文件
  永不重写；预览/执行时带 `include_appended: true` 即在同一套来源规则下一起清洗，
  发布时先落一个 `kind: "batch_append"` 的数据快照版本，再产出清洗版本。
- **规则修改影响分析**：`POST /api/projects/{name}/rule-impact` 传入新旧参数，
  返回受影响的**旧记录**（`changed_decisions`，含原值与新旧动作）、新规则覆盖的
  记录（`newly_handled`，新批次以 `is_new_row` 标出），以及与新规则冲突的人工例外
  （`conflicting_exceptions`）。冲突必须由用户逐条选择「保留人工决定」或
  「改用新规则（撤回例外）」。
- **人工例外**：以 `{row_id}|{step}:{column}:{stage}:{issue}` 为键保存在
  `exceptions.json`，作用于具体一条记录（保留待核对 / 排除 / 明确替代值）。
  预览面板的每条受影响行都可设置；已保存例外在保存重开后仍生效，撤回后该行
  立即恢复按规则处理。原值、单位换算结果与排除原因仍逐条记录在 `affected_rows`
  与血缘 timeline 中，并以 `decision_source: rule|manual` 标明决定来源。
- **版本对比**：`POST /api/projects/{name}/diff` 区分 `data_added`（数据新增）、
  `value_changed`（`cause=rule_changed|manual`）、`dropped_rows`（规则排除）、
  `restored_rows`/`manual_rows`（人工决定保留或恢复）三类影响。

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
- `POST /api/projects/{name}/batches/append` 追加新实验批次（不重写已发布版本）
- `GET  /api/projects/{name}/batches/{n}/proposal` 查看结构变化批次的测量提案
- `POST /api/projects/{name}/batches/{n}/mappings` 确认一个或多个测量/单位对应
- `POST /api/projects/{name}/batches/{n}/mappings/revoke` 撤回对应并重检依赖决定
- `POST /api/projects/{name}/batches/{n}/mapping-diff` 比较两套对应方案
- `POST /api/projects/{name}/exceptions/set|revoke` 设置或撤回单条人工例外
- `POST /api/projects/{name}/rule-impact` 规则改动影响分析（旧记录/新记录/冲突例外）
- `POST /api/projects/{name}/diff` 比较两个版本，区分数据新增、规则变化、人工决定

预览/执行请求体可带 `include_appended`（包含工作区追加批次）和 `use_exceptions`
（应用生效中的人工例外，默认 true）。

预览/执行报告中每步都带 `stats.affected_rows`（行级影响：转换前后值、
填充、删除、被合并的行），版本文件另存 `step_actions`，血缘接口在
`timeline` 字段返回该结果行经历的每步处理描述。

## 测试

```bash
python3 -m unittest discover -s tests        # 流水线/血缘/原子性/API
cd frontend && node node_modules/vitest/vitest.mjs run   # 前端组件
```
