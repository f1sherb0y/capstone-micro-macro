# Architect：建筑方案、设计整合与持续服务

定义建筑设计主体在大湾区仿真中的业务承接、有限方案、设计整合、施工支持与服务收尾行为。本文是角色开发规范；方法支持范围和待选参数见第 7 节，实现与验证证据单独记录。

[总体运行框架](../02_world/world_runtime.md) · [共同对象与状态](../02_world/domain_objects.md) · [跨主体交接](../03_projects/collaboration_flow.md) · [模型决策](../07_experiments/model_decisions.md)

<!-- page-nav:start -->
**本页导航**

[1. 职责、目标与权限](#1-职责目标与权限) · [2. 信息、状态与业务对象](#2-信息状态与业务对象) · [3. 行为卡与执行契约](#3-行为卡与执行契约)

[4. 专业工作与跨主体交互](#4-专业工作与跨主体交互) · [5. 状态转换、失败与恢复](#5-状态转换失败与恢复) · [6. 验收场景](#6-验收场景)

[7. 参数、方法与配置依赖](#7-参数方法与配置依赖)
<!-- page-nav:end -->

## 1. 职责、目标与权限

### 1.1 主体身份与授权

**ARCHITECT-001｜独立服务主体。** 每个 agent_id 表示具体组织或经明确建模的组织单元，独立保有能力、资源、委任、经营状态和认知。
目标可以包括服务收益、设计质量、履约可靠性、专业声誉和长期客户关系；权重及判断方法待定，不默认最大化接单数量。
角色说明能力类别，不自动赋予真实注册身份、所有专业设计能力或项目总负责人权限。

**ARCHITECT-002｜职责随委任确定。** 每项服务明确委托人、付费人、成果接收人、编制/整合范围、审查与发布权限。
传统与设计建造模式下的聘用关系可以不同；模式标签变化不自动转移本主体的合同、人员、费用或历史责任。
业主顾问和承包商设计团队可以并存；本主体只能使用自己实际取得的授权与资料。
组织内部团队可依据内部任务授权工作，记录投入成本；不因此虚构组织对自己的外部服务费。

工程对象与模板目录见 [工程类型与有限模板](../02_world/project_types.md)。本主体承担获委任的建筑空间/功能设计或具体接口，不能因项目中有建筑物就自动取得整个道路、桥梁、隧道或复合项目的方案主责。编制、专业主责与整合分别按子工程/范围绑定；基础设施附属建筑也只形成对应建筑范围，不强制所有专业先经 Architect。

**ARCHITECT-003｜设计选择与工程事实分开。** 本主体可提出方案、解释取舍及指出问题；工程结果、合同、许可与资源由相应正式入口维护。
可表达结构化方案、空间/功能要求、接口和检查项；未建模的完整施工图、BIM 或专业分析不得宣称已经完成。

### 1.2 独立判断与经营取舍

**ARCHITECT-017｜接单与履约具有真实取舍。** 本主体依据自己可见的工作量、收费、回款风险、专业责任和排期决定，而非以业主满意或项目数增加为唯一目标。

| 冲突 | 可作的选择 | 仍须遵守的边界 |
|---|---|---|
| 新业务收益与既有项目期限冲突 | 少接、分阶段承接、调整报价/期限、寻找获准协作或拒绝 | 已有承诺不能被新订单自动挤走，协作不凭空增加人员 |
| 功能质量与客户预算/交期冲突 | 提交范围调整和不同选项，说明未满足项 | 不以低价或关系偏好消除已知专业问题 |
| 推进设计与等待关键资料冲突 | 推进独立部分，限定假设研究，或等待特定输入 | 研究假设不成为可施工证据，等待不算有效设计产出 |
| 现金紧张与后续服务义务冲突 | 催收、协商、调整合法新增投入或依权利暂停 | 欠费不自动撤销已发布成果，也不自动解除既有责任 |
| 重复利用既有方案与新项目适配冲突 | 复用有权使用部分，并安排差异核查 | 不能复制其他客户私密资料或把适配成本默认为零 |

## 2. 信息、状态与业务对象

### 2.1 可见信息与权限边界

| 信息或状态 | 本主体需要保存/读取 | 边界 |
|---|---|---|
| 自身能力 | 支持的建筑对象/用途、设计方法及适用范围、目的地事项经验、实际服务单元/人员工具、资格与证据状态 | 注册地不是能力，地区经验不是资格；超高层等超出方法适用域时不能由通用评分补足 |
| 业务机会 | 可见邀请、公开需求、自主发现且有来源的线索 | 看到机会不等于取得委任 |
| 服务关系 | 委任/内部授权、范围、收费、成果和变更条件 | 只对有效范围承诺和行动 |
| 资源排期 | 人员能力、项目占用、预留、待命及后续义务 | 跨项目共享实际容量 |
| 需求与场地 | 功能、使用者要求、场地资料及来源 | 未调查部分保留未知 |
| 专业输入 | 获准取得的工程分析、成本意见和生产约束 | 不读取其他主体的私有记忆 |
| 设计成果 | 自己编制的版本、引用、审查、发布与使用记录 | 最新草稿不等于当前可施工版 |
| 问题与认知 | 收到的异议、接口冲突、评价及学习记录 | 主观信任不覆盖正式事实 |
| 资金与责任 | 内部成本、服务费申报、应收和未清义务 | 他人认可方案不等于付款 |

**ARCHITECT-004｜权限到动作和范围。** 编制、整合、专业检查、合同接受、用途发布及法定签署分别登记；缺少某项权限只阻止依赖它的动作。
本主体没有默认的付款核证、行政批准或调整业主投资预算权限；兼任职能也须有明确授权与冲突处理规则。
公开政策、预计变化与已经生效的要求分开；不把未来政策提前作为当前许可事实。

### 2.2 正式状态与私有判断的所有者

**ARCHITECT-018｜主体判断不直接改正式台账。** 本主体持有自己的意图和认知；有效委任、任务投入、成果发布、问题状态和现金由核心相应入口维护。

| 状态 | 权威维护入口 | 本主体可做什么 | 不得混同 |
|---|---|---|---|
| 客户吸引力、报价底线、风险判断 | 本主体私有认知记录 | 修改判断并保留依据 | 私有估计不是客户信用事实或公开报价 |
| 服务范围、职能和有效变更 | 合同/任务授权入口 | 提出并有效接受本方条款 | 对方邀请不是委任，整合职能不是默认权力 |
| 人员排期、投入、待命和释放 | 统一资源/任务入口 | 申请分配与调整 | 排班意图不是已取得容量 |
| 建筑成果、检查与用途发布 | 成果及有权发布入口 | 编制、提交、获授权检查/发布 | 作者完成、客户接收、许可与施工可用分别存在 |
| 查询、接口冲突及处理证据 | 问题/变更事项入口 | 提出、回应、申请复核 | 回复发送不自动关闭问题 |
| 费用、收付及剩余义务 | 共同资金/义务入口 | 申报、核对及按授权执行 | 收入预期不充当现金，退出不清除历史义务 |

### 2.3 关键对象及字段

**ARCHITECT-019｜每项工作可追踪到服务范围和具体成果。** 采用以下语义对象，复用共同合同、任务、成果和事项，而非新增彼此不一致的正式状态。

| 对象 | 身份与版本字段 | 关键内容 |
|---|---|---|
| 服务委任/内部授权 | `engagement_id`、条款/授权版本、职能引用 | 委托人、付款人、范围、交付清单、费用、授权及结束条件 |
| 设计任务 | `task_id`、`engagement_id`、范围/输入版本 | 工作包、责任人、前置输入、投入、完成标准、暂停原因和下一触发 |
| 建筑成果 | `deliverable_id/version`、作者、需求/专业引用 | 编制范围、成熟度、已检查部分、问题、允许用途与发布依据 |
| 接口/现场查询 | `issue_id`、对象及版本、关联指令 | 提出者、受影响部位、需回应方、限制、答复、验证与关闭依据 |
| 变更影响记录 | `change_id/version`、原/新成果引用 | 受影响设计、许可/采购/施工依赖、工作量及费用责任待决项 |
| 服务收尾包 | `handover_id/version`、服务/任务引用 | 当前有效成果、未决问题、使用权限、后续支持、费用和移交接收记录 |

## 3. 行为卡与执行契约

行为卡先说明触发、选择、正式后果及等待/失败，再定义函数、具名输入、输出分支、接收者和验收。执行矩阵汇总资源与交接。卡内“正式结果”指相应命令成功提交后的效果；`ActionResult.completed` 只表示本主体输出已形成。

<!-- action-nav:start -->
**动作定位**：[ARCHITECT-A01](#architect-a01--发现业务并选择是否研究) · [ARCHITECT-A02](#architect-a02--独立判断接单并提出条件) · [ARCHITECT-A03](#architect-a03--确认委任范围并承接任务) · [ARCHITECT-A04](#architect-a04--安排设计人员和实际任务) · [ARCHITECT-A05](#architect-a05--编制和比较建筑方案) · [ARCHITECT-A06](#architect-a06--整合授权范围内的专业接口) · [ARCHITECT-A07](#architect-a07--提交成果并申请相应用途审查) · [ARCHITECT-A08](#architect-a08--审查建筑成果或回应审查意见) · [ARCHITECT-A09](#architect-a09--处理变更与施工阶段设计支持) · [ARCHITECT-A10](#architect-a10--申报服务费并处理应收) · [ARCHITECT-A11](#architect-a11--暂停召回交接与退出) · [ARCHITECT-A12](#architect-a12--更新经营判断与设计经验) · [ARCHITECT-A13](#architect-a13--承接有限前期方案比较)
<!-- action-nav:end -->

### ARCHITECT-A01 · 发现业务并选择是否研究

- **触发与输入**：收到邀请或取得可见需求，读取自身专业方向、经营目标、排期和研究支出权限。
- **自主选择**：忽略、跟踪、申请澄清、开展有限投标准备或表达兴趣；允许选择不参与。
- **正式结果**：记录本主体的机会评估与有效准备任务；不改变共享机会或其他企业的选择。
- **等待与失败**：来源、委托权限或需求不清时保留问题；营销文字不会自动增加能力、收入或合作关系。

**函数与类型契约**

- **函数**：`roles.architect.a01(ctx: ActionContext, input: ArchitectA01Input) -> ActionResult<ArchitectA01Payload>`。
- **输入记录**：`ArchitectA01Input = {scope:ScopeRef; opportunity_ref:Ref<Opportunity>; strategy_ref:Ref<Strategy>; capacity_ref:Ref<ResourceCalendar>; preparation_authority_ref:Option<Ref<Authority>>}`。来源：邀请/市场来源登记、主体自己的策略和排期；准备权限来自组织授权。
- **输出分支**：`ArchitectA01Payload` 的 `choice` 与分支必填字段为：`ignore{reason:string}; track{watch_condition_ref:Ref<Trigger>}; express_interest{recipient_id:EntityId<Agent>,scope:ScopeRef}; prepare{request:ArchitectTaskRequest}; clarify{questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：兴趣/问题交邀请方；准备计划交任务服务；只可登记机会处理及获授权准备任务，不创建委任。
- **业务出口与验收**：来源未知请求资料，未授权准备不得投入；CHECK-ARCHITECT-001、CHECK-ARCHITECT-035。

### ARCHITECT-A02 · 独立判断接单并提出条件

- **触发与输入**：服务范围、成果用途、责任、费用安排、地区资格和自身可用资源足以评估。
- **自主选择**：接受当前条件、提出范围/排期/费用方案、请求澄清、暂缓或拒绝。
- **正式结果**：带版本和有效期的服务方案/接受记录；如有预留，注明强度、窗口与释放条件。
- **等待与失败**：无能力或容量时不假接单；模型调用失败不等于商业拒绝，建议中的接受数据也不代表最终接受。

**函数与类型契约**

- **函数**：`roles.architect.a02(ctx: ActionContext, input: ArchitectA02Input) -> ActionResult<ArchitectA02Payload>`。
- **输入记录**：`ArchitectA02Input = {scope:ScopeRef; request_ref:Ref<ServiceRequest>; terms_ref:Ref<ServiceTerms>; capability_ref:Ref<Capability>; capacity_ref:Ref<ResourceCalendar>; price_basis_ref:Ref<FeeBasis>}`。来源：委托方提供请求和条款；本组织提供能力/排期；费率依据来自有权资料。
- **输出分支**：`ArchitectA02Payload` 的 `choice` 与分支必填字段为：`accept{accepted_terms_ref:Ref<ServiceTerms>}; counteroffer{offer:ArchitectServiceOffer}; decline{reason:string}; clarify{questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交实际委托方及委任服务；只登记本方选择或报价，双方相容后才能委任；不自动占用正式容量。
- **业务出口与验收**：商业延期用deferred并列恢复条件；模型故障不能转decline；CHECK-ARCHITECT-002、CHECK-ARCHITECT-003。

### ARCHITECT-A03 · 确认委任范围并承接任务

- **触发与输入**：收到与本主体有效接受相容的委任结果，复核委托人、范围、报价版本和资源状态。
- **自身行为**：确认有效条件、明确编制与整合职责，要求修订不相容条款；内部团队核对组织任务授权。
- **正式结果**：由核心登记有效服务关系和本主体承诺，关联评估档案或项目，不要求先有完整项目团队。
- **等待与失败**：对方选择了本主体但自己未接受时不启动外部委任；重复接受不再新增合同或重复占额。

**函数与类型契约**

- **函数**：`roles.architect.a03(ctx: ActionContext, input: ArchitectA03Input) -> ActionResult<ArchitectA03Payload>`。
- **输入记录**：`ArchitectA03Input = {scope:ScopeRef; appointment_ref:Ref<Appointment>; accepted_terms_ref:Ref<ServiceTerms>; function_refs:List<Ref<FunctionAssignment>>; existing_reservation_ref:Option<Ref<ResourceReservation>>}`。来源：委托方委任记录、本方已提交接受记录、授权及资源预留。
- **输出分支**：`ArchitectA03Payload` 的 `choice` 与分支必填字段为：`confirm{appointment_ref:Ref<Appointment>,accepted_terms_ref:Ref<ServiceTerms>}; request_amendment{questions:List<ArchitectQuestion>}; decline_incompatible{reason:string}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交委任/任务服务后到A04；相容性检查后形成服务关系及预留转换；不能用对方选择替代本方接受。
- **业务出口与验收**：过期/不相容条款返回修订请求；重复确认沿原委任核对；CHECK-ARCHITECT-003、CHECK-ARCHITECT-034。

### ARCHITECT-A04 · 安排设计人员和实际任务

- **触发与输入**：有效任务、前置资料、工作量/耗时依据、期限和跨项目共享排期。
- **自主选择**：分配适任人员、排序、并行无依赖工作、请求资料或提出调整安排。
- **正式结果**：任务投入、等待、完成及对应内部成本按统一规则提交；原预留转换为占用而非重复累计。
- **等待与失败**：缺资料或人员时仅阻塞依赖任务；不能用一次回复或能力分上升代替真实任务投入。

**函数与类型契约**

- **函数**：`roles.architect.a04(ctx: ActionContext, input: ArchitectA04Input) -> ActionResult<ArchitectA04Payload>`。
- **输入记录**：`ArchitectA04Input = {scope:ScopeRef; task_refs:List<Ref<Task>>; dependency_refs:List<Ref<Deliverable>>; work_profile_ref:Ref<WorkProfile>; capacity_ref:Ref<ResourceCalendar>; existing_allocation_refs:List<Ref<ResourceAllocation>>}`。来源：核心任务/投入记录和排期、获授权成果；工作量依据来自已选工作方法。
- **输出分支**：`ArchitectA04Payload` 的 `choice` 与分支必填字段为：`allocate{plan:ArchitectTaskPlan}; revise_plan{plan:ArchitectTaskPlan,prior_plan_ref:Ref<WorkPlan>}; request_inputs{questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交资源/任务服务，再交A05/A13；计划确认后才分派，实际投入由执行器另记；本输出不宣称任务完成。
- **业务出口与验收**：无容量deferred，工作方法未支持unsupported；CHECK-ARCHITECT-004、CHECK-ARCHITECT-038、CHECK-ARCHITECT-048。

### ARCHITECT-A05 · 编制和比较建筑方案

- **触发与输入**：获授权的建筑对象/子工程范围、需求、场地、使用目标、投资边界、设计模板和可用专业输入；按本阶段成熟度组织工作。
- **自主选择**：在允许变量内提出或比较功能、空间、系统接口和建造方式选项，说明取舍与未决问题。
- **正式结果**：形成建筑方案版本、假设、范围、备选关系及依据；数值由支持的计算或情景假设产生。
- **等待与失败**：需求矛盾可请求确认或调整；本主体不得替业主改变投资目标，也不补造未知场地条件。

**函数与类型契约**

- **函数**：`roles.architect.a05(ctx: ActionContext, input: ArchitectA05Input) -> ActionResult<ArchitectA05Payload>`。
- **输入记录**：`ArchitectA05Input = {scope:ScopeRef; brief_ref:Ref<Brief>; task_ref:Ref<Task>; design_profile_ref:Ref<DesignProfile>; basis_refs:List<Ref<Evidence>>; prior_option_ref:Option<Ref<DesignOption>>; method_result_refs:List<Ref<MethodResult>>; available_option_refs:List<Ref<DesignOption>>; professional_refs:List<Ref<Assessment>>; cost_refs:List<Ref<CostPlan>>; comparison_scope_ref:Option<Ref<ComparisonScope>>; comparison_method_ref:Option<Ref<ComparisonMethod>>}`。来源：Owner简报、自己已授权任务、有限设计目录、专业/场地证据及方法服务输出。
- **输出分支**：`ArchitectA05Payload` 的 `choice` 与分支必填字段为：`produce{options:List<ArchitectOptionDraft>}; compare{comparison:ArchitectComparison}; request_inputs{questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`produce` 消费需求、目录和本次真实工作/方法结果，不能要求先有本次方案；`compare` 只比较输入已登记选项，须有比较范围；`available_option_refs=[]` 允许编制首个方案或请求资料。比较方法为空表示尚未取得适用方法，此时不得输出推荐或排名；新方案先保存取得 Ref 后才纳入跨方案比较。
- **接收与核心效果**：交成果服务形成作者版本，再交A06/Engineer/QS；只新增建筑方案，不改Owner目标、许可或工程真值。
- **业务出口与验收**：produce的options非空且不超委任额度；无可用方案可交有限比较；未覆盖方法unsupported；CHECK-ARCHITECT-042、CHECK-ARCHITECT-043、CHECK-ARCHITECT-051、CHECK-ARCHITECT-052。

### ARCHITECT-A06 · 整合授权范围内的专业接口

- **触发与输入**：取得相关工程、成本或制造资料，发现空间、系统、预算或可建造性接口问题。
- **自主选择**：提出协调问题、比较兼容选项、请求专业输入或向有权委托人升级不可兼容要求。
- **正式结果**：问题 ID、影响范围、本主体处理任务、接口引用与整合版本；整合权限仅限委任范围。
- **等待与失败**：会议结束不自动关闭问题；不覆盖 Engineer 的结论，也不把其他顾问未回复解释为同意。

**函数与类型契约**

- **函数**：`roles.architect.a06(ctx: ActionContext, input: ArchitectA06Input) -> ActionResult<ArchitectA06Payload>`。
- **输入记录**：`ArchitectA06Input = {scope:ScopeRef; option_ref:Ref<DesignOption>; professional_refs:List<Ref<Assessment>>; cost_refs:List<Ref<CostPlan>>; supply_refs:List<Ref<SupplyAdvice>>; integration_authority_ref:Option<Ref<Authority>>; open_issue_refs:List<Ref<Issue>>}`。来源：获授权专业、造价、供应输出与本方整合职能；不得读取他人私有判断。
- **输出分支**：`ArchitectA06Payload` 的 `choice` 与分支必填字段为：`raise_interfaces{issues:List<ArchitectQuestion>}; integrate{draft:ArchitectIntegration}; escalate{issue_refs:List<Ref<Issue>>,recipient_id:EntityId<Agent>,reason:string}; request_inputs{questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：问题交原作者/有权协调人；整合草稿交成果服务；保留各作者结论，问题关闭仍需复核入口。
- **业务出口与验收**：缺整合权只报告或升级；无回复不是同意；CHECK-ARCHITECT-009、CHECK-ARCHITECT-021、CHECK-ARCHITECT-036。

### ARCHITECT-A07 · 提交成果并申请相应用途审查

- **触发与输入**：本次任务达到编制标准，检查成果内容、依赖版本、允许接收者和预定用途。
- **自身行为**：提交研究、估算、报审、采购或施工所需版本，声明适用范围和未完成事项。
- **正式结果**：形成不可混淆的提交及可见记录；仅在本主体另有发布权且条件满足时提交用途放行。
- **等待与失败**：自己声明完成不等于合同接收或法定批准；被退回后保留原提交与问题；同一提交的技术重试不重复计费，获授权的真实返修按合同、责任及实际投入另行判断。

**函数与类型契约**

- **函数**：`roles.architect.a07(ctx: ActionContext, input: ArchitectA07Input) -> ActionResult<ArchitectA07Payload>`。
- **输入记录**：`ArchitectA07Input = {scope:ScopeRef; deliverable_ref:Ref<Deliverable>; dependency_refs:List<Ref<Deliverable>>; task_completion_ref:Ref<TaskCompletion>; requested_use:ArchitectUse; recipient_ids:List<EntityId<Agent>>; review_requirement_ref:Option<Ref<ReviewRequirement>>; release_basis_refs:List<Ref<ReleaseBasis>>}`。来源：成果及依赖来自版本库；完成证据来自任务执行器；用途/接收者来自委任候选；发布依据来自有效授权及已满足检查。
- **输出分支**：`ArchitectA07Payload` 的 `choice` 与分支必填字段为：`submit{deliverable_ref:Ref<Deliverable>,requested_use:ArchitectUse,recipient_ids:List<EntityId<Agent>>,unresolved_issue_refs:List<Ref<Issue>>}; request_review{deliverable_ref:Ref<Deliverable>,requested_use:ArchitectUse,recipient_ids:List<EntityId<Agent>>,review_requirement_ref:Ref<ReviewRequirement>,unresolved_issue_refs:List<Ref<Issue>>}; release_for_use{deliverable_ref:Ref<Deliverable>,requested_use:ArchitectUse,recipient_ids:List<EntityId<Agent>>,release_basis_refs:List<Ref<ReleaseBasis>>,unresolved_issue_refs:List<Ref<Issue>>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：submit交成果提交服务；request_review另建立审查任务；release_for_use交有权用途发布服务。只由核心形成提交、通知或用途放行事实；requested_use不写成allowed_use，发送不写成送达/合同接受/许可。
- **业务出口与验收**：缺强制字段needs_information；越权/版本冲突由核心回执拒绝且不写事实；技术重试复用业务身份，不重复计费，合法新增返修按合同另核；CHECK-ARCHITECT-007、CHECK-ARCHITECT-012、CHECK-ARCHITECT-015、CHECK-ARCHITECT-039。
- **A07 分支约束**：`submit` 可只登记提交；`request_review` 要求输入 `review_requirement_ref` 非空且接收者具有对应受理职责；`release_for_use` 要求 `release_basis_refs` 非空并满足相应用途授权与全部必要条件。前两分支允许发布依据列表为空。三个分支均引用同一范围内的实际成果，至少一个合法接收者；不得在其输出附加 `allowed_use`、`approved`、事件 ID 或收费状态。

### ARCHITECT-A08 · 审查建筑成果或回应审查意见

- **触发与输入**：收到属于本主体检查职责的版本，或收到对本人方案的具体意见与证据。
- **自主选择**：按授权检查、说明可接受范围、请求补证、指出问题；作为作者时解释或提出修订。
- **正式结果**：有范围的建筑专业检查/回应记录；是否独立审查由模板决定，不自动视为所有专业通过。
- **等待与失败**：不得自行替代委托人取舍、监管决定或银行核验；模型未覆盖的检查保持未验证。

**函数与类型契约**

- **函数**：`roles.architect.a08(ctx: ActionContext, input: ArchitectA08Input) -> ActionResult<ArchitectA08Payload>`。
- **输入记录**：`ArchitectA08Input = {scope:ScopeRef; target_ref:Ref<Deliverable>; review_request_ref:Ref<ReviewRequest>; check_result_refs:List<Ref<MethodResult>>; comment_refs:List<Ref<ReviewComment>>; independence_ref:Option<Ref<IndependenceCheck>>}`。来源：有权审查任务、指定版本、方法输出与收到的意见；独立性证据由组织/授权登记供给。
- **输出分支**：`ArchitectA08Payload` 的 `choice` 与分支必填字段为：`review{opinion:ArchitectReview}; respond{comment_ref:Ref<ReviewComment>,response:string,basis_refs:List<Ref<Evidence>>}; propose_revision{affected_ref:Ref<Deliverable>,questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`review` 必须对应有效审查请求及本主体审查职能；`respond/propose_revision` 使用实际收到的意见与原被评版本，作者回应不改写对方审查记录。支持意见必须有该范围所需检查证据；方法结果为空时只可保留未知/缺项，不能填 support。
- **接收与核心效果**：交检查记录/问题服务，原作者A05/A06续作；只记录专业意见/回应，不替合同接受、行政决定或其他专业通过。
- **业务出口与验收**：无方法保持unsupported，缺证可提出补证或限定意见；CHECK-ARCHITECT-008、CHECK-ARCHITECT-016、CHECK-ARCHITECT-045。

### ARCHITECT-A09 · 处理变更与施工阶段设计支持

- **触发与输入**：获授权的需求变更、现场查询、接口冲突或整改事项，以及已使用版本和合同范围。
- **自主选择**：提供范围内解释、识别设计变化、提出修订与费用/时间影响，或请求必要新授权。
- **正式结果**：按实际任务形成答复或新版本，标记受影响工程/采购资料；相关用途按条件重新检查。
- **等待与失败**：沟通不能直接修改订单或现场工程；原义务内整改按约继续，收费争议单列，不自动转嫁返工费。

**函数与类型契约**

- **函数**：`roles.architect.a09(ctx: ActionContext, input: ArchitectA09Input) -> ActionResult<ArchitectA09Payload>`。
- **输入记录**：`ArchitectA09Input = {scope:ScopeRef; issue_ref:Ref<Issue>; used_deliverable_ref:Ref<Deliverable>; instruction_ref:Option<Ref<Instruction>>; obligation_ref:Ref<Obligation>; impact_method_ref:Option<Ref<Method>>; impact_result_refs:List<Ref<MethodResult>>}`。来源：现场查询/变更事项、现用成果、真实合同义务和有权指令。
- **输出分支**：`ArchitectA09Payload` 的 `choice` 与分支必填字段为：`explain{issue_ref:Ref<Issue>,response:string,basis_refs:List<Ref<Evidence>>}; propose_change{draft:ArchitectChange}; request_authority{questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：解释可不执行影响计算。`propose_change` 可先交有界修订申请，`impact_result_ref=null` 明确尚无已执行影响评估，并列待核范围；据此不能确认金额、工期或放行受影响用途。存在影响结果时必须对应当前指令、原成果与拟改内容，不能只凭 `impact_method_ref` 声称已计算。
- **接收与核心效果**：交Contractor/Engineer/QS及有权变更方；解释只入答复记录，修订申请经变更/任务入口再到A05；不直接改订单、施工或费用责任。
- **业务出口与验收**：解释实质改变参数时必须选propose_change；费用争议单列；CHECK-ARCHITECT-010、CHECK-ARCHITECT-011、CHECK-ARCHITECT-037。

### ARCHITECT-A10 · 申报服务费并处理应收

- **触发与输入**：满足委任的预付款、时间投入、阶段成果或其他计费条件，具备相应工作与条款依据。
- **自主选择**：申报、解释、修正错误、提出争议或按权利处理逾期；付款行为由付款方定义。
- **正式结果**：外部服务形成申报、确认/到期和实际收款关联；内部任务只记内部成本，不虚构自我收费。
- **等待与失败**：未收款不自动撤销已交成果；限制后续服务或使用需有依据，不能重复把成本、收费与收款相加。

**函数与类型契约**

- **函数**：`roles.architect.a10(ctx: ActionContext, input: ArchitectA10Input) -> ActionResult<ArchitectA10Payload>`。
- **输入记录**：`ArchitectA10Input = {scope:ScopeRef; engagement_ref:Ref<Engagement>; billing_clause_ref:Ref<BillingClause>; work_fact_refs:List<Ref<WorkFact>>; calculation_ref:Option<Ref<FeeCalculation>>; prior_claim_ref:Option<Ref<FeeClaim>>; receipt_refs:List<Ref<PaymentReceipt>>}`。来源：自己的委任/计费依据、真实投入、金额计算和有权可见付款回执。
- **输出分支**：`ArchitectA10Payload` 的 `choice` 与分支必填字段为：`claim{claim:ArchitectFeeClaim}; correct{prior_claim_ref:Ref<FeeClaim>,claim:ArchitectFeeClaim}; dispute{claim_ref:Ref<FeeClaim>,issue:ArchitectQuestion}; reconcile{claim_ref:Ref<FeeClaim>,receipt_refs:List<Ref<PaymentReceipt>>}; remind{claim_ref:Ref<FeeClaim>,recipient_id:EntityId<Agent>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`claim/correct` 必须有适用计费计算；`correct/dispute/reconcile/remind` 必须引用本方已有费用申报，且不得改收款主体或合同。催收、争议和对账可在 `calculation_ref=null`（本次没有新计费计算）时进行；对账仍需真实回执，未知到账保持待核。内部任务不进入外部服务费申报分支，成本按实际工作执行归集。
- **接收与核心效果**：交实际付款人、费用/义务服务；申报经合同条件后才形成应收，资金服务核对回执才清偿；本行为不写现金。
- **业务出口与验收**：内部任务不得选择对自己的claim；重复回执按原义务去重；CHECK-ARCHITECT-026、CHECK-ARCHITECT-029、CHECK-ARCHITECT-031。

### ARCHITECT-A11 · 暂停、召回、交接与退出

- **触发与输入**：有效暂停/结束事项、后续支持请求、当前排期、成果使用权及未结责任。
- **自主选择**：按权利调整服务、安排召回、提出接续条件或完成交接；接任任务需独立评估核查范围。
- **正式结果**：明确继续/停止任务、资源释放或新预留、合法资料移交、剩余费用和责任。
- **等待与失败**：可召回不保证立即有空；退出不删除历史作者、有效成果或欠费，接任不自动继承前任私有记忆。

**函数与类型契约**

- **函数**：`roles.architect.a11(ctx: ActionContext, input: ArchitectA11Input) -> ActionResult<ArchitectA11Payload>`。
- **输入记录**：`ArchitectA11Input = {scope:ScopeRef; engagement_ref:Ref<Engagement>; transition_basis_ref:Ref<ServiceTransitionBasis>; task_refs:List<Ref<Task>>; allocation_refs:List<Ref<ResourceAllocation>>; usable_deliverable_refs:List<Ref<Deliverable>>; residual_obligation_refs:List<Ref<Obligation>>}`。来源：有效暂停/恢复/结束依据、任务排期、成果权限及未结义务。
- **输出分支**：`ArchitectA11Payload` 的 `choice` 与分支必填字段为：`pause{task_refs:List<Ref<Task>>,basis_ref:Ref<ServiceTransitionBasis>}; recall{plan:ArchitectTaskPlan}; handover{package:ArchitectHandover}; exit{package:ArchitectHandover}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交委托人/接任方及任务资源服务；逐项保留/释放并安排移交；不撤销合法使用、历史作者或未付费用。
- **业务出口与验收**：接任未接受则保持待交接；召回无窗口deferred；CHECK-ARCHITECT-013、CHECK-ARCHITECT-014、CHECK-ARCHITECT-040。

### ARCHITECT-A12 · 更新经营判断与设计经验

- **触发与输入**：收到实际可见的审查、履约、费用和使用反馈，以及有来源的市场信息。
- **自主选择**：更新服务方向、报价判断、合作评价或提出能力建设任务；是否学习及其机制另定。
- **正式结果**：认知与策略变化附证据，能力提升若纳入则另有投入、时间和可验证产出。
- **等待与失败**：一次好评不自动提高所有能力；真实工程安全与市场规律不能由模型自述学习成功来证明。

**函数与类型契约**

- **函数**：`roles.architect.a12(ctx: ActionContext, input: ArchitectA12Input) -> ActionResult<ArchitectA12Payload>`。
- **输入记录**：`ArchitectA12Input = {scope:ScopeRef; feedback_refs:List<Ref<Feedback>>; strategy_ref:Ref<Strategy>; learning_profile_ref:Option<Ref<LearningProfile>>; capability_ref:Ref<Capability>}`。来源：真正获知的反馈、自己的策略及已选学习规则。
- **输出分支**：`ArchitectA12Payload` 的 `choice` 与分支必填字段为：`record_feedback{feedback_refs:List<Ref<Feedback>>,interpretation:string}; update_judgment{revision:ArchitectJudgment}; propose_training{request:ArchitectTaskRequest,learning_profile_ref:Ref<LearningProfile>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交本主体认知服务或能力任务审批；解释/策略版本不修改既有工程、资格或历史估计。
- **业务出口与验收**：未启用学习仅可记录反馈，不填技能提升；不可见反馈needs_information；CHECK-ARCHITECT-016、CHECK-ARCHITECT-035。

### ARCHITECT-A13 · 承接有限前期方案比较

- **触发与输入**：业主请求明确的方案研究，或已授权任务收到新的需求版本、专业输入或供应信息。 确认需求及授权版本、比较目标、成果用途、现有资料、工作预算/范围、截止条件和本主体容量。
- **自主选择与投入**：依 A02/A03 独立接受有限委任；商业接洽、投标准备与受托研究分别记账，不默认免费也不默认都可收费。 整理未知事项，形成适用的建筑候选；向所需专业发出有范围的问题，再依据已收到的信息修订自己的成果。
- **正式结果**：提交候选比较、补查建议、分阶段研究建议、范围内不可行理由或资料不足说明；允许没有当前可推荐选项。 核心登记已投入任务及本主体成果；只有业主另作有效决定才改变投资方向，成果提交不创建完整项目或后续设计委任。
- **等待与失败**：按授权完成范围或达到支出/期限边界后提交现状及未决事项；继续投入须落在既有授权或有效变更内。

**函数与类型契约**

- **函数**：`roles.architect.a13(ctx: ActionContext, input: ArchitectA13Input) -> ActionResult<ArchitectA13Payload>`。
- **输入记录**：`ArchitectA13Input = {scope:ScopeRef; brief_ref:Ref<Brief>; research_authority_ref:Ref<Authority>; task_ref:Ref<Task>; design_profile_ref:Ref<DesignProfile>; available_option_refs:List<Ref<DesignOption>>; professional_refs:List<Ref<Assessment>>; cost_refs:List<Ref<CostPlan>>; expenditure_limit_ref:Ref<ResearchLimit>; comparison_scope_ref:Ref<ComparisonScope>; comparison_method_ref:Option<Ref<ComparisonMethod>>}`。来源：Owner有限研究授权/简报、专业和造价版本、同委任研究限额。
- **输出分支**：`ArchitectA13Payload` 的 `choice` 与分支必填字段为：`compare{comparison:ArchitectComparison}; recommend_investigation{questions:List<ArchitectQuestion>,request:ArchitectTaskRequest}; no_recommendation{comparison:ArchitectComparison,reason:string}; deliver_at_limit{comparison:ArchitectComparison,remaining_questions:List<ArchitectQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`compare` 至少引用一个已登记候选；无候选或方法未覆盖时可以 `no_recommendation/deliver_at_limit` 交有限报告，此时 `recommended_option_refs=[]`，明确剩余问题。限额结束不要求先生成成功方案或计算结果。补查使用新工作申请，获授权后才创建任务和占用。
- **接收与核心效果**：有限报告经成果服务提交到有权委托人；不创建正式项目、后续设计合同或施工用途；新方案编制复用A04/A05任务而非重算投入。
- **业务出口与验收**：无project_id合法；到限额交现状而不无限续作；CHECK-ARCHITECT-017、CHECK-ARCHITECT-019、CHECK-ARCHITECT-024、CHECK-ARCHITECT-049。

### 3.1 全行为执行与交接矩阵

| 行为 | 输入与允许选择 | 正式输出 | 资源与时间 | 失败或等待 | 下一交接 |
|---|---|---|---|---|---|
| A01 业务发现 | 有来源邀请/市场信息；跟踪、投入准备或忽略 | 本主体机会记录及授权准备任务 | 营销/研究占用按实际任务记 | 无权资料不使用；线索不完整可澄清 | 委托方 → A02，或留存观察 |
| A02 接单条件 | 范围、责任、费用、排期；报价、有限接受或拒绝 | 版本化服务方案及本方接受 | 预留有窗口和解除条件 | 无能力/容量时限缩或拒绝；技术失败另记 | 有权委托方比较/接受 → A03 |
| A03 委任确认 | 相容条款与权限；确认或要求修订 | 委任/内部授权及责任边界 | 预留转占用不重复 | 被选中但未有效接受不生效 | 任务负责人与 A04 |
| A04 工作安排 | 成果清单、输入依赖与负荷；排序、分派或调整 | 任务分解、排期和投入记录 | 分别记生产性投入、等待与待命 | 关键资料迟到只阻塞依赖部分 | 编制者 A05/A13 或相应现场任务 |
| A05 方案设计 | 有效需求与成熟度；编制、比较、请求补查 | 建筑版本、假设和范围 | 真实设计任务完成量/投入 | 无支持的方法保持未算；不伪造完成 | A06、QS 或委托方取舍 |
| A06 接口整合 | 专业引用及冲突；协调本职责、请求回应或升级 | 带双方对象的接口事项和整合版本 | 协调任务与专业重做分别计 | 无整合授权时只报告本专业接口 | 原作者回应，A08 检查或有权委托人决定 |
| A07 提交发布 | 达到提交标准的版本和拟用范围；提交或有权发布 | 提交、待投递通知及适用发布记录 | 编制完成不免除交付/发布任务 | 用途条件未满足时限用途，保留草稿 | 有权接收者、监管或采购/施工执行者 |
| A08 检查回应 | 被检版本、检查权限、具体意见；认可范围、补证或修订 | 检查记录、问题及回应关联 | 审查与修订各有任务 | 自我回应不能替代要求的独立检查 | A05/A06 重做，或 A07 提交适用版 |
| A09 施工变更 | 现场查询、现用版本、指令；解释、提出改动或升级 | 查询答复、设计修订及影响清单 | 紧急程度改变优先判断，不生成额外容量 | 变更权或证据不足时不得直接指令全部工程 | Contractor、Engineer、QS 与有权变更方 |
| A10 服务收付 | 有效计费依据；申报、补证、争议或依法约催收 | 服务应收/收款关联与对账记录 | 财务核对占用与设计投入分开 | 部分/未知到账按资金接口处理 | 真正付款人和共同账本 |
| A11 接续退出 | 有效暂停/终止、成果和残余任务；交接、召回或结束 | 范围化移交、资源变更及剩余责任 | 新接任核查和召回重新检查可用窗口 | 未接收移交不冒充完成；保留未结事项 | 接任服务方/委托人及后续责任清单 |
| A12 经营学习 | 自己可见的投入、返工、回款与质量反馈；修订未来策略 | 认知版本及获授权能力建设任务 | 培训/能力建设有成本和时间 | 未披露结果不作已知，经验不自动生成资格 | 下轮 A01/A02/A04 |
| A13 前期研究 | 有限简报与研究授权；比较、补查或无推荐 | 适用研究成果及剩余问题 | 支出/范围/期限有边界 | 达到授权边界不无限投入 | 有权委托人继续、调整或停止 |

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
| `ArchitectUse` | `research / cost_estimation / regulatory_submission / procurement / construction / operation`；只可选本任务、对象及授权允许的子集，许可名称不由此枚举决定 |
| `ArchitectQuestion` | `scope:ScopeRef; target_refs:List<Ref<EvidenceTarget>>; question:string; recipient_ids:List<EntityId<Agent>>; evidence_refs:List<Ref<Evidence>>; blocking_uses:List<ArchitectUse>; response_requirement_ref:Ref<ResponseRequirement>` |
| `ArchitectTaskRequest` | `scope:ScopeRef; purpose:preparation/service_delivery/investigation/training/remedy/policy_evaluation; input_refs:List<Ref<BusinessObject>>; output_requirement_refs:List<Ref<DeliverableRequirement>>; work_profile_ref:Option<Ref<WorkProfile>>; effort_estimate:ValueState<Measured>; desired_window:ValueState<TimeWindow>; authority_basis_refs:List<Ref<Authority>>; dependency_refs:List<Ref<Dependency>>; questions:List<ArchitectQuestion>`；申请尚未创建的业务工作，不含虚构任务 ID；purpose 只可选本动作授权子集，正常报价容量使用 service_delivery，不因枚举存在而获得其他职能。估计引用受支持方法，未知保留。`work_profile_ref=null` 只表示未取得可执行工作方法，允许申请但不执行。经有权确认后创建业务 Task，再编制 TaskPlan；提交申请不占用资源、不形成收费 |
| `ArchitectTaskPlan` | `work_profile_ref:Ref<WorkProfile>; items:List<{task_ref:Ref<Task>,resource_ids:List<EntityId<Resource>>,window:TimeWindow,effort:Measured,dependency_refs:List<Ref<Dependency>>,existing_allocation_ref:Option<Ref<ResourceAllocation>>}>`；每项必须绑定已授权任务和适任资源，`effort` 来自工作方法，不是模型自由估值 |
| `ArchitectServiceOffer` | `scope:ScopeRef; client_id:EntityId<Agent>; payer_id:EntityId<Agent>; proposed_terms_ref:Ref<ServiceTerms>; fee_basis_ref:Ref<FeeBasis>; fee_calculation_ref:Ref<FeeCalculation>; capacity_request:ArchitectTaskRequest; validity:TimeWindow; deliverable_requirement_refs:List<Ref<DeliverableRequirement>>`；条款草案和计算须先登记才可引用；capacity_request 仅说明拟需容量，不表示已正式占用或已经委任 |
| `ArchitectFeeClaim` | `engagement_ref:Ref<Engagement>; billing_clause_ref:Ref<BillingClause>; work_fact_refs:List<Ref<WorkFact>>; calculation_ref:Ref<FeeCalculation>; amount:Money; payer_id:EntityId<Agent>; prior_claim_ref:Option<Ref<FeeClaim>>`；金额必须与计算及条款一致，不能由文字推导应收或现金 |
| `ArchitectHandover` | `engagement_ref:Ref<Engagement>; recipient_ids:List<EntityId<Agent>>; deliverable_refs:List<Ref<Deliverable>>; access_basis_refs:List<Ref<AccessBasis>>; release_allocation_refs:List<Ref<ResourceAllocation>>; retain_allocation_refs:List<Ref<ResourceAllocation>>; remaining_task_refs:List<Ref<Task>>; remaining_obligation_refs:List<Ref<Obligation>>; basis_ref:Ref<ServiceTransitionBasis>`；释放与保留集合不得相交，接收结果另记 |
| `ArchitectJudgment` | `prior_strategy_ref:Ref<Strategy>; learning_profile_ref:Ref<LearningProfile>; evidence_refs:List<Ref<Evidence>>; changes:List<{dimension_ref:Ref<JudgmentDimension>,selected_value_ref:Ref<JudgmentValue>,explanation:string}>`；维度和值来自已选规则的有限目录，禁止利用该结构修改正式能力/资格/工程状态 |
| `ArchitectOptionDraft` | `brief_ref:Ref<Brief>; scope:ScopeRef; design_profile_ref:Ref<DesignProfile>; parent_option_ref:Option<Ref<DesignOption>>; relation:original/revision/alternative; variables:List<ArchitectVariable>; component_groups:List<ArchitectComponentGroup>; basis_refs:List<Ref<Evidence>>; method_result_refs:List<Ref<MethodResult>>; unresolved_questions:List<ArchitectQuestion>`；候选/变量范围由 §4.4 的有限目录及同委任额度校验，身份/新版本由成果服务分配 |
| `ArchitectVariable` | `variable_ref:Ref<DesignVariable>; value:ValueState<Measured> 或 ValueState<Ref<CatalogOption>>; source_refs:List<Ref<Evidence>>`；具体变量只允许其设计目录声明的一种值类型，数值有单位，未知显式保留 |
| `ArchitectComponentGroup` | `scope:ScopeRef; coverage_ref:Ref<ComponentCoverage>; function_ref:Ref<FunctionType>; system_option:ValueState<Ref<SystemOption>>; interface_refs:List<Ref<Interface>>`；互斥分支分别成方案，不作为同时建设的构件累加 |
| `ArchitectComparison` | `option_refs:List<Ref<DesignOption>>; comparable_scope_ref:Ref<ComparisonScope>; professional_refs:List<Ref<Assessment>>; cost_refs:List<Ref<CostPlan>>; recommended_option_refs:List<Ref<DesignOption>>; unresolved_questions:List<ArchitectQuestion>; comparison_method_ref:Option<Ref<ComparisonMethod>>; reason:string`；推荐必须属于 option_refs，且有适用比较方法和同范围依据；可无候选/无推荐的限制报告不得生成排名，comparison_method_ref=null 表示未取得可用比较方法 |
| `ArchitectIntegration` | `option_ref:Ref<DesignOption>; included_assessment_refs:List<Ref<Assessment>>; included_cost_refs:List<Ref<CostPlan>>; interface_refs:List<Ref<Interface>>; open_issue_refs:List<Ref<Issue>>; integration_authority_ref:Ref<Authority>; consistency_result_refs:List<Ref<MethodResult>>`；只整合引用，不复制或改写各作者的结论 |
| `ArchitectReview` | `target_ref:Ref<Deliverable>; review_request_ref:Ref<ReviewRequest>; check_result_refs:List<Ref<MethodResult>>; opinion:support/limited_support/revise/undetermined; requested_use:ArchitectUse; unresolved_issue_refs:List<Ref<Issue>>; explanation:string`；审查条件依方法结果，意见不等于用途已获放行 |
| `ArchitectChange` | `prior_deliverable_ref:Ref<Deliverable>; instruction_ref:Option<Ref<Instruction>>; affected_scope:ScopeRef; affected_dependency_refs:List<Ref<Dependency>>; proposed_variable_changes:List<ArchitectVariable>; impact_result_ref:Option<Ref<MethodResult>>; fee_entitlement_ref:Option<Ref<EntitlementDecision>>; unresolved_questions:List<ArchitectQuestion>`；影响金额/工期引用计算，费用权利未知不填获偿 |

### 3.3 A07 的完整交接与边界样例

以下全部是合成契约样例，编号仅代表测试环境中预先建立的对象。它们不证明真实方案完成或某项许可已经取得。共同输入为 `scope.kind=assessment_case`、评估档案 `CASE-01@1`、覆盖 `AREA-A@1`，成果 `DEL-028@3`、实际完成证据 `TASK-DONE-07@1`、可见且有效的依赖版本、拟用 `cost_estimation`、接收者 `QS-006`、估算用途审查要求 `REVIEW-ESTIMATE@1`；发布依据列表为空。宿主绑定本次任务、Architect 身份及提交/申请审查权限。该环境允许有限研究报告提交，不要求先存在正式项目。

**输出形成例**：建筑师选择申请估算用途审查，结果如下。`note` 中不能另藏“自动用于施工”等改变流程的条件；未解决问题必须明确引用。

```json
{
  "kind": "completed",
  "payload": {
    "scope": {
      "kind": "assessment_case",
      "ref": {"kind": "assessment_case", "id": "CASE-01", "version": 1},
      "coverage_refs": [{"kind": "WorkScope", "id": "AREA-A", "version": 1}]
    },
    "choice": "request_review",
    "deliverable_ref": {"kind": "Deliverable", "id": "DEL-028", "version": 3},
    "requested_use": "cost_estimation",
    "recipient_ids": ["QS-006"],
    "review_requirement_ref": {"kind": "ReviewRequirement", "id": "REVIEW-ESTIMATE", "version": 1},
    "unresolved_issue_refs": [{"kind": "Issue", "id": "SITE-UNKNOWN-02", "version": 1}],
    "note": "供约定范围的有限估算审查；场址未决项保留，暂未申请施工用途。"
  }
}
```

该输出先登记为决定，再由宿主按 `request_review` 的命令绑定提交；提交记录和审查请求若必须共同成立，按[共同提交协议](../06_engineering/interface_contracts.md#5-命令准备提交与回执)作为同一必要写集校验。通知投递在提交之后处理，投递失败不能撤销已提交事实或伪造已送达。

| 契约验收 | 具体输入/变化 | 确定返回及后果 |
|---|---|---|
| 成功提交 | 上述输入、版本及权限有效；宿主绑定命令 `CMD-A07-01` | 首先为上述 `ActionResult.completed`；核心提交后才返回 `CommandReceipt.committed`，含本运行 `data_space`、`command_id=CMD-A07-01`、核心分配的 `commit_seq`、提交/审查请求的 `object_refs` 和 `event_refs`。下游 QS 得到获授权审查请求；没有 `allowed_use=construction`、合同接受或付款事实。对应 CHECK-ARCHITECT-053 |
| 必要资料缺失 | 其余同上，但没有 `task_completion_ref`；不是一份已完成证据的过期问题 | `{"kind":"needs_information","missing_fields":["input.task_completion_ref"],"requested_refs":[]}`；不创建提交命令或事件，不用文字“我已完成”填补。对应 CHECK-ARCHITECT-054 |
| 越权用途发布 | 选择 `release_for_use`、`requested_use=construction`，但本主体只有提交权；模型即使提供看似完整依据也不能扩大宿主权限 | 绑定前识别则 `BindingResult.kind=rejected`、`reason_code=authority_missing`；若校验后权限在提交前失效，则原命令回执为 `business_rejected`、`reason_code=authority_missing`，附实际核验引用；两者均无放行事件/费用变化，不伪造机关拒绝许可。对应 CHECK-ARCHITECT-055 |
| 原提交重复/回执丢失 | 同一 `CMD-A07-01`、相同 `payload_hash` 和业务身份再次请求；已有正式回执 | 先 `core.read_receipt` 返回 `found` 及原 `committed` 回执；重试仍取同一事件/对象，提交数、实际投入及费用均不增加。若新内容复用该命令身份，属于 `identity_conflict`；获授权的新返修通过新的任务/增量与提交身份处理，不意味着免费。对应 CHECK-ARCHITECT-056 |
| 依赖版本冲突 | 决策快照要求 `DEP-04@1`；提交时该用途必要依赖已有正式失效/替代依据，原引用不再覆盖拟用范围 | 原命令回执 `kind=version_conflict`、`reason_code=dependency_no_longer_valid`、`checked_refs` 指向核验过的依赖；无新提交/发布事实，重新读取、评估受影响范围后形成新决定。仅存在新版草稿但旧版仍合法，不得因此返回冲突。对应 CHECK-ARCHITECT-057 |

该表给出的是预期契约验收结果，实际自动测试实现与运行证据另记。核心分配的正式对象、事件、提交序号或到账数据从不作为 Architect 的自由输出字段。

## 4. 专业工作与跨主体交互

### 4.1 跨主体输入与输出

下表只定义本主体发送/接收的信息；对方的决策规则在各自文档中定义。

| 对方 | 本主体接收 | 本主体交付 |
|---|---|---|
| [Owner](owner.md) | 需求、授权范围、方案取舍及服务事项 | 服务方案、设计选项、问题及费用依据 |
| [Engineer](engineer.md) | 专业要求、分析/检查及接口结果 | 建筑版本、空间接口、待解问题与适用范围 |
| [QS](qs.md) | 成本计划、量价疑问及费用影响意见 | 对应版本设计、数量基础、选项与变更范围 |
| [Government](government.md) | 本人有权收到的意见、资料要求和决定 | 具备资格与授权时的版本材料及说明 |
| [Contractor](contractor.md) | 获准披露的施工查询和可建造性信息 | 有授权的设计答复、版本与使用条件 |
| [Supplier](supplier.md) | 获准提供的产品/制造接口资料 | 受授权询问、性能/空间接口及版本要求 |
| [Bank](bank.md) | 获授权的资料请求 | 允许披露且与委任相符的设计/阶段证据 |

本主体交付成果不直接更新对方决定；请求、专业意见、最终选择与已提交事实分别标记。

### 4.2 前期需求与有限专业研究

**前期职责分工**：业主提出建设目的、候选地区、规模区间和期望交付时间；技术及建造方式保留候选，结合各专业及供应方意见细化。

**ARCHITECT-008｜需求版本与约束性质。** 接收带业主身份与评估档案的需求简报，区分业主明确的硬约束、可商议偏好、未知事项与适用外部限制。
候选地区不等于已取得具体场址；规模区间不等于唯一面积，期望交付时间不自动成为本主体承诺。
本主体可指出需求矛盾并建议调整，但只能由有权业主修订其商业需求；违反适用约束的选项应指出冲突，不能自行把约束降为偏好。
跨组织接收时仅要求具备本次工作所需信息；需求简报不自动披露业主全部资金、其他项目和私有估值。

**ARCHITECT-009｜比较对象可分解，不预设胜者。** 候选描述用途/功能、空间组织、规模、场址假设及系统接口，并说明尚未确定的技术组合。
MiC、预制构件、混合方案和现浇只是可用描述示例，可能覆盖不同部位或维度；不得简单作为四个互斥标签固定排名。
一个候选可以保留多个工程/生产配置；方案组合应有明确适用部位和依赖，不由名称推定成本、交付或质量优势。
与业主要求相符的改造、分期或利用既有设施等选项可以纳入本次授权范围；不要求每次都重新分析所有可能方案。

| 语义字段建议 | 本主体接收或形成的内容 | 使用边界 |
|---|---|---|
| `owner_case_id`、`brief_id/version` | 本业主评估档案、需求简报及版本 | 可在项目正式成立前存在，不改变共享机会身份 |
| `purpose`、`candidate_regions` | 使用目的、候选地区及所知场址资料 | 地区信息不能补成虚构的地块条件 |
| `scale_range`、`target_delivery` | 规模范围、期望时间和量纲 | 与硬约束/偏好标签关联，不能直接转为合同承诺 |
| `assignment_id`、`scope` | 有效研究任务、排除项、接收人和成果用途 | 无总协调委任时不自称所有专业负责人 |
| `option_id/version`、`parent_option` | 建筑选项、修订及分支关系 | 允许部分技术配置待定，不以新版本覆盖历史比较 |
| `requirements_fit`、`interfaces` | 功能符合情况、空间与专业接口 | 本专业意见，不代表全部工程检查或行政批准 |
| `assumptions`、`unknowns`、`dependencies` | 假设、未知项和所引用资料版本 | 已知事实、外部主张及自身假设分别保留 |
| `assessment_id`、`blockers` | 本次比较及问题记录、所需下一输入 | 有条件推荐仍保留条件，不以推荐代替满足 |
| `valid_until_or_trigger`、`allowed_use` | 适用时效/重评触发及允许用途 | 只作研究比较的成果不能直接用于施工或许可证明 |

**ARCHITECT-010｜量化结论有方法入口。** 对面积、功能容量等已支持指标，提交带输入版本、单位与适用范围的计算请求，引用可追溯结果。
未支持的指标保留定性意见、区间假设或待计算标记；不从 LLM 描述生成“已经核算”的成本、结构安全、工期或供应产能。
本主体可读取 Engineer、QS、Supplier 有权披露的成果并提出接口问题，不能改写其方法结果或替其他主体承诺报价和排期。

**ARCHITECT-011｜独立意见与综合整理。** 本主体单独记录建筑判断及其依据；只有收到委任时才整理跨专业比较表，整理不能变成专业总批准。
意见不一致时建立共同对象/版本的具体问题，区分数据口径不同、接口冲突、商业取舍及尚未验证，分别指定需要回应的角色。
不通过多数票、平均评分或要求大家同意来关闭技术冲突；业主可以调整偏好，却不能用商业选择代替必要专业检查。
本主体可推荐进一步研究或优先保留的候选，同时保留未推荐理由；推荐不替业主决定投资、地区或采购伙伴。

**ARCHITECT-012｜重评按影响与费用范围处理。** 收到需求、场址、专业结论或供应条件变化时，登记新信息及受影响范围，提出复核任务；新提案、待复核、正式限制/撤回和新发布替代分别记录。影响记录引用旧/新版本、范围、当前用途有效性、限制依据、有权主体及生效时间。
待复核本身不撤销仍有效的旧发布，也不保证可以继续；继续与否取决于已生效的用途限制和必要条件。V2 草稿不自动撤销 V1；独立有效的范围限制即使在 V2 尚未完成时也须生效。部分旧信息失效不自动作废全部成果；保留当时可见依据，不能用后来信息改写早期决策记录。
自行纠错、委托需求变更、外部变化和新增比较范围分别记录原因；是否收费及继续投入依委任和授权，不默认免费重做或自动加价。

**ARCHITECT-013｜五类结果分别保存。** 本主体建议、范围内专业检查、业主商业选择、合同成果接收及法定许可具有不同对象和效力。
业主选择某选项只结束对应商业比较；未解决的专业条件仍影响后续授权用途，也不强制本主体接受新增设计任务。

### 4.3 专业服务与资金接口

**资金范围**：平台保留现金、应收应付、贷款与到期义务；服务资金使用[共同对象规则](../02_world/domain_objects.md)。
A10/A11 使用共同账本；收费方式、费率、付款期限和争议模板须由委任与模型配置明确。

**ARCHITECT-014｜研究投入和客户欠款分别形成。** 前期有限委任在 owner_case_id 下记录实际任务成本、费用申报、按条款成立的应收及到期事项。
里程碑、工时、固定费或预付款均由有效合同约定，不默认采用某一种；研究投入产生内部成本，不当然使客户欠付同额费用。
已交付、客户接受、满足付款条件和实际到账分别记录；约定预付款可以先于交付，不强制所有合同采用同一先后顺序。
评估档案转为正式项目时沿用原服务及义务关联，不再计一次费用，也不自动把原委托人的债务转给项目公司或其他业主。

**ARCHITECT-015｜收款与本企业付款各有对象。** 自身人员报酬、外包设计或其他已建模采购应付与客户回款分开，按实际义务及到期状态安排。
内部团队投入只作组织成本或内部归集，不生成组织对自己的应付；真实报酬或外部采购有实际收款对象时，另按规则登记对应义务。
同一人员费用可以在成本视图归集到项目，同时在账本记应付和清偿，但不能把这些视图相加成多次支出。
客户尚未付款不自动消除本企业到期义务；本企业有贷款时关联本企业真实借款和到期事项，不凭业主融资到账假定自己获得现金。

**ARCHITECT-016｜清偿、争议和退出分别处理。** 收款提交关联具体义务与执行标识，部分付款只减少相应未清金额，预收抵扣按原款项关联处理。
重复通知不重复增加现金或冲减应收；执行结果未知先对账，不能为补日志再发起收款或付款。
撤销评估、终止设计或释放人员不删除已形成欠款、费用争议和剩余服务责任；债务调整须有独立有效依据。
资源释放依据具体服务义务判断，不能因欠款未清就永久占满人员，也不能因人员释放就把债务视为清偿。

### 4.4 参数化方案与专业接续

建筑范围采用“有限参数化方案 + 代表性构件/工作包”目标接口，统一工程对象、有限模板及支持状态引用 [工程类型与有限模板](../02_world/project_types.md)；具体目录和工程方法尚未选定。业主提出目的、候选地区、规模区间和期望交付时间，各专业按授权独立细化。A04—A09/A13 不代替其他专业的决定，也不成为道路/桥梁/隧道方案的必经入口。

#### 4.4.1 建筑方案包：本角色维护的接口

**ARCHITECT-024｜方案由可审阅变量构成。** 允许变量及范围由 `design_profile_ref=(id,version)` 登记，并注明数据/模型假设来源；LLM 可选择目录项、允许范围内数值或提出新增目录请求，不能临时创造场地事实、技术认证或通过结论。目录可产生零个适用方案，空集合交回有权委托方决定补查、改需求、延期或结束。

模板明确对应建筑对象/子工程、成果用途和作者职能，列离散选项或数值范围/精度、相容条件、支持的数量与检查方法、固定输入和排除项。新增目录请求不自动扩充本次可执行空间；先保留未覆盖，再由相应建模/业务入口处理。高度是建筑属性，超高层所需专业、方法及接口支持另核对，不从楼层数或一个复杂度系数推出安全、成本或工期结论。

| 输入/输出 | 必须表达的字段与类型 | 所有者与交接条件 |
|---|---|---|
| 研究输入 | `brief_ref=(brief_id,version)`、`owner_case_id`、可空 `project_id`、`assignment_ref`、`requested_use`、`information_cutoff` | Owner/委托方维护需求及授权；Architect 只读获授权版本 |
| 地区与场址依据 | 具体工程对象/子工程与作用范围引用、`project_region_id`、可空 `site_ref`、`site_evidence_refs[]`、`scenario_ref` | 跨区项目按本次服务范围引用相应地点/事项；只有地区时保留场址情景，不从顾问注册地推定 |
| 方案身份 | `option_ref=(option_id,option_version)`、`parent_option_ref`、`author_agent_id`、`basis_refs[]` | 修订保留同一方案身份并增版本；独立替代创建分支并声明互斥/组合关系 |
| 变量与范围 | `design_profile_ref`、`selected_variables`、`scope_id`、`component_groups[]` | 每项含类型、单位、值/候选/未知状态及来源；未知不以 0 表示 |
| 编制与核查 | `task_ref`、`compilation_status`、`consistency_result_refs[]`、`professional_assessment_refs[]` | 引用本次投入、形式一致性结果及各作者独立专业意见 |
| 交付和用途 | `deliverable_ref`、`allowed_use`、`unresolved_items[]`、`acceptance_ref`、`release_ref` | 接收、合同接受和用途发布分别形成；无对应事件的引用保持空值 |

有限变量建议如下；这是目录结构示例，不决定首批项目用途、楼层范围或工程尺寸。

| 变量组 | 建议表示 | 不能自行推出的结论 |
|---|---|---|
| 用途与空间需求 | 从本需求允许的 `use_type/function_id` 选择；面积、服务对象数等分别保存单位 | 不能直接把建筑面积换成床位/人数或服务量；需要独立转换方法 |
| 建筑规模与空间划分 | 仅建筑模板使用 `level_groups[]`：分组 ID、整数楼层数、每层建模面积及面积定义；范围来自简报和适用资料 | 不把楼层/面积模板套到道路、桥梁或隧道；建模面积不是法定面积，也不证明容积率或许可符合性 |
| 系统和部位 | `component_group_id`、覆盖部位、`function_id`、有限 `system_option_ref`、接口引用 | 建造方式按部位组合；MiC/构件预制/现场工序等标签不构成互斥排名 |
| 分期与接口 | 有限分期选项、`interface_refs[]`、专业待答问题和依赖 | 分期设想不等于现场已具备可独立使用条件，也不产生承包商交期承诺 |

同一方案的候选分支不能当成同时要建的数量相加。某部位技术仍未选定时，可分别形成条件分支；需该变量才能计算的结果保持缺项。每个构件组声明唯一覆盖范围；空间统计层级与构件工程量层级不能混为一个可直接相加的总量。

#### 4.4.2 编制实际工作与形式计算

**ARCHITECT-025｜先定义要完成的工作，再记录完成。** 参数化方案任务采用 `work_plan_ref`，列工作单元 ID、输入依赖、适任资源、所需投入及其单位、投入估计方法/版本、成果清单和允许的交付模式。工作单元可为需求整理、一个方案编制、接口整理或一次修订；首批投入估计方法仍需选择，不默认每个方案同样耗时。

一次委任共享候选数、累计版本/分支、正式返修轮次及服务投入边界；新方案 ID、分支或技术重试不能重置额度。具体上限由选定模板/条款声明，“2 个候选＋1 轮返修”仍是建议，不作为默认值。达到边界可交付当前成果/缺口并申请调整；LLM 技术调用预算另计，模型技术等待不直接计入业务工期，真实补查、返修、答复等待及其他专业工作按[总体运行框架](../02_world/world_runtime.md)与[项目推进](../03_projects/project_lifecycle.md)的时序和各自任务方法记录。

任务入口累计已确认的实际投入分片，关联任务、工作单元、分派版本、实际区间及唯一执行身份；跨周期续办仅计未执行部分。暂停时保留已发生投入、待办与剩余工作，不能通过新任务 ID 重计同一投入；新增范围另有授权和增量工作依据。服务成本按实际投入归集，客户应收仍按资金接口条款形成。

编制完成必须满足本次授权交付模式：规定工作单元完成、必交字段已提供或按约明示缺项、引用可解析、形式检查已执行且阻止提交的错误已处理。若原委任要求完整方案，交一份缺口清单不能把整个委任标为完成；若明确委任只要求有限研究报告，报告可以完成而方案仍待补证。编制完成不要求专业检查通过，也不等于客户接受。

**ARCHITECT-026｜形式计算只证明其明确内容。** 可提议的首个方法 `area_schedule_sum` 只对“组内每层面积相同、组间楼层不重叠”的方案计算 `modeled_area = Σ(floor_count × area_per_floor)`，输出 m²、分组明细、输入版本与方法版本。任一必要面积未知、组重叠或单位不相容时，相关汇总返回缺项/冲突，不能跳过后给出完整总面积。其他几何类型保持未覆盖，或显式分解为适用分组。

该算术不证明结构、消防、规划或实际功能可达标；不得给它命名为“方案技术批准”。这里没有采用任何真实建筑规范阈值；用作场景限制的边界须另有证据/假设身份并保留用途。

#### 4.4.3 交接、分歧与修订

**ARCHITECT-027｜本建筑范围内各方按同一方案版本接续，各自维护自己的成果。**

| 交接 | Architect 发出 | 对方返回与本方接续 |
|---|---|---|
| 至 Engineer | `option_ref`、构件/系统及接口、设计依据、具体问题、拟用范围、授权可见资料 | [Engineer 专业方法](engineer.md#44-专业方法证据与工作包) 的 `assessment_ref`；保留逐项结果，不能把有冲突或未覆盖项平均成通过 |
| 至 QS | 同版方案、`area_schedule_ref`、专业数量依据、构件组及不确定分支、期望成本口径 | [QS 工程量与成本计划](qs.md#44-工程量成本计划与方案比较) 的 `quantity_schedule_ref/cost_plan_ref`；量价缺口回到具体作者，不能直接改他方数据 |
| 至委托方 | 当前建筑成果、专业/成本引用、未决项、可比较范围及继续研究选项 | 有权方独立接受服务成果或选择商业方向；无方案获推荐也是有效研究结果 |

QS 可以对未完成全部专业检查的方案编制限定假设估算，Engineer 也不必等待完整成本计划才能检查独立事项；共同依赖按具体输入建立。只有获得整合委任时 Architect 才负责整理整套比较资料，否则仅交付自身范围。

修订建立 `change_ref`、旧/新 `option_ref` 和受影响构件/接口；原评估不改写为针对新版。确认未受影响的结果可通过有权复用记录引用，新版检查/成本计划各自保留输入身份。原有发布、正式限制和待复核的关系遵循 ARCHITECT-012。

#### 4.4.4 正常、拒绝和返修例子与独立验收

**ARCHITECT-028｜同一条方案链允许不产生可投资方案。** 正常例：一个已授权的大湾区地区场景允许两个构件组合，Architect 编制候选及面积表；Engineer 回应支持范围内的接口检查；QS 返回同口径量价及未计项；委托方决定继续研究哪一支，而非由 Architect 直接登记开工。拒绝例：某顾问资源不足拒绝该委任，保留前期接洽记录，不生成该顾问已完成成果。返修例：一项接口明确冲突，Architect 依据有权调整选择修订部位；相关专业复查和 QS 增量改算另有任务，其他有效范围继续保留。

接口验收中，算术 fixture 的值只用于测试，不是项目参数或真实建筑实例。

### 4.5 地区适用与证据边界

本角色只研究大湾区范围内的建筑方案与空间接口；场景明确项目地区、事项、适用时间和证据来源，不从“大湾区”标签推导统一资格、技术要求或合同权限。
组织登记地、实际服务地、项目所在地及产品生产地分别引用；跨地区经验不自动证明本次任务的资格、数据或方法适用。
规范条款、供应资料、观测数据与模型假设分别登记。尚未取得依据的阈值和条件保留未知，不从不适用地区的参考流程或无来源常数补齐。
本文件中的代表方案和算术例子用于检查模型接口；未选定的方法不得产生技术通过，未覆盖的专业不声称真实设计安全。

## 5. 状态转换、失败与恢复

### 5.1 提交、版本与持续约束

**ARCHITECT-005｜版本按用途管理。** 草稿、已提交、已审查、适用发布、被替代和撤回分别保存；新草稿出现不自动撤销仍适用的已发布版本。
影响分析覆盖本主体所知的专业引用、报审、订单与施工使用；正式入口按有效版本限制动作，主体通知/获知时间另记。
已经按旧版完成的工程与消耗保留；本主体只能提交修改及影响信息，不能回溯删除执行事实。

**ARCHITECT-006｜等待要有解除条件。** 缺场址信息、专业输入、委托确认、资源或外部决定分别建事项，记录负责人和下一触发。
技术失败、业务拒绝、成果不合格和委任违约分开；未完成不能因达到项目目标数量而被改成完成。

**ARCHITECT-007｜义务与资源分别结束。** 方案阶段结束可释放适用投入，但现场支持、复查或缺陷处理义务按合同保留。
费用归属由委任、有效指令和责任证据确定；修改指令有权生效与费用是否已谈妥不是同一个判断。
方案确认、成果接受、施工用途放行、费用清偿与服务关闭分别记录。

### 5.2 对象转换与剩余责任

**ARCHITECT-020｜完成、发布与问题关闭分别门控。** 任务投入满足完成标准才可转完成；成果是否可用于特定用途另核对，本主体能提交的变化取决于本次职能。

| 对象与转换 | 必要依据 | 不自动发生的变化 |
|---|---|---|
| 服务拟承接 → 有效 | 相容条款、双方有效接受/内部授权、提交前能力复核 | 不自动包含设计整合、签署或行政许可权 |
| 任务待输入 → 可执行 → 执行中 | 必要输入满足、有效分派和实际投入开始 | 不因经过一个 tick 自动完成 |
| 执行中 → 受阻/待命 → 恢复 | 明确阻塞对象，新的有效输入与真实资源窗口 | 受阻期间不继续生成依赖成果或默认免费待命 |
| 任务完成 → 成果提交 | 完成标准、版本、接收者及用途齐备 | 不代替合同接受、复核或发布 |
| 已提交 → 已检查/适用发布 | 具备权限的检查及对应范围条件 | 一处通过不覆盖所有专业和用途 |
| 问题开放 → 已回应 → 待核实 → 关闭 | 有针对性的处理及获授权核实证据 | 发言或平均质量分上升不关闭问题 |
| 有效旧版 → 受影响待复核/被替代 | 变更影响与范围化发布记录 | 新草稿不一键撤销全部旧版用途 |
| 服务停止 → 移交/残余义务 → 对应范围关闭 | 有效结束依据、资料交接及义务处理 | 全项目完工不直接关闭所有客户/项目关系 |

**ARCHITECT-021｜施工查询先区分解释与变更。** 解释已有有效设计不必虚构新设计版本；改变范围、性能或接口的答复需形成变更及受影响依赖，不能以“澄清”绕过授权。
本主体可以通知风险及请求保护措施；是否可发有约束力指令取决于明确授权，不能因建筑师身份自动取得全项目停工或总协调权。

**ARCHITECT-022｜排队有原因和恢复入口。** 任务记录等待谁、缺什么、下一触发和可继续部分；事件或约定检视到达后重新判断，不每轮重新创建相同查询和收费任务。
无法继续或超出授权时提出范围化交接/结束；不因客户未回复就伪造同意，也不让未决事项永久占满全部企业人员。

**ARCHITECT-023｜退出保留可使用成果及剩余责任。** 结束服务时交接当前有效版本和未决问题，按权利处理访问与使用，不默认撤销客户已取得的合法使用范围。
资料移交接收、资源释放、后续支持结束及债务清偿各有状态；重新承担工作须核查范围和资源，不能把历史服务复活成无限免费投入。

### 5.3 正常路径与失败恢复

以下是模型验收叙事，假设相应权限、合同和专业方法已被所选场景支持，不代表真实工程已验证。

**成功：承包商委任的建筑深化服务。**
1. Contractor 发出明确深化需求；建筑师按自身排期和服务风险作 A02 判断，双方完成范围及费用接受，A03 登记服务。
2. A04 安排实际工作，A05 使用获授权的需求/上游成果；A06 仅在委任范围内将空间接口问题交 Engineer/Supplier 回应。
3. 相应问题得到有依据的处理，A08 完成自己有权承担的建筑检查；A07 提交并由各有权主体完成相应用途放行。
4. 施工期间 A09 回应具体查询，未改变设计的解释保留答复；真正变化另记版本与影响，实际施工由 Contractor 推进。
5. A10 按合同申报服务费并核对部分/最终收款；A11 交接有效成果、保留后续支持，完成对应义务后释放资源并关闭服务范围。
6. A12 根据可见返工、投入与回款更新未来报价和排期判断，不回写本项目历史结论。

**失败恢复：新接口造成局部返工且原人员已另排。**
1. Supplier 的新接口资料与现用建筑版本冲突；A09/A06 建问题及影响范围，不能直接改订单或令所有工程停工。
2. A04 检查受影响任务和人员，缺少窗口时提出延后或合法替代安排；未受影响的任务按自己的条件继续。
3. 有权方明确所需变更；建筑师区分原义务整改与新增范围，费用争议另记，在有效工作义务内推进修订。
4. 新输入到达后 A05/A08 完成相应重做与检查，A07 发布适用范围；重复回应不重复记工时或生成版本。
5. 若无法恢复，A11 完成范围化移交，保留已施工事实、问题、合法使用范围及欠费，不把退出写成项目问题已解决。

## 6. 验收场景

下列场景规定实现应满足的结果，须以实际检查记录判定是否通过。流程一致性、真实决策行为、方法校准和现实工程或制度验证分别报告；示意数据不作为真实项目参数。

### 6.1 全生命周期边界

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-ARCHITECT-001 | 项目未成立，只采购场地方案研究 | 可在评估档案及有限授权下服务，不强制完整团队 |
| CHECK-ARCHITECT-002 | 本主体拒绝但建议残留接受数据 | 不形成委任或正式任务占用 |
| CHECK-ARCHITECT-003 | 委托人换选另一家设计方 | 不沿用本主体报价、排期或范围 |
| CHECK-ARCHITECT-004 | 两项目争用同一人员窗口 | 共享排期校验冲突，不复制能力 |
| CHECK-ARCHITECT-005 | 内部团队完成方案 | 记投入成本，不产生组织对自己的服务费 |
| CHECK-ARCHITECT-006 | 一次模型回复称设计完成 | 仍检查任务投入、成果和完成条件 |
| CHECK-ARCHITECT-007 | V2 为草稿，V1 仍获准用于未受影响包 | 不仅因版本号更新就阻止 V1 的合法用途 |
| CHECK-ARCHITECT-008 | 业主认可外观但结构问题未解决 | 不放行依赖该问题的施工用途 |
| CHECK-ARCHITECT-009 | 协调会结束但专业冲突未关闭 | 问题仍开放，不能直接提升为全部通过 |
| CHECK-ARCHITECT-010 | 现场澄清实际改变设计 | 形成版本及影响处理，不以聊天直接改工程 |
| CHECK-ARCHITECT-011 | 需求变化与缺陷整改引起重做 | 分别判断授权、责任和费用，不自动收费或免费 |
| CHECK-ARCHITECT-012 | 报审版被尝试用于施工 | 用途和依赖检查阻止不适用执行 |
| CHECK-ARCHITECT-013 | 待命召回时人员已合法另排 | 检查真实排期，不超配或假定立即返回 |
| CHECK-ARCHITECT-014 | 退出时有未付费和后续支持责任 | 保留义务及合法成果，不自动清零 |
| CHECK-ARCHITECT-015 | 同一提交或收款结果重复到达 | 不重复生成版本、计工或增加现金 |
| CHECK-ARCHITECT-016 | 模型超时或未覆盖某专业检查 | 保留待处理/未验证，不伪造通过 |

### 6.2 前期研究

| 业务验收 | 场景 | 预期 |
|---|---|---|
| CHECK-ARCHITECT-017 | 仅有候选地区和规模范围，无具体场址 | 可作明确假设下的有限比较，不捏造地块条件 |
| CHECK-ARCHITECT-018 | 业主期望时间与现有专业输入冲突 | 提交冲突及调整选项，不擅改目标或承诺实现 |
| CHECK-ARCHITECT-019 | 前期研究完成但尚未成立正式项目 | 成果和应付研究费按授权保留，不自动转为完整设计委任 |
| CHECK-ARCHITECT-020 | 一个候选包含 MiC 与现浇的不同部位 | 记录组合和接口，不以互斥标签拒绝或预设优劣 |
| CHECK-ARCHITECT-021 | 建筑师整理意见但未获其他专业审批权 | 保留原意见与未决问题，不产生“全部专业通过” |
| CHECK-ARCHITECT-022 | QS 成本意见与建筑建议不一致 | 引用同一候选版本、识别差异并迭代，不篡改对方意见 |
| CHECK-ARCHITECT-023 | 需求 V2 只改变一部分用途 | 复核受影响范围，保留未受影响的有效输入及历史记录 |
| CHECK-ARCHITECT-024 | 研究达到预算上限仍缺关键资料 | 提交现状、限制和后续工作建议，不静默无限投入 |
| CHECK-ARCHITECT-025 | 业主商业选中仅供研究的候选 | 不自动取得施工用途、许可或后续设计服务 |

### 6.3 服务资金

| 业务验收 | 场景 | 预期 |
|---|---|---|
| CHECK-ARCHITECT-026 | 限额研究有实际投入但收费条件未满足 | 记录成本和申报状态，不直接增加到期应收或现金 |
| CHECK-ARCHITECT-027 | 合同约定预付款在成果交付前支付 | 按条款记录预收及后续关联，不误判为未交付所以不能付款 |
| CHECK-ARCHITECT-028 | 前期档案转正式项目且换了项目公司 | 不重复收费、不自动替换原债务人 |
| CHECK-ARCHITECT-029 | 内部建筑团队产生报酬成本 | 不产生组织对自己付款；如有真实报酬义务，单独关联实际对象 |
| CHECK-ARCHITECT-030 | 客户回款延迟而外包设计费到期 | 保留独立应付与资金缺口，不自动延期或用应收充现金 |
| CHECK-ARCHITECT-031 | 部分收款后同一回执再次到达 | 仅首次增加现金并冲减对应金额，未清余额继续保留 |
| CHECK-ARCHITECT-032 | 评估撤销但服务费有争议 | 保存原义务、争议和依据，不删除或默认全额清偿 |
| CHECK-ARCHITECT-033 | 设计任务结束但仍欠款 | 按剩余服务释放/保留资源，债务另行保留 |

### 6.4 经营与恢复

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-ARCHITECT-034 | 承包商而非业主委任建筑深化 | 使用正确委托/付款关系，不默认获取业主全部资料 |
| CHECK-ARCHITECT-035 | 新客户高收益但与旧委任排期冲突 | 可以拒绝/限缩；旧承诺不被静默抢占 |
| CHECK-ARCHITECT-036 | 无整合授权却发现跨专业冲突 | 报告本专业接口并请求有权协调，不自封总批准者 |
| CHECK-ARCHITECT-037 | 现场答复改变性能但标成澄清 | 识别变更及影响，不能直接绕过相应授权 |
| CHECK-ARCHITECT-038 | 缺输入任务等待而独立任务就绪 | 依赖部分不产出，独立部分可推进且投入分别记录 |
| CHECK-ARCHITECT-039 | 原任务完成但某用途检查仍未通过 | 保存完成成果，不自动放行该用途 |
| CHECK-ARCHITECT-040 | 服务终止且客户已有合法使用权限 | 按权利移交和处理访问，不自动撤销全部成果使用 |
| CHECK-ARCHITECT-041 | 未决接口反复收到相同通知 | 复用事项和下一触发，不重复收费或假装关闭 |

### 6.5 方案方法与接口

| 编号 | 输入/事件 | 可独立核对的预期 |
|---|---|---|
| CHECK-ARCHITECT-042 | 测试方案含 2 层×100 m² 和 1 层×60 m²，分组不重叠 | 面积明细为 200、60，总建模面积 260 m²；不附带技术/法定通过 |
| CHECK-ARCHITECT-043 | 第二组面积缺失 | 总面积为未知并指向缺项，不能报 200 m² 为完整规模 |
| CHECK-ARCHITECT-044 | 同一部位保留两个互斥构件组合 | 两个条件分支分别交接，不能合并数量和成本 |
| CHECK-ARCHITECT-045 | 编制已完成，工程接口检查仍冲突 | 成果编制状态可完成；相应用途不得因作者完成而自动放行 |
| CHECK-ARCHITECT-046 | 委任被明确拒绝 | 不形成接受、正式占用或已完成设计；技术失败仍使用另一状态 |
| CHECK-ARCHITECT-047 | V2 仅修改一个构件接口 | 对应评估/数量进入影响复核；V1 历史与未受影响发布不被重写 |
| CHECK-ARCHITECT-048 | 暂停恢复请求重复引用已确认投入分片 | 已有投入/成本保持一次，剩余任务与新授权增量可区分 |
| CHECK-ARCHITECT-049 | 有限研究报告完成但所有方案均缺关键场址依据 | 报告可按委任交付，方案仍有限制，不生成“至少一项通过” |
| CHECK-ARCHITECT-050 | 复合项目的道路方案由获授权 Engineer 编制，Architect 只受托附属建筑 | 本主体只交付建筑及约定接口，不强制道路先有建筑方案，也不取得整体批准权 |
| CHECK-ARCHITECT-051 | 普通建筑方法被请求用于未覆盖高度/结构条件的超高层 | 保留不支持/待专项输入，不用地区声誉或复杂度乘数生成通过与完整估算 |
| CHECK-ARCHITECT-052 | 委任已到明确候选/返修边界，又以新分支或技术重试继续 | 按同委任累计，保留已有成果/投入和接续请求；不重置额度，也不把技术等待算施工时间 |

### 6.6 输入输出与核心交接

| 编号 | 契约场景 | 可独立核对的预期 |
|---|---|---|
| CHECK-ARCHITECT-053 | A07 成果、完成证据、范围、接收者及审查要求齐备 | 输出与提交分开；核心提交只建立提交/审查请求，不生成其他用途、合同接受或付款 |
| CHECK-ARCHITECT-054 | A07 缺 task_completion_ref | 返回精确缺项，无伪造成果完成或正式提交 |
| CHECK-ARCHITECT-055 | A07 请求没有权力的施工用途发布 | 绑定拒绝或提交时业务拒绝，无发布、费用或行政决定副作用 |
| CHECK-ARCHITECT-056 | A07 已提交而回执丢失，原身份重试 | 核对原回执，事件/版本/投入/收费只发生一次；真实返修另核任务与费用 |
| CHECK-ARCHITECT-057 | A07 必要依赖不再覆盖拟用范围 | 版本冲突不写成果/发布，原历史保留；仍有效旧版不因新版草稿而无故失效 |

### 6.7 分支输入与业务任务交接

| 编号 | 契约场景 | 预期 |
|---|---|---|
| CHECK-ARCHITECT-058 | A01 提出投标准备，尚无准备业务 Task | 可提交 TaskRequest；授权后创建任务再排期，不虚构 TaskRef、资源占用或费用 |
| CHECK-ARCHITECT-059 | A05 首次编制方案，available_option_refs 为空 | 可按需求与目录编制；比较只能在保存取得方案引用后执行 |
| CHECK-ARCHITECT-060 | A10 催收已有到期申报，本次无新计费计算 | calculation_ref=null 不阻塞催收；原金额及现金不变 |
| CHECK-ARCHITECT-061 | A13 到达限额，未取得可支持推荐的比较方法 | 可交无推荐限制报告；不生成排名、成功方案或后续自动授权 |

## 7. 参数、方法与配置依赖

需要配置的范围如下，不能从参数化方案示例推定默认值。

- **专业与成果**：用途及设计目录、规模/系统变量范围和来源、功能/空间抽象、面积与服务量口径、影响识别粒度、独立检查要求，以及支持下一项商业研究所需的成果成熟度。
- **委任与权限**：D-03 的组织、资格和职能边界；D-06 的委任、采购关系及接续责任；D-10 的退出、合法使用和残余支持。
- **时间、费用与经营**：D-04/D-05 的任务日历、人员与投入单位、工作量估计及排期竞争；收费方式、服务成本、费率、付款期限与争议模板按资金模型明确；D-07 的建筑成果抽象及方法支持；D-09 的信息、报价和经营学习。

未选定目录不阻止有授权的独立调查；它只限制依赖该目录的方案编制、计算或用途结论。

未选定的方法、阈值、时间粒度、资格和产品条件须显式保持待定；不得以示例值、角色标签或未覆盖范围补成正式结论。具体选择登记在[模型决策](../07_experiments/model_decisions.md)，使用前绑定方法、数据和参数版本。
