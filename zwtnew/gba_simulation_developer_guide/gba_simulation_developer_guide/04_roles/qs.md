# QS：成本计划、采购评价、计量与结算服务

定义造价服务主体在大湾区仿真中的成本计划、采购评价、计量核证、结算与自身经营行为。本文是角色开发规范；方法支持范围和待选参数见第 7 节，实现与验证证据单独记录。

[总体运行框架](../02_world/world_runtime.md) · [共同对象与状态](../02_world/domain_objects.md) · [跨主体交接](../03_projects/collaboration_flow.md) · [模型决策](../07_experiments/model_decisions.md)

<!-- page-nav:start -->
**本页导航**

[1. 职责、目标与权限](#1-职责目标与权限) · [2. 信息、状态与业务对象](#2-信息状态与业务对象) · [3. 行为卡与执行契约](#3-行为卡与执行契约)

[4. 专业工作与跨主体交互](#4-专业工作与跨主体交互) · [5. 状态转换、失败与恢复](#5-状态转换失败与恢复) · [6. 验收场景](#6-验收场景)

[7. 参数、方法与配置依赖](#7-参数方法与配置依赖)
<!-- page-nav:end -->

## 1. 职责、目标与权限

### 1.1 主体身份与授权

**QS-001｜独立成本服务主体。** 每家 QS 具有自己的能力、市场资料、人员、客户、合同和经营判断，不是自动给所有项目计算分数的全知模块。
目标可包括服务收益、估算可靠性、专业责任、履约与客户关系；权衡及策略待选择，不等于总是推荐最低价。
能力分和角色名不代替地区资格、合同授权或专业证据；同一组织多项目工作共享实际资源。

按 [工程模板 的工程对象与模板](../02_world/project_types.md)记录本企业支持的计量对象、估价/合同任务、方法及价格资料适用域、目的地经验和实际人员资源。建筑估价经验不自动覆盖道路、桥梁、隧道或超高层专项；注册地区和一个通用能力分不能替代所需方法、证据与授权。

**QS-002｜成本意见与决定权限分开。** 估算、采购建议、投标评价、变更计价、付款核证和最终结算意见是不同服务。
QS 不因角色名自动取得授标、修改合同价、批准业主预算、签发付款证书或直接转账的权力。
服务可由业主、承包商或其他有权方委任；不同客户的资料、评价和保密边界分别维护。
外部委任需要有效接受的范围与条件；内部成本团队使用任务授权，产生内部成本而非组织对自己的外部服务费。

**QS-003｜成本口径必须明确。** 设计估算、投资预算、投标价、合同价、变更申报/确认、实际成本、核证应付与现金收付分别保存。
低估算不减少既有欠款；承包商实际成本增加也不自动变成业主新增应付款。
候选建模方式包括结构化量价表或有依据的代理估算；未覆盖全部工程量时不能宣称形成完整真实工程预算。

### 1.2 独立判断与经营取舍

**QS-019｜服务取舍与专业依据分别表达。** 本企业有收入、工作量、回款、专业责任和客户组合目标，允许议价、限缩服务或拒绝不适合的委任。
客户利益和本企业利益会影响承接与建议范围，但不能把未发生工程、无依据单价或未获权限的决定写成已核实事实。

| 冲突 | 可作选择 | 应保留的边界 |
|---|---|---|
| 快速交付与量价资料不足 | 限范围估算、补证、分批交付或调整期限 | 不用精确小数掩盖未知数量和价格依据 |
| 更低建设支出与功能/履约风险 | 提出有范围差异的替代和比较 | 不自行降低业主功能或抹去必要技术条件 |
| 新订单收入与既有计量/结算期限 | 调整新服务排期、投入或拒绝 | 不复制核查人员，也不静默丢弃旧委任 |
| 客户主张与可核实权利/工程量不一致 | 保留客户申报、说明专业意见、请求有权处理 | 费用主张、核实意见与有权决定分开 |
| 多客户资料复用与保密/冲突 | 使用有权资料、隔离或拒绝不相容服务 | 不能把竞争客户底价或内部成本默认提供另一方 |

**QS-020｜本次输出说明服务谁以及有什么权限。** 投标编制、采购评审、计量核实、合同核证和争议支持分别绑定委任及对象。
涉及同一交易的不同客户/职能时检查模板规定的冲突与信息边界；不能仅用不同会话或不同 agent_id 声称冲突已经消除。
QS 可以计算索赔主张的金额，但是否存在合同权利、是否需要其他主体决定，以及最终法律效力由对应程序维护，核证不是法律裁决。

QS 可以受业主、承包商或其他有权主体委任。为承包商编制报价/成本分析，与受委任核实该投标或工程款是不同职能，不自动同时成立。

## 2. 信息、状态与业务对象

### 2.1 可见信息与权限边界

| 信息或状态 | 本主体需要保存/读取 | 边界 |
|---|---|---|
| 业务与委任 | 可见需求、服务范围、报价、费用、委托人和授权 | 邀请或角色参与不等于已取得全部成本权限 |
| 资源排期 | 估算、采购评审、计量等任务与跨项目人员 | 不把同一时段人员用于多份满负荷任务 |
| 设计数量 | 成果版本、范围、工程量/计量依据与未知项 | 不默认为最终设计或已完工程 |
| 价格资料 | 来源、地区、币种、单位、时点、有效范围 | 历史价格和市场预测不等于当前有效报价 |
| 采购材料 | 获准读取的采购文件、投标及澄清记录 | 不默认看到其他顾问客户或投标人内部成本 |
| 合同与指令 | 适用计价方式、有效条款、变更和核证授权 | 有权评估费用不等于有权改变双方合同 |
| 履约证据 | 获准取得的数量、检查、交付和计量记录 | 付款申报不直接成为已核证事实 |
| 成本成果 | 估算、比较、评价、计价与结算版本和引用 | 新报告不静默覆盖旧报告或正式账本 |
| 自身资金认知 | 内部成本、服务应收、实际收款及伙伴评价 | 对项目成本判断与本企业现金状态分开 |

**QS-004｜信息同口径后才比较。** 每次比较说明范围、时间、币种、税费/价格组成及风险假设；缺少必要转换依据时保留不可比项。
只向有权接收方披露对应资料；同时服务多个客户时，不把一方保密报价当作另一方可见事实。
合法排除投标、出具具有合同效力的核证或确定计价结果，均需单独说明本次授权和依据。

### 2.2 正式状态与私有判断的所有者

| 状态 | 权威维护者/私有归属 | 本主体可改变的范围 |
|---|---|---|
| 商业吸引力、估算假设、客户风险和报价底线 | 本主体私有认知 | 更新判断及来源，不修改对方报价/实际成本 |
| 私有价格资料库与已取得来源记录 | 本主体资料记录及来源版本 | 整理有权数据，不能捏造新市场观测 |
| 委任、评价/核证权限和范围 | 共同合同/授权入口 | 提出、有效接受及申请变更自己的服务 |
| 人员排期、任务投入和完成 | 共同资源/任务入口 | 提交分派与证据，不能让总价服务自动完成 |
| 估算、评标、计量与计价结果 | 成果/计量/有权核证入口 | 写本次有权范围，保留输入和原始申报 |
| 正式合同价、义务、清偿与自身收费 | 相应合同/共同资金入口 | 提交意见或有权结果供核心处理，不直接改现金 |

### 2.3 关键对象及字段

**QS-021｜每项金额能说明对象、量价基础及法律/业务性质。** 下列字段定义业务语义；事实记录与估算、申报、核实、核证分别保留。

| 对象 | 身份、版本及关键字段 | 主要用途 |
|---|---|---|
| 服务职能 | `engagement_id/version`、客户、付款人、职能、范围、保密/冲突及权限 | 识别本次代表谁、可提交何种结果 |
| 量价基础 | `quantity_basis_id/version`、设计/包件/部位、单位、计量规则、原数量、方法及证据 | 不把设计量、已完量、到货量和付款认可量混用 |
| 价格/估算 | `estimate_id/version`、来源价、时点、币种、范围、假设与可比调整 | 保留原报价与专业比较，报告未知/排除项 |
| 采购评价 | `procurement_round_id`、文件/投标/澄清版本、评价授权、原值及调整理由 | 逐份评价而不改投标人报价或替采购人授标 |
| 变更/索赔估值 | `change_or_claim_id/version`、事件、权利判断引用、范围、估值、争议及有效决定 | 区分事件发生、主张、有权结果及账本后果 |
| 计量/核证 | `application_id/version`、范围/期间、累计或本期口径、核证版本、组成及义务引用 | 识别新增/重复范围、保留款、抵扣和修正 |
| 最终账目/移交 | `account_id/version`、基准、有效调整、核证/清偿引用、未决项和接收 | 核对金额来源、合法余额和剩余支持义务 |

## 3. 行为卡与执行契约

行为卡先说明触发、选择、正式后果及等待/失败，再定义函数、具名输入、输出分支、接收者和验收。执行矩阵汇总资源与交接。卡内“正式结果”指相应命令成功提交后的效果；`ActionResult.completed` 只表示本主体输出已形成。

<!-- action-nav:start -->
**动作定位**：[QS-A01](#qs-a01--识别业务并维护可用市场资料) · [QS-A02](#qs-a02--独立评估服务范围并接单) · [QS-A03](#qs-a03--确认委任并安排实际任务) · [QS-A04](#qs-a04--编制方案估算与成本计划) · [QS-A05](#qs-a05--准备量价与采购成本资料) · [QS-A06](#qs-a06--评价投标并提出成本意见) · [QS-A07](#qs-a07--评估变更索赔与费用影响) · [QS-A08](#qs-a08--计量核实支付申请或获授权核证) · [QS-A09](#qs-a09--编制最终结算意见与清单) · [QS-A10](#qs-a10--申报本企业服务费并收款) · [QS-A11](#qs-a11--暂停交接及结束服务) · [QS-A12](#qs-a12--从履约反馈更新估算与经营判断) · [QS-A13](#qs-a13--接收需求版本并形成前期方案成本比较)
<!-- action-nav:end -->

### QS-A01 · 识别业务并维护可用市场资料

- **触发与输入**：可见咨询机会、市场报价/指数和自身专业方向、资料权限及研究预算。
- **自主选择**：跟踪需求、表达兴趣、请求澄清、开展有投入的资料整理或不参与。
- **正式结果**：本主体的机会评估、资料来源和版本；新增数据只按其真实性和适用范围使用。
- **等待与失败**：市场更新文字不自动生成新价格观测或订单；无法比较的历史资料保留限制。

**函数与类型契约**

- **函数**：`roles.qs.a01(ctx: ActionContext, input: QSA01Input) -> ActionResult<QSA01Payload>`。
- **输入记录**：`QSA01Input = {scope:ScopeRef; opportunity_refs:List<Ref<Opportunity>>; price_source_refs:List<Ref<PriceSource>>; strategy_ref:Ref<Strategy>; research_authority_ref:Option<Ref<Authority>>}`。来源：可见咨询机会、报价/指数原始来源、经营目标及获准研究范围。
- **输出分支**：`QSA01Payload` 的 `choice` 与分支必填字段为：`track{opportunity_ref:Ref<Opportunity>,trigger_ref:Ref<Trigger>}; express_interest{recipient_id:EntityId<Agent>,scope:ScopeRef}; prepare{request:QSTaskRequest}; register_source{source_refs:List<Ref<PriceSource>>,applicability:QSPriceApplicability}; ignore{reason:string}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交机会/资料服务或邀请方；整理资料不生成新的真实价格观测、有效订单或自动提高可信度。
- **业务出口与验收**：原数据权限/可比性不足保留限制；CHECK-QS-006、CHECK-QS-026。

### QS-A02 · 独立评估服务范围并接单

- **触发与输入**：要求提供的估算/采购/计量等服务、责任、资料成熟度、期限、费用和共享排期。
- **自主选择**：接受当前条款、提出费用/排期/阶段范围、请求补充信息、暂缓或拒绝。
- **正式结果**：服务方案、有效期、接受状态与必要预留；前期估算可以是独立有限服务。
- **等待与失败**：无能力、资料或资源时说明限制；顾问技术失败不被替换为正式接受或商业拒绝。

**函数与类型契约**

- **函数**：`roles.qs.a02(ctx: ActionContext, input: QSA02Input) -> ActionResult<QSA02Payload>`。
- **输入记录**：`QSA02Input = {scope:ScopeRef; request_ref:Ref<ServiceRequest>; terms_ref:Ref<ServiceTerms>; capability_ref:Ref<Capability>; capacity_ref:Ref<ResourceCalendar>; conflict_check_ref:Option<Ref<ConflictCheck>>}`。来源：委托方请求和条款、本方能力/排期及职能冲突核验。
- **输出分支**：`QSA02Payload` 的 `choice` 与分支必填字段为：`accept{terms_ref:Ref<ServiceTerms>}; counteroffer{offer:QSServiceOffer}; decline{reason:string}; clarify{questions:List<QSQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`conflict_check_ref=null` 表示尚无已核验利益冲突记录，可澄清/报价但不能形成依赖独立性的有效接受；已知冲突按本任务规则拒绝或请求调整，技术失败不能冒充冲突结论。
- **接收与核心效果**：交实际委托方/委任服务；记录本方选择/报价，不将被选中写成有效委任或核证权。
- **业务出口与验收**：技术故障不作为业务拒绝；CHECK-QS-002、CHECK-QS-003、CHECK-QS-034。

### QS-A03 · 确认委任并安排实际任务

- **触发与输入**：相容有效的委任或内部授权、具体职能、工作量/耗时、前置资料及最新资源状态。
- **自身行为**：确认服务和核证边界，分配人员、排序、安排合法并行或请求调整。
- **正式结果**：核心登记服务与任务承诺，报价预留转占用；投入及完成关联真实模型内工作证据。
- **等待与失败**：对方选择不能代替本主体接受；重复提交不重复占额；任务续办不被自己的既有占用阻断。

**函数与类型契约**

- **函数**：`roles.qs.a03(ctx: ActionContext, input: QSA03Input) -> ActionResult<QSA03Payload>`。
- **输入记录**：`QSA03Input = {scope:ScopeRef; appointment_ref:Ref<Appointment>; accepted_terms_ref:Ref<ServiceTerms>; function_refs:List<Ref<FunctionAssignment>>; task_refs:List<Ref<Task>>; capacity_ref:Ref<ResourceCalendar>; work_profile_ref:Option<Ref<WorkProfile>>; existing_allocation_refs:List<Ref<ResourceAllocation>>}`。来源：相容接受、具体职能/工作清单、任务投入方法和本方真实排期。
- **输出分支**：`QSA03Payload` 的 `choice` 与分支必填字段为：`confirm{appointment_ref:Ref<Appointment>,accepted_terms_ref:Ref<ServiceTerms>}; confirm_and_plan{appointment_ref:Ref<Appointment>,accepted_terms_ref:Ref<ServiceTerms>,plan:QSTaskPlan}; request_amendment{questions:List<QSQuestion>}; revise_plan{plan:QSTaskPlan,prior_plan_ref:Ref<WorkPlan>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：首次委任尚无业务 Task 时允许 `confirm`，由有效委任和工作清单创建任务后再排期；`task_refs=[]` 不阻止单独确认。`confirm_and_plan/revise_plan` 要求真实任务及非空 work_profile_ref；该字段为空仅表示尚未取得排期方法，不能凭报价直接生成已占容量。
- **接收与核心效果**：先委任服务确认，再资源服务分派；两个命令各有回执，分派失败不得伪报全部完成；实际投入另记。
- **业务出口与验收**：无容量deferred，续办复用已有占用；CHECK-QS-003、CHECK-QS-004、CHECK-QS-005。

### QS-A04 · 编制方案估算与成本计划

- **触发与输入**：对应成熟度的设计版本、数量/价格依据、项目范围、地区、时点与不确定性。
- **自主选择**：采用支持的方法估算、比较选项、提出敏感假设、请求询价/补量或说明无法可靠判断。
- **正式结果**：成本计划版本、明细或代理方法、范围/排除项和区间；向获授权接收方提供取舍依据。
- **等待与失败**：不强制前期先有最终施工价；不得凭 LLM 自编数值绕过计算，也不把估算写成预算批准或已发生成本。

**函数与类型契约**

- **函数**：`roles.qs.a04(ctx: ActionContext, input: QSA04Input) -> ActionResult<QSA04Payload>`。
- **输入记录**：`QSA04Input = {scope:ScopeRef; brief_ref:Ref<Brief>; option_ref:Ref<DesignOption>; task_ref:Ref<Task>; cost_scope_ref:Ref<CostScope>; quantity_basis_refs:List<Ref<QuantityBasis>>; price_refs:List<Ref<Price>>; method_result_refs:List<Ref<MethodResult>>; comparison_basis_ref:Ref<ComparisonBasis>}`。来源：授权设计/专业数量依据、同口径价格、量取/计价正式方法结果；不是客户预算倒推值。
- **输出分支**：`QSA04Payload` 的 `choice` 与分支必填字段为：`estimate{draft:QSCostPlan}; request_quantity{questions:List<QSQuestion>}; request_price{questions:List<QSQuestion>}; report_limits{draft:QSCostPlan,reason:string}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`estimate` 必须具有适用计算，至少存在已计算范围；允许代理估算但须声明代理方法及未计范围。`report_limits` 可在尚无量表/计算时形成缺项报告，此时不生成已知小计或总价。首次任务不要求先有本次 CostPlan，保存后取得版本再交 A13。
- **接收与核心效果**：交成本成果服务及Owner/Architect/Engineer；形成估算版本和缺项，不能改变投资预算、合同债务、已发生成本或现金。
- **业务出口与验收**：未知保留ValueState，完整范围缺项则complete_total为空；CHECK-QS-007、CHECK-QS-042、CHECK-QS-043、CHECK-QS-044、CHECK-QS-045。

### QS-A05 · 准备量价与采购成本资料

- **触发与输入**：获授权采购任务、设计/性能范围、所选采购方式及需定价的合同包。
- **自主选择**：整理计量基础、价目/报价结构、费用边界，识别漏项与不确定部分并提出澄清。
- **正式结果**：带版本的量价文件、计价假设与待决项，按本主体权限提交或申请发布。
- **等待与失败**：不自动补齐未设计部分；QS 发布成本资料不等于采购人已批准招标或监管已准许施工。

**函数与类型契约**

- **函数**：`roles.qs.a05(ctx: ActionContext, input: QSA05Input) -> ActionResult<QSA05Payload>`。
- **输入记录**：`QSA05Input = {scope:ScopeRef; procurement_scope_ref:Ref<ProcurementScope>; design_refs:List<Ref<Deliverable>>; measurement_rule_ref:Ref<MeasurementRule>; quantity_schedule_ref:Option<Ref<QuantitySchedule>>; prior_document_ref:Option<Ref<ProcurementDocument>>; publication_authority_ref:Option<Ref<Authority>>}`。来源：采购包范围、设计版本、量取规则、已正式形成的工程量表及独立发布权。
- **输出分支**：`QSA05Payload` 的 `choice` 与分支必填字段为：`prepare{draft:QSProcurementDocument}; identify_gaps{questions:List<QSQuestion>}; request_publication{document_ref:Ref<ProcurementDocument>,recipient_id:EntityId<Agent>}; publish_authorized{document_ref:Ref<ProcurementDocument>,publication_basis_ref:Ref<PublicationBasis>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`identify_gaps` 可在尚无量表时返回，`quantity_schedule_ref=null` 只表示本次没有已登记量表。编制依赖量表的文件前，先按选定计量方法生成并登记量表；需要暂定/未定数量的采购方式须由其模板显式支持。发布分支必须引用已保存文件、完成必要用途检查与授权，不能直接发布尚未保存的 draft。
- **接收与核心效果**：编制成果交有权采购人；已编文件经采购发布入口后投标人可见；草稿不自动改已发采购文件。
- **业务出口与验收**：修订必须列受影响包件/数量；缺发布权只能请求发布；CHECK-QS-010、CHECK-QS-037。

### QS-A06 · 评价投标并提出成本意见

- **触发与输入**：获准读取的同轮采购文件、有效投标、澄清和规定的评价职责/方法。
- **自主选择**：比较可比价格与风险、请求合规澄清、评价或在获得权限时排除不符合要求的投标。
- **正式结果**：逐份评价、理由、证据和可比性调整记录；价格规范化不直接修改投标人的原报价。
- **等待与失败**：最低名义价不自动最优；推荐或评分不直接授标，未知资格与技术失败不得伪装为真实废标理由。

**函数与类型契约**

- **函数**：`roles.qs.a06(ctx: ActionContext, input: QSA06Input) -> ActionResult<QSA06Payload>`。
- **输入记录**：`QSA06Input = {scope:ScopeRef; round_ref:Ref<ProcurementRound>; procurement_document_ref:Ref<ProcurementDocument>; bid_refs:List<Ref<Bid>>; clarification_refs:List<Ref<Clarification>>; evaluation_profile_ref:Ref<EvaluationProfile>; method_result_refs:List<Ref<MethodResult>>}`。来源：同轮文件/原始报价及合法澄清，有权评价方法和已算可比转换。
- **输出分支**：`QSA06Payload` 的 `choice` 与分支必填字段为：`evaluate{evaluations:List<QSBidEvaluation>,ranking_ref:Option<Ref<MethodResult>>}; clarify{questions:List<QSQuestion>}; no_valid_bid{evaluations:List<QSBidEvaluation>,reason:string}; exclude_authorized{bid_ref:Ref<Bid>,rule_ref:Ref<EvaluationRule>,evidence_refs:List<Ref<Evidence>>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交采购评价服务和有权授标人；可以提出推荐或有权排除，不修改原投标、不直接授标签约。
- **业务出口与验收**：无有效报价是业务结果；未知资格/技术故障不记废标；CHECK-QS-008、CHECK-QS-009、CHECK-QS-020、CHECK-QS-037。

### QS-A07 · 评估变更、索赔与费用影响

- **触发与输入**：有效指令或申报、原合同、变更范围、量价、延误/扰动证据与本主体授权。
- **自主选择**：计价、要求补证、提出可认定与有争议部分、形成范围内建议或有权结果。
- **正式结果**：计价版本、依据、责任待决项和费用/工期接口；后续合同或付款变化引用有效决定。
- **等待与失败**：原因标签不决定谁付款；发生实际费用不等于合同有权获偿，费用争议不自动阻止所有有义务的工作。

**函数与类型契约**

- **函数**：`roles.qs.a07(ctx: ActionContext, input: QSA07Input) -> ActionResult<QSA07Payload>`。
- **输入记录**：`QSA07Input = {scope:ScopeRef; claim_or_change_ref:Ref<ChangeClaim>; contract_ref:Ref<Contract>; instruction_ref:Option<Ref<Instruction>>; evidence_refs:List<Ref<Evidence>>; entitlement_ref:Option<Ref<EntitlementDecision>>; valuation_result_ref:Option<Ref<MethodResult>>}`。来源：原合同、有权指令/真实事件、申报及权利判断、正式量价输出。
- **输出分支**：`QSA07Payload` 的 `choice` 与分支必填字段为：`value{valuation:QSValuation}; request_evidence{questions:List<QSQuestion>}; determine_authorized{valuation:QSValuation,determination_basis_ref:Ref<DeterminationBasis>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：缺计价结果时可 `request_evidence`；`valuation_result_ref=null` 表示尚无本次适用计价结果。`value/determine_authorized` 必须取得结果，金额与结果一致；后者另需有权确定依据。待定权利不阻止有据估值，估值也不反向产生权利。
- **接收与核心效果**：交有权合同决定者及计价服务，再到A08/A09；估值不自动确认获偿权；有权决定才触发相应合同/义务变更。
- **业务出口与验收**：责任待决不填确定付款人；CHECK-QS-011、CHECK-QS-036。

### QS-A08 · 计量、核实支付申请或获授权核证

- **触发与输入**：有效付款申请、已完/交付证据、合同计价、保留/抵扣与既有核证及支付记录。
- **自主选择**：核量、请求补证、确认适用部分、提出争议；具有核证权时才提交正式证书/结果。
- **正式结果**：说明申报、核实、核证和余额的对应关系，按合同保留记录；实际付款由相应资金入口执行。
- **等待与失败**：工程师检查意见只作为其范围证据，不直接替代计价与付款条件；不能因项目有资金就全部核准申报。

**函数与类型契约**

- **函数**：`roles.qs.a08(ctx: ActionContext, input: QSA08Input) -> ActionResult<QSA08Payload>`。
- **输入记录**：`QSA08Input = {scope:ScopeRef; application_ref:Ref<PaymentApplication>; contract_ref:Ref<Contract>; performed_work_refs:List<Ref<WorkFact>>; prior_certificate_refs:List<Ref<Certificate>>; payment_receipt_refs:List<Ref<PaymentReceipt>>; measurement_result_refs:List<Ref<MethodResult>>; certification_authority_ref:Option<Ref<Authority>>}`。来源：承包/供货付款申请、实做/交付证据、合同保留抵扣、历史核证与有权可见付款。
- **输出分支**：`QSA08Payload` 的 `choice` 与分支必填字段为：`verify{statement:QSValuation}; request_evidence{questions:List<QSQuestion>}; certify{statement:QSValuation,certification_basis_ref:Ref<CertificationBasis>}; correct_certificate{prior_certificate_ref:Ref<Certificate>,statement:QSValuation,correction_basis_ref:Ref<CorrectionBasis>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`verify/certify/correct_certificate` 均需与申报范围和期间对应的计量/计价结果；否则请求补证或返回缺项。修正证书必须引用本合同原证书并有纠正权，不能新造第二笔累计义务；付款证据不可见与没有发生付款分别表示。
- **接收与核心效果**：核实交有权核证者；certify/correct经核证/义务服务只调整适用义务，付款由付款人/资金服务执行；不得生成现金。
- **业务出口与验收**：同范围累计须给本期差额计算引用，无核证权不得certify；CHECK-QS-012、CHECK-QS-013、CHECK-QS-028、CHECK-QS-029、CHECK-QS-038、CHECK-QS-039。

### QS-A09 · 编制最终结算意见与清单

- **触发与输入**：获授权结算任务、合同基准、已确认变更/索赔、计量、核证、已付款及未决事项。
- **自主选择**：核对、补证、提出结算建议，按权限分列无争议与争议金额并回应质疑。
- **正式结果**：可追溯结算版本、余额和待决责任；具有确定效力的结果必须说明授权与适用机制。
- **等待与失败**：完工不自动确定最终价；结算形成不代表已付款、贷款已清偿或所有争议消失。

**函数与类型契约**

- **函数**：`roles.qs.a09(ctx: ActionContext, input: QSA09Input) -> ActionResult<QSA09Payload>`。
- **输入记录**：`QSA09Input = {scope:ScopeRef; contract_ref:Ref<Contract>; determined_change_refs:List<Ref<EntitlementDecision>>; certificate_refs:List<Ref<Certificate>>; payment_receipt_refs:List<Ref<PaymentReceipt>>; unresolved_claim_refs:List<Ref<ChangeClaim>>; reconciliation_result_ref:Option<Ref<MethodResult>>}`。来源：有效合同和确定调整、量证付款历史、未決事项及正式对账计算。
- **输出分支**：`QSA09Payload` 的 `choice` 与分支必填字段为：`propose_account{account:QSFinalAccount}; request_evidence{questions:List<QSQuestion>}; determine_authorized{account:QSFinalAccount,determination_basis_ref:Ref<DeterminationBasis>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`reconciliation_result_ref=null` 表示尚无本次适用对账结果，可补证；`propose_account/determine_authorized` 必须取得范围和付款记录相容的对账结果。资料不可见造成的金额未知保留 ValueState，不把未知变为零或认为已清偿。
- **接收与核心效果**：交合同双方/有权结算者及义务服务；只确认有依据范围，不删除争议、未付款或Bank贷款。
- **业务出口与验收**：完工不能替代结算决定，回执未知不能填已付；CHECK-QS-014、CHECK-QS-040。

### QS-A10 · 申报本企业服务费并收款

- **触发与输入**：自身委任的计费条件、投入/成果证据、费用条款、确认与到账状态。
- **自主选择**：申报、补证、修正、提出异议或按权利处理逾期；不得将本企业收费混入他人合同核证。
- **正式结果**：外部服务应收与实际收款关联；内部任务记录内部成本，不形成组织对自己的顾问费。
- **等待与失败**：未付本企业费用不自动改变其已提交的工程估算或结算；原合同义务和新增服务收费分开。

**函数与类型契约**

- **函数**：`roles.qs.a10(ctx: ActionContext, input: QSA10Input) -> ActionResult<QSA10Payload>`。
- **输入记录**：`QSA10Input = {scope:ScopeRef; engagement_ref:Ref<Engagement>; billing_clause_ref:Ref<BillingClause>; work_fact_refs:List<Ref<WorkFact>>; calculation_ref:Option<Ref<FeeCalculation>>; prior_claim_ref:Option<Ref<FeeClaim>>; receipt_refs:List<Ref<PaymentReceipt>>}`。来源：QS自身委任/收费依据和投入，与他人工程款资料严格分开。
- **输出分支**：`QSA10Payload` 的 `choice` 与分支必填字段为：`claim{claim:QSFeeClaim}; correct{prior_claim_ref:Ref<FeeClaim>,claim:QSFeeClaim}; dispute{claim_ref:Ref<FeeClaim>,issue:QSQuestion}; reconcile{claim_ref:Ref<FeeClaim>,receipt_refs:List<Ref<PaymentReceipt>>}; remind{claim_ref:Ref<FeeClaim>,recipient_id:EntityId<Agent>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`claim/correct` 必须有适用计费计算；`correct/dispute/reconcile/remind` 必须引用本方已有费用申报，且不得改收款主体或合同。催收、争议和对账可在 `calculation_ref=null`（本次没有新计费计算）时进行；对账仍需真实回执，未知到账保持待核。内部任务不进入外部服务费申报分支，成本按实际工作执行归集。
- **接收与核心效果**：交真正委托/付款方和资金义务服务；保存自身应收/支付关联，不修改他人核证或以自身收款清偿客户工程款。
- **业务出口与验收**：内部任务不产生自我收费；CHECK-QS-005、CHECK-QS-015、CHECK-QS-033、CHECK-QS-041。

### QS-A11 · 暂停、交接及结束服务

- **触发与输入**：有效暂停/退出、后续计量或争议支持请求、当前排期、资料使用权和未清责任。
- **自主选择**：按权利调整任务、安排召回、移交合法资料或评估接任范围。
- **正式结果**：逐任务处理资源及资料访问，保留作者、价格来源、计量轨迹、费用与未决结算义务。
- **等待与失败**：关闭项目不自动释放所有争议支持责任；接任者不无成本继承全部确认，也不获取前任私有客户资料。

**函数与类型契约**

- **函数**：`roles.qs.a11(ctx: ActionContext, input: QSA11Input) -> ActionResult<QSA11Payload>`。
- **输入记录**：`QSA11Input = {scope:ScopeRef; engagement_ref:Ref<Engagement>; transition_basis_ref:Ref<ServiceTransitionBasis>; task_refs:List<Ref<Task>>; allocation_refs:List<Ref<ResourceAllocation>>; deliverable_refs:List<Ref<Deliverable>>; residual_obligation_refs:List<Ref<Obligation>>}`。来源：合法暂停/结束依据，后续计量/争议支持与数据访问权限。
- **输出分支**：`QSA11Payload` 的 `choice` 与分支必填字段为：`pause{task_refs:List<Ref<Task>>,basis_ref:Ref<ServiceTransitionBasis>}; recall{plan:QSTaskPlan}; handover{package:QSHandover}; exit{package:QSHandover}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交接任QS/委托方及资源任务服务；逐项处理访问和占用，保存原作者、量价与未结义务。
- **业务出口与验收**：接任核查有投入；资源释放不等于债务清偿；CHECK-QS-016、CHECK-QS-041。

### QS-A12 · 从履约反馈更新估算与经营判断

- **触发与输入**：有权取得的中标、履约、结算、市场及本企业成本/收款反馈。
- **自主选择**：比较此前估计与可比结果，修订未来假设、业务选择或提出能力建设任务。
- **正式结果**：保留原预测及误差解释，新增有来源的资料/认知版本；能力更新需另有明确机制。
- **等待与失败**：不能拿最终结算价格回填过去预测后宣称估算准确；未经授权的他人实际成本不作为已知数据。

**函数与类型契约**

- **函数**：`roles.qs.a12(ctx: ActionContext, input: QSA12Input) -> ActionResult<QSA12Payload>`。
- **输入记录**：`QSA12Input = {scope:ScopeRef; forecast_refs:List<Ref<CostPlan>>; outcome_refs:List<Ref<Outcome>>; feedback_refs:List<Ref<Feedback>>; comparability_result_ref:Option<Ref<MethodResult>>; learning_profile_ref:Option<Ref<LearningProfile>>; strategy_ref:Ref<Strategy>}`。来源：有权可见的历史预测与实际结果、独立可比性检验和已启用学习规则。
- **输出分支**：`QSA12Payload` 的 `choice` 与分支必填字段为：`record_feedback{feedback_refs:List<Ref<Feedback>>,interpretation:string}; analyze_error{forecast_ref:Ref<CostPlan>,outcome_ref:Ref<Outcome>,error_result_ref:Ref<MethodResult>}; update_judgment{revision:QSJudgment}; propose_training{request:QSTaskRequest,learning_profile_ref:Ref<LearningProfile>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交认知/资料服务或能力建设任务；只生成新认知/校准版本，不回填旧预测，不改他方私有成本。
- **业务出口与验收**：不可比结果不能产误差指标，无学习机制不自动更新能力；CHECK-QS-017、CHECK-QS-026。

### QS-A13 · 接收需求版本并形成前期方案成本比较

- **触发与输入**：获授权的前期研究任务，以及 Owner 的需求简报、当前选项和可取得的专业/供应资料。
- **自主选择**：开展有限估算、提出可比性修正、请求有针对性的补充研究或询价，或说明当前无法可靠排序。
- **正式结果**：形成带输入版本、成本范围、依据、不确定项和适用用途的比较意见；可供业主继续调查、调整方案或判断投资。
- **等待与失败**：未形成正式项目或完整设计不阻止有限研究；输入资料不足不被转换为项目不可行、确定价格或投资批准。

**函数与类型契约**

- **函数**：`roles.qs.a13(ctx: ActionContext, input: QSA13Input) -> ActionResult<QSA13Payload>`。
- **输入记录**：`QSA13Input = {scope:ScopeRef; brief_ref:Ref<Brief>; research_authority_ref:Ref<Authority>; task_ref:Ref<Task>; option_refs:List<Ref<DesignOption>>; assessment_refs:List<Ref<Assessment>>; cost_plan_refs:List<Ref<CostPlan>>; comparison_basis_ref:Ref<ComparisonBasis>; expenditure_limit_ref:Ref<ResearchLimit>}`。来源：Owner简报/有限委任、同版方案、专业/供应输入及A04正式成本计划。
- **输出分支**：`QSA13Payload` 的 `choice` 与分支必填字段为：`compare{comparison:QSComparison}; request_research{questions:List<QSQuestion>,request:QSTaskRequest}; cannot_rank{comparison:QSComparison,reason:string}; deliver_at_limit{comparison:QSComparison,remaining_questions:List<QSQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：成本计划列表可为空，此时只可补查、交有限报告或 cannot_rank；`compare` 至少消费一个已提交成本计划，各计划与输入方案/比较基准相容。`comparable=true` 不自动产生排名，排序还需指定方法；新估算沿 A04 先形成并保存，不在 A13 另造金额。
- **接收与核心效果**：比较报告经成果服务交Owner/有权委托人；可不排序，不直接授标/锁价/保留产能或作投资批准，估算任务沿A04去重。
- **业务出口与验收**：无project_id合法，币种/范围不齐须cannot_rank或补证；CHECK-QS-001、CHECK-QS-019、CHECK-QS-022、CHECK-QS-023、CHECK-QS-024、CHECK-QS-027。

### 3.1 全行为执行与交接矩阵

表中“正式输出”只有在权限、版本和证据检查后成立；估算/计量数值来自获支持的方法，语言模型不另造一套正式金额。

| 行为 | 输入与允许选择 | 正式输出 | 资源与时间 | 失败或等待 | 下一交接 |
|---|---|---|---|---|---|
| A01 业务/资料经营 | 有来源机会和价格信息；整理、研究、跟踪或忽略 | 资料版本、私有机会与授权研究任务 | 收集清理有实际投入 | 失效/不适用资料标记限制，不填新观测 | A02 或后续估算任务 |
| A02 接单 | 具体职能、费用、责任和负荷；报价、限缩、接受或拒绝 | 服务方案和有效接受 | 必要预留有期限/释放依据 | 冲突、能力不足或技术失败分别处理 | 相容接受后 A03 |
| A03 委任排程 | 授权与工作清单；分派、合法并行或调期 | 服务/任务承诺及实际投入 | 共享人员、续办延续已有分派 | 资料待补只阻塞其依赖任务 | A04—A09 或 A13 |
| A04 成本计划 | 设计/数量与价格版本；估算、补量、询价或给限制 | 分项估算/区间及比较基准 | 量取和估算各有工作依据 | 缺数据不填零，不从预算倒造单价 | 有权委托方、Architect/Engineer |
| A05 采购资料 | 包件范围、计量规则和设计；编表、识别漏项或补问 | 量价文件及未决项、提交/发布引用 | 按包件和成熟度安排任务 | 设计变化标影响，不自动改已发采购版 | 有权采购人发布、投标方使用 |
| A06 投标评价 | 同轮采购文件、原投标及澄清；比较、询问或获授权排除 | 逐份评价、可比调整和推荐 | 每份评审有范围和投入 | 缺项/无效报价/技术失败不混同，零有效投标可返回 | 有权授标方决定，投标人有权回应 |
| A07 变更索赔 | 指令/事件、条款、数量及责任证据；估值、补证或分列争议 | 金额建议/有权计价及适用范围 | 事件调查与计价投入分开 | 有成本不等于有获偿权，待决部分不自动消失 | 有权合同方/决定者与 A08/A09 |
| A08 计量核证 | 申请范围/期间、工作与交付证据、原核证；核量、限认可或补证 | 核实或有权核证版本及原义务引用 | 计量窗口与证据取得需时间 | 未检部分不全额认可，重复累计范围不新增 | 实际付款人及共同义务入口 |
| A09 最终账目 | 原合同、有效变更、累计量价及争议；核对、分列或建议确定 | 结算版本、差额、未决责任 | 最终对账和补证有任务 | 完工不等于结算一致，贷款不由本表清偿 | 有权合同方，资金/争议程序 |
| A10 自身服务费 | QS 自己的合同、工作及到期；申报、催收、修正或争议 | 独立服务应收与现金引用 | 财务核对与工程款核证分开 | 自身欠费不改变他人工程款结论 | 真正委托/付款方 |
| A11 接续退出 | 有效暂停/结束、资料权限和残余事项；移交、召回或限缩 | 任务资源处理、合法资料与责任清单 | 接任核查/后续争议支持有独立排期 | 不无成本继承确认，不销毁未决计量轨迹 | 接任 QS/委托方及后续事项 |
| A12 反馈学习 | 可比估计/结果与本企业投入回款；校对误差、修订未来假设 | 新认知/资料版本与能力任务 | 校准/培训若纳入有投入 | 不回填旧估算伪造准确率 | A01/A02/A04 后续业务 |
| A13 前期比较 | 有限简报与备选；有限估算、补充研究或不排序 | 同范围比较、未知和可用条件 | 研究限额及共享任务去重 | 无正式项目不阻止研究，研究不自动定价/授标 | 有权委托方的研究/投资取舍 |

### 3.2 输入输出类型与提交边界

本节与每张行为卡共同构成函数契约。所有签名是目标开发接口，不表示已有同名函数或方法已实现。完整公共类型见[接口契约](../06_engineering/interface_contracts.md)。

- `ActionContext.task_ref` 标识宿主登记的本次决策调用任务；业务工作任务由各 Input 的 `task_ref/task_refs` 明确引用，两者不能互换。首次机会评估或工作申请不要求尚未创建的业务任务。
- 每个 `Input` 为封闭记录，均包含 `scope:ScopeRef`，加本卡列明字段；前期工作允许 `assessment_case`，不要求虚构项目。经营/发现行为可用 `organization`。身份、职能、授权、可见版本和候选由 `ActionContext` 绑定，不接受主体在输入里自行增权。
- 本卡写作 `choice{fields}` 的每一项表示独立分支 `{choice:"choice",fields...}`；合起来就是对应具名 `Payload` 的完整判别联合。各分支另共同包含 `scope:ScopeRef` 和 `note:Option<string>`。未声明字段禁止出现；不得在拒绝分支夹带接受、金额、资源占用或批准字段。
- `Option<T>` 可空且键仍存在，其他字段必填。输入列表为空只表示当前已获准可见的集合没有记录，不证明世界上不存在该事实；必需资料的覆盖另由要求清单核验。分支所需接收者、申请依据、实际方案/任务及费用条款不得为空。宿主无法装配必填输入时登记 `needs_information`；错误类型/漏键先走结构校验。`scope` 必须落在授权范围内且与输入对象一致。
- `completed(payload)` 仅表示行为输出完成。其后由应用服务拆分并提交必要原子命令，由核心回执确认正式效果；多条命令不默认为一个已全部成功的事务。接收者收到的是获授权的已提交对象投影。技术错误走 `technical_error`，业务拒绝是 `payload.choice`，资源/业务等待走 `deferred`；方法不支持走 `unsupported`，可独立完成的有限报告仍保留未覆盖项。
- 空值语义固定：`prior_*`/`parent_*` 表示没有适用前序；可空授权/签署/独立性依据表示当前没有可用记录，依赖该依据的分支必须返回缺项或权限拒绝；可空方法结果表示尚无适用执行结果，不能填通过；`learning_profile_ref=null` 表示没有启用学习规则。已知数值缺失仍用 `ValueState`，不能挪用空值或空列表表达零。本角色 `complete_total=null` 只表示尚无可给出的完整范围总额，`price_ref=null` 表示该行未匹配价格，`ranking_ref=null` 表示未形成支持的排序结果；认可/已付金额未知须用 `ValueState<Money>`，不能填零。
- `Ref<MethodResult>` 指已登记的具体方法执行记录（输入版本、方法版本、输出 schema、结果及来源），不是未提交的通用 `MethodResult<T>` 返回信封；需要使用其数值时先校验执行成功、支持范围和用途。输出中所有新引用均须可解析；尚未存在的对象使用本节封闭草案记录交责任服务创建。
- 文本用于解释、问答及专业理由。会影响后续门控的用途、数量、条件、缺项和受影响范围必须使用字段/引用表达。所有数值输出来自适用计算/观察方法；纯登记、转送、排期执行和去重可由确定性程序处理，不强制调用 LLM。
- 对尚未执行的数值计算、量取、观测或检查，先保留候选/问题并安排获授权方法执行；方法执行记录保存后，宿主才能在下一次装配中提供可解析引用。一个行为可由多个函数协作完成，不把一次模型回复等同全部任务执行。有限报告完成与其所评对象满足要求分别验收。
- 下表 `Ref<K>` 的 K 为有版本对象类别，含义由本角色 §2.3、§4 及[共同对象](../02_world/domain_objects.md)约束；不是自由附件或任意字典。已有对象的相容投影可以只读复用；尚未登记的准备对象须先由其责任服务创建并绑定 schema/method/profile，禁止编造一个引用绕过缺失实现。正式 `EntityId<K>` 由核心创建；草案内局部行键不能冒充正式业务 ID。

| 局部类型 | 完整字段或封闭取值 |
|---|---|
| `QSUse` | `research / cost_estimation / regulatory_submission / procurement / construction / operation`；只可选本任务、对象及授权允许的子集，许可名称不由此枚举决定 |
| `QSQuestion` | `scope:ScopeRef; target_refs:List<Ref<EvidenceTarget>>; question:string; recipient_ids:List<EntityId<Agent>>; evidence_refs:List<Ref<Evidence>>; blocking_uses:List<QSUse>; response_requirement_ref:Ref<ResponseRequirement>` |
| `QSTaskRequest` | `scope:ScopeRef; purpose:preparation/service_delivery/investigation/training/remedy/policy_evaluation; input_refs:List<Ref<BusinessObject>>; output_requirement_refs:List<Ref<DeliverableRequirement>>; work_profile_ref:Option<Ref<WorkProfile>>; effort_estimate:ValueState<Measured>; desired_window:ValueState<TimeWindow>; authority_basis_refs:List<Ref<Authority>>; dependency_refs:List<Ref<Dependency>>; questions:List<QSQuestion>`；申请尚未创建的业务工作，不含虚构任务 ID；purpose 只可选本动作授权子集，正常报价容量使用 service_delivery，不因枚举存在而获得其他职能。估计引用受支持方法，未知保留。`work_profile_ref=null` 只表示未取得可执行工作方法，允许申请但不执行。经有权确认后创建业务 Task，再编制 TaskPlan；提交申请不占用资源、不形成收费 |
| `QSTaskPlan` | `work_profile_ref:Ref<WorkProfile>; items:List<{task_ref:Ref<Task>,resource_ids:List<EntityId<Resource>>,window:TimeWindow,effort:Measured,dependency_refs:List<Ref<Dependency>>,existing_allocation_ref:Option<Ref<ResourceAllocation>>}>`；每项必须绑定已授权任务和适任资源，`effort` 来自工作方法，不是模型自由估值 |
| `QSServiceOffer` | `scope:ScopeRef; client_id:EntityId<Agent>; payer_id:EntityId<Agent>; proposed_terms_ref:Ref<ServiceTerms>; fee_basis_ref:Ref<FeeBasis>; fee_calculation_ref:Ref<FeeCalculation>; capacity_request:QSTaskRequest; validity:TimeWindow; deliverable_requirement_refs:List<Ref<DeliverableRequirement>>`；条款草案和计算须先登记才可引用；capacity_request 仅说明拟需容量，不表示已正式占用或已经委任 |
| `QSFeeClaim` | `engagement_ref:Ref<Engagement>; billing_clause_ref:Ref<BillingClause>; work_fact_refs:List<Ref<WorkFact>>; calculation_ref:Ref<FeeCalculation>; amount:Money; payer_id:EntityId<Agent>; prior_claim_ref:Option<Ref<FeeClaim>>`；金额必须与计算及条款一致，不能由文字推导应收或现金 |
| `QSHandover` | `engagement_ref:Ref<Engagement>; recipient_ids:List<EntityId<Agent>>; deliverable_refs:List<Ref<Deliverable>>; access_basis_refs:List<Ref<AccessBasis>>; release_allocation_refs:List<Ref<ResourceAllocation>>; retain_allocation_refs:List<Ref<ResourceAllocation>>; remaining_task_refs:List<Ref<Task>>; remaining_obligation_refs:List<Ref<Obligation>>; basis_ref:Ref<ServiceTransitionBasis>`；释放与保留集合不得相交，接收结果另记 |
| `QSJudgment` | `prior_strategy_ref:Ref<Strategy>; learning_profile_ref:Ref<LearningProfile>; evidence_refs:List<Ref<Evidence>>; changes:List<{dimension_ref:Ref<JudgmentDimension>,selected_value_ref:Ref<JudgmentValue>,explanation:string}>`；维度和值来自已选规则的有限目录，禁止利用该结构修改正式能力/资格/工程状态 |
| `QSPriceApplicability` | `price_source_ref:Ref<PriceSource>; price_time:TimePoint; region_ref:Ref<Region>; delivery_scope_ref:Ref<DeliveryScope>; measurement_rule_ref:Ref<MeasurementRule>; included_scope_refs:List<Ref<CostScope>>; excluded_scope_refs:List<Ref<CostScope>>; evidence_refs:List<Ref<Evidence>>`；缺必要口径时不得建成可用价格，保留源资料待补 |
| `QSCostPlan` | `option_ref:Ref<DesignOption>; cost_scope_ref:Ref<CostScope>; comparison_basis_ref:Ref<ComparisonBasis>; quantity_schedule_ref:Option<Ref<QuantitySchedule>>; lines:List<QSCostLine>; calculation_ref:Option<Ref<MethodResult>>; known_subtotal:ValueState<Money>; complete_total:Option<Money>; missing_items:List<QSQuestion>`；完整总额仅在声明范围无缺项/重复且计算支持时存在。quantity_schedule_ref=null 表示无已登记量表（采用有据代理方法或尚待量取，须在方法/缺项中区分）；calculation_ref=null 表示尚无适用计算；没有可计算行时 known_subtotal 为 unknown，不能以零假装已算。存在成功计算时小计与完整总额须取同次、同口径计算结果 |
| `QSCostLine` | `line_key:string; covered_scope:ScopeRef; cost_component_ref:Ref<CostComponent>; quantity:ValueState<Measured>; price_ref:Option<Ref<Price>>; amount:ValueState<Money>; basis_refs:List<Ref<Evidence>>; calculation_ref:Option<Ref<MethodResult>>; predecessor_line_keys:List<string>`；标识为本计划内唯一行键，量价金额取正式方法结果，不能用这个字段临时造价 |
| `QSProcurementDocument` | `procurement_scope_ref:Ref<ProcurementScope>; design_refs:List<Ref<Deliverable>>; quantity_schedule_ref:Ref<QuantitySchedule>; measurement_rule_ref:Ref<MeasurementRule>; pricing_rule_ref:Ref<PricingRule>; exclusions:List<Ref<CostScope>>; open_questions:List<QSQuestion>; prior_document_ref:Option<Ref<ProcurementDocument>>` |
| `QSBidEvaluation` | `bid_ref:Ref<Bid>; round_ref:Ref<ProcurementRound>; status:comparable/not_comparable/clarification_required/exclusion_recommended; normalization_result_refs:List<Ref<MethodResult>>; rule_refs:List<Ref<EvaluationRule>>; unresolved_questions:List<QSQuestion>; explanation:string`；排除建议不等于已排除，更不等于授标 |
| `QSValuation` | `contract_ref:Ref<Contract>; source_application_ref:Ref<ChangeClaim> 或 Ref<PaymentApplication>; covered_scope:ScopeRef; period:TimeWindow; basis:incremental/cumulative; calculation_ref:Ref<MethodResult>; assessed_amount:Money; recognized_amount:ValueState<Money>; disputed_amount:ValueState<Money>; retention_result_ref:Option<Ref<MethodResult>>; deduction_result_ref:Option<Ref<MethodResult>>; prior_statement_refs:List<Ref<ValuationStatement>>; entitlement_refs:List<Ref<EntitlementDecision>>; unresolved_questions:List<QSQuestion>`；估值/核实与权利认定分开；累计值通过计算引用明确本期差额，不重复新增应付 |
| `QSFinalAccount` | `contract_ref:Ref<Contract>; reconciliation_result_ref:Ref<MethodResult>; determined_total:ValueState<Money>; certified_total:ValueState<Money>; paid_total:ValueState<Money>; unsettled_amount:ValueState<Money>; unresolved_claim_refs:List<Ref<ChangeClaim>>; source_statement_refs:List<Ref<ValuationStatement>>`；余额由计算及有权可见支付依据产生，未知到账不能填零 |
| `QSComparison` | `option_refs:List<Ref<DesignOption>>; cost_plan_refs:List<Ref<CostPlan>>; comparison_basis_ref:Ref<ComparisonBasis>; comparable:bool; normalization_result_refs:List<Ref<MethodResult>>; ranked_option_refs:List<Ref<DesignOption>>; missing_items:List<QSQuestion>; explanation:string`；`comparable=false` 时排名必须为空，未选排序方法也不得隐式排序 |

## 4. 专业工作与跨主体交互

### 4.1 跨主体输入与输出

这里只定义本主体提供和接收的资料；其他主体如何作决定以各自文件为准。

| 对方 | 本主体接收 | 本主体交付 |
|---|---|---|
| [Owner](owner.md) | 目标、授权、范围、预算及获准采购任务 | 成本计划、评价/结算意见、问题及自身服务费依据 |
| [Architect](architect.md) | 建筑版本、选项、设计变化和数量基础 | 量价疑问、成本比较及范围内调整建议 |
| [Engineer](engineer.md) | 工程数量/专业范围、检查与技术变更证据 | 计量询问、费用影响和需核实技术事项 |
| [Contractor](contractor.md) | 获准披露的投标、计量、变更和费用申报 | 合规澄清、评价/核实意见及待补证项目 |
| [Supplier](supplier.md) | 有授权来源的报价、供货和交付证据 | 询价范围、计价/计量问题及引用条件 |
| [Bank](bank.md) | 获授权的成本或工程款核验证据请求 | 指定版本报告、核实范围和不确定性 |
| [Government](government.md) | 适用且本人有权获知的程序要求 | 有资格与授权时提交的成本/采购相关材料 |

银行、业主或监管收到 QS 报告不自动通过其审批；多个核实者对同一工程款的意见不能重复形成应付义务。

### 4.2 前期需求与有限专业研究

Owner 提出建设目的、候选地区、规模区间和期望交付时间；技术及建造方式先保留候选，再结合各专业及供应方意见细化。

QS-A04/A13 与 [Owner](owner.md)、[Architect](architect.md)、[Engineer](engineer.md) 和 [Supplier](supplier.md) 的独立意见对接。

**QS-008｜先定义比较对象。** 同一次比较先声明建设目的、功能与性能要求、规模基准、地区、交付条件和服务范围。
不同面积、寿命、性能或交付责任的方案不能只按总价排序；能够规范化的部分保留转换依据，不能规范化的部分分别列示。
新建、扩建、改造或利用既有空间仅在该需求允许时进入比较；不得擅自替业主改变功能目标或把缺失的替代方案视为已被否决。
MiC、构件预制、现场施工及其组合按具体范围形成选项，不把技术标签当作必然降本、缩期或质量改善的系数。

**QS-009｜统一口径但保留原始资料。** 每项价格或费用记录原始数量单位、地区、币种、价格时点、税费、运送/安装责任和覆盖范围。
汇率、指数、价格调整和跨地区转换必须给出来源、基准时点及适用限制；没有依据时可以保留区间、未知项或不可比结论。
原始供应方报价与 QS 比较口径分别保存；调整后的比较值不成为供应商的新报价，也不修改其商务条件。
量价计算由受控计算方法执行；LLM 可解释假设、识别漏项和建议询价，不能编造数量、单价、区间端点或数据来源。

**QS-010｜成本区间和费用边界可审阅。** 前期区间说明是观测价格范围、情景假设、估算误差范围还是概率区间；没有统计依据时不称置信区间。
研究版成本不是有约束报价，也不是业主预算承诺；设计成熟度提高后可以收窄或扩大区间，并保留修订原因。
建设投入、运营维护、更新和处置等生命周期费用分别呈现；未覆盖的类别标为未计，不能按零费用处理。
融资费用另列借款人、安排、时点及假设；不得把它混入供应单价或在建设成本与投资现金流中重复计入。
如需现值或总成本比较，明确分析期限、价格基准、折现及残值假设；口径未确定时保留分项，不自动生成综合排名。

**QS-011｜专业判断保留来源。** 数量依据来自对应建筑/工程版本，技术可行性、接口适配和法规适用由有权主体核实。
供应方的价格、产能和交期意见标记出具者、用途、有效期和承诺程度；市场推广陈述不能直接变成已验证的节约率。
专业意见冲突时列出受影响的数量、费用和依赖条件，并反馈给相应作者；QS 不以低价替代技术核实或要求所有意见强行一致。

| 输入/输出语义 | 必须能说明的内容 | 限制 |
|---|---|---|
| 需求引用 | 业主评估档案、需求简报版本、建设目的、地区、规模区间、期望交付时间 | 可在正式项目成立前存在，期望时间不等于已承诺工期 |
| 选项与比较基准 | 方案身份/版本、功能性能、比较数量、范围差异、可组合技术范围 | 方案名称相似不代表范围相同 |
| 专业输入引用 | 建筑、工程、供应意见及有效版本、作者、依据和未决问题 | 未收到或无权读取的资料保持未知 |
| 价格与费用依据 | 原始单位/地区/时间/币种、来源、转换方法、包含/排除项 | 保留原始价格及授权可见范围 |
| 比较结果 | 分项金额或有依据区间、生命周期与融资费用、不可比项和敏感假设 | 不形成合同价、应付义务或投资决定 |
| 使用与更新条件 | 接收者、允许用途、成熟度、有效期/触发条件、待核实责任人 | 后续使用检查版本与权限，不自动扩大披露 |

**QS-012｜方案共用资料不复制工作和费用。** 多个选项可引用同一数量基础、价格研究或共同现场调查，注明共享任务与适用范围。
同一已完成研究被多个选项引用，不重复记工时、产生成果费或增加项目总成本；另有合法授权的增量工作另记任务及费用。
若做方案比较需分摊共同前期费，保存唯一费用事实和分摊视图；多个分摊视图不能叠加成多笔实际支出。
不同客户间的资料复用需有权使用；去重不构成向其他客户披露保密价格或商业条件的理由。

**QS-013｜版本更新按影响范围复核。** 需求规模、地点、期限或专业版本变化时，标记被影响的估算项与前提，说明可继续使用、待复核或已过期。
旧报告保留当时判断和用途；不能静默复制到新版方案，也不能因为一项更新就自动注销所有历史成果。
资料不足可给分项区间与补充研究请求；技术失败保留执行状态，不以默认最低价或全零成本填补。

**QS-014｜成本咨询不决定供应方中选。** 早期提供信息的供应方可以形成待核实候选，其意见不取得排他设计权、订单或产能承诺。
QS 不把咨询参与、愿意披露信息或报价便宜自动解释为符合后续采购资格；适用程序、利益冲突处理和同等信息要求待 D-06 确定。
业主或其他有权采购方决定后续程序；未参与早期咨询的主体也不因这一事实自动被排除。

后续细化对应 D-02 费用/融资口径、D-06 采购程序、D-07 估算粒度与数据、D-09 资料权限、D-11 版本和计算契约。

### 4.3 专业服务与资金接口

资金账本包含现金、应收应付、贷款和到期义务。
QS-A08—A10 沿用[共同资金与提交规则](../02_world/domain_objects.md) OBJ-011、OBJ-012，不在 QS 内建立另一套正式余额。

**QS-015｜核证按权限确定金额或提供证据。** QS 接收具体合同/申请版本、已完工作证据、计价条件和有权读取的既往核证及支付引用。
无核证权时只提交核实意见；具有核证权时确定授权范围内金额和依据，不能直接批准贷款、修改银行现金或执行付款。
核证是否形成支付义务、何时到期及哪些部分保留或争议，由适用条款与正式入口判断，不默认核证当天必须全额转账。

**QS-016｜申请、核证、义务和清偿相互关联但不累加。** 原申请、核证版本、有效应付、到期条件、保留/争议部分及已清偿金额分别引用。
累计核证报告须指出截至日期及已核证范围，不能把累计总额当作本期新增应付；新增、修正和撤回均保留原依据与差额。
同一工程款只有一组配对义务身份；业主、银行和 QS 的多份报告不各自增加一次欠款，重复提交不再次核证或清偿。
保留款释放、争议解决及核证修正按有效依据调整对应部分；不能通过更名、结算或项目关闭删除既有欠款。

| 交接内容 | 必须保留的对应关系 | 本角色的边界 |
|---|---|---|
| 申请与证据 | 申请身份/版本、合同、工程范围、申请方及原始金额 | 申报不自动成为认可金额 |
| 核实或核证 | 权限依据、核证身份/版本、核定范围、金额和未决部分 | 报告不是现金执行指令 |
| 义务与到期 | 正式义务引用、付款人/收款人、到期依据、保留和争议状态 | 依条款判断，不另造独立欠款 |
| 付款与余额 | 获授权读取的执行身份、实际清偿分配、有效调整和未清余额 | 不把批准、预计到账或部分付款当作全额清偿 |

**QS-017｜可追溯不等于全知。** 报告可以引用其有权取得的合同、计量、核证和支付证据；不可见或尚未确认的执行结果保持未知。
核心账本的一致性校验不向 QS 自动公开其他项目余额、银行私有授信判断或合同外的商业资料。
收款结果未知时申请核对相关执行记录，不凭付款方的口头描述认定到账，也不重新创建同一应付。

**QS-018｜自身收费单独识别。** 为其他合同核证的金额与本企业的服务费申请、应收、到期和实际收款分别关联对应合同与双方。
本企业获得服务费不清偿承包商工程款；替业主核证付款也不使 QS 成为该笔工程款的付款人或收款人。

付款期限、保留/争议处理模板及具体实现仍待 D-02、D-06、D-11 细化。

### 4.4 工程量、成本计划与方案比较

按 [工程类型与有限模板](../02_world/project_types.md) 的工程对象/子工程接收有权作者的方案与数量依据；[Architect 参数化方案](architect.md#44-参数化方案与专业接续)和 [Engineer 专业方法](engineer.md#44-专业方法证据与工作包)分别提供适用专业接口，不要求每项估算先有建筑面积表。具体参数化目录、代表工作包及量价方法仍待选择；成本计划不自动成为合同价或付款依据。

#### 4.4.1 同版方案进入量取与价格匹配

**QS-025｜先形成可追溯的工程量表，再形成成本计划。** QS 接收 `brief_ref`、`option_ref=(option_id,option_version)`、授权/任务版本、对应工程对象/子工程的数量依据、获准的 `assessment_ref` 和 `quantity_basis_ref`；建筑面积仅在相应建筑模板适用。不强制所有专业完成后才能估算有明确假设的独立部分，凡用到未完成检查或假设，保留其范围和用途限制。

| 对象 | 必须表达的字段与类型 | 写入与交接边界 |
|---|---|---|
| 估算请求 | `task_ref`、`assignment_ref`、`brief_ref`、`option_ref`、`cost_scope_ref`、`as_of`、接收者/信息截止 | 明确客户、估算目的、比较基准和允许投入；客户预算不能反推“正确”单价 |
| 工程量表 | `quantity_schedule_ref=(id,version)`、输入版本、`measurement_method_ref`、`lines[]`、缺项/排除项 | QS 维护本次量取结果，引用原作者依据，不改建筑或工程原成果 |
| 工程量行 | `line_id`、工程对象/子工程引用、`scope_id`及适用的`component_group_id`、作业/计量项、`basis_refs[]`、公式/来源、`quantity`、`unit`、`quantity_status` | 保留实物覆盖与汇总层级；数量区分有据计算、场景假设、缺资料及未覆盖，0 必须有依据 |
| 价格依据 | `price_ref=(id,version)`、数值 `unit_rate` 或明示未知、来源、原币种、计价单位、价格时点/有效期、包含排除项、地区/交付条件 | 报价、历史观测与情景价格分开；获准读取不等于取得可成交承诺 |
| 成本计划 | `cost_plan_ref=(id,version)`、方案/数量/价格/计算方法引用、逐行金额、`known_subtotal`、`complete_total`、未计项、基准币种 | `known_subtotal` 用 ValueState 区分已算小计与未计算；`complete_total` 可空。含义限于声明成本范围，不能把局部完整当全项目完整 |
| 差异与反馈 | 旧/新计划引用、原/新增/删除/拆分行关系、数量差/价差、原因/假设差异、待答主体 | 工程疑问回作者，价格请求交有权供应/采购方，预算取舍交客户 |

地区口径分别保存项目所在地、构件生产/来源地、服务执行地及交付目的地；`source_region_id` 若采用，必须说明是具体产品生产/来源引用，不能从组织注册地推断。跨地区价格转换、运送、安装和币种换算各有方法、时点和证据；不存在统一“大湾区价格系数”或默认资格互认。

工程量行是设计/估算范围，不是已生产、到货、已安装或获付款认可的事实。代表工序可以对同一构件列制造、运输、安装的不同成本行，但各行注明自身计价对象，不能把它们累加为三份构件实物。互斥方案各有工程量表，不合并成一个项目的总数量。

建筑面积、道路区段长度/面积、桥梁构件数量、隧道区段/土方等使用各自计量方法及完整单位语义；不是要求每类都采用这些单位。路线长度、车道长度、展开面积或开挖体积不能仅因单位相近就互换。超高层及不同结构/施工方法的价格基础须有适用证据；缺专项依据时保留未知，不给普通建筑单价乘任意复杂度或地区系数后称完整成本。

#### 4.4.2 可执行的量价方法边界

**QS-026｜算术关系与估价依据分别有效。** 候选量价方法采用明示数量乘同口径单价的分项估算；每个计价行先验证数量/价格单位、计量规则、范围、时点及地区适用性，再计算 `line_amount = quantity × unit_rate`。转换必须有被引用的方法和结果；不相容的 m²、m³、件或套不能靠文字自动换算。

| 检查/计算 | 必要条件 | 返回与限制 |
|---|---|---|
| 量取 | 输入版本齐备，计量方法覆盖该几何/构件及用途，重复范围已处理 | 具体数量及来源，或缺项/未覆盖；不能用设计评分代替数量 |
| 价匹配 | 价格单位、规格、范围、时点和交付条件适用；必要转换有据 | 原价引用与规范化记录，或不可比/待询价；不回写供方原报价 |
| 分项计算 | 该行必要量价已知且方法有效 | 金额、币种和输入引用；方法错误另记技术状态 |
| 范围汇总 | 每行具有可核对身份，包含项不重复，汇率及汇总口径齐备 | 已知小计；仅声明范围全部必要项已计且无未解决重复时给该范围总额 |
| 不确定性 | 区间端点/情景及合并方法有明确依据 | 分情景或区间结果；没有联合假设不把独立极值拼成有概率含义的置信区间 |

包含/排除项采用 `cost_component_id + covered_scope` 关联：若供应单价已包含某范围安装，同范围独立安装行必须先明确拆分、扣除或不同覆盖依据；问题未解决时不能发布重复累计的总额。人工、运输、服务费或融资费用亦按覆盖关系核对，不靠名称不同躲过去重。不同成本主体的视图可引用同一事实，但不相加成多次项目支出。

复合项目的“总项目—子工程—工作包”是汇总关系：同一统计视图选择不重叠的计价范围，父级已含子项的金额不再与子项相加；独立共同费用须说明覆盖及分摊，分摊引用不再新增一笔实际成本。地区分摊与工程分解是同一事实的不同视图，跨区桥梁不能在每个地区各计一份全桥。同口径父级总额、未被子项覆盖的直接费用和子项明细保留可核对关系；合同价、各方支出和全链资源成本分别汇总，不删去真实的分包/供应应付款以求统计去重。

一个缺价行仍保留数量，缺量行仍可保留适用价格；完整总额保持空并列出缺口。未知项不是零，也不能用“备用金”名义默默填平；若委托方允许有依据的风险准备，须作为明示估算项说明覆盖风险及避免重叠的规则。只有在同口径、同范围且未计差异已说明时才进行排序；可以返回无法可靠排序。

**QS-027｜成本计算不提前决定商业或工程结果。** 形成成本计划不生成采购订单、冻结供方价格、占用产能、确认业主预算、应付或现金变化。Engineer 的范围内检查通过也不使单价有效；低成本不消除技术冲突。客户选择一种成本情景后，后续询价、采购接受、计量核证和付款仍各有自己的版本及授权。

#### 4.4.3 编制工作、接受与修订闭环

**QS-028｜工作完成、数据完整和客户接受分别判断。** 为取量、整理/询价、范围核对、计算、复核与比较登记工作单元、输入依赖、人员/工作量及估计方法、时间/投入单位、输出和授权交付模式。投入入口记录实际分片及已确认范围；等待报价不是新增已完成取量，恢复和重发不能重复计工。

当约定的有限估算工作及必要复核已完成，可交付“包含未计项的有限成本计划”；其 `compilation_status` 可完成而 `coverage_status` 为部分。若合同要求完整范围报价/预算，有限报告不解除剩余任务义务。客户接受、用途发布、自身服务应收以及现金收取仍分别记录，不将报告编制耗费等同向客户收费金额。

方案 V2 到达后，先对数量、专业条件、价格有效性及包含范围建立影响清单，再处理受影响行；未变行可以显式复用原依据而不复制研究费用。行拆分/合并保留原行关系，保证一个范围不因改名再次累计。已发生工程款/付款不随估算修订而改写；已签合同变更走 A07，有效核证更正走 A08，不挪用成本计划接口。

#### 4.4.4 贯通例子与独立验收

**QS-029｜可核对的成本报告也允许没有可比较总价。** 正常例：获授权方案作者提供同版方案/数量依据，建筑范围可引用 Architect 面积表，道路/桥梁/隧道按相应 Engineer 的专业依据；QS 在受支持范围取量、匹配有来源价格并形成成本计划，客户独立决定下一轮研究。拒绝例：QS 无容量或任务存在不能接受的冲突，拒绝委任，不用全零报告表示拒绝。返修例：专业发现要求调整某范围，原作者发 V2；QS 更新相关工程量与费用覆盖，旧计划、已发生投入与实际义务保留。

以下测试数字人为构造，仅检验算术、身份和状态，不是大湾区市场报价、工程预算或默认费率。

### 4.5 地区适用与证据边界

本角色只研究大湾区范围内的工程量与成本口径；场景明确项目地区、事项、适用时间和证据来源，不从“大湾区”标签推导统一资格、技术要求或合同权限。
组织登记地、实际服务地、项目所在地及产品生产地分别引用；跨地区经验不自动证明本次任务的资格、数据或方法适用。
规范条款、供应资料、观测数据与模型假设分别登记。尚未取得依据的阈值和条件保留未知，不从不适用地区的参考流程或无来源常数补齐。
本文件中的代表方案和算术例子用于检查模型接口；未选定的方法不得产生技术通过，未覆盖的专业不声称真实设计安全。

## 5. 状态转换、失败与恢复

### 5.1 提交、版本与持续约束

**QS-005｜版本贯通设计与量价。** 每份估算、评标、变更计价和结算明确输入版本、计算口径、作者及适用用途。
新设计只使受影响部分进入复核；最新草稿不自动替代已发布采购文件，价格条件变化也不回写原始投标或合同。
对已经采购、已施工或已支付的事实保留原记录，修订通过有依据的后续调整处理。

**QS-006｜投入与判断各有完成标准。** 整理数量、核查证据、评审和结算耗费实际模型内人员与时间，不能靠阶段推进自动生成全部资料。
资料缺失、技术意见未到、委托权限不足和资源冲突分别等待；未发生的工作不因收费方式是总价就视作已完成。
技术失败、商业拒绝、专业不认可和争议分别记录；重复提交不重复记工时、计费或形成核证。

**QS-007｜金额性质不能混算。** 原始申报、QS 核实/建议、有效确定金额、到期义务和实际支付分别记录并关联。
计量/核证修正保留依据和历史，按权限调整余额；不能直接扣企业现金，也不能因一次核证就重复增加已存在的工程款义务。
本企业内部成本、向客户服务收费与项目工程成本分别有归属；汇总时说明主体与统计边界，避免同一费用重复计入。

### 5.2 对象转换与剩余责任

**QS-022｜量与价各有证据，权利与金额各有状态。** 拟变更估值可以先于最终决定形成，供各方取舍；它不自行改变合同价或形成业主应付。
实际执行了变更但权利/责任仍有争议时，保存工程与费用证据，允许范围内估值和后续调整，不把“未确定获偿”写成“未发生工作”。

| 对象与转换 | 必要依据 | 不自动发生的后果 |
|---|---|---|
| 拟服务 → 有效委任/内部授权 | 相容接受、职能与冲突检查、真实资源 | 不同时取得所有客户和核证权限 |
| 量价草稿 → 已核对 → 提交/获授权发布 | 输入版本、计量/价格方法及用途条件 | 不成为成交价、已完工程量或现金支出 |
| 投标待评价 → 待澄清/已评价/有权排除 | 同轮文件与有权规则、逐份证据 | 评价完成不自动授标，澄清不无权改投标 |
| 变更已报告 → 待权利/范围判断 → 已估值 | 事件和条款引用、数量价格依据 | 估值通过不自动消除权利争议 |
| 估值 → 有效合同调整/义务依据 | 适用权限与决定、生效范围 | 技术整改存在不自动由任意一方承担全部价款 |
| 申请 → 已核量/核价 → 有权核证 | 同范围证据、累计/本期口径、保留/争议处理 | 核证不直接扣现金或自动取得贷款 |
| 核证修订 → 差额与原义务关联 | 原证书、修订理由、有权结果及已清偿引用 | 不全额新增应付，不删除已支付历史 |
| 最终账目建议 → 有权确定/部分确定 | 合同基准、有效调整、未决项与接受/决定机制 | 不自动形成全面权利放弃、债务清偿或法律裁决 |
| 服务停止 → 资料移交/残余事项 → 对应范围关闭 | 合法资料接收和剩余任务/费用明细 | 不以一个结算报告结束所有争议支持 |

**QS-023｜核证组成能回到唯一范围。** 同一核证区分累计已认定范围、本次新增/修正、保留或争议、已付预款的非现金抵扣及既往清偿引用。
不是每种合同都有全部组成；按所选条款启用并统一口径，不能让预付款抵扣和既往付款各再扣一次同款，或将累计额全当新增。
已支付金额超过有权修订后义务时，向共同账本提供差额依据；退款/后续抵扣有独立合法记录，QS 不自行把收款人现金改回。

**QS-024｜任务排队和服务收尾保留明确责任。** 缺计量证据、价格依据、权利决定、授权或人员窗口分别记录负责方和下一触发；其余可独立工作按条件继续。
移交保留原作者、原申报和每次调整轨迹；结束本企业服务不删除委托方的未结工程款，也不强制本企业无限期免费支持。
本企业回款、外包/人员义务和客户合同金额分别维护；资金不足影响合法排程和经营选择，不反向篡改估算或核证证据。

### 5.3 正常路径与失败恢复

以下用于模型验收，假设所需计量、计价和合同权限已被选定模板支持，不构成真实造价或法律验证。

**成功：分阶段采购、计量到最终账目的服务。**
1. QS 根据自身容量和利益冲突作 A02 判断，A03 接受明确成本服务；是否有核证权单独登记。
2. A04 形成成本计划，A05 编制合同包量价资料；采购人依法约发布后，A06 对有效投标逐份给意见，授标方自行决定。
3. 履约时 A08 按具体范围计量；只有有权者核证，结果关联唯一义务，由付款方按条件执行实际支付。
4. 发生获授权变更时 A07 保存事件和依据，区分权利判断与估值；有效结果进入后续计量及 A09 最终账目。
5. A09 核对原合同、有效调整、既往清偿和未决项；有权主体确定相应范围，尚未付款/争议部分继续保留。
6. A10 核对 QS 自身服务费，A11 交接及释放任务资源，A12 用可比结果更新未来估算，不回填原预测。

**失败恢复：累计核证被误当本期金额且部分已经支付。**
1. A08 发现申请将此前核证范围再次计入，先标明重复范围与差异，保留原申请而非替申报方偷偷改值。
2. 若错误尚未正式提交，只修订自己的待发布结果；若已形成正式核证，按权限创建关联更正版本，不删除旧证书。
3. 更正与既往实际支付在共同账本核对，未清部分只调整有效差额；已超付部分形成待处理退款/合法抵扣，不能直接抹除现金历史。
4. 权利或数量仍有争议时分列待决部分，继续处理符合条款的无争议部分；不能把客户资金充裕当全额认可理由。
5. 取得补证/有效决定后更新对应义务和 A09 账目；若 QS 服务已终止，按 A11 向有权接任者移交轨迹及必要支持范围。

## 6. 验收场景

下列场景规定实现应满足的结果，须以实际检查记录判定是否通过。流程一致性、真实决策行为、方法校准和现实工程或制度验证分别报告；示意数据不作为真实项目参数。

### 6.1 全生命周期边界

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-QS-001 | 仅需前期粗估且项目尚未成立 | 可在有限委任下给带不确定性的估算，不要求最终投标价 |
| CHECK-QS-002 | 顾问拒绝或技术失败残留候选 ID | 不形成委任与正式任务占用 |
| CHECK-QS-003 | 最终服务方改变 | 范围、费用、排期及报价版本成套重绑 |
| CHECK-QS-004 | 多项目计量任务争用同一人员 | 共享排期校验冲突，续办不重复占额 |
| CHECK-QS-005 | 内部团队整理成本计划 | 记内部工作成本，不生成自我服务费 |
| CHECK-QS-006 | 跨地区报价币种/范围不同 | 使用有依据口径比较，未可比部分明确保留 |
| CHECK-QS-007 | 新估算明显降低 | 不减少已发生工程成本、合同债务或贷款本金 |
| CHECK-QS-008 | 最低报价存在未解合规问题 | 不自动中选；按获授权规则处理评价与补证 |
| CHECK-QS-009 | QS 只有评标建议权 | 不直接授标、签约或任意排除投标人 |
| CHECK-QS-010 | 设计变更但相关价格基础未更新 | 标记受影响计价，不自动复用全部旧量价 |
| CHECK-QS-011 | 承包商实际成本超支 | 不自动形成等额业主应付，保留合同权利判断 |
| CHECK-QS-012 | QS 无付款核证权但完成工程量核实 | 交核实报告，不生成正式证书或扣款 |
| CHECK-QS-013 | 相同核证或多方报告重复到达 | 不重复形成工程款义务或累计核证金额 |
| CHECK-QS-014 | 最终结算已形成但未付款 | 保留实际应收应付，不标记现金清偿 |
| CHECK-QS-015 | 服务费到期未付 | 保留本企业应收，不擅改工程评价或删除成果 |
| CHECK-QS-016 | 退出时还有争议支持和欠费 | 交接与资源按明细处理，保留未结责任 |
| CHECK-QS-017 | 用最终结果回看早期预测 | 保留原预测版本，不能回填后伪造准确性 |
| CHECK-QS-018 | 模型高分但计算依据缺失 | 不当作完整预算、专业核证或验证成功 |

### 6.2 前期成本比较

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-QS-019 | 相同目的但面积、性能或责任范围不同 | 保留差异与规范化依据，不直接以名义总价排名 |
| CHECK-QS-020 | 跨地区/币种/时点资料缺转换依据 | 明示不可比或待补，不编转换值或区间端点 |
| CHECK-QS-021 | MiC 与现场施工组合含不同运输和安装范围 | 按实际包含项比较，不使用技术标签固定收益 |
| CHECK-QS-022 | 建设、运维与融资费用有重叠 | 分列边界，唯一费用事实不在综合结果中重复累计 |
| CHECK-QS-023 | 专业意见冲突或缺关键数量 | 定位冲突与未知项，输出有限意见，不假称完整可行 |
| CHECK-QS-024 | 一个价格研究被多个方案反复引用 | 允许引用，任务工时、应付及实际支出去重 |
| CHECK-QS-025 | 业主更新规模但只影响部分估算 | 标记受影响部分复核，旧判断和未受影响依据保留 |
| CHECK-QS-026 | 收到竞争者保密成本或未获授权报价 | 不向无权接收方披露或作为对方已知输入 |
| CHECK-QS-027 | 早期供应咨询后形成低估算方案 | 不自动中标、锁定采购或预留产能；继续适用后续程序 |

### 6.3 计量与资金

| 验收编号 | 场景 | 预期 |
|---|---|---|
| CHECK-QS-028 | QS 提交有权核证结果 | 按适用条款形成或调整相应义务，不直接增减现金 |
| CHECK-QS-029 | 本期报告复列累计核证金额 | 识别历史范围及本期差额，不重复增加应付 |
| CHECK-QS-030 | 部分款到期，另有保留款及争议 | 保留各自依据和状态，不将全部金额同日付清或删除 |
| CHECK-QS-031 | 银行与业主同时引用同一核证 | 关联同一义务，重复结果不重复增加或清偿 |
| CHECK-QS-032 | QS 只能查看指定付款证据 | 未授权余额保持不可见，未知到账不被填为已付款 |
| CHECK-QS-033 | QS 服务费与工程款同日支付 | 各自关联正确合同、收款人和义务，不交叉清偿 |

### 6.4 经营与恢复

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-QS-034 | 为承包商编报价后又被请求评审同一交易 | 核对职能、冲突及权限，不默认换会话即可承接 |
| CHECK-QS-035 | 设计工程量与已完工程量不同 | 绑定计量对象和方法，不用设计量直接核证全部付款 |
| CHECK-QS-036 | 变更估值完成但获偿权仍未确定 | 保留估值和争议，不自动改合同价或新增业主应付 |
| CHECK-QS-037 | 采购轮次变化却复用旧投标澄清 | 核对同轮文件及有效版本，不无条件沿用或改原报价 |
| CHECK-QS-038 | 累计核证误作本期且部分已支付 | 更正按原范围和差额追踪，已支付历史不删，超付另处理 |
| CHECK-QS-039 | 预款已抵扣又出现在既往现金清偿中 | 引用同款及组成关系，避免重复扣减本期金额 |
| CHECK-QS-040 | 最终账目确定但存在未结争议和未付款 | 仅关闭获有效确定范围，不生成全面清偿或法律裁决 |
| CHECK-QS-041 | 退出时客户工程款未结而 QS 自己已收款 | 分别保存不同合同义务，不交叉销账 |

### 6.5 工程量与成本方法

| 编号 | 输入/事件 | 可独立核对的预期 |
|---|---|---|
| CHECK-QS-042 | 测试范围只含一个面积计价行：Architect 面积表 260 m²，测试单价 2 CNY/m² | 行金额及该测试范围总额为 520 CNY；不称为真实项目完整造价，不形成应付/现金 |
| CHECK-QS-043 | 上述范围再要求一项运输费用但价格未知 | 已知小计保持 520 CNY，完整总额为空并列运输缺价；不把未知计零 |
| CHECK-QS-044 | 工程量单位 m²，价格单位 m³，缺换算依据 | 阻止该行金额和完整总额，保留原输入及待补对象 |
| CHECK-QS-045 | 构件报价已含指定安装范围，又加同范围安装行 | 发现覆盖重叠，未获合法拆分依据前不得累计发布总额 |
| CHECK-QS-046 | Engineer 只有限定场景相容结论，另有专业未覆盖 | 估算保持相应假设/限制，不能扩为可施工、已合规或已批准预算 |
| CHECK-QS-047 | V2 拆分原行且有未变价格研究可复用 | 追踪原行与覆盖关系，只计算新版目标范围一次，不重计原研究费 |
| CHECK-QS-048 | 有限报告已完成且客户拒绝继续研究 | 保留报告、实际投入及按条款成立的费用；不生成后续合同或清除欠款 |
| CHECK-QS-049 | 计算重试或同一成本计划被多个顾问引用 | 结果与实际投入保持一次；引用次数不增加金额、工程量或可信度 |
| CHECK-QS-050 | 道路方案有长度依据但无适用面积/体积转换，且没有 Architect 成果 | 可处理已支持的计量项；其余保持缺项，不强制补建筑面积表或用建筑单价直接计价 |
| CHECK-QS-051 | 父级总额已含两个子工程，另有跨区统计分摊 | 同一视图不再相加父子或重复整项地区份额；共同费用按覆盖分配，真实合同义务仍保留 |
| CHECK-QS-052 | 本地 QS 只有普通建筑价格资料，被请求给未覆盖超高层/桥梁完整总价 | 保留方法/价格缺口，地区身份与复杂系数不能补齐；允许有据独立范围继续估算 |

### 6.6 分支输入与业务任务交接

| 编号 | 契约场景 | 预期 |
|---|---|---|
| CHECK-QS-053 | A03 双方委任相容，但任务清单尚未创建 | 先 confirm；委任提交后按授权创建 Task，再排期，不需伪造前置任务 |
| CHECK-QS-054 | A04 全部价格/计算缺失，需要形成有限报告 | report_limits 保留 unknown 小计与空完整总额；不能生成零元完整估算 |
| CHECK-QS-055 | A05 缺量表，或 A07/A09 尚无估值/对账计算 | 可发有范围补证请求；无结果不能发布依赖数量文件、确定估值或最终账目 |
| CHECK-QS-056 | A10 催收旧申报但无新费用计算 | 可引用原申报催收，不重复计算/形成收费或改变现金 |

## 7. 参数、方法与配置依赖

需要配置的范围如下，估算、合同金额与资金清偿继续使用不同对象。

- **量价方法**：计量对象/粒度与规则、成本覆盖范围、价格来源、地区及币种转换、风险准备和不确定性方法、价差/变更与索赔模板。
- **委任与权限**：采购及合同模板、评标职责和利益冲突、核证效力及组成、客户接受条件、资料保密和争议支持范围。
- **投入与费用**：量取和比较工作量、任务资源与时间单位、服务收费、付款期限、保留与争议处理；资金、采购和执行语义分别沿 D-02、D-06、D-11 明确。

选择或数据不足可阻塞相关完整估算，不阻塞已有授权且输入充分的独立研究。成本计划金额不能直接写入现金或应收应付。

未选定的方法、阈值、时间粒度、资格和产品条件须显式保持待定；不得以示例值、角色标签或未覆盖范围补成正式结论。具体选择登记在[模型决策](../07_experiments/model_decisions.md)，使用前绑定方法、数据和参数版本。
