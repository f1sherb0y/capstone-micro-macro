# 已有结果导航

优先读以下材料，不重新运行已保存的模型请求。

本仓库为精简版：链接到 `Capstone报告/`、`output/integration/`、`validation/benchmark_ge3_compact/` 的历史材料不在其中，需从组内交接仓库 [XiongBT49/capstone-micro-macro](https://github.com/XiongBT49/capstone-micro-macro) 按相同相对路径获取；`capstone.py results` 会把它们显示为 `available: false`。`results/experiments/` 下的新实验完整包含在本仓库中。

- [历史角色推荐](../output/integration/capstone_retrieval_improvement_20261106/summary.json)：用于检索支撑，Hit@5为66.05%；与LLM业务回答评价分开。
- [业务首轮比较](../Capstone报告/验证体系/实验/2026-11-13_总实验收尾/CP01首轮业务结果_001.md)：相同题面下原生成与当前生成实现的成对业务评价，保存初始回答。
- [定向修正结果](../Capstone报告/验证体系/实验/2026-11-13_总实验收尾/CP01修复后业务结果_001.md)：95对修正前后回答单列，不替代首轮成绩。
- [宏观首个固定来源块](../Capstone报告/验证体系/实验/2026-11-13_总实验收尾/宏观首块业务结果_001.md)：四种机制在当前来源块的轨迹相同；保留该结果与解释边界。
- [可读与已评数量](../Capstone报告/验证体系/实验/2026-11-13_总实验收尾/business_readiness_CP08_review_progress_005.json)：区分已返回、可读与已复核，避免把请求提交当作实验完成。
- [停止状态记录](../Capstone报告/验证体系/实验/2026-11-13_总实验收尾/serial_pipeline_003/state.json)：历史流水线已停止，本记录不构成重新启动指令。
- [确定性反馈对照](../output/integration/capstone_validation_20261105/feedback/summary.json)：6个窗口、18次条件运行；说明规则应变，不表述为模型学会盈利。
- [真实模型端到端跑通](experiments/e2e-case0014-1119/README.md)：CASE-0014 从业主拆包、投标、签约到宏观施工、结算、关闭全程使用真实模型。单个案例的运行证据，不是效果评价。[第二案例 CASE-0001](experiments/e2e-case0001-1119/README.md) 同样跑通。
- [单智能体与多智能体微观评分](experiments/micro-org-1118/README.md)：6个项目、三种组织方式、353份输出的模型评审分。未经人工校准，待验收；与上面各项的评价口径不同，不合并计算。

## 当前完成度

先期两批可读首轮188+190均已逐项评分复核；当前模型其中162/189行动适当，85.7%不是全量成功率。新增业务926份可读回答中160份已复核，766份待评；组织286份可读最终回答待评。定向修正95对单列。

宏观保留已启动链的实际输入与运行目录，未执行链仅保留配置和生成工具。首固定四机制块已提取八类指标，轨迹相同；历史连续案例与付款子链是补充证据，不拼接为同一因果实验。

总进度文件含早于停止事件的“运行中”字段，不能直接当最新状态。原始暂停标记及流水线停止记录均保留；本仓库不自动恢复运行。

原运行JSON中的旧绝对路径属于历史记录。浏览或再分析时使用仓库内相对路径，迁移映射见 `provenance/relocation.json`。本次没有改写原评分、哈希或失败。

## 连续案例与补充证据

| 保存区 | 用途 |
|---|---|
| `output/integration/linked_case0014_20261102/` | 已有联动案例及其核对，不作为新增独立项目累加 |
| `output/integration/origin_lifecycle_20261025_09/` | 原生规则连续链、事件与反馈 |
| `output/integration/origin_model_lifecycle_20261025_03/` | 已有有限选项模型参与连续链 |
| `output/integration/case0005_model_lifecycle_20261026_08/` | 另一来源的模型连续案例 |
| `output/integration/case0005_payment_continuation_20261026_02/` | 付款子链及其核对 |
| `Capstone报告/验证体系/实验/` | 当前冻结设计、原始模型回答、评分、复核、账本与宏观已启动链 |
| `validation/` | 现有结论需要的历史采样与来源追溯 |

内部日期用于区分证据来源，日常工作从本页进入。补充案例不与不同实验设置下的结果直接合并计算总准确率。
