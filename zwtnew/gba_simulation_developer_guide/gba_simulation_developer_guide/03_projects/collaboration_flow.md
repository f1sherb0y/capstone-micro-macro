# 跨主体协作与交接索引

规范性质：交接索引。P01—P23 用于定位职责与上下游引用，不定义顺序状态机。

[八类主体总入口](../README.md) · [世界与时间](../02_world/world_runtime.md) · [项目运行与推进](project_lifecycle.md) · [共同对象与账本](../02_world/domain_objects.md) · [工程类型与建造方案模板](../02_world/project_types.md) · [待定选择](../07_experiments/model_decisions.md)

本文定位各项工作的主体行为入口、交接对象及权限分界。完整行为只由相应角色规范维护，项目依赖和责任绑定只由项目生命周期规范维护；项目不必顺序通过全部索引项。

需要修改项目进入、放行、并行、等待、变更、停复工或关闭条件时，进入 [项目运行与推进](project_lifecycle.md)。本表只同步入口和交接范围，避免两处维护同一流程条件。

逐步发起/跟进、执行、独立决定、核验与结果接收责任，以及运行时绑定具体智能体的规则，统一在 [项目运行](project_lifecycle.md) 第 4 节维护。本索引的角色名称是职能入口，不能据此随便选一家同类企业执行；每个粗步骤可拆成多个责任不同的任务。

<!-- page-nav:start -->
**本页导航**

