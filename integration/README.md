# 微宏观衔接运行说明

## 实现范围与阅读入口

`integration/` 将原宏观请求和实际事件交给既有微观处理器，再将受约束的决定交回宏观，保存输入、结果、事件和后轮消费者的对应关系。

- [项目现状](../docs/项目现状.md)
- [连续案例与运行命令](../docs/从立项到结算的大模型案例.md)
- [当前计划](../PLAN.md)、[执行目标](../GOALS.md)
- [宏观动作接线清单](../docs/宏观动作接线清单.md)

## 运行环境与宏观来源

在仓库根目录使用 `.venv-integration/Scripts/python.exe`。PowerShell 中文输出设置：

```powershell
$env:PYTHONIOENCODING='utf-8'
```

[bootstrap.py](bootstrap.py) 指向根目录宏观发布包的解压代码，`zwtnew/` 提供规范参考。当前版本包含授权接口修复及独立情景付款模块，具体范围见 [宏观修改说明](../docs/宏观代码相对原始ZIP的修改清单.md)。

## 主要入口

| 模块 | 用途 | 配置／说明 |
| --- | --- | --- |
| `origin_lifecycle_case` | 空项目起步的离线或 LLM 连续案例 | `config/origin_lifecycle_case.json`、`config/origin_model_lifecycle_case.json` |
| `origin_lifecycle_report` | 关联连续案例中的真实输入、决定、宏观事件与后轮消费者 | [连续案例](../docs/从立项到结算的大模型案例.md) |
| `dual_lifecycle_case`、`dual_lifecycle_report` | 同输入 25 tick 离线／LLM 链及配对记录 | `config/dual_lifecycle_case.json` |
| `case_library_lifecycle` | CASE-0005 的明确立项阶段入口 | `config/case0005_model_lifecycle.json` |
| `case0005_payment_continuation` | 指定两项付款的独立情景执行及 A10 后轮反馈 | [付款说明](../docs/CASE0005付款反馈续跑结果.md) |
| `verify_goal4_integration` | 当前宏观业务范围五场景联调的交付入口 | [联调说明](../docs/GOAL4整体联调与运行交付.md) |
| `tender_model_development`、`action_model_host` | 合法投标候选、单智能体及组织讨论装配 | [执行目标](../GOALS.md) |
| `paired_experiment_entrypoint`、`paired_experiment_run` | 预定模式、来源和预算下的配对试验 | [计划](../PLAN.md) |

## 查看已保存结果

```powershell
Get-Content -Encoding UTF8 output/integration/origin_model_lifecycle_20261025_03/case-summary.json
Get-Content -Encoding UTF8 output/integration/case0005_model_lifecycle_20261026_08/case-summary.json
Get-Content -Encoding UTF8 output/integration/case0005_payment_continuation_20261026_02/result.json
```

查看文件不运行 API。源码核验须匹配入口基线：部分交付核验固定为 174 文件／120 个 Python，新增情景付款模块需要独立核对，不能把文件数变化直接认定为业务失败。

## 执行与结果边界

1. 构建输入、实际运行和报告核验分别执行；准备完成不代表业务完成。
2. 输入和配置在运行前固定，采用尚不存在的输出目录。凭据通过既有环境入口提供，不写入文档。
3. 真实 API 使用预定预算，保存实际尝试、失败、选项与 token；连续案例不静默回退规则答案。
4. 宏观正式执行与状态变化以原事件或合法查询证明，反馈绑定同一结果。内部草稿、聚合值和诊断不冒充实体回执。
5. 不同运行隔离任务、缓存、记忆和检查点；未知提交先查询，已完成命令不重复执行。
6. 缺资料时按原处理器等待或拒绝；付款补充是新的关联阶段，不等于原会话自动恢复。

## 文件分工

- `bindings/`、`gba_v1_module.py`：原宏观接口适配与业务分派。
- 各角色 host、worker、source 模块：授权读取、方法调用与真实结果关联。
- `action_model_host.py`：模型选择和讨论装配。
- `paired_experiment_*`：配置、隔离、运行、计量和汇总。
- `verify_*`：各自声明范围的检查入口。
- `output/integration/<独立运行目录>/`：固定输入、日志、原任务库、事件、调用审计、摘要和核验结果。

具体业务参数和命令在相应专项文档维护；动作清单与交付配置分别位于 `config/action_registry.json`、`config/gba_v1_goal3_delivery.json` 和 `config/gba_v1_goal4_delivery.json`。
