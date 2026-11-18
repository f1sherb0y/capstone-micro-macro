# 安装与运行

在本仓库根目录使用Python 3.12。无需旧工作区的虚拟环境。首次克隆后先执行 `git lfs install` 和 `git lfs pull`，确保数据库等大文件已下载。

```powershell
uv sync
uv run python capstone.py doctor
uv run python capstone.py data
uv run python capstone.py results
uv run python capstone.py micro-demo
uv run python capstone.py macro-demo
```

本地已有独立 `.venv`，也可直接调用 `.venv/Scripts/python.exe capstone.py doctor`。两个demo均禁止外网，允许Windows事件循环需要的本机连接，输出使用 `runs/` 下的新目录。微观采用确定性替身，宏观采用规则模式；这是运行检查，不新增研究效果证据。

`macro-demo` 默认只运行1步，确认场景装配、宏观引擎与微观处理器能够连接。完整生命周期入口为 `uv run python capstone.py macro-demo --full`，运行48步且涉及大型数据库，可能明显耗时；完整运行也使用独立的新输出目录。默认示例不宣称完成投标或结算。

宏观示例保留48步完整输入，通过已有检查点接口在第1步停止，并在输出目录复制独立的可写数据库。`vendor/gba/` 下保留的数据库不作为新示例的写入目标。每次宏观示例约额外占2GB磁盘，`runs/` 已忽略。

可用 `uv run pytest tests` 检查本项目回归；宏观供应包自带测试保留在 `vendor/gba/`，不混入默认测试收集。此次迁移的实际检查范围见[验收记录](verification.md)。

## 真实模型运行

以下命令会调用真实模型并产生费用，凭据读 `.env`。

```powershell
# 单个案例端到端：微观采购（真实模型）接入宏观生命周期，约 500 次调用
uv run python -m scripts.run_e2e_case --case CASE-0014 --output runs/<新目录>
uv run python -m scripts.summarize_e2e_run runs/<新目录>

# 单/多智能体对照与模型评审，见 docs/micro_org_rubric.md
uv run python -m scripts.micro_org_experiment --cases CASE-0014,CASE-0001 --output runs/<新目录>
uv run python -m scripts.micro_org_judge --experiment runs/<新目录>
```

真实模型凭据只放本地 `.env`，参考 `.env.example`。已有冻结实验的恢复不属于demo；需先核对当前研究问题、停止状态、预算、未知请求和迁移后的冻结路径，不能直接重跑旧批次入口。

