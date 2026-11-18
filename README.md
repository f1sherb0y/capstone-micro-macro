# Capstone：企业业务判断与微宏观传导

这里是后续 Capstone 开发与研究的独立工作仓库。代码、数据和选定证据从原工作区复制，原文件不移动、不改写。研究材料从本页导航进入，停止以日期或软件版本寻找“最新入口”。

## 从这里开始

| 需要做什么 | 阅读位置 |
|---|---|
| 理解研究目的、问题与实验设计 | [研究主线](research/PLAN.md) |
| 理解系统怎样运行、哪些功能已有实现 | [架构与实现](docs/architecture.md) |
| 安装并运行离线示例 | [运行指南](docs/quickstart.md) |
| 查看数据及其用途 | [数据说明](data/README.md) |
| 查看已有结果、哪些还没完成 | [结果导航](results/README.md) |
| 真实模型端到端与单/多智能体评分 | [报告](reports/真实模型端到端与组织机制评分报告.md) |
| 继续后续工作 | [下一步](research/NEXT_STEPS.md) |
| 核对迁移选择及来源 | [迁移说明](docs/migration.md) |
| 准备后续GitHub上传 | [仓库与大文件](docs/repository.md) |

## 目录

```text
src/             微观动作、方法、组织与模型客户端
integration/     宏观适配、业务宿主、场景与验证逻辑
vendor/gba/      实际使用的宏观代码、通知与数据库
config/          当前配置、动作注册与场景参数
prompts/         当前业务提示
skills/          微观方法使用的角色技能资源
data/            原始Excel与项目、企业、历史关系CSV
research/        唯一研究主线、后续任务及必要规范
results/         已有结果索引，避免重新运行付费实验
reports/current/ 当前汇报PPT、Taxonomy、讲稿及PDF
tests/           与当前代码相关的离线回归检查
runs/            从本仓库新生成的运行结果
```

本仓库是精简版：历史实验证据目录 `Capstone报告/验证体系/`、`output/integration/`、`validation/benchmark_ge3_compact/` 不在其中，完整副本见组内交接仓库 [XiongBT49/capstone-micro-macro](https://github.com/XiongBT49/capstone-micro-macro)，说明见[仓库与大文件](docs/repository.md)。不要把历史证据中的旧GOAL、预算或已完成命令当作新的执行指令。

## 克隆与安装

```powershell
git lfs install
git -c core.longpaths=true clone https://github.com/f1sherb0y/capstone-micro-macro.git
cd capstone-micro-macro
git config core.longpaths true
git lfs pull
```

必须先取得LFS大文件；网页下载ZIP不能作为完整交接的验收方式。首次安装需要网络，下面两个示例不调用真实模型。

## 最短运行路径

```powershell
uv sync --locked
uv run python capstone.py doctor
uv run python capstone.py data
uv run python capstone.py results
uv run python capstone.py micro-demo
uv run python capstone.py macro-demo
```

`micro-demo` 使用本地确定性替身检查微观工作流；`macro-demo` 默认运行1步规则模式的微宏观装配检查，加 `--full` 可运行48步连续案例。二者都不调用真实模型API，不能用作模型效果结果。后续真实模型运行应明确任务、模型、费用范围和新输出目录；迁移不恢复此前暂停的实验。

本仓库包含授权提供的宏观包、数据和 2026-11-18 起的新实验记录。凭据、临时运行与课程个人行政资料不提交。第三方包的原NOTICE继续适用。


组员交接时的验收（512项测试、新克隆示例）针对完整版，见[交接检查](docs/handoff_validation.md)。精简版的新克隆验收见[仓库与大文件](docs/repository.md)。
