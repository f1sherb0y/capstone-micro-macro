# 仓库与大文件

## 两个远程仓库

| 仓库 | 内容 | 用途 |
|---|---|---|
| `https://github.com/f1sherb0y/capstone-micro-macro`（本仓库，`origin`） | 代码、配置、数据、文档、宏观运行包与数据库、2026-11-18 起的新实验结果 | 日常开发与公开展示 |
| `https://github.com/XiongBT49/capstone-micro-macro`（`handoff`） | 上述内容加全部历史实验证据，保留原 3 个提交 | 组内完整交接；历史证据的唯一远程副本 |

2026-11-19 起本仓库改为精简版，并从一个新提交重新开始历史。原历史另存为仓库外的 bundle 文件，并完整保留在 `handoff` 远程中。

精简版不含以下目录。它们在原工作目录中仍然存在，已加入 `.gitignore`，需要时从 `handoff` 仓库获取：

| 目录 | 大小 | 内容 |
|---|---|---|
| `Capstone报告/验证体系/` | 约 2 GB | 冻结实验设计、原始模型回答、评分、复核、账本、宏观已启动链 |
| `output/integration/` | 约 1 GB | 历史连续案例与付款子链 |
| `validation/benchmark_ge3_compact/` | 约 350 MB | 历史采样包 |
| `reports/template/` | 约 50 MB | 汇报 PPT 模板 |

例外：保留 `output/integration/implementation_20261016_01/macro_baseline.json`（21 KB），宏观示例读取它。依赖这些目录的历史分析脚本（`scripts/` 下带旧日期的文件）和 1 项读取历史评审摘录的测试，在精简版中无法运行或会跳过。当前入口、离线示例和新实验不受影响。

## 大文件

宏观数据库 `vendor/gba/data/processed/agent_database.sqlite.gz`（约 160 MB）和 `results/experiments/*/full_run.zip` 通过 Git LFS 管理。`.gitattributes` 同时关闭了自动换行转换，以免改动文件内容、使冻结的哈希失效。

```powershell
git lfs install
git -c core.longpaths=true clone https://github.com/f1sherb0y/capstone-micro-macro.git
cd capstone-micro-macro
git lfs pull
uv sync --locked
uv run python capstone.py doctor
```

宏观示例会在 `runs/` 中创建独立的可写数据库，每次约额外占用 2 GB。

## 不提交的内容

不提交凭据与 `.env`、虚拟环境、缓存、`runs/`、课程个人行政资料 `research/admin/`。仓库可见性由用户管理；上传不授予、也不转授第三方开源许可，`vendor/gba/NOTICE.md` 与原协作约定继续适用。

## 后续维护

新实验先输出到 `runs/`。验收后，把需要长期保存的输入、响应、评分、日志和摘要冻结到 `results/experiments/<实验标识>/`（可用 `scripts/freeze_experiment.py`），并更新结果索引。新增大文件要补 LFS 规则。不要覆盖历史评分、未知请求或原始输入。
