# Engineer：专业分析、技术检查与履约支持

定义工程服务主体在大湾区仿真中的专业设计、独立审查、获授权合同工程师职能与持续服务行为。本文是角色开发规范；方法支持范围和待选参数见第 7 节，实现与验证证据单独记录。

[总体运行框架](../02_world/world_runtime.md) · [共同对象与状态](../02_world/domain_objects.md) · [跨主体交接](../03_projects/collaboration_flow.md) · [模型决策](../07_experiments/model_decisions.md)

<!-- page-nav:start -->
**本页导航**

[1. 职责、目标与权限](#1-职责目标与权限) · [2. 信息、状态与业务对象](#2-信息状态与业务对象) · [3. 行为卡与执行契约](#3-行为卡与执行契约)

[4. 专业工作与跨主体交互](#4-专业工作与跨主体交互) · [5. 状态转换、失败与恢复](#5-状态转换失败与恢复) · [6. 验收场景](#6-验收场景)

[7. 参数、方法与配置依赖](#7-参数方法与配置依赖)
<!-- page-nav:end -->

## 1. 职责、目标与权限

### 1.1 主体身份与授权

**ENGINEER-001｜专业范围具体到任务。** 一个 Engineer 主体需说明可承担的工程对象、专业和服务，例如建筑结构/机电、道路、桥梁、隧道或岩土任务，不能默认同时覆盖全部专业；统一对象与模板目录见 [工程类型与有限模板](../02_world/project_types.md)。
目标可以包含专业服务收益、可靠性、风险控制、履约质量和长期声誉；具体权衡待定，不预设所有主体同质。
每个 agent_id 保留独立能力、人员、合同和认知；同一组织的不同专业任务共享其真实资源边界。

**ENGINEER-002｜设计、检查与合同管理分开。** 专业设计者、技术检查者、现场支持者及合同中的 Engineer 职能不因同名而自动合并。
是否可以检查本人编制成果、是否需要独立复核，以及谁可签署或核证，由适用资格、委任、责任矩阵与模板确定。
本主体可以服务于业主、承包商或其他有权委托人；设计建造等模式改变服务关系，不能自动转移责任。
内部专业团队依内部任务授权工作并记录成本；外部服务需有效接受的条款，不强制每个项目先委任全部专业。

工程对象、专业任务和有效委任共同确定方案作者与专业主责。道路、桥梁、隧道的获授权 Engineer 可直接依据需求/调查形成专业方案，无须先由 Architect 创建设计；附属建筑、跨专业整合与独立检查另按范围绑定。复合项目的子工程分别维护作者、接口和地区适用条件，一个专业主责不获得其他专业或整个项目的总批准权。

**ENGINEER-003｜专业意见不能覆盖正式事实。** 本主体给出有范围的分析、检查或建议，不能直接改项目真实缺陷、已完成量或贷款状态。
候选建模方式包括代表性技术选项、约束和检查模型；未做完整结构或机电计算时明确抽象边界，不声称真实安全或合规已经证明。

### 1.2 独立判断与经营取舍

**ENGINEER-017｜经营选择受专业能力与既有义务约束。** 本主体权衡服务收益、现金持续性、专业责任、估计工作量和人员/工具容量，可以拒绝不适合的任务。

| 目标冲突 | 允许的业务选择 | 不可越过的边界 |
|---|---|---|
| 尽快出意见与证据不足 | 限定结论、分阶段检查、请求调查或等待 | 不能因客户急需把假设签为已核实事实 |
| 高收费新订单与旧项目复查冲突 | 提出新排期、限缩或拒绝新订单 | 不取消既有复查义务，也不复制专业人员 |
| 客户偏好与专业发现冲突 | 报告问题、提出替代、建议调整或转介 | 不以继续获聘为由静默抹去本次已取得的专业发现 |
| 深入检查与调查成本/现场影响冲突 | 在授权内选择检查范围或申请扩展 | 检查强度和发现结果可不同，不默认全查或零漏检 |

**ENGINEER-018｜职能标签具体到本次动作。** 同一组织可承接不同服务，但每次输出绑定委任、专业和职能；以下三类不自动互相授予权力。

| 职能 | 主要工作与输出 | 需单独满足的条件 | 不自动拥有 |
|---|---|---|---|
| 工程设计者 | 按对象/子工程编制专业方案、分析和修改；可承担明确委任的专业主责；对应 A04/A05/A07/A09 | 对象类型、适用专业、输入、支持方法及编制/签署权限；整合另有范围 | 独立审查身份、其他专业主责、合同价格决定或监管许可 |
| 独立审查者 | 核对明确对象，形成问题、复核与范围结论；对应 A03/A06/A07/A09 | 模板规定的独立性、证据访问和检查权限 | 原作者修改权、全部专业通过或现场实际整改完成 |
| 合同工程师职能 | 按委任检查、发指定合同通知/指令、核证或提出决定；对应 A06—A09 | 具体合同条款、事项范围、权限及必要程序 | 所有项目停工、任意改价、直接付款或法律裁决 |

独立性是否满足按组织/人员关系和所选模板判定，不因换一个 agent_id 就成立；同一客户付费也不自动证明或否定独立性。
只有设计职能的主体发现合同问题时可以报告或转介，不可借角色英文名称提交另一种职能才有权作出的正式决定。

## 2. 信息、状态与业务对象

### 2.1 可见信息与权限边界

| 信息或状态 | 本主体需要保存/读取 | 边界 |
|---|---|---|
| 专业资格与能力 | 工程对象/专业任务、支持方法及适用域、目的地事项经验、资格和证据状态、实际团队/工具位置 | 注册地、角色名、通用评分和历史经验不能生成资格或未具备的专项能力 |
| 业务机会 | 可见技术服务需求、邀请和调查线索 | 机会存在不等于已承诺承担责任 |
| 服务权限 | 编制/审查/签署/现场检查范围与排除项 | 核证付款、行政决定必须另有依据 |
| 资源 | 专业人员、所需工具/检验能力及跨项目排期 | 未建模的设备或实验能力不默认无限 |
| 调查输入 | 场地、材料、荷载或系统要求及来源 | 自报、假设、实测和未知分别记录 |
| 技术对象 | 设计版本、方法、参数、计算/检查结果和适用条件 | 结果仅支持其明确覆盖范围 |
| 检查事项 | 请求、现场可见证据、发现问题和复查状态 | 未发现缺陷不等于实际没有缺陷 |
| 费用责任 | 内部工作成本、服务费、应收及后续义务 | 专业通过不代表收费已获认可或到账 |
| 主体认知 | 伙伴反馈、事故/缺陷经验和市场判断 | 不读取未获授权的隐蔽真实状态 |

**ENGINEER-004｜每次意见标明身份。** 同一主体兼任不同职能时，本次输出必须指出所依据的委任、专业、对象与授权，不能以一个总审批结果代替。
需要签署的材料检查签署权限及版本；不默认本主体可以直接作为申请人或替监管机关批准。
对专业以外的问题可以提出转介请求，但不能填入一个通用高分使其通过。

### 2.2 正式状态与私有判断的所有者

| 状态 | 正式维护者/私有归属 | 本主体动作边界 |
|---|---|---|
| 业务取舍、风险估计、经验和报价底线 | 本主体私有认知 | 可更新推断，不能重写现场真值或其他主体评价 |
| 专业、资格、委任职能与授权版本 | 身份/资格及合同授权入口 | 可提供证据并申请改变，描述能力不等于资格更新 |
| 分专业人员、工具、任务投入和排期 | 统一资源/任务入口 | 提交分配和调整，跨职能任务仍共享真实容量 |
| 计算、检查、发现问题和复查证据 | 正式分析/检查/事项入口 | 写入获支持范围的结果，不能直接将隐藏缺陷清零 |
| 成果签署、发布和合同指令 | 各有权成果/合同入口 | 仅按本次职能提出/提交，不合并为一个“批准” |
| 收付、债务及残余专业义务 | 共同资金/义务入口 | 管理自己的申报与履约，不能替客户或银行改余额 |

### 2.3 关键对象及字段

**ENGINEER-019｜分析、检查和实际问题具有不同身份。** 以下字段为目标语义，复用共同任务/成果/事项；所有对象均保留作者、时间、版本、可见范围及来源。

| 对象 | 关键标识与内容 | 对应闭环 |
|---|---|---|
| 专业服务职能 | `engagement_id/version`、`discipline`、`function`、权限、独立性依据 | 谁可编制、复核、签署或发何种合同指令 |
| 分析任务/结果 | `analysis_id/version`、输入、`method_id/version`、假设、适用域、单位及结果引用 | 输入核验、分析、适用性检查和提交 |
| 检查计划/记录 | `inspection_id/version`、对象/部位、范围、观察窗口、方法、准入、证据与未检部分 | 授权、排程、实际观察和结果评估 |
| 发现问题与复查 | `finding_id`、原始证据、受影响范围、回应/整改引用、`recheck_id` | 发现、处置、实际整改证据、复查及关闭 |
| 合同职能事项 | `instruction_or_certificate_id/version`、合同条款、事项、签发权限及效力范围 | 有权发出、送达/执行、异议及修正 |
| 调试/支持与残余清单 | `task_id`、系统范围、前置试验、未决项、接任与到期依据 | 调试、问题处理、范围结束与后续支持 |

## 3. 行为卡与执行契约

行为卡先说明触发、选择、正式后果及等待/失败，再定义函数、具名输入、输出分支、接收者和验收。执行矩阵汇总资源与交接。卡内“正式结果”指相应命令成功提交后的效果；`ActionResult.completed` 只表示本主体输出已形成。

<!-- action-nav:start -->
**动作定位**：[ENGINEER-A01](#engineer-a01--识别专业需求与经营机会) · [ENGINEER-A02](#engineer-a02--判断是否承接并提出服务方案) · [ENGINEER-A03](#engineer-a03--核对委任和检查独立性) · [ENGINEER-A04](#engineer-a04--安排专业任务与调查需求) · [ENGINEER-A05](#engineer-a05--分析并形成专业方案) · [ENGINEER-A06](#engineer-a06--检查指定成果与接口) · [ENGINEER-A07](#engineer-a07--提交成果签署及用途说明) · [ENGINEER-A08](#engineer-a08--提供施工检查与技术支持) · [ENGINEER-A09](#engineer-a09--处理修改调试与缺陷复查) · [ENGINEER-A10](#engineer-a10--提交服务费依据并管理应收) · [ENGINEER-A11](#engineer-a11--暂停召回与专业交接) · [ENGINEER-A12](#engineer-a12--维护资格与专业经验) · [ENGINEER-A13](#engineer-a13--承接范围明确的前期技术评估)
<!-- action-nav:end -->

### ENGINEER-A01 · 识别专业需求与经营机会

- **触发与输入**：可见调查、设计、审查、施工支持需求及本主体专业方向、经营资源与已有承诺。
- **自主选择**：跟踪、表达兴趣、要求明确专业边界、开展获授权准备或不参与。
- **正式结果**：记录本主体业务评估和研究任务，不改变其他组织的选择或共享机会状态。
- **等待与失败**：任务名称不清或超出专业范围时先澄清/转介，不将市场观察描述当作新订单。

**函数与类型契约**

- **函数**：`roles.engineer.a01(ctx: ActionContext, input: EngineerA01Input) -> ActionResult<EngineerA01Payload>`。
- **输入记录**：`EngineerA01Input = {scope:ScopeRef; opportunity_ref:Ref<Opportunity>; capability_ref:Ref<Capability>; capacity_ref:Ref<ResourceCalendar>; preparation_authority_ref:Option<Ref<Authority>>}`。来源：公开/获邀专业需求、本组织能力及资源与获准研究权。
- **输出分支**：`EngineerA01Payload` 的 `choice` 与分支必填字段为：`track{trigger_ref:Ref<Trigger>}; express_interest{recipient_id:EntityId<Agent>,discipline_ref:Ref<Discipline>}; prepare{request:EngineerTaskRequest}; clarify{questions:List<EngineerQuestion>}; decline{reason:string}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交邀请方或任务服务；只登记机会回应/获准准备，不形成订单和资格。
- **业务出口与验收**：专业不清先clarify；技术失败不等于decline；CHECK-ENGINEER-001、CHECK-ENGINEER-003。

### ENGINEER-A02 · 判断是否承接并提出服务方案

- **触发与输入**：具体技术范围、预期成果、资料成熟度、责任、费用、期限和本主体可用能力。
- **自主选择**：接受有效条件、提出阶段划分/补充调查/排期方案、暂缓或拒绝。
- **正式结果**：版本化服务方案、限制和接受状态；如形成预留，记录专业资源及有效窗口。
- **等待与失败**：不因业主迫切需要而虚构资格或可用人员；模型失败不代替真实业务拒绝。

**函数与类型契约**

- **函数**：`roles.engineer.a02(ctx: ActionContext, input: EngineerA02Input) -> ActionResult<EngineerA02Payload>`。
- **输入记录**：`EngineerA02Input = {scope:ScopeRef; request_ref:Ref<ServiceRequest>; terms_ref:Ref<ServiceTerms>; capability_ref:Ref<Capability>; capacity_ref:Ref<ResourceCalendar>; independence_requirement_ref:Option<Ref<IndependenceRequirement>>}`。来源：委托方的专业范围/用途和条款，本方能力、排期及独立性要求。
- **输出分支**：`EngineerA02Payload` 的 `choice` 与分支必填字段为：`accept{terms_ref:Ref<ServiceTerms>}; counteroffer{offer:EngineerServiceOffer}; decline{reason:string}; clarify{questions:List<EngineerQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交委托方/委任服务，记录本方接受或条件；不自动完成委任、签署或专业分析。
- **业务出口与验收**：不满足独立性不能以换agent_id修复；CHECK-ENGINEER-002、CHECK-ENGINEER-003、CHECK-ENGINEER-037。

### ENGINEER-A03 · 核对委任和检查独立性

- **触发与输入**：委任或内部任务授权到达，核对专业、成果用途、签署权限、原作者及所需独立性。
- **自身行为**：确认本主体接受的范围，披露职责冲突，要求调整超范围内容或不相容安排。
- **正式结果**：核心登记有效服务与职能，继承已有预留关联；范围可局限于单项前期技术检查。
- **等待与失败**：被列为候选或收到委托人选择不等于已有效委任；未满足独立检查要求时不冒充独立复核。

**函数与类型契约**

- **函数**：`roles.engineer.a03(ctx: ActionContext, input: EngineerA03Input) -> ActionResult<EngineerA03Payload>`。
- **输入记录**：`EngineerA03Input = {scope:ScopeRef; appointment_ref:Ref<Appointment>; accepted_terms_ref:Ref<ServiceTerms>; function_refs:List<Ref<FunctionAssignment>>; independence_check_ref:Option<Ref<IndependenceCheck>>; reservation_ref:Option<Ref<ResourceReservation>>}`。来源：双方记录的相容条款、真实关系/独立性证据及资源预留。
- **输出分支**：`EngineerA03Payload` 的 `choice` 与分支必填字段为：`confirm{appointment_ref:Ref<Appointment>,accepted_terms_ref:Ref<ServiceTerms>}; disclose_conflict{conflict_refs:List<Ref<ConflictOfInterest>>,questions:List<EngineerQuestion>}; request_amendment{questions:List<EngineerQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交委任服务后到A04；仅形成获授权专业范围与相应资源关系，不取得其他专业签署权。
- **业务出口与验收**：缺必要独立性证据needs_information；已知冲突选择disclose_conflict；CHECK-ENGINEER-004、CHECK-ENGINEER-037。

### ENGINEER-A04 · 安排专业任务与调查需求

- **触发与输入**：有效任务、输入缺口、工作量/耗时依据、专业人员及工具可用性和跨项目排期。
- **自主选择**：配置资源、分解任务、安排合法并行、请求调查/试验或等待必要输入。
- **正式结果**：任务起止、实际投入、等待及内部成本；调查由相应获授权执行者提供证据，不凭请求即完成。
- **等待与失败**：必要输入缺失仅阻塞依赖的任务；已有成果复用仍检查适用性、权限和剩余工作量。

**函数与类型契约**

- **函数**：`roles.engineer.a04(ctx: ActionContext, input: EngineerA04Input) -> ActionResult<EngineerA04Payload>`。
- **输入记录**：`EngineerA04Input = {scope:ScopeRef; task_refs:List<Ref<Task>>; dependency_refs:List<Ref<Evidence>>; work_profile_ref:Ref<WorkProfile>; capacity_ref:Ref<ResourceCalendar>; existing_allocation_refs:List<Ref<ResourceAllocation>>}`。来源：有效专业任务、输入清单、工作方法及实际人员/设备排期。
- **输出分支**：`EngineerA04Payload` 的 `choice` 与分支必填字段为：`allocate{plan:EngineerTaskPlan}; revise_plan{plan:EngineerTaskPlan,prior_plan_ref:Ref<WorkPlan>}; request_investigation{questions:List<EngineerQuestion>,observation_method_ref:Ref<Method>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交任务资源服务与获权调查执行者；分派和观测各自提交，调查请求不是已有试验结果。
- **业务出口与验收**：无准入/设备或证据等待明确下一触发；CHECK-ENGINEER-005、CHECK-ENGINEER-006、CHECK-ENGINEER-007。

### ENGINEER-A05 · 分析并形成专业方案

- **触发与输入**：获授权工程对象/子工程、需求与调查证据、专业模板及获支持的方法/参数范围；已有设计时引用其版本，新编方案不强制存在 Architect 前置成果。
- **自主选择**：提出技术选项、采用适用方法比较、识别敏感假设、要求补查或指出当前不可接受项。
- **正式结果**：带输入版本、方法、假设、计算/检查引用和适用限制的专业成果；数值经正式方法产生。
- **等待与失败**：计算失败、模型不适用和证据不足分别记录；不得把 LLM 自编数值当作有效工程计算结果。

**函数与类型契约**

- **函数**：`roles.engineer.a05(ctx: ActionContext, input: EngineerA05Input) -> ActionResult<EngineerA05Payload>`。
- **输入记录**：`EngineerA05Input = {scope:ScopeRef; brief_ref:Ref<Brief>; task_ref:Ref<Task>; engineering_profile_ref:Ref<EngineeringProfile>; evidence_refs:List<Ref<Evidence>>; method_result_refs:List<Ref<MethodResult>>; prior_option_ref:Option<Ref<DesignOption>>}`。来源：已授权任务、需求/调查、适用方法及其真实输出；无Architect成果不阻止独立工程设计。
- **输出分支**：`EngineerA05Payload` 的 `choice` 与分支必填字段为：`produce{draft:EngineerDesign}; request_investigation{questions:List<EngineerQuestion>}; report_limit{assessment:EngineerAssessment}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：新编专业方案不要求本次方案已经存在，`prior_option_ref=null` 表示无前序。没有方法结果时只能形成目录允许的未核验候选/限制报告，不得填已通过检查或完整计算量；需进一步方法执行时沿真实任务安排后再取得结果。
- **接收与核心效果**：交成果服务后到专业复核、QS/Contractor；创建自身专业成果，不直接写工程安全真值或修改他人设计。
- **业务出口与验收**：方法不可用unsupported；有限报告可保留out_of_scope项；CHECK-ENGINEER-008、CHECK-ENGINEER-048、CHECK-ENGINEER-053、CHECK-ENGINEER-054。

### ENGINEER-A06 · 检查指定成果与接口

- **触发与输入**：本主体获授权的检查对象、版本、标准/模型范围、必要独立性和专业接口信息。
- **自主选择**：给出范围内通过、问题、待补证或复查结论，请求接口协调；不强制二元通过/拒绝。
- **正式结果**：检查记录、发现问题、证据及影响范围；问题关闭需适用处理与复查依据。
- **等待与失败**：某专业通过不扩展为全部专业通过；协调会议结束或风险分下降不能直接关闭实际问题。

**函数与类型契约**

- **函数**：`roles.engineer.a06(ctx: ActionContext, input: EngineerA06Input) -> ActionResult<EngineerA06Payload>`。
- **输入记录**：`EngineerA06Input = {scope:ScopeRef; target_ref:Ref<Deliverable>; review_request_ref:Ref<ReviewRequest>; check_spec_refs:List<Ref<CheckSpec>>; method_result_refs:List<Ref<MethodResult>>; independence_check_ref:Option<Ref<IndependenceCheck>>; interface_refs:List<Ref<Interface>>}`。来源：授权检查对象、方法/结果、可见专业接口及独立性核验。
- **输出分支**：`EngineerA06Payload` 的 `choice` 与分支必填字段为：`assess{assessment:EngineerAssessment}; request_evidence{questions:List<EngineerQuestion>}; request_coordination{issue_refs:List<Ref<Issue>>,recipient_id:EntityId<Agent>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交检查/问题服务、原作者或整合者；逐项登记范围内结论，关闭问题另验复查证据；不平均出全项目通过。
- **业务出口与验收**：保留已知conflict与未知项并存，技术失败无实质结论；CHECK-ENGINEER-023、CHECK-ENGINEER-045、CHECK-ENGINEER-046、CHECK-ENGINEER-047。

### ENGINEER-A07 · 提交成果、签署及用途说明

- **触发与输入**：任务已达到编制标准，成果和依赖版本完整，接收/签署权限与拟用范围明确。
- **自身行为**：向获授权接收方提交专业设计、技术意见或核验记录；仅在有权时签署或发布指定用途。
- **正式结果**：成果提交、签署/发布记录及未解决事项；接收、法定决定及提款判断由各自主体承担。
- **等待与失败**：自己的“完成”不能替代合同接受或行政许可；签署范围不足时保留限制，不补造其他专业证明。

**函数与类型契约**

- **函数**：`roles.engineer.a07(ctx: ActionContext, input: EngineerA07Input) -> ActionResult<EngineerA07Payload>`。
- **输入记录**：`EngineerA07Input = {scope:ScopeRef; deliverable_ref:Ref<Deliverable>; task_completion_ref:Ref<TaskCompletion>; requested_use:EngineerUse; recipient_ids:List<EntityId<Agent>>; signing_basis_refs:List<Ref<SigningBasis>>; release_basis_refs:List<Ref<ReleaseBasis>>}`。来源：成果版本、真实完成记录、委任接收者、独立签署和用途发布依据。
- **输出分支**：`EngineerA07Payload` 的 `choice` 与分支必填字段为：`submit{deliverable_ref:Ref<Deliverable>,requested_use:EngineerUse,recipient_ids:List<EntityId<Agent>>,unresolved_issue_refs:List<Ref<Issue>>}; sign{deliverable_ref:Ref<Deliverable>,signing_basis_refs:List<Ref<SigningBasis>>,requested_use:EngineerUse}; release_for_use{deliverable_ref:Ref<Deliverable>,release_basis_refs:List<Ref<ReleaseBasis>>,requested_use:EngineerUse}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`submit` 允许 signing/release 依据列表为空；`sign` 必须有适用签署依据，`release_for_use` 必须有用途授权和已满足条件。接收者从本次获准集合选取；签署只涉及已签范围，不自动提交到机关、完成通知或放行其他用途。
- **接收与核心效果**：交成果/签署/用途发布入口后通知获权接收者；一次选择只走该分支，有效签署、送达、合同接受和许可分别记。
- **业务出口与验收**：无签署权不生成签署；requested_use不等于allowed_use；CHECK-ENGINEER-002、CHECK-ENGINEER-012、CHECK-ENGINEER-018。

### ENGINEER-A08 · 提供施工检查与技术支持

- **触发与输入**：有效现场检查/技术查询任务、适用设计、允许访问的现场/试验资料及职责范围。
- **自主选择**：安排检查、解释技术要求、请求试验/补证、报告问题或提出整改建议。
- **正式结果**：按实际可获得证据形成检查/支持报告，明确观察时间、范围和待处理事项。
- **等待与失败**：提出停工或核证意见是否具有正式效力取决于授权；不得默认本主体可以停止所有项目或直接付款。

**函数与类型契约**

- **函数**：`roles.engineer.a08(ctx: ActionContext, input: EngineerA08Input) -> ActionResult<EngineerA08Payload>`。
- **输入记录**：`EngineerA08Input = {scope:ScopeRef; inspection_task_ref:Ref<Task>; applicable_design_ref:Ref<Deliverable>; access_ref:Option<Ref<SiteAccess>>; observation_method_ref:Ref<Method>; observation_refs:List<Ref<Observation>>; query_refs:List<Ref<Issue>>}`。来源：获权现场任务、已获准资料、正式观察方法生成的可见结果。
- **输出分支**：`EngineerA08Payload` 的 `choice` 与分支必填字段为：`plan_inspection{plan:EngineerTaskPlan}; report{assessment:EngineerAssessment,observation_refs:List<Ref<Observation>>}; respond{question_ref:Ref<Issue>,response:string,basis_refs:List<Ref<Evidence>>}; request_test{questions:List<EngineerQuestion>,method_ref:Ref<Method>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：计划和请求试验不要求先有观测结果；无现场准入时可以申请安排，但不得产生实查报告。远程资料答复按资料权利处理，不因没有 SiteAccess 一律阻塞；`report` 只覆盖已取得且可见的观测。
- **接收与核心效果**：交现场问题服务/Contractor及有权处置者；只记录真实观察及范围意见，不直接停工、付款或揭示隐藏缺陷。
- **业务出口与验收**：无准入保持等待，部分观察保留未覆盖区；CHECK-ENGINEER-009、CHECK-ENGINEER-011、CHECK-ENGINEER-038、CHECK-ENGINEER-039、CHECK-ENGINEER-040。

### ENGINEER-A09 · 处理修改、调试与缺陷复查

- **触发与输入**：获授权变更、调试异常或缺陷事项，原成果、已施工/试验事实及有效义务。
- **自主选择**：分析影响、提出处理选项、修订专业成果、请求必要试验或安排复查。
- **正式结果**：新版本、相关任务、技术依据及范围内复查结论；调试结果与使用许可分别记录。
- **等待与失败**：旧工程事实不可回溯删除；按有效义务推进技术工作，费用争议不自动决定所有工作停做或免费。

**函数与类型契约**

- **函数**：`roles.engineer.a09(ctx: ActionContext, input: EngineerA09Input) -> ActionResult<EngineerA09Payload>`。
- **输入记录**：`EngineerA09Input = {scope:ScopeRef; issue_ref:Ref<Issue>; obligation_ref:Ref<Obligation>; prior_deliverable_ref:Ref<Deliverable>; instruction_ref:Option<Ref<Instruction>>; evidence_refs:List<Ref<Evidence>>; method_result_refs:List<Ref<MethodResult>>}`。来源：已知缺陷/调试异常、原设计、有效工作义务与有权改动依据。
- **输出分支**：`EngineerA09Payload` 的 `choice` 与分支必填字段为：`propose_remedy{request:EngineerTaskRequest,affected_refs:List<Ref<Deliverable>>}; revise{draft:EngineerDesign,change_basis_ref:Ref<ChangeBasis>}; reassess{assessment:EngineerAssessment}; request_test{questions:List<EngineerQuestion>,method_ref:Ref<Method>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交成果/问题服务和施工责任方；只新增方案/复查结果，实际整改由责任方执行；法定使用许可在适用时由有权 Government 决定，专业用途发布和合同接收仍由各自获授权主体负责。
- **业务出口与验收**：整改计划不等于完成，费用争议不抹去工作义务；CHECK-ENGINEER-013、CHECK-ENGINEER-014、CHECK-ENGINEER-041、CHECK-ENGINEER-051。

### ENGINEER-A10 · 提交服务费依据并管理应收

- **触发与输入**：委任约定的计费事件、实际专业投入/成果、费用依据与付款状态。
- **自主选择**：申报、补证、纠正错误、提出费用影响或按权利处理逾期；不替付款方清偿。
- **正式结果**：外部服务形成费用申报、确认/到期及收款关联，内部授权只形成内部成本。
- **等待与失败**：专业意见、工作成本、合同收费与实际到账不混同；同一申报的技术重试不新增费用或现金；获授权的新工作仍按条款另行核算。

**函数与类型契约**

- **函数**：`roles.engineer.a10(ctx: ActionContext, input: EngineerA10Input) -> ActionResult<EngineerA10Payload>`。
- **输入记录**：`EngineerA10Input = {scope:ScopeRef; engagement_ref:Ref<Engagement>; billing_clause_ref:Ref<BillingClause>; work_fact_refs:List<Ref<WorkFact>>; calculation_ref:Option<Ref<FeeCalculation>>; prior_claim_ref:Option<Ref<FeeClaim>>; receipt_refs:List<Ref<PaymentReceipt>>}`。来源：自身合同/任务投入与费用计算，实际可见资金回执。
- **输出分支**：`EngineerA10Payload` 的 `choice` 与分支必填字段为：`claim{claim:EngineerFeeClaim}; correct{prior_claim_ref:Ref<FeeClaim>,claim:EngineerFeeClaim}; dispute{claim_ref:Ref<FeeClaim>,issue:EngineerQuestion}; reconcile{claim_ref:Ref<FeeClaim>,receipt_refs:List<Ref<PaymentReceipt>>}; remind{claim_ref:Ref<FeeClaim>,recipient_id:EntityId<Agent>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`claim/correct` 必须有适用计费计算；`correct/dispute/reconcile/remind` 必须引用本方已有费用申报，且不得改收款主体或合同。催收、争议和对账可在 `calculation_ref=null`（本次没有新计费计算）时进行；对账仍需真实回执，未知到账保持待核。内部任务不进入外部服务费申报分支，成本按实际工作执行归集。
- **接收与核心效果**：交实际付款人和费用/义务服务；申报不直接成为现金；内部任务只走成本归集。
- **业务出口与验收**：重复提交/回执去重；不得用专业通过替代计费条件；CHECK-ENGINEER-015、CHECK-ENGINEER-029、CHECK-ENGINEER-034。

### ENGINEER-A11 · 暂停、召回与专业交接

- **触发与输入**：暂停/恢复/退出的有效依据、尚待检查任务、真实排期、成果权限和剩余义务。
- **自主选择**：按权利调整任务、确定召回安排、提供移交范围或评估接任任务。
- **正式结果**：逐任务释放/保留专业资源，移交允许使用的资料并保留原作者、结论范围和未清费用。
- **等待与失败**：退出不清除历史责任；接任方需要自己的接收与核查投入，不能自动获得前任所有记忆与确认。

**函数与类型契约**

- **函数**：`roles.engineer.a11(ctx: ActionContext, input: EngineerA11Input) -> ActionResult<EngineerA11Payload>`。
- **输入记录**：`EngineerA11Input = {scope:ScopeRef; engagement_ref:Ref<Engagement>; transition_basis_ref:Ref<ServiceTransitionBasis>; task_refs:List<Ref<Task>>; allocation_refs:List<Ref<ResourceAllocation>>; deliverable_refs:List<Ref<Deliverable>>; residual_obligation_refs:List<Ref<Obligation>>}`。来源：合法暂停/退出依据、真实排期、成果权限和剩余专业义务。
- **输出分支**：`EngineerA11Payload` 的 `choice` 与分支必填字段为：`pause{task_refs:List<Ref<Task>>,basis_ref:Ref<ServiceTransitionBasis>}; recall{plan:EngineerTaskPlan}; handover{package:EngineerHandover}; exit{package:EngineerHandover}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交委托/接任方、任务资源服务；逐项释放/保留、移交；不转移未批准的责任或前任私有记忆。
- **业务出口与验收**：接任资料不足限范围或请求补查；CHECK-ENGINEER-016、CHECK-ENGINEER-017、CHECK-ENGINEER-036、CHECK-ENGINEER-044。

### ENGINEER-A12 · 维护资格与专业经验

- **触发与输入**：资格状态事件、可见技术反馈、市场变化及本主体可安排的能力建设资源。
- **自主选择**：提出学习/维护计划，更新对风险、伙伴和服务范围的判断。
- **正式结果**：认知变化有来源；资格更新与能力提高如纳入，分别由相应证据、投入和规则提交。
- **等待与失败**：月度“维护资格”文字不自动续期资格，也不能使任何专业风险变为零。

**函数与类型契约**

- **函数**：`roles.engineer.a12(ctx: ActionContext, input: EngineerA12Input) -> ActionResult<EngineerA12Payload>`。
- **输入记录**：`EngineerA12Input = {scope:ScopeRef; qualification_refs:List<Ref<Qualification>>; feedback_refs:List<Ref<Feedback>>; learning_profile_ref:Option<Ref<LearningProfile>>; strategy_ref:Ref<Strategy>}`。来源：可见真实资格事件、反馈及本组织已选经营/学习规则。
- **输出分支**：`EngineerA12Payload` 的 `choice` 与分支必填字段为：`record_feedback{feedback_refs:List<Ref<Feedback>>,interpretation:string}; update_judgment{revision:EngineerJudgment}; propose_training{request:EngineerTaskRequest,learning_profile_ref:Ref<LearningProfile>}; request_qualification_update{qualification_ref:Ref<Qualification>,evidence_refs:List<Ref<Evidence>>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交认知、能力任务或资格核验服务；只有资格证据的有权提交可更新资格，不因叙述自动续期。
- **业务出口与验收**：无学习机制返回unsupported或仅记录反馈；CHECK-ENGINEER-002、CHECK-ENGINEER-008。

### ENGINEER-A13 · 承接范围明确的前期技术评估

- **触发与输入**：收到有限可行性/技术比较请求，或已有研究引用的需求、方案、证据与方法适用条件发生变化。 核对委任/内部授权、专业、对象和版本、拟回答问题、成果用途、独立性、费用与资源边界。
- **自主选择与投入**：依据 A02/A03 单独接受任务，可只承担一个专业或一组问题；前期研究可有偿，但不默认任何询问都形成收费义务。 提出可适用选项，列出必要证据，使用获支持的方法作范围内分析；请求其他专业或供应方提供自身不能确定的信息。
- **正式结果**：范围内支持、存在条件、存在冲突、证据不足或方法不适用，附可继续研究的方向；不能为了产生候选而保证至少一项通过。 核心登记任务投入和专业成果；建议及有限检查不直接确定建造方式、开工许可、投资承诺或完整工程设计任务。
- **等待与失败**：明确待调查/试验/接口问题、下一响应主体和允许继续部分；达到工作边界后提交成果或请求有效扩展。

**函数与类型契约**

- **函数**：`roles.engineer.a13(ctx: ActionContext, input: EngineerA13Input) -> ActionResult<EngineerA13Payload>`。
- **输入记录**：`EngineerA13Input = {scope:ScopeRef; brief_ref:Ref<Brief>; research_authority_ref:Ref<Authority>; task_ref:Ref<Task>; option_refs:List<Ref<DesignOption>>; check_spec_refs:List<Ref<CheckSpec>>; evidence_refs:List<Ref<Evidence>>; expenditure_limit_ref:Ref<ResearchLimit>; available_assessment_refs:List<Ref<Assessment>>; method_result_refs:List<Ref<MethodResult>>}`。来源：有限专业研究授权、选项版本、专项问题、可见证据和同委任研究额度。
- **输出分支**：`EngineerA13Payload` 的 `choice` 与分支必填字段为：`compare{assessments:List<EngineerAssessment>,comparable_scope_ref:Ref<ComparisonScope>}; recommend_investigation{questions:List<EngineerQuestion>,request:EngineerTaskRequest}; no_recommendation{assessments:List<EngineerAssessment>,reason:string}; deliver_at_limit{assessments:List<EngineerAssessment>,remaining_questions:List<EngineerQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：没有候选时可围绕 Brief 作有限专业研究或请求调查；`compare` 的 assessments 不能为空且各自引用可见对象、已执行检查或明确未覆盖项，不强制至少一项支持。已登记评估可复用；新的检查数值只能来自本次适用方法结果。到限额允许无成功评估并保留未决事项，后续投入另需授权。
- **接收与核心效果**：交成果服务及Owner/Architect/QS；研究报告可交付而方案仍冲突/未知；方法执行复用A04—A06并沿投入身份去重。
- **业务出口与验收**：无正式项目仍可研究；未覆盖不编造通过；CHECK-ENGINEER-019、CHECK-ENGINEER-020、CHECK-ENGINEER-025、CHECK-ENGINEER-027、CHECK-ENGINEER-028。

### 3.1 全行为执行与交接矩阵

表中资源与耗时按实际模型内任务记录；外部模型调用失败只影响执行状态，不直接算作专业拒绝或现实工程延期。

| 行为 | 输入与允许选择 | 校验后的正式输出 | 资源与时间 | 失败或等待 | 下一交接 |
|---|---|---|---|---|---|
| A01 识别业务 | 专业需求与自身方向；跟踪、转介、准备或不参与 | 本主体机会与授权准备任务 | 研究有真实投入 | 来源/专业不清先澄清 | 委托方与 A02 |
| A02 承接判断 | 范围、责任、方法能力与排期；限缩、分阶段、报价或拒绝 | 服务方案和本方接受 | 预留指向所需专业/工具窗口 | 无能力不能用其他专业高分顶替 | 双方相容接受后 A03 |
| A03 职能确认 | 委任、资格及关系；确认、披露冲突或要求修订 | 有效职能、授权及独立性结论 | 预留转正式分派 | 不满足独立性不冒充独立复核 | A04 或有权委托人调整安排 |
| A04 分解任务 | 问题、输入缺口和完成标准；排程、调查请求或等待 | 专业任务、投入及调查依赖 | 人员/工具和现场窗口分别记录 | 申请调查不等于已拿到结果 | 调查/试验执行者与 A05/A06 |
| A05 设计分析 | 指定输入与方法；选择适用方法、提出选项或补查 | 专业成果及计算引用 | 有效计算与工程编制任务各记投入 | 方法错误、输入不足、技术失败分开 | A06/A07，Architect 或 QS |
| A06 检查核验 | 被检对象、职能和证据；检查、补证、问题或范围内认可 | 检查记录、发现及适用结论 | 审查范围/次数与实际任务关联 | 未检查部分不默认通过；作者回应不自动独立复核 | 原作者/履行方整改，再 A09 |
| A07 签署提交 | 成果、依赖和用途；提交或获授权签署/发布 | 带职能的提交及发布依据 | 交付/签署任务有完成条件 | 无权签署可提交意见但不生成签署事实 | 有权接收者、监管或合同方 |
| A08 现场支持 | 现场准入、现用成果和检查任务；观察、要求补证或发有权通知 | 现场证据及范围内指令/意见 | 出勤/检验窗口与工具约束 | 无现场证据不作实查记录；超权问题转介 | Contractor/Supplier 处理与 A09 |
| A09 修订复查 | 原发现、处理方案、实际整改/试验；修订、复查、保持开放 | 新版本、复查结果、问题关闭依据 | 整改与复查是不同主体/任务的投入 | 只交整改计划不能关闭；不把费用争议当技术通过 | 获授权用途放行、下一试验或残余清单 |
| A10 服务收费 | 自身费用条款与工作；申报、纠错、催收或争议 | 本企业应收与清偿引用 | 财务核对单独记 | 客户欠费不篡改专业发现 | 实际付款人、共同账本 |
| A11 暂停接续 | 有效结束、剩余专业事项；移交、召回、调整或退出 | 资源变更与责任/资料交接 | 接任核查和后续复查仍需容量 | 交接不带走或复制前任私有记忆 | 接任方与有权委托人 |
| A12 经验维护 | 可见误差、检查及资格事件；更新判断或能力计划 | 认知与有证据的资格/能力变化 | 维护/培训工作有投入 | 未验证学习不能宣称方法已校准 | A01/A02/A04 后续判断 |
| A13 前期评估 | 有限问题及需求/选项版本；条件意见、补查或无结论 | 范围化研究与未决条件 | 授权工作限额和排期 | 不因无完整项目而禁止研究，不因研究结束扩大权限 | 委托人及相应设计/投资取舍 |

### 3.2 输入输出类型与提交边界

本节与每张行为卡共同构成函数契约。所有签名是目标开发接口，不表示已有同名函数或方法已实现。完整公共类型见[接口契约](../06_engineering/interface_contracts.md)。

- `ActionContext.task_ref` 标识宿主登记的本次决策调用任务；业务工作任务由各 Input 的 `task_ref/task_refs` 明确引用，两者不能互换。首次机会评估或工作申请不要求尚未创建的业务任务。
- 每个 `Input` 为封闭记录，均包含 `scope:ScopeRef`，加本卡列明字段；前期工作允许 `assessment_case`，不要求虚构项目。经营/发现行为可用 `organization`。身份、职能、授权、可见版本和候选由 `ActionContext` 绑定，不接受主体在输入里自行增权。
- 本卡写作 `choice{fields}` 的每一项表示独立分支 `{choice:"choice",fields...}`；合起来就是对应具名 `Payload` 的完整判别联合。各分支另共同包含 `scope:ScopeRef` 和 `note:Option<string>`。未声明字段禁止出现；不得在拒绝分支夹带接受、金额、资源占用或批准字段。
- `Option<T>` 可空且键仍存在，其他字段必填。输入列表为空只表示当前已获准可见的集合没有记录，不证明世界上不存在该事实；必需资料的覆盖另由要求清单核验。分支所需接收者、申请依据、实际方案/任务及费用条款不得为空。宿主无法装配必填输入时登记 `needs_information`；错误类型/漏键先走结构校验。`scope` 必须落在授权范围内且与输入对象一致。
- `completed(payload)` 仅表示行为输出完成。其后由应用服务拆分并提交必要原子命令，由核心回执确认正式效果；多条命令不默认为一个已全部成功的事务。接收者收到的是获授权的已提交对象投影。技术错误走 `technical_error`，业务拒绝是 `payload.choice`，资源/业务等待走 `deferred`；方法不支持走 `unsupported`，可独立完成的有限报告仍保留未覆盖项。
- 空值语义固定：`prior_*`/`parent_*` 表示没有适用前序；可空授权/签署/独立性依据表示当前没有可用记录，依赖该依据的分支必须返回缺项或权限拒绝；可空方法结果表示尚无适用执行结果，不能填通过；`learning_profile_ref=null` 表示没有启用学习规则。已知数值缺失仍用 `ValueState`，不能挪用空值或空列表表达零。其他可空对象的必要性由本卡分支明确，不得静默忽略。
- `Ref<MethodResult>` 指已登记的具体方法执行记录（输入版本、方法版本、输出 schema、结果及来源），不是未提交的通用 `MethodResult<T>` 返回信封；需要使用其数值时先校验执行成功、支持范围和用途。输出中所有新引用均须可解析；尚未存在的对象使用本节封闭草案记录交责任服务创建。
- 文本用于解释、问答及专业理由。会影响后续门控的用途、数量、条件、缺项和受影响范围必须使用字段/引用表达。所有数值输出来自适用计算/观察方法；纯登记、转送、排期执行和去重可由确定性程序处理，不强制调用 LLM。
- 对尚未执行的数值计算、量取、观测或检查，先保留候选/问题并安排获授权方法执行；方法执行记录保存后，宿主才能在下一次装配中提供可解析引用。一个行为可由多个函数协作完成，不把一次模型回复等同全部任务执行。有限报告完成与其所评对象满足要求分别验收。
- 下表 `Ref<K>` 的 K 为有版本对象类别，含义由本角色 §2.3、§4 及[共同对象](../02_world/domain_objects.md)约束；不是自由附件或任意字典。已有对象的相容投影可以只读复用；尚未登记的准备对象须先由其责任服务创建并绑定 schema/method/profile，禁止编造一个引用绕过缺失实现。正式 `EntityId<K>` 由核心创建；草案内局部行键不能冒充正式业务 ID。

| 局部类型 | 完整字段或封闭取值 |
|---|---|
| `EngineerUse` | `research / cost_estimation / regulatory_submission / procurement / construction / operation`；只可选本任务、对象及授权允许的子集，许可名称不由此枚举决定 |
| `EngineerQuestion` | `scope:ScopeRef; target_refs:List<Ref<EvidenceTarget>>; question:string; recipient_ids:List<EntityId<Agent>>; evidence_refs:List<Ref<Evidence>>; blocking_uses:List<EngineerUse>; response_requirement_ref:Ref<ResponseRequirement>` |
| `EngineerTaskRequest` | `scope:ScopeRef; purpose:preparation/service_delivery/investigation/training/remedy/policy_evaluation; input_refs:List<Ref<BusinessObject>>; output_requirement_refs:List<Ref<DeliverableRequirement>>; work_profile_ref:Option<Ref<WorkProfile>>; effort_estimate:ValueState<Measured>; desired_window:ValueState<TimeWindow>; authority_basis_refs:List<Ref<Authority>>; dependency_refs:List<Ref<Dependency>>; questions:List<EngineerQuestion>`；申请尚未创建的业务工作，不含虚构任务 ID；purpose 只可选本动作授权子集，正常报价容量使用 service_delivery，不因枚举存在而获得其他职能。估计引用受支持方法，未知保留。`work_profile_ref=null` 只表示未取得可执行工作方法，允许申请但不执行。经有权确认后创建业务 Task，再编制 TaskPlan；提交申请不占用资源、不形成收费 |
| `EngineerTaskPlan` | `work_profile_ref:Ref<WorkProfile>; items:List<{task_ref:Ref<Task>,resource_ids:List<EntityId<Resource>>,window:TimeWindow,effort:Measured,dependency_refs:List<Ref<Dependency>>,existing_allocation_ref:Option<Ref<ResourceAllocation>>}>`；每项必须绑定已授权任务和适任资源，`effort` 来自工作方法，不是模型自由估值 |
| `EngineerServiceOffer` | `scope:ScopeRef; client_id:EntityId<Agent>; payer_id:EntityId<Agent>; proposed_terms_ref:Ref<ServiceTerms>; fee_basis_ref:Ref<FeeBasis>; fee_calculation_ref:Ref<FeeCalculation>; capacity_request:EngineerTaskRequest; validity:TimeWindow; deliverable_requirement_refs:List<Ref<DeliverableRequirement>>`；条款草案和计算须先登记才可引用；capacity_request 仅说明拟需容量，不表示已正式占用或已经委任 |
| `EngineerFeeClaim` | `engagement_ref:Ref<Engagement>; billing_clause_ref:Ref<BillingClause>; work_fact_refs:List<Ref<WorkFact>>; calculation_ref:Ref<FeeCalculation>; amount:Money; payer_id:EntityId<Agent>; prior_claim_ref:Option<Ref<FeeClaim>>`；金额必须与计算及条款一致，不能由文字推导应收或现金 |
| `EngineerHandover` | `engagement_ref:Ref<Engagement>; recipient_ids:List<EntityId<Agent>>; deliverable_refs:List<Ref<Deliverable>>; access_basis_refs:List<Ref<AccessBasis>>; release_allocation_refs:List<Ref<ResourceAllocation>>; retain_allocation_refs:List<Ref<ResourceAllocation>>; remaining_task_refs:List<Ref<Task>>; remaining_obligation_refs:List<Ref<Obligation>>; basis_ref:Ref<ServiceTransitionBasis>`；释放与保留集合不得相交，接收结果另记 |
| `EngineerJudgment` | `prior_strategy_ref:Ref<Strategy>; learning_profile_ref:Ref<LearningProfile>; evidence_refs:List<Ref<Evidence>>; changes:List<{dimension_ref:Ref<JudgmentDimension>,selected_value_ref:Ref<JudgmentValue>,explanation:string}>`；维度和值来自已选规则的有限目录，禁止利用该结构修改正式能力/资格/工程状态 |
| `EngineerDesign` | `brief_ref:Ref<Brief>; scope:ScopeRef; engineering_profile_ref:Ref<EngineeringProfile>; parent_option_ref:Option<Ref<DesignOption>>; selected_parameter_refs:List<Ref<ValidatedEngineeringParameter>>; method_result_refs:List<Ref<MethodResult>>; evidence_refs:List<Ref<Evidence>>; interface_refs:List<Ref<Interface>>; quantity_basis_refs:List<Ref<QuantityBasis>>; unresolved_questions:List<EngineerQuestion>`；参数记录须携目录、值类型/单位与来源并通过方法适用域校验，不是任意参数字典；没有现成方案时可从需求与调查创建本专业方案 |
| `EngineerAssessment` | `target_ref:Ref<Brief> 或 Ref<DesignOption> 或 Ref<Deliverable>; task_ref:Ref<Task>; check_items:List<EngineerCheckItem>; opinion:support_limited_option/revise/investigate/reserve_interpretation; requested_use:EngineerUse; uncovered_scope_refs:List<Ref<EngineeringScope>>; explanation:string` |
| `EngineerCheckItem` | `check_spec_ref:Ref<CheckSpec>; evidence_refs:List<Ref<Evidence>>; evidence_status:sufficient/missing/assumption_based; method_result_ref:Option<Ref<MethodResult>>; result:Option<satisfied/conflict/undetermined/out_of_scope>; missing_field_paths:List<string>; issue_refs:List<Ref<Issue>>`；未执行/技术失败的 `result` 为空并列缺项或失败引用，不把技术失败写为 undetermined 的成功检查；已成功执行但无法判定时为 undetermined；方法适用域检查确认不覆盖时为 out_of_scope。satisfied/conflict 必须逐项追溯适用的成功方法结果，不准由模型写成功执行标志 |

## 4. 专业工作与跨主体交互

### 4.1 跨主体输入与输出

对方行为只在相应角色文件定义；本主体仅发送/接收与自身委任相符的信息。

| 对方 | 本主体接收 | 本主体交付 |
|---|---|---|
| [Owner](owner.md) | 技术服务需求、授权和目标约束 | 服务方案、专业选项、限制和工作证据 |
| [Architect](architect.md) | 建筑版本、空间接口及协调问题 | 工程要求、分析结论、冲突与修订资料 |
| [QS](qs.md) | 量价疑问、费用范围和成本限制信息 | 经支持的工程数量/技术范围及变更依据 |
| [Government](government.md) | 获准接收的技术问题与材料要求 | 有资格和授权的签署、分析及检查资料 |
| [Contractor](contractor.md) | 现场查询、施工/试验资料和方法信息 | 范围内技术答复、检查意见与整改依据 |
| [Supplier](supplier.md) | 获准提供的性能、试验和接口资料 | 技术需求、证据请求及相应核查结果 |
| [Bank](bank.md) | 获授权的专项核验证据请求 | 指定范围的专业/进度证据及限制 |

向银行提供报告不直接通过提款条件；向监管机关提交签署材料不直接获得许可；工程检查也不自行更新合同价。

### 4.2 前期需求与有限专业研究

**前期职责分工**：业主提出建设目的、候选地区、规模区间和期望交付时间；技术及建造方式保留候选，结合各专业及供应方意见细化。

**ENGINEER-008｜首先核对专业和需求版本。** 接收业主需求版本、本次评估对象、建筑选项或待研究的技术问题，核对本主体可以承担的专业范围。
业主目的、地区、规模区间和时间要求分别标出硬约束、可商议偏好和未知项；工程师不能自行改变业主需求，也不能自行豁免适用技术限制。
只有地区而无具体场址时，使用标明依据的场址情景或请求调查；不可虚构地质、运输净空、现场条件或已有批准。
资料不完整不要求全部停工：可先研究不依赖缺失输入的事项，依赖缺口的结论保留限制和后续检查要求。

**ENGINEER-009｜选项具体到专业系统及接口。** 比较指定专业中的系统选择、性能要求、材料/构件接口和可施工条件，不以一个通用工程分数替代全部判断。
MiC、预制、混合与现浇可以指不同系统或部位，也可能组合使用；技术比较必须明确比较对象、适用边界及组合接口。
同一建造标签在不同规模、场址、运输、起吊或供应条件下不能沿用一个默认结论；本主体只检查所获专业授权和支持方法覆盖的条件。
生产供货能力、价格承诺及商业风险接受分别交由相应主体；工程师可提出需求或验证证据，不代替供应方承诺交付。

| 语义字段建议 | 本主体接收或形成的内容 | 使用边界 |
|---|---|---|
| `owner_case_id`、`brief_id/version` | 业主评估档案及需求版本 | 不要求已经取得正式项目编号 |
| `option_id/version`、`system_scope` | 选项、具体专业/系统/部位及接口 | 不将局部检查扩展成全项目结论 |
| `assignment_id`、`question` | 有效任务与本次需要回答的问题 | 自己不能批准超出委任的新任务与费用 |
| `requirements`、`evidence_refs` | 性能条件、输入证据及可见来源 | 把实测、自报、假设、待验证分别标识 |
| `method_id/version`、`input_refs` | 支持的分析方法、输入及其版本 | 方法不适用时不得伪造有效计算结果 |
| `assessment_id`、`scope` | 具备作者身份的专业评估及范围 | 不自动满足独立复核、签署或监管要求 |
| `findings`、`conditions`、`blockers` | 结果、适用条件、技术冲突和缺口 | 有条件意见不等于条件已经满足 |
| `assumptions`、`sensitivity` | 假设及有依据的敏感性比较 | 未计算的概率/区间不得包装成实测置信水平 |
| `dependencies`、`valid_until_or_trigger` | 依赖版本与重评触发条件 | 不自动因新版本出现作废全部旧结果 |
| `allowed_use`、`review_status` | 研究用途和范围内检查状态 | 前期比较不直接成为施工、付款或许可证明 |

**ENGINEER-010｜权威计算入口也有适用边界。** 技术数值通过获支持的工程/场景计算接口取得，输入与返回结果均关联单位、版本、方法和适用范围。
工程师选择适用方法、提出输入并解释结果；由正式计算记录保存结果，不允许 LLM 回写任意安全度、承载力、缺陷或工期为已算事实。
计算成功仅证明该次方法按输入完成，不证明输入正确、方法足够或真实方案安全；必要检查与独立复核仍另记。
模型暂未覆盖的专业内容可以提出定性限制或调查建议，但不得用建筑师认可、供应方承诺或委托方偏好补成技术通过。

**ENGINEER-011｜独立反馈可以保留分歧。** 工程意见必须说明本专业引用的对象与证据，并明确针对建筑选项、供应证据还是业主要求中的具体问题。
与 Architect/QS/Supplier 意见矛盾时，先校对版本、单位、范围、假设和数据时点，再提出复核、改方案或补证；不默认任一角色的总分更高就覆盖对方。
两个工程专业可能各自满足局部条件而接口不兼容，应保留共同问题及责任接口，不能把局部通过相加为整体可行。
工程师可以建议保留或淘汰候选，并记录适用前提；业主决定商业方向，必要技术条件及独立检查不因商业决定自动完成。

**ENGINEER-012｜迭代不改写过去的证据。** 需求、建筑版本、调查、供应说明或计算方法适用性变化时，识别受影响分析并提出重评范围。
新证据只更新其影响的结论；保留旧结论在当时输入下的记录、已发生工作和费用，不回溯撤销全部事实。
变更请求、原专业错误整改、额外调查和扩大研究范围分别归因；依据委任分配费用和后续义务，不自动全免或新增收费。

**ENGINEER-013｜缺证不是已证明不可行。** 证据不足、方法不适用、超出专业范围和范围内明确冲突采用不同结论，并分别列出可解除条件。
有明确冲突时不能以“待补证”隐藏已知限制；有限研究结束仍可留下未解决事项，是否继续支出由有权委托人决定。
本主体意见、范围内检查、合同成果接受、业主商业选择与行政许可分别存在，不产生一个可覆盖所有效力的“工程师同意”。

仍待细化：首批专业及计算抽象、证据取得和调查耗时、独立复核要求；专业边界不能由示例名称直接确定。

### 4.3 专业服务与资金接口

**资金范围**：平台保留现金、应收应付、贷款与到期义务；服务资金使用[共同对象规则](../02_world/domain_objects.md)。
A10/A11 使用共同账本；专业费率、计费方式、付款期限与争议模板须由委任与模型配置明确。

**ENGINEER-014｜专业工作成本与服务应收分别记录。** 有限前期分析、调查或检查按有效任务记录实际投入，向客户收费依有效委任及计费条件形成。
按工时、里程碑、固定费、预付款或其他方式结算由条款决定，不因技术意见通过就默认满足全部收费条件。
成果提交、客户接受、付款条件满足及到账是独立状态；某些合同有预付款，不把这四项强制成唯一串行流程。
前期 owner_case_id 转项目时保留原任务、投入和义务关联，不重复确认费用，不自动把原委托人债务移给新项目公司或接任主体。

**ENGINEER-015｜专业投入的付款责任独立于客户回款。** 本企业人员报酬、外包分析、调查试验等已建模采购分别登记真实对象及应付/到期事项。
内部专业团队工作可形成组织成本及项目归集，不能生成同一组织对自己的应付；真实人员报酬或外部服务有实际收款对象时另记义务。
同一投入的成本归集、应付余额和现金清偿是不同视图，不能重复相加成三次支出；实际收费也不默认等于实际成本。
客户尚未接受报告或尚未付款，不自动取消已有效发生的外包应付；本企业的借款和偿债按其自身安排记录，不用客户贷款直接充入本企业现金。

**ENGINEER-016｜款项关联、剩余义务和专业退出分别维护。** 每次清偿关联原义务及执行标识，部分付款只冲减对应未清金额，预付款按其有效关联抵扣。
重复收款回执不重复增加现金；结果未知先核对实际执行，不为弥补状态缺失自动重发付款。
专业意见被修订、评估撤销或顾问退出不会删除已形成费用及争议；调整责任或金额须有相应有效依据，不能由技术结论直接推导全部债务。
人员、工具释放依据后续检查/支持义务判断，资金清偿另记；不以欠款永久占用全部资源，也不以全部资源释放宣称义务已清。

### 4.4 专业方法、证据与工作包

依据 [工程类型与有限模板](../02_world/project_types.md) 按工程对象绑定有限模板，衔接相应方案作者；[Architect 参数化方案](architect.md#44-参数化方案与专业接续) 是建筑范围的一条路径，Engineer 也可在授权范围直接编制专业方案。A04—A09/A13 使用明示的专业接口和代表工作包；所支持专业、方法与参数须经配置确定，接口存在不证明真实设计或安全核验完成。

#### 4.4.1 专业请求与方法登记

**ENGINEER-024｜每次专业任务说明编制/检查对象和判断依据。** 绑定同一 `brief_ref`、工程对象/子工程范围、`scope_id`、适用时的 `component_group_id`、`interface_refs[]`、任务/委任版本、请求用途和信息截止点。检查引用 `option_ref=(option_id,option_version)`；新编方案由本次设计任务创建该引用，不伪造前置成果。地区按具体区段引用实际作用地及事项，有关构件另引生产地、使用地和产品证据，不从供应商注册地推定。

| 对象 | 最小字段 | 写入与适用边界 |
|---|---|---|
| 方法登记 | `method_ref=(method_id,version)`、工程对象/专业、`method_kind`、输入类型/单位、几何/结构/场地等适用域、证据要求、计算/判定规则、输出类型、测试依据 | 方法负责人维护；真实资料、场景假设与测试 fixture 分开；只有名称、城市或复杂度分数不算支持 |
| 专业编制/检查任务 | `task_ref`、`engagement_ref`、`function`、模板与输入/输出 `option_ref`、适用的 `check_specs[]`、范围/用途、工作计划、独立性要求 | 本次明确为设计分析、独立审查或合同职能；方案作者不自动具备三者权限 |
| 单项检查定义 | `check_id`、`scope_id`、`question`、`method_ref`、`required_input_refs[]`、必要证据/覆盖范围、适用用途 | 标明为什么需要本项；是否为某用途必要条件不能由检查总分决定 |
| 输入证据 | `evidence_ref`、对象/版本、来源/提供者、观察或试验时点、记录时点、单位、取得方法、可见范围、`basis_kind` | `basis_kind` 区分实测、自报、场景假设及其他有来源资料；缺失不是零 |
| 专业结果 | `assessment_ref=(assessment_id,version)`、作者/职能、任务/方案引用、逐项结果、解释、未覆盖项、`allowed_use`、复核触发 | 工程师维护本次意见，正式方法记录保存数值和可见证据；作者不能改他方原始结果 |
| 数量/工作包依据 | `quantity_basis_ref`、构件组、数量驱动项、计量单位、`method_ref`、专业范围、候选工序/接口 | 交 QS 量取和成本计划、Contractor 判断可建造性；不是已完工程量或施工排期 |

方法登记至少区分资料一致性、简化工程/场景计算、资料审查和现场观察。候选方法可以只核对目录内接口是否相容、必要空间是否在输入边界内；阈值和相容表必须来自明确资料或标明的场景假设，不能由模型临时编出。采用简化方法只得到该方法范围的结论，不得命名为真实设计安全认证。

有限专业方案库按对象限定变量、可选系统/工序、单位与方法依赖，例如道路的区段/断面、桥梁的跨与构件、隧道的区段/断面和施工方法；这些是目录维度，不预定数值或可直接执行算法。楼层面积不作为上述对象的通用输入。超高层按所需专业及高度/结构等适用域逐项核对；普通建筑、桥梁或其他对象方法不能乘一个复杂系数后宣称覆盖。未覆盖可请求适任支持，不用地区标签或联合组织名称补齐。

候选、累计分支/版本、返修与实际研究投入沿本次委任/模板累计，新增目录请求不自动扩范围；具体上限仍待选择。工程师修改自己的专业成果；修改他方方案需发变更/接口请求，由原作者或有权整合者处理，不因担任专业主责而直接改写他方结论。

#### 4.4.2 产生证据、计算结果与主体判断的先后

**ENGINEER-025｜核心检查合法性，不替专业方全知验收。** 任务先取得被授权资料或通过明示观察方法形成可见证据，再运行适用方法，工程师据此解释、提出限制或请求补查。现场观察执行入口可以在内部使用被建模实际状态生成受控观测，但必须经观察方法限定覆盖、误差与可见内容；不得把完整隐藏状态直接给主体或普通报告校验器。

提交校验可以用真实资源、有效权限、对象版本和实际执行记录核对合法性；核对专业意见时只检查其与本次合法可见证据、方法输出和声明范围是否相容。隐藏缺陷不能成为拒绝一份有限检查意见的隐形 oracle；“已提交某意见”表示意见及依据存在，不表示工程实际无缺陷。正式数值结果不可被主体改写，但主体可记录不同解释、请求复核或质疑输入适用性。

每个 `check_id` 保留以下独立维度，不合并为一个 approved：

| 维度 | 建议状态 | 允许的后果 |
|---|---|---|
| 执行状态 | `pending/running/succeeded/technical_failure` | 技术失败不生成实质通过或拒绝；重试沿原执行身份核对 |
| 证据状态 | `sufficient/missing/assumption_based`，附缺项及来源 | 假设可支持明确的研究场景判断，不能变成已核实场址/产品事实 |
| 范围内结果 | `satisfied/conflict/undetermined/out_of_scope` | `satisfied` 仅表示所列方法及输入下满足本项；`conflict` 指出具体规则与证据 |
| 专业意见 | 支持限定选项、要求修订、建议补查、保留不同解释 | 保留逐项结果，不能抹去已知冲突、修改计算值或扩大范围 |
| 用途状态 | 引用独立发布/许可/合同决定及剩余条件 | 专业意见不能替代有权方发布或法定许可，未经授权保持未放行 |

尚未完成/执行失败的检查没有实质结果；缺必需证据的已执行检查可返回 `undetermined`；方法超出适用域返回 `out_of_scope`。不同检查可分别有明确冲突和缺证，不能因其他缺项把已知冲突隐藏为统一“待补”。每个检查的输入是快照引用；后来的数据不回填早期检查。

#### 4.4.3 实际投入、编制完成与工作包输出

**ENGINEER-026｜专业任务完成不取决于得到好结论。** 工作计划为输入核对、方法执行、专业编制、检查/独立复核分别登记工作单元、能力/工具、工作量及其估计方法、单位、任务成果和授权边界。实际投入分片引用执行身份、起止区间、分派和输入版本；暂停恢复只续办未确认部分，共享人员/工具不因生成多个报告而复制容量。

任务的编制完成条件是本次必需工作已执行、要求的输出/缺项说明和追溯信息齐备，且达到委任允许的交付模式。范围内结论为冲突仍可完成一份有效检查报告；方法错误尚未完成分析时不能只靠文字解释标记分析完成。有限缺口报告与完整专业设计有不同成果义务，客户接受和使用授权另行记录。修订、补查或复查有新的工作范围/投入依据，不默认零成本，也不因重发报告重复收费。

**ENGINEER-027｜代表工作包只提供工程依据，不占有施工与计价决定。**

| 输出内容 | 建议字段与形成方法 | 接收方怎样使用 |
|---|---|---|
| 专业系统选择 | `system_option_ref`、工程对象/适用构件组、方案变量、依据/限制、接口要求 | 原方案作者或获授权整合方决定怎样纳入新版；Engineer 可编制自己的专业版本，不直接改他方方案 |
| 数量驱动依据 | `quantity_basis_ref`、输入项、数量公式/换算来源、单位、排除项及未知项 | [QS 工程量与成本计划](qs.md#44-工程量成本计划与方案比较) 形成版本化工程量表，不由设计总分推量 |
| 候选工序分解 | `work_recipe_ref`、构件组、代表 `operation_type`、必要前置/接口、数量驱动引用 | Contractor 另作实际施工方案/排期与资源选择；Supplier 对制造/供货部分独立确认 |
| 复查与变更 | `finding_id/change_ref`、受影响对象、所需处理证据、复查范围及方法 | 实际整改由相应执行方产生；工程师完成复查不能代记施工产出 |

例如一组预制构件可有制造、运输、安装等不同成本/作业环节，它们引用同一构件身份；不能把三个环节相加成三倍建筑物。原位施工部分使用另一相容的代表工序，连接与现场接口仍须检查。是否采用这些工序、生产率和运输条件依项目/供应证据与选定模板，技术标签本身不提供优势系数。只有数量形成方法及输入已受支持时才交具体数量，其他部分交显式未覆盖项。

#### 4.4.4 正常、拒绝与返修的可核对例子

**ENGINEER-028｜方法有可独立复核的输入输出。** 建议先用一个清楚的接口目录方法作测试切片，而非把所有专业压成高低分。测试目录明确只把相同接口代码视为本模型此项相容；这是人为测试规则，不是实物相容或工程规范证据。

正常例：相应方案作者的 `option_ref` 与供方获授权接口资料按方法产生逐项结果；建筑范围可由 Architect 编制，获授权道路/桥梁/隧道专业方案可由相应 Engineer 编制。检查方提交有限报告及数量依据，QS 可估算受覆盖部分，客户另作成果接受。拒绝例：工程师无所需专业或不满足独立性要求，拒绝/转介委任，不伪造专业失败。返修例：方法识别接口冲突，原作者修订对应版本；新检查只复查受影响及必要关联范围，旧证据和费用保留。

### 4.5 地区适用与证据边界

本角色只研究大湾区范围内的专业系统、方法与检查范围；场景明确项目地区、事项、适用时间和证据来源，不从“大湾区”标签推导统一资格、技术要求或合同权限。
组织登记地、实际服务地、项目所在地及产品生产地分别引用；跨地区经验不自动证明本次任务的资格、数据或方法适用。
规范条款、供应资料、观测数据与模型假设分别登记。尚未取得依据的阈值和条件保留未知，不从不适用地区的参考流程或无来源常数补齐。
本文件中的代表方案和算术例子用于检查模型接口；未选定的方法不得产生技术通过，未覆盖的专业不声称真实设计安全。

## 5. 状态转换、失败与恢复

### 5.1 提交、版本与持续约束

**ENGINEER-005｜结果可追溯且适用范围有限。** 分析引用输入、方法与参数版本，检查引用被检对象和证据；模拟结果只在所建模边界内成立。
资料自报、实际检查发现与潜在未发现问题分别保存，智能体不提前知道隐藏缺陷；发现机制、检查强度及误差需明示。
最新草稿不覆盖仍适用的已发布版本；变更通过依赖关系识别受影响的分析、检查、施工和许可范围。

**ENGINEER-006｜必要能力不能由通用分数补足。** 不同专业人员、工具与时间窗口按所选粒度表达，跨项目分配在提交前复核。
本人任务已占用资源时，续办应延续有效分派；不能重复占额，也不能因自己占用而拒绝续办。
无调查、试验、现场准入或复查证据时明确等待对象；任务耗时不由模型响应秒数推算。

**ENGINEER-007｜核证、建议与付款分开。** 只有受委任且具备相应权限时，本主体才可作合同核证或有约束力指令；其效力须使用独立事项记录。
返工原因、责任、工作指令、费用主张和有效决定分别保存，不因技术问题存在就自动把全部费用分配给某一方。
技术失败保留待处理状态；专业不通过、合同违约和行政拒绝不能互相代替。

### 5.2 对象转换与剩余责任

**ENGINEER-020｜状态变化依赖可核查证据。** 技术分析有效、实际工程状态、检查发现和行政许可是不同状态，不能互相覆盖。

| 对象与转换 | 必要条件 | 保留事项 |
|---|---|---|
| 拟委任 → 有效职能 | 相容接受、适用资格/授权及独立性检查 | 超范围事项不随同生效 |
| 分析待输入 → 可执行 → 结果形成 | 必需资料、适用方法、人员/工具及真实投入 | 假设、方法错误或未覆盖范围 |
| 分析结果 → 专业检查/发布 | 指定范围的核查及必要签署/用途权限 | 数值成功不等于现实安全证明 |
| 检查已计划 → 已实施 | 实际准入、人员、窗口和观察/试验证据 | 未能接触或未检部位仍未知 |
| 问题发现 → 待处置 → 待复查 | 有权处理方向及实际整改/补证到达 | 提交计划不能代替整改发生 |
| 待复查 → 范围关闭/仍开放 | 适用方法及获授权复查结果 | 新发现可另关联，原历史不删 |
| 技术变更 → 依赖复核 → 新用途状态 | 原/新版本、受影响分析/施工/许可范围 | 不受影响的有效结果可以保留 |
| 服务停止 → 已移交/残余义务 → 范围关闭 | 有效结束依据、资料接收与剩余事项清单 | 债务、历史作者与未尽责任继续存在 |

**ENGINEER-021｜问题的处理与责任判断分开。** 发现缺陷时先记录可观察证据和受影响工作；处理选项、施工执行、费用归责及合同责任通过各自有权流程完成。
安全或质量风险可触发通知和获授权的临时控制；未赋予停工/保护指令权时应向有权方升级，不虚构全项目指挥权。具体触发和时限待模板选择。

**ENGINEER-022｜检查存在信息边界。** 检查计划明确覆盖范围、观察方式和投入，实际是否发现问题由对应证据/受控机制决定，不直接读取全部潜在缺陷。
抽查结论不得扩展为全体构件完美；已知发现不能因平均质量分提高而自动关闭，复查仍有独立任务和证据。

检查引用 OBJ-022 的独立观察方法：登记实际检查任务/范围、投入、方法与结果，不直接修改真实缺陷。减少检查只改变证据取得过程；对真实发生率的影响需另有生成机制依据。同次检查重试复用原结果，新的复查须有新任务和投入。检查意见、真实修复、合同接受和法定使用仍分别核对，见[质量方法链](../02_world/domain_objects.md#工程转换与质量状态的方法链)。

**ENGINEER-023｜专业退出留下可执行的责任清单。** 移交分析方法/输入引用、当前有效成果、未检和未复查范围及合法使用权，接任者独立确认核查范围。
顾问结束本次现场任务不等于调试或缺陷义务结束；召回按真实人员与工具安排，不以保持义务为由永久占满全部资源。

### 5.3 正常路径与失败恢复

**成功：有权委托的专项设计、独立复核及施工支持。** 以下假定所选模板要求独立复核，且相关专业方法已被模型支持。
1. 设计方通过 A02/A03 接受专项委任，A04 获取授权调查并安排投入，A05 编制专业成果和方法引用。
2. 满足独立性条件的审查方依据自己的委任作 A06，提出具体接口问题；它不代设计方修改原成果。
3. 原设计方修订，审查方核对所涉范围并形成结论；各有权主体按 A07 完成相应用途提交/发布。
4. 现场阶段 A08 按实际检查任务取得证据，A09 将出现的问题交执行方处理并复查；调试/复查结论不替代使用许可。
5. A10 按各自合同核对服务费，A11 分别释放任务资源并移交剩余义务；A12 仅从各自可见反馈更新判断。

**失败恢复：试验结果与原假设冲突。**
1. A08 取得不支持原假设的试验记录，登记发现和受影响范围；未观察的同类构件仍保持其真实核验状态。
2. A09 请求处理方向及必要补查；是否需要暂缓某工作包由具有相应权限者决定，不直接改全项目状态。
3. 设计方 A05 在授权内重算/修订；若仅原方法不适用，明确该限制，不以换一个分数声明合格。
4. 执行方提供实际整改/补证，审查/检查方在可用窗口安排复查；人员不可用则记录待办及调整，不强行即时完成。
5. 复查通过只关闭覆盖的问题；仍不通过则保留处理循环或有效终止/移交，费用及历史责任继续存在。

## 6. 验收场景

下列场景规定实现应满足的结果，须以实际检查记录判定是否通过。流程一致性、真实决策行为、方法校准和现实工程或制度验证分别报告；示意数据不作为真实项目参数。

### 6.1 全生命周期边界

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-ENGINEER-001 | 只需前期地质/结构可行性意见 | 允许有限委任，不要求完整设计与正式项目先成立 |
| CHECK-ENGINEER-002 | 结构专业被要求签署未覆盖机电事项 | 不默认跨专业通过，说明缺项并请求适任支持 |
| CHECK-ENGINEER-003 | 顾问拒绝或技术失败仍残留接受字段 | 不形成有效委任或正式投入 |
| CHECK-ENGINEER-004 | 模板要求独立复核，作者兼任检查者 | 识别不符合条件，不能称为独立复核完成 |
| CHECK-ENGINEER-005 | 同一专业人员同时被两项目占满 | 提交阶段发现冲突，不复制人员 |
| CHECK-ENGINEER-006 | 本人占用资源后下一期继续原任务 | 延续有效占用，不重复扣资源或无故拒绝续办 |
| CHECK-ENGINEER-007 | 必要调查数据未知 | 保留假设/未知与补查任务，不编实测数据 |
| CHECK-ENGINEER-008 | 一次 LLM 返回高可信技术结论 | 仍检查方法、数据、投入和成果范围 |
| CHECK-ENGINEER-009 | 潜在缺陷尚未被发现 | 不提前向主体透露；检查通过不宣称零缺陷 |
| CHECK-ENGINEER-010 | 建筑版本变化影响部分分析 | 复核对应范围，不自动通过或清零全部成果 |
| CHECK-ENGINEER-011 | 本主体有检查权但无付款核证权 | 可交检查意见，不能提交正式付款核证或扣款 |
| CHECK-ENGINEER-012 | 银行收到专业报告 | 不自动提款，报告仍保留版本和限制 |
| CHECK-ENGINEER-013 | 调试通过但尚无所需使用许可 | 不产生行政批准或实际使用放行 |
| CHECK-ENGINEER-014 | 技术整改有义务但费用存在争议 | 按有效工作义务处理，费用争议另记 |
| CHECK-ENGINEER-015 | 内部专业团队工作 | 记录内部成本，不产生对自己的外部服务费 |
| CHECK-ENGINEER-016 | 项目结束仍有工程师参与占用 | 按明细释放可释放部分，保留未结责任 |
| CHECK-ENGINEER-017 | 接任另一家工程顾问 | 保留原作者和结论，接任有核查投入与权限 |
| CHECK-ENGINEER-018 | 重复提交检查或收款事件 | 不重复耗时、收费、关闭问题或增加现金 |

### 6.2 前期研究

| 业务验收 | 场景 | 预期 |
|---|---|---|
| CHECK-ENGINEER-019 | 只有地区资料但方案需要具体地质条件 | 明确场址假设及调查缺口，不伪造实测条件 |
| CHECK-ENGINEER-020 | 一个专业具备输入，另一专业缺证 | 可推进独立部分，整体结论保留未覆盖范围 |
| CHECK-ENGINEER-021 | 供应商自报性能满足要求 | 记录来源与核验状态，不当成工程师已验证证据 |
| CHECK-ENGINEER-022 | 支持的方法返回成功但关键输入有假设 | 保留假设和适用范围，不宣称真实安全已证明 |
| CHECK-ENGINEER-023 | 混合方案的两个系统分别通过但接口冲突 | 保留接口问题，不自动得出整体可行 |
| CHECK-ENGINEER-024 | QS 与工程师使用不同选项版本 | 先对齐版本和范围，不按平均得分消除分歧 |
| CHECK-ENGINEER-025 | 商业优选方案缺少必要技术检查 | 不自动补为技术通过，指出下一任务及限制 |
| CHECK-ENGINEER-026 | 新调查只影响某一系统分析 | 复核受影响部分，保留其他有效成果与历史证据 |
| CHECK-ENGINEER-027 | 限额研究结束仍无适用计算方法 | 返回方法限制及后续选择，不编造通过结果或无限投入 |
| CHECK-ENGINEER-028 | 同一问题分别为证据不足与已知冲突 | 输出不同状态和解除条件，不混同为统一拒绝 |

### 6.3 服务资金

| 业务验收 | 场景 | 预期 |
|---|---|---|
| CHECK-ENGINEER-029 | 技术意见通过但合同收费条件未满足 | 保存专业结果与成本，不自动形成到期应收或现金 |
| CHECK-ENGINEER-030 | 前期研究转正式项目且委托关系拟变更 | 原义务不重复计费，债务人变更需独立有效依据 |
| CHECK-ENGINEER-031 | 内部工程团队使用本组织人员 | 只作适当成本归集；真实报酬义务有独立对象，不作自我应付 |
| CHECK-ENGINEER-032 | 外包试验费已到期但客户尚未回款 | 保留独立付款责任，记录现金约束，不把应收当到账 |
| CHECK-ENGINEER-033 | 合同允许分析任务开始前预付款 | 单独记录预付/预收与后续抵扣关联，不强制等待专业通过 |
| CHECK-ENGINEER-034 | 同一部分收款回执重复到达 | 只首次计入现金及对应清偿，保留剩余未清金额 |
| CHECK-ENGINEER-035 | 原分析结果修订且费用责任存在争议 | 保留原任务、费用和争议，按有效依据调整而非自动清零 |
| CHECK-ENGINEER-036 | 退出并释放人员后仍有欠款和复查义务 | 资金与专业义务分别保留，资源安排与清偿不互相代替 |

### 6.4 经营与恢复

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-ENGINEER-037 | 设计方更换 agent_id 后申请充当独立审查方 | 按真实关系与模板核验独立性，不凭 ID 区别放行 |
| CHECK-ENGINEER-038 | 只有设计委任却发合同核证或停工指令 | 阻止越权提交，允许范围内报告和转介 |
| CHECK-ENGINEER-039 | 检查已排程但没有现场准入 | 不生成已实施检查或现场发现证据 |
| CHECK-ENGINEER-040 | 抽查部分通过且隐藏位置仍有未知状态 | 不把局部结果推广为全部合格或零缺陷 |
| CHECK-ENGINEER-041 | 施工方只提交整改计划 | 问题进入待处理，不当作整改完成或复查通过 |
| CHECK-ENGINEER-042 | 不同专业分别通过但系统接口未核对 | 保留接口待办，不生成全项目技术批准 |
| CHECK-ENGINEER-043 | 新订单与已有复查义务竞争同一设备 | 按实际排期处理，不静默丢弃复查或复制设备 |
| CHECK-ENGINEER-044 | 服务交接后发现旧分析依赖缺失 | 接任方可限结论、补查或拒绝新增范围，不能默认继承验证 |

### 6.5 专业方法与接口

| 编号 | 输入/事件 | 可独立核对的预期 |
|---|---|---|
| CHECK-ENGINEER-045 | 测试规则为代码相等；双方代码均 A，资料及方法适用 | 本项为 `satisfied`，只说明测试接口一致，不生成结构安全/许可结论 |
| CHECK-ENGINEER-046 | 同一规则下双方为 A 与 B | 本项为 `conflict`，指出对象和依据；不能平均其他分数后通过 |
| CHECK-ENGINEER-047 | 一方代码缺失，另有独立检查已知冲突 | 前项 `undetermined` 并列缺项，后项仍保留冲突 |
| CHECK-ENGINEER-048 | 请求用上述接口方法证明未覆盖的结构承载力 | 返回 `out_of_scope`，无虚构承载力数值和通过结论 |
| CHECK-ENGINEER-049 | 未被当前观察发现的隐藏缺陷存在 | 不泄漏真值或自动拒绝有限报告；后续实际发现才形成新的可见证据 |
| CHECK-ENGINEER-050 | 报告结论为冲突，但编制工作和约定交付均完成 | 报告可完成提交，客户接受与后续用途仍独立；不抹除实际投入 |
| CHECK-ENGINEER-051 | 修改一项接口后提交 V2 请求 | 原 V1 结果保留，V2 依影响范围复查；技术失败不冒充 V2 已通过 |
| CHECK-ENGINEER-052 | 方法执行响应未知或重复，随后收到同一有效结果 | 先核对原执行；证据/结果/投入不重复，不凭重复次数增加可信度 |
| CHECK-ENGINEER-053 | 已委任道路专业设计，仅有需求/调查且无 Architect 方案 | 输入和方法充分时可编制自身方案；独立复核另核权限，不强制造一个建筑成果 |
| CHECK-ENGINEER-054 | 普通结构方法被请求证明未覆盖的超高层或桥梁性能 | 返回不支持/待专项输入；地区经验、组织联合和复杂度分数不能代替适用方法 |
| CHECK-ENGINEER-055 | 跨区复合项目同时有桥梁、道路及附属建筑 | 各范围分别绑定作者、方法和适用地点；接口有跟进者，任一专业通过不变成全项目批准 |

### 6.6 分支输入与业务任务交接

| 编号 | 契约场景 | 预期 |
|---|---|---|
| CHECK-ENGINEER-056 | A09 提出尚未获授权的补查/整改工作 | 输出 TaskRequest，不假定已创建 Task 或已消耗工程资源 |
| CHECK-ENGINEER-057 | A13 没有方案或成功分析，仍需交限额报告 | 可围绕 Brief 报告未知/未覆盖；不补出至少一个通过结论 |
| CHECK-ENGINEER-058 | A07 只有成果提交权，没有签署和发布依据 | submit 可形成提交；sign/release_for_use 拒绝，不能把提交成功当许可 |
| CHECK-ENGINEER-059 | A08 无入场权但获准读取资料并答复远程查询 | 允许范围内资料答复；不登记到场检查、观测或发现隐藏缺陷 |

## 7. 参数、方法与配置依赖

需要配置的范围如下，不能用通用能力分代替专业支持。

- **工程方法**：所支持专业及对象范围、真实资料与情景方法、输入适用性、分析/检查/发现方法、观察误差和证据取得机制。
- **委任与权限**：资格、独立性判定、签署要求、合同工程师职能、接续与残余支持范围；编制者、独立审查者和合同工程师的权限分别绑定。
- **时间、投入与资金**：人员/工具粒度、任务工作量与耗时方法、资源时间单位、专业费率、计费条件、付款期限和争议模板；具体配置遵循 D-02—D-07、D-09—D-11 的适用选择。

接口验收只能证明按指定方法和规则处理，不能证明未建模专业已被覆盖，也不能替代真实工程设计与安全验证。

未选定的方法、阈值、时间粒度、资格和产品条件须显式保持待定；不得以示例值、角色标签或未覆盖范围补成正式结论。具体选择登记在[模型决策](../07_experiments/model_decisions.md)，使用前绑定方法、数据和参数版本。