[1. 怎样读交接](#1-怎样读交接) · [2. 需求、投资、委任与融资](#2-需求投资委任与融资) · [3. 设计、许可、采购与履约](#3-设计许可采购与履约)

[4. 完工、使用、移交和剩余义务](#4-完工使用移交和剩余义务) · [5. 全程反复发生的交接](#5-全程反复发生的交接) · [6. 交接变更维护](#6-交接变更维护)

[7. 交接异常示例](#7-交接异常示例) · [8. P01—P23 的接口接线表](#8-p01p23-的接口接线表)
<!-- page-nav:end -->

## 1. 怎样读交接

表中列的是主要衔接，实际参加者、权限与条件由项目/地区/采购模板确定。同一主体可并行处理多个项目和多个事项；进入一个索引项不表示其他工作停止。

工程目录、方法与模板支持情况查 [工程模板](../02_world/project_types.md)；总项目、子工程/区段、工作包和父子归集查 OBJ-005/006/022；范围与专业职责、许可和功能依赖的运行绑定查 [项目运行 第 2.1 节](project_lifecycle.md#21-总项目与子范围按已选模板分别推进)。本索引不把建筑类示例推广为道路、桥梁等工程必须采用的角色或工序。

一次交接至少可追踪：发送/提出主体、接收及有权处理主体、对象 ID 与版本、允许披露内容、作用范围、发送/获知时间、待办或决定、正式提交结果。没有相关业务需要时不强制建立消息或再次调用模型。

跨子工程或地区交接还需带 `project_id`、实际 `scope_ref`、接口/方案版本与对应工作包；接收者只处理获授权范围。分段成果、检查、许可和付款分别交接，不从某段完成推定总体功能或其他地区条件已满足；独立范围可继续的条件仍只在 [项目运行](project_lifecycle.md) 维护。

## 2. 需求、投资、委任与融资

| 索引 | 主体行为入口 | 交出 → 接收/处理 | 需要保留的分界 |
|---|---|---|---|
| P01 需求与条件变化 | [Owner](../04_roles/owner.md) OWN-A01；WORLD-003/017/019—021 | 地区 × 用途的需求、存量/在建、市场及政策指标 → 业主观察 | 聚合需求侧提供观察；世界条件、私人预期、实际使用与回款分别记录 |
| P02 提案与机会评估 | Owner OWN-A01/A16/A02 | 已有机会或自主提案 → 私有方案、评估档案与调查 | 三类目标共用入口；无需先有完整项目清单，提案不授予权利或自动生成正式项目 |
| P03 前期需求与咨询 | Owner OWN-A02/A16；[Architect](../04_roles/architect.md)、[Engineer](../04_roles/engineer.md)、[QS](../04_roles/qs.md)、[Supplier](../04_roles/supplier.md)；[Government](../04_roles/government.md) 按事项 | 目的/地区/规模/期望交期的版本简报 → 各自有限任务、意见及候选 | 技术方式逐步细化；可先于正式项目，咨询不等于许可、确定报价或产能承诺 |
| P04 可行性比较 | Owner OWN-A03；Architect/Engineer/QS/Supplier 各自 A13；[Bank](../04_roles/bank.md) A13；Contractor 按模板参与 | 同版需求、专业及供应意见、三类目标和资金时序 → 可比候选与投资选择 | 不拼接不同方案的有利数值，不以多数投票替代专业条件；意见分歧、缺证、硬条件与偏好分别处理；初步融资不是实际现金 |
| P05 投资授权 | Owner OWN-A03 | 本业主方案及授权 → 有条件准备或正式项目 | 附条件准备不自动获得资金、土地权、完整合同和许可 |
| P06 采购安排 | Owner OWN-A04/A09、各受托主体 | 目标与采购模板 → 责任、范围和资格要求 | 顾问雇主及设计责任依模板确定，不默认永远属于业主 |
| P07 专业委任 | Owner OWN-A04；Architect、Engineer、QS；[Contractor](../04_roles/contractor.md) 如为雇主 | 服务邀请/报价 → 有效委任或内部任务 | 受邀、愿意服务、有效合同和任务占用不同 |
| P08 融资安排 | Owner OWN-A05—06；[Bank](../04_roles/bank.md) BANK-A02—07 | 申请/报价/有效接受 → 安排、条件、提款批次、现金/债务与清偿引用 | 批准、在途、实际执行分别记录，允许与设计/审批迭代 |

## 3. 设计、许可、采购与履约

| 索引 | 主体行为入口 | 交出 → 接收/处理 | 需要保留的分界 |
|---|---|---|---|
| P09 设计与成本计划 | 按工程模板受托的 Architect/Engineer/QS；Owner OWN-A07 | 需求和委任 → 对应范围的专业成果、成本计划、问题、业主取舍 | 技术检查、客户接受与按用途发布不同；引用具体版本，不强制所有工程包含建筑师任务 |
| P10 规划与法定事项 | Owner OWN-A08；获授权专业方；Government GOV-A01—09 | 申请/补件 → 受理、审查、决定、许可及条件 | 权限、范围与时效逐项判断；无权机关不能替代有权机关 |
| P11 采购准备 | Owner OWN-A09；QS、专业方；Contractor | 具备适用条件的成果/范围 → 同版采购包和邀请 | 可允许的提前采购由模板声明；不以设计尚未完全结束一概禁止或放行 |
| P12 独立投标与评审 | Contractor；[Supplier](../04_roles/supplier.md) 如直接供货；Owner、QS及授权评审方 | 采购包 → 独立报价/澄清 → 有权方比较 | 各自报价、私有信息和有效期独立；零合格候选是有效业务结果；未选、拒绝或过期不留下虚假合同或无依据的资源独占 |
| P13 合同形成 | Owner OWN-A10；Contractor/Supplier 或其他真实当事方 | 同版条款与有效接受 → 合同、义务、参与和资源承诺 | 单方选中不自动产生对方对新条款的接受；提交时复核 |
| P14 供应、制造与物流 | Contractor；Supplier SUPPLIER-A01—09；专业方依授权核验 | 规格/订单 → 批次生产、检验、发运、到货及可用量 | 订单、产出、在途、到场、合格可用和实际消耗不同 |
| P15 施工准备与放行 | Contractor；Owner、Government、专业方按权限供给依据 | 计划、人员设备、场地、版本、许可及资金 → 具体工作包就绪 | 每项必要投入真实到位；只放行满足条件的范围 |
| P16 持续施工与管理 | Contractor；Supplier、Architect、Engineer、QS、Owner、Bank、Government | 执行/检查/付款/变更/风险事项 → 各角色分别决定并继续履约 | 多个循环并行；工程量由投入和工程机制产生，消息不直接增进度 |

## 4. 完工、使用、移交和剩余义务

| 索引 | 主体行为入口 | 交出 → 接收/处理 | 需要保留的分界 |
|---|---|---|---|
| P17 完工检查与测试 | Contractor；Engineer/Architect；Supplier | 完工申报、资料与测试 → 专业核验、问题和复检 | 工程声称完成、合格证明和合同接受不同，允许分范围处理 |
| P18 法定使用条件 | Government GOV-A11；Owner及获授权申请方 | 适用使用申请/证据 → 决定、范围和持续条件 | 工程完工不自动产生使用权；并非所有项目都适用同一事项 |
| P19 移交接管 | Owner OWN-A12；Contractor、专业方、Supplier | 实际交付清单、资产/资料/责任 → 有权接收；清单依 CONTRACTOR-036 | 分段和整体按实际范围交接；接管、使用许可、付款与责任解除分别记录，最新设计不代替实际建成配置 |
| P20 缺陷与保证 | Contractor、Supplier；专业方核验；Owner | 缺陷通知/证据 → 责任判断、实际整改、复检 | 不默认免费整改一切，也不因离场抹除已成立义务 |
| P21 最终计价与争议 | QS；Owner、Contractor、Supplier及各合同当事方 | 最终资料、计量与争议 → 有权核证、接受或后续处理 | QS 意见权限明确；工程合同、专业服务和供货合同分别结算 |
| P22 支付与义务解除 | 全部相应付款方/收款方；Bank BANK-A09—11 | 有效到期义务和付款授权 → 实际收付、债务核对、释放 | 已结算不等于已支付；银行核销不等于借款方免债 |
| P23 归档与后续经营 | 八类主体；共享结果与事件入口 | 已提交事实/获授权观察 → 历史档案、私有学习与后续决定 | 工程、合同、许可、债务的终态分别判断；企业仍可继续经营 |

## 5. 全程反复发生的交接

| 持续活动 | 主要入口 | 索引怎样连接 |
|---|---|---|
| 环境和政策更新 | WORLD-003—005/017；Government 仅在启用调控且有权时决定 | 经可见需求、资格、费用/融资、程序等条件影响提案及投资；不直接强制新增项目或指定绩效 |
| 资产持有、实际使用与回款 | Owner OWN-A14；OBJ-017 与交易/外部支付接口 | 聚合使用/吸纳机制待细化；物理存量、实际使用、应收与到账分开，不能从使用率生成现金 |
| 企业经营与跨项目竞争 | 每个角色自身经营/资源行为 | 订单、贷款、专业人员与现场资源统一检查本组织的其他承诺 |
| 新资料和版本变化 | 提出修改的角色 + 有权接收/审查的角色 | 更新受影响范围，重查具体依赖；不自动全盘重置或全部沿用 |
| 付款、融资与风险 | 实际当事方及获授权专业方 | 资金过程与工程过程相互约束；付款失败不等于工程事实消失 |
| 暂停、失败、退出与接续 | 各角色的异常/退出行为 | 分别处理任务、资源、合同、许可、资金和剩余责任；可恢复性按规则表达 |
| 技术失败与重复提交 | 共享提交/去重入口 | 先核对事实，再恢复或重试；不伪造同意、拒绝或重复付款 |
| 运行截止 | 世界调度及结果入口 | 保留未完项目、债务、在途和待办，不能为凑完整链条伪造关闭 |

## 6. 交接变更维护

修改任一角色行为时，检查对方是否知道、能接收、拥有决定权限并能表达拒绝/等待；检查对象版本、资源资金和正式事实的更新入口；最后更新本索引的连接。角色规则仍只在对应主文档维护。

八类角色不覆盖社会中全部机构。土地权利人、住户/最终用户、物流/海关、保险、独立争议处理方等，若未独立建模，应在场景/模板中注明由哪个外部机制或获授权角色承担接口，以及不能据此解释哪些结果。是否增加角色是 D-03/D-06 的模型选择，不默认为“无人负责所以自动通过”。

## 7. 交接异常示例

正常链条通过 P01—P23 检索，详细的发起、执行、决定、核验及接续责任统一见[项目生命周期第 4.4 节](project_lifecycle.md#44-p01p23-的逐步责任表)。其中包含建筑设计任务的委任关系只用于说明；道路、桥梁等按工程模板绑定实际专业，不强制凑齐全部角色。前期研究、融资、设计和采购可按依赖并行或往返，不按索引行数推进时间，也不强制每个节点产生模型发言。

以下保留一个跨角色异常传播示例，核对交接是否覆盖问题发现、独立判断、授权、执行和无法恢复的出口；不新增角色行为或采购模板。

### 7.1 一次设计与供货冲突怎样传播

1. **问题产生**：供应商按获授权需求核对发现某批次产品不满足当前接口，提出明确偏差和候选；原合格/不合格事实由对应证据及规则判断，不能靠报价较低消除问题。
2. **履约方判断**：承包商比较等待原品、替代、调整施工次序等合法选择，记录影响范围；需要新设计或合同权利时提交请求，不自行宣称替代等效。
3. **专业方各自处理**：建筑师处理受托建筑接口；工程师处理受托专业验证；QS比较增量数量、费用和已有合同依据。每方可要求调查、拒绝结论或提出修订，不共享一个“顾问已同意”标记。
4. **投资与权限处理**：业主决定商业/需求取舍与授权；若影响许可，申请方交政府按具体事项决定；如影响提款条件，银行依据可见证据独立复核。未受影响的有效决定不用全盘重做。
5. **执行与反馈**：协商形成新条款时取得必要当事方的同版有效接受；已有合同允许的有效指令或紧急义务则按其权限、范围和条件放行，未议定费用单独进入计价/争议，不把“费用尚未谈妥”一概当作不得执行。两条路径均核对必要技术、许可和投入条件，再调整资源与批次、实际交付和检查；新增费用、已发生等待、退款或索赔按各自依据记录，不把紧急标签当作无限授权。
6. **无法恢复时**：保留已完成工程、库存/在途、欠款和安全保管责任，交有权主体处理替换、缩减、暂停或终止。仿真不替各方达成妥协，也不自动制造贷款或许可解锁流程。

该链的成本和延期由所选工程、合同、资源及时间方法计算；交接关系本身不提供定量结果或验证证据。

## 8. P01—P23 的接口接线表

本表补充“哪份已提交数据由谁生产、谁按什么契约消费”。角色行为的选择字段仍由角色文档维护；函数签名及专用类型统一见[系统接口目录](../06_engineering/system_interfaces.md)，模型/规则输出及提交结果见[公共协议](../06_engineering/interface_contracts.md)。所有 `prepare_*` 返回拟变化，只有公共提交回执中的对象才能进入下游正式输入；同义类型名必须按[角色输入投影](../06_engineering/system_interfaces.md#91-正式对象与角色-input-的显式投影)登记字段映射，不能直接强转。

| 步骤 | 具体生产者与行为 | 正式交接数据及字段基准 | 消费者、系统入口及不满足时的去向 |
|---|---|---|---|
| P01 | world/market；Owner OWN-A01 | MarketSignal.cells 的地区/用途/服务范围/数量单位、信息截止、来源 → 本主体可见 DemandObservation | `market.prepare_signals → observations.prepare_delivery → agents.build_action_input` → OWN-A01/A16；缺口留 unknown，不默认新建项目 |
| P02 | Owner OWN-A01/A16 | OwnerCase 的主体/来源观察；OwnerBrief 的目的、地区、规模、候选技术、期望交期与未决项 | `opportunities.prepare_case / proposals.prepare_briefs` → OWN-A02/A03及专业A13；缺权利/信息形成调查待办，档案不等于Project |
| P03 | OWN-A02；ARCHITECT-A13、ENGINEER-A13、QS-A13、SUPPLIER-A13；BANK-A13/CONTRACTOR-A13按委任 | 同版Brief、有限服务范围/费用/期间、独立接受、专业材料用途及限制 | `work.prepare_request / work.prepare_authorization / project.prepare_task_graph` 按有效内部授权或适用外部委任创建任务；外部协议与绑定分别走 `agreements.prepare_effectiveness / project.prepare_binding`，邀请不等于授权 |
| P04 | ARCHITECT-A13、ENGINEER-A13、QS-A13、SUPPLIER-A13、BANK-A13；Owner OWN-A03 | 同版ProjectOption、专业Assessment、数量/CostPlan、SupplyAdvice、FinanceAdvice → OptionComparison | `methods.evaluate_option / work.prepare_deliverable / agents.build_action_input` → OWN-A03；缺量纲/版本/方法返回needs_information或unsupported，不让汇总器猜值 |
| P05 | Owner OWN-A03 的有权投资选择 | RecordedDecision 的选项、范围、条件、有效权限与登记依据 | `project.prepare_registration` → 稳定Project及后续任务/在建管线；附条件准备继续关联原档案，不获得全面开工权 |
| P06 | OWN-A04/A09；CONTRACTOR-A05按实际采购权限 | ProcurementProcedure、Scope、责任槽位、包件分配与专业/采购模板版本 | `project.prepare_task_graph / procurement.prepare_package` → 对应雇主/采购负责人；职责缺项由实际采购方补齐，不默认Owner接管全部 |
| P07 | OWN-A04；ARCHITECT-A02/A03、ENGINEER-A02/A03、QS-A02/A03；Contractor为雇主时CONTRACTOR-A05 | 同版ServiceTerms、每方RecordedDecision、Agreement、Appointment、ResponsibilityBinding | `agreements.prepare_effectiveness / project.prepare_binding` → 各专业A04；缺接受/资格/独立性由委任方和该服务方处理，不强制接单 |
| P08 | OWN-A05/A06；CONTRACTOR-A10/SUPPLIER-A10可为各自融资申请人；BANK-A02—07 | FinanceApplication→FinanceOffer→FinanceArrangement→DrawRequest→TransferInstruction→真实SettlementFragment；同银行/借款人/用途/币种 | `finance.prepare_application / prepare_offer / prepare_arrangement / prepare_draw_request / prepare_transfer`，`payments.* → finance.prepare_settlement` → 真实收款人/债務/后续任务；未知沿原指令核对 |
| P09 | ARCHITECT-A04—09、ENGINEER-A04—09、QS-A04；Owner OWN-A07 | Deliverable 的task/scope/方案/数量/依赖版本；Submission、Review、UseRelease分别记录 | `work.prepare_deliverable / prepare_submission / prepare_review / prepare_use_release` → 明确接收者、估算/采购/许可；退回只重开受影响依赖，不能合成一个“设计已通过” |
| P10 | OWN-A08及合法代理；GOV-A01—09 | MatterCase 的申请人、事项、地区/范围、证据版本；MatterDecision/Permit的有权签发、用途、条件、时效 | `matters.prepare_case / matters.prepare_decision` → 申请人及具体任务前置；`matters.prepare_clock_status` 独立记录计时/逾期，缺材料回责任作者，机关未定不自动通过 |
| P11 | OWN-A09或CONTRACTOR-A05；QS-A05；专业获授权发布方 | ProcurementPackage 的范围、允许采购用途的技术版本、数量依据、程序和候选资格 | 首次准备草案经 `procurement.prepare_package` 登记；招标用 `procurement.prepare_round`，直接询价用 `procurement.prepare_inquiry` → 对应承包/供货候选；不强制所有询价先招标 |
| P12 | CONTRACTOR-A01—03、SUPPLIER-A01—03；QS-A06及Owner OWN-A09 | Bid/SupplyOffer 的真实报价方、包件及招标/询价来源与版本、价量条件、有效期与澄清；独立评审材料 | `procurement.prepare_offer / work.prepare_deliverable / agents.build_action_input` → 有权采购方；零合格候选沿重招/修改/等待，不伪造中标和资源占用 |
| P13 | OWN-A10、CONTRACTOR-A04、SUPPLIER-A04；其他合同的真实双方 | AgreementAssembly 的同版条款、必要接受/核验、承诺与形成条件 | `agreements.prepare_effectiveness` 联合 `resources.prepare_reservations / finance.prepare_obligations` → 有效合同/任务/账本；冲突拒绝整个必要写集，不只留下selected字段 |
| P14 | CONTRACTOR-A05；SUPPLIER-A04—09；有权接收/专业核验方 | Order/Batch、生产WorkSlice、批次数量、实际路线/移动片段、收货/检验/可用放行证据 | `engineering.prepare_execution / inventory.prepare_movement / prepare_inspection` → 现场可用材料及订单义务；在途/不合格分开，重复收货不复制库存 |
| P15 | CONTRACTOR-A06；OWN-A08、GOV-A08、专业用途发布者按权限 | 具体WorkPackage的授权、有效成果/许可、人机料场、资金条件与实际范围 | `engineering.check_readiness / project.evaluate_dependencies` → 施工任务；缺哪项回其责任方，只阻塞真实依赖 |
| P16 | CONTRACTOR-A07—10；SUPPLIER履约；专业/Owner/Bank/Government各自事项 | WorkSlice与EngineeringOutcome、实际投入/净工程量/返工/成本；独立变更/核证/支付/监管事实 | `engineering.prepare_execution / project.evaluate_dependencies / finance.* / matters.*` → 工程检查、计量与后续任务；消息不直接增量，变更不擦除原履约 |
| P17 | CONTRACTOR-A11；ENGINEER-A08/A09、ARCHITECT-A08/A09；SUPPLIER-A07/A09 | 分范围完工申报、实际试验/Inspection、质量结论、待整改项与权限 | `inventory.prepare_inspection / work.prepare_review / project.evaluate_closure` → 合同接收/使用申请；自报不替独立核验，不合格交具体责任方 |
| P18 | 合法申请人OWN-A08；GOV-A11 | 对应使用MatterCase/Decision及有权Permit、覆盖范围、时效、持续条件 | `matters.prepare_case / prepare_decision` → 合法使用前置；无适用依据不能默认为豁免，缺材料继续原案 |
| P19 | CONTRACTOR-A11；OWN-A12及实际有权接收方；SUPPLIER/专业各交自身部分 | HandoverDraft的as-built、实物/资料清单、接收者权限、资产和剩余义务；Rights按W3 | `assets.prepare_handover / project.prepare_closure` → 资产经营/残余任务；最新设计不冒充实建，接管不清债务 |
| P20 | CONTRACTOR-A11、SUPPLIER-A11；ARCHITECT-A09、ENGINEER-A09；OWN-A12 | 缺陷Issue、有效责任依据、整改Task/WorkSlice、复检Review/Inspection与费用归属 | `project.prepare_task_graph / engineering.prepare_execution / work.prepare_review` → 有权关闭/责任继续；不能默认每种问题免费或自动消失 |
| P21 | QS-A09；CONTRACTOR-A11、SUPPLIER-A10/A11；各合同实际双方 | SettlementProposal/量价材料、核证权限、争议/无争议组成、有效接受及Obligation依据 | `work.prepare_deliverable / finance.prepare_obligations / prepare_adjustment` → 真实债务人/债权人及争议责任方；QS意见不自动成为法律裁决 |
| P22 | OWN-A06；BANK-A07/A09—11；CONTRACTOR-A10、SUPPLIER-A10；各专业服务费/付款方 | TransferInstruction、ExecutionEvidence、Reconciliation、唯一SettlementFragment与义务分配 | `payments.dispatch_instruction / query_execution → finance.reconcile_execution / prepare_settlement` → 双方现金/债务/剩余任务；结算不等于到账，unknown不重复划款 |
| P23 | OWN-A15、BANK-A12、ARCHITECT-A12、ENGINEER-A12、QS-A12、CONTRACTOR-A12、SUPPLIER-A12；GOV-A12按职责 | 已授权Observation/反馈、私有CognitiveState、ClosureVector、事实读点及ResultVersion | `cognition.prepare_update / organizations.prepare_operating_period / project.prepare_closure / results.prepare_projection` → 后续经营/实验/页面；归档不抹剩余责任，不强制停止全部主体 |

跨步骤统一保留 `run/数据空间、scope、实体版本、来源、单位、业务时间、可见时点、命令与事实身份`。父子范围归集不得重复数量或资金；技术重试沿原身份，真实授权修订使用新身份与原对象引用。P编号不代表固定调度次序，也不要求所有工程都调用全部角色。
