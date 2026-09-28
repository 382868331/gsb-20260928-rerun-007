# 实验数据清洗工作台（第一版）

一条可追溯的实验数据清洗流程：本地 CSV 进入后生成**不可变原件版本**，在 React 界面配置
**缺失值处理 → 单位换算 → 重复记录合并**三步流水线，执行前预览影响，执行后发布新版本，
任何结果行都能追溯到原件中的记录 ID。

## 设计要点

- **原件不可变**：上传即 `v1.csv`，之后所有修改都是新版本文件，原件永不覆盖。
- **稳定数据身份**：每行携带 `__source_ids__`（原件记录 ID 列表，如 `r2|r3`），贯穿所有步骤；
  合并记录取并集，后续再增加处理步骤也不需要重建身份。
- **版本链**：`metadata.json` 记录每个版本的父版本、规则快照、行数和每步影响报告，重开工程可继续查看。
- **失败不发布半成品**：流水线先在内存完整计算，成功后才写临时文件并 `os.replace` 原子落盘；
  任何步骤抛错都不会产生新文件或残留临时文件。
- **冲突可感知**：重复键下数值不一致会在预览的 `conflicting_groups` 中明确报告，而不是静默覆盖。

## 目录

- `backend/app/pipeline.py`：三步清洗引擎与血缘传递
- `backend/app/storage.py`：版本存储、原子提交、血缘查询
- `backend/app/main.py`：FastAPI 接口
- `backend/sample_data.csv`：含单位混用（kPa/bar/mmHg/hPa/psi、°C/K）、缺失值、冲突重复记录的样例
- `frontend/`：React + Vite 工作台（上传 / 配置 / 预览 / 版本血缘）

## 运行

后端（默认数据目录 ./data，可用 DATA_DIR 覆盖）：

    python -m uvicorn app.main:app --app-dir backend --reload --port 8000

前端：

    cd frontend && npm install && npm run dev

打开 http://localhost:5173 ，`/api` 已代理到 8000。

在界面中上传 `backend/sample_data.csv`，建议规则：

1. 缺失值：均值填充全部数值列；
2. 单位换算：数值列 `reading`、单位列 `unit`、目标单位 `kPa`，系数
   `bar=100`、`mmHg=0.1333224`、`hPa=0.1`、`psi=6.894757`；
3. 重复合并：键选 `experiment_id`（或 `experiment_id,site`），冲突取均值。

预览中可看到 8 行 → 7 行；E-003 的冲突读数 760/765 mmHg 换算后取均值，来源为 `r2, r3`；
若填入缺少单位的系数（如漏配 psi），预览返回错误且不会生成任何版本。

## 测试

    python -m unittest discover -s backend/tests
    cd frontend && npx vitest run
