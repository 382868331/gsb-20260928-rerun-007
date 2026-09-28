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

内置三步：缺失值处理（删行/常量/均值/中位数/众数）、单位换算
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
   摄氏度/华氏度混用、空值、同一样本的重复且冲突记录）。
2. 添加「单位换算」：数值列 `temperature`，单位列 `temp_unit`，标准单位 `C`，
   规则 `C = factor 1`、`F = factor 0.5555556, offset -17.777778`。
3. 添加「缺失值处理」：中位数填充 `temperature`、均值填充 `pressure`。
4. 添加「重复记录合并」：主键 `sample_id`，数值列取均值。
5. 「预览影响」确认行数 7 → 5 与每步统计，再「执行并生成新版本」。
6. 在 `v1` 表格点任意行的来源图标，查看合并它的原始行（如 S1 ← r0001, r0004）。

## HTTP API

- `GET  /api/projects` 工程列表
- `POST /api/projects` 以 `{name, csv}` 导入并创建工程
- `GET  /api/projects/{name}` manifest 与列信息
- `GET  /api/projects/{name}/versions/{n}` 某版本数据与步骤报告
- `GET  /api/projects/{name}/versions/{n}/lineage/{row_id}` 结果行的原始来源
- `POST /api/projects/{name}/preview` 内存试跑返回影响，不写盘
- `POST /api/projects/{name}/apply` 全部步骤成功后原子提交新版本

## 测试

```bash
python3 -m unittest discover -s tests        # 流水线/血缘/原子性/API
cd frontend && node node_modules/vitest/vitest.mjs run   # 前端组件
```
