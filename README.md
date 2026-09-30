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

内置四步：数值有效性检查（按来源区分缺失、非法文字、超出有限范围）、缺失值处理（删行/常量/均值/中位数/众数）、单位换算
（支持 `factor + offset`，如华氏度 → 摄氏度；未知单位报错中止）、
重复记录合并（按主键分组，数值冲突可均值/首条/末条，可选择冲突即中止）。

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
2. 添加「单位换算」：数值列 `temperature`，单位列 `temp_unit`，标准单位 `C`，
   规则 `C = factor 1`、`F = factor 0.5555556, offset -17.777778`。
3. 添加「缺失值处理」：中位数填充 `temperature`、均值填充 `pressure`。
4. 添加「重复记录合并」：主键 `sample_id`，数值列取均值。
5. 「预览影响」后逐步查看每一步会动到哪些行（受影响行高亮与原值→新值），
   逐一点「接受这一步」；某一步不想要就「退回这一步」，该步被移除后
   需重新计算预览，下游不会再显示旧结果。全部步骤接受后才能执行发布。
   数值有效性在**换算前后各检查一次**：`inf`/`Infinity`/`NaN` 等文字与
   换算后溢出的结果都不会被当作可用数值（不会悄悄变成 0）。未配置处理
   策略时，报错信息直接给出原始行号与原值（如 `r0008='ERR'`），预览与
   执行都不会发布半成品。
   也可以先添加「数值有效性检查」，按**来源**为同一列分别选择：
   保留待核对（原值不动、行内打标，后续数值步骤自动跳过）、排除该行
   （行号与原值进入步骤报告与血缘）、或使用规则中明确给出的替代值
   （替代值本身必须是有限数值）。
   在左侧版本历史选中任意基线版本后再预览/执行，即可基于同一份原始数据
   保存多套策略（如 v1 保留待核对、v2 排除）互相比较；v0 原件和已发布
   的成功版本都不会被改写。
6. 在 `v1` 表格点任意行的来源图标，查看合并它的原始行以及它在每一步中
   采用的处理（如 S1 ← r0001, r0004，并列出单位换算/缺失填充/合并说明）。

## HTTP API

- `GET  /api/projects` 工程列表
- `POST /api/projects` 以 `{name, csv}` 导入并创建工程
- `GET  /api/projects/{name}` manifest 与列信息
- `GET  /api/projects/{name}/versions/{n}` 某版本数据与步骤报告
- `GET  /api/projects/{name}/versions/{n}/lineage/{row_id}` 结果行的原始来源
  `affected_rows` 受影响行明细（含异常类型 missing/invalid/nonfinite、
  原值与来源），不写盘；请求可带 `base_version` 指定基线版本
- `POST /api/projects/{name}/apply` 全部步骤成功后原子提交新版本；
  可带 `base_version` 基于历史版本另存新版本，绝不覆盖旧版本

预览/执行报告中每步都带 `stats.affected_rows`（行级影响：转换前后值、
填充、删除、被合并的行），版本文件另存 `step_actions`，血缘接口在
`timeline` 字段返回该结果行经历的每步处理描述。

## 测试

```bash
python3 -m unittest discover -s tests        # 流水线/血缘/原子性/API
cd frontend && node node_modules/vitest/vitest.mjs run   # 前端组件
```
