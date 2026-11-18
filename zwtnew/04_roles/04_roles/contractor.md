# Contractor｜承包商主体主规范

定义承包企业在大湾区仿真中的投标、合同履约、采购施工、交付、收付款与责任收尾行为。本文是角色开发规范；方法支持范围和待选参数见第 7 节，实现与验证证据单独记录。

[总体运行框架](../02_world/world_runtime.md) · [共同对象与状态](../02_world/domain_objects.md) · [跨主体交接](../03_projects/collaboration_flow.md) · [模型决策](../07_experiments/model_decisions.md)

<!-- page-nav:start -->
**本页导航**

[1. 职责、目标与权限](#1-职责目标与权限) · [2. 信息、状态与业务对象](#2-信息状态与业务对象) · [3. 行为卡与执行契约](#3-行为卡与执行契约)

[4. 专业工作与跨主体交互](#4-专业工作与跨主体交互) · [5. 状态转换、失败与恢复](#5-状态转换失败与恢复) · [6. 验收场景](#6-验收场景)

[7. 参数、方法与配置依赖](#7-参数方法与配置依赖)
<!-- page-nav:end -->

## 1. 职责、目标与权限

### 1.1 主体身份与授权

**CONTRACTOR-001｜主体持续存在。** 每个承包企业有独立身份、经营资源、资金约束、项目组合和私有认知；项目结束不删除企业，也不自动清除其义务。
同一组织兼任设计方、制造方或供应商时，须有对应授权，并共享实际资金和能力，不能复制身份获得额外资源。

| 边界 | 本角色的目标语义 |
|---|---|
| 经营目标 | 在可承受风险下获取业务、维持现金与产能、履行已承诺合同并积累合作经验；目标权重待定义 |
| 项目责任 | 按合同组织约定工程范围；总承包、专业承包、D&B 等模板分别确定设计和接口责任 |
| 决策权 | 判断参投、提出报价、接受条款、安排投入、提出变更/索赔及补救请求 |
| 权限边界 | 不代业主接受投资或付款，不代监管签发许可，不代顾问认可设计，不替供应商承诺生产 |
| 未建模服务 | 分包、运输、检测等尚未有独立主体时，用有来源和履约状态的外部接口表达 |

**CONTRACTOR-002｜目标与约束分开。** 高利润意向不能放宽资格、施工放行、资源、现金或安全条件；报价胜出也不等于具备履约条件。
投标阶段的风险判断、履约中实际发生的问题和最终责任分别记录，不将预期利润当作实现利润。

### 1.2 独立判断与经营取舍

**CONTRACTOR-022｜管理组合而非逐项目孤立最优。** 企业比较新业务与在手义务，保存利润、现金、队伍连续性、履约风险和关系目标的取舍。
高报价可能失去业务，低报价可能带来现金压力；赶工可能占用另一项目的资源，保留待命队伍也有成本与机会损失。
这些冲突进入本企业可见的比较依据，不预置统一最优答案；目标权重和学习机制仍待定。
企业可不参投、拒绝新增范围、调整合法任务次序或请求修订，不能因系统希望项目继续就自动接受亏损或超额承诺。
自己的预测、实际观察和正式结果分别保存；工程结果没有发生前，不能借未来真实成本反算当初投标判断。
未中标仍可能发生投标准备成本，参与前期咨询也不保证后续合同；失败业务可影响未来判断，但不自动提高或降低能力分。

## 2. 信息、状态与业务对象

### 2.1 可见信息与权限边界

**CONTRACTOR-003｜按权限观察。** 承包商使用已收到的采购文件、澄清、设计/许可、合同及自身账本作判断。
竞争者底价、业主全部现金、供应商内部排期和隐藏质量缺陷不默认可见；未知项保留来源、时点和不确定性。

| 状态组 | 主体掌握或提出 | 正式状态的提交者与边界 |
|---|---|---|
| 私有经营判断 | 成本预测、目标报价、风险容忍、伙伴信任、投标意图 | 本主体认知；不改写其他主体记忆 |
| 投标与谈判 | 报价版本、例外条件、承诺意向、接受/拒绝 | 核心按授权、有效期及适用程序提交 |
| 资源与排期 | 拟投入队伍/设备、采购计划、调配请求 | 资源账本统一预留、占用、冲突处理与释放 |
| 工程与质量 | 实际工作记录、检查申请、问题报告、整改计划 | 履约计算和有权核验形成工程事实及缺陷状态 |
| 合同与资金 | 变更/索赔、计量申请、付款请求、预测 | 合同及资金入口分别提交有效变更、义务与实际收付 |

**CONTRACTOR-004｜保留相互独立的状态。** 区分未参投、投标准备、有效报价、被选中、有效合同、动员、施工、暂停、移交、缺陷责任与财务未结。
同一企业可在不同项目处于不同状态；项目的工程完成不自动将承包商全部关系标为关闭。

### 2.2 正式状态与私有判断的所有者

| 状态 | 本企业可以做什么 | 正式所有者及禁止越界 |
|---|---|---|
| 机会判断、底价、预计利润、伙伴评价 | 按本企业可见证据更新，选择披露范围 | 本企业私有认知；不改写对方判断或真实合同 |
| 报价和合同回应 | 提出版本、接受、修订或合法撤回 | 采购/合同入口校验权限与双方适用接受，不由草稿直接生效 |
| 队伍、设备和工作排期 | 提出分配、替代、召回和释放请求 | 共享资源账本按身份、数量、时段提交；项目副本不能独占同一资源 |
| 工作包、工程量和材料消耗 | 提出施工安排、报告事实依据与异常 | 核心按有效投入、依赖和计算规则提交，主体不能直接改百分比 |
| 检查和问题 | 自检、申请外部核验、提出整改证据 | 对应有权检查/接受入口确认适用范围，不由风险分清除缺陷 |
| 现金、应收应付和贷款 | 查询获授权记录、申请、收付款与核对 | 统一资金入口处理实际执行、配对义务及清偿；预测不充当现金 |

核心持有正式资源与工程状态，不代表承包商知道其他企业全部产能、价格或隐藏质量真值。
承包商可读取自身有效承诺及获授权现场事实；未知、待核、真实拒绝和技术无结果保持不同状态。

### 2.3 关键对象及字段

以下为语义字段，允许实施时采用其他名称；对象身份、单位、版本和相互引用不能省略。

| 对象 | 至少保留的内容 | 核心约束 |
|---|---|---|
| 采购包与报价 | 包身份/版本、雇主、范围、设计引用、价格/币种、期限、条件、回应 | 选择身份与整套报价一致，修订有来源 |
| 工作包 | `work_package_id`、范围/位置、合同、工程量/单位、成果版本、责任者 | 原范围、批准变更与剩余工作可核对，不用全项目百分比代替 |
| 依赖与放行 | 前置工作及所需结果、许可/用途、场地条件、材料要求、证据版本 | 只满足被明确要求的条件才放行，依赖循环要暴露 |
| 资源分配 | 资源身份/类型、数量/单位、时段、承诺来源、临时/正式、释放条件 | 人员、设备、材料和场地不可无依据互换 |
| 工作记录 | 执行身份、工作包/版本、期间、投入、毛完成量、消耗、成本与依据 | 同一执行重试不新增产出，报告与正式记录可区分 |
| 检查及返工 | 检查身份、覆盖数量/范围、标准、结果、问题、返工任务与复检 | 认可范围、不可用量、返工投入和责任分别关联 |
| 接收与计量 | 可使用范围、实际采用批次、获接受工程量、计价/核证及历史引用 | 收货不等于已安装，工程认可不直接增加现金 |
| 实际交付清单 | 清单 ID/版本、交付范围、实际工作/产品批次/数量、实际采用的设计规格、检查/试验、有效偏离及未决项 | 引用已发生记录，不以最新设计重写实际配置；核验和接收引用同一范围/版本 |
| 暂停与接续 | 生效范围/时间、依据、保护任务、资源去向、现场资产和未清事项 | 退出或换承包商保留已有成果来源，防止重复建设/计价 |

**CONTRACTOR-036｜交付依据实际配置而不是最新设计。** A11 申报分范围交付时编制实际交付清单，关联合同/有效变更、工作记录、安装或交付批次/数量、各范围采用版本、相应检查/试验、获准偏离与未决项。它是已有可核实事实的汇集，不增加工程量或安装事实；未知部分保持待核，不读取无权获得的隐藏质量真值。最新草稿、未实施修订和未接受替代不能直接充当实际配置。

多个合法版本并存时按实际范围列明，相邻/共同系统接口交已绑定的有权主体核验。既有报告须与实际输入配置/范围匹配或有明确复用依据，才可用于此次交付。承包商跟进缺项和真实提供者；接收方按合同决定接收范围，专业核验和适用使用申请引用该清单版本及各自证据，不以一方接受替代其他决定。

例如 A 区按仍有效 V1 安装 X，V2 只改变未施工的 B 区为 Y，随后 B 按 V2 实施：清单保留 A/V1/X 与 B/V2/Y。仅覆盖 X/X 的系统报告不自动适用于 X/Y；未核实接口限制依赖范围，不使独立部分全部倒退，也不删除已做工程。

## 3. 行为卡与执行契约

行为卡定义触发、选择和结果边界；执行矩阵集中说明跨行为的资源、时间、阻塞与接收方。正式输出均须经共同提交入口校验；模型回复不代替业务任务投入。

以下行为卡是目标能力，不表示每项均须调用 LLM。每次决定引用对象 ID、版本、观察截止时点和权限；固定计算由专门模块执行。

<!-- action-nav:start -->
**动作定位**：[CONTRACTOR-A01｜观察机会并筛选是否参投](#contractor-a01观察机会并筛选是否参投) · [CONTRACTOR-A02｜形成投标方案与报价](#contractor-a02形成投标方案与报价) · [CONTRACTOR-A03｜处理澄清、修改和撤回](#contractor-a03处理澄清修改和撤回) · [CONTRACTOR-A04｜判断授标与形成合同承诺](#contractor-a04判断授标与形成合同承诺) · [CONTRACTOR-A05｜制定履约排期并采购供应](#contractor-a05制定履约排期并采购供应) · [CONTRACTOR-A06｜核对动员与具体施工放行](#contractor-a06核对动员与具体施工放行) · [CONTRACTOR-A07｜安排施工、报告进展并调整投入](#contractor-a07安排施工报告进展并调整投入) · [CONTRACTOR-A08｜检查质量、安全并组织整改](#contractor-a08检查质量安全并组织整改) · [CONTRACTOR-A09｜处理设计接口、变更与索赔](#contractor-a09处理设计接口变更与索赔) · [CONTRACTOR-A10｜申请计量、收款并支付下游](#contractor-a10申请计量收款并支付下游) · [CONTRACTOR-A11｜交付、缺陷责任与最终结算](#contractor-a11交付缺陷责任与最终结算) · [CONTRACTOR-A12｜暂停、退出、接续与经营反馈](#contractor-a12暂停退出接续与经营反馈) · [CONTRACTOR-A13｜可选参与前期可建造性与施工组织咨询](#contractor-a13可选参与前期可建造性与施工组织咨询)
<!-- action-nav:end -->

### CONTRACTOR-A01｜观察机会并筛选是否参投

- **触发与输入**：收到有效邀请或发现可公开获取的采购包；读取范围、地区、资格、期限、资金信号及自身在手任务。
- **本主体决定**：参投、请求澄清、等待信息或不参投；识别资格不足、排期冲突和风险来源。
- **提交与交接**：登记该企业对该采购包版本的意向；向采购授权方发送必要的资格或澄清请求。
- **异常与观察**：信息缺失不等于拒标；技术无结果保持待处理，适用截止条件继续按已定规则运行。

**函数与类型契约**

- **函数**：`roles.contractor.a01(ctx: ActionContext, input: ContractorA01Input) -> ActionResult<ContractorA01Payload>`。
- **输入记录**：`ContractorA01Input = {invitation_refs: List<Ref<Invitation>>, package_ref: Ref<ProcurementPackage>, capability_ref: Ref<ContractorCapability>, qualification_refs: List<Ref<Qualification>>, commitments_ref: Ref<CommitmentSnapshot>, screening_profile_ref: Ref<OpportunityScreeningProfile>}`。
- **输出分支**：`ContractorA01Payload`：`{choice: participate / clarify / decline, package_ref: Ref<ProcurementPackage>, basis_refs: List<Ref<Evidence>>, note: string}`；澄清含 `requirement_refs: List<Ref<Requirement>>`。
- **来源、接收与核心效果**：可见招采/本企业能力 → 采购方/A02；登记意向或查询，不建合同、报价或交付占用。
- **分支前置与约束**：公开采购包可无 invitation_refs；participate 只形成参投意向，不要求已形成投标。资格未知返回信息缺口，已知不满足才拒绝相应参投。
- **业务出口与验收**：无资格不得投标；技术失败不是拒绝；缺资料请求信息。CHECK-CONTRACTOR-001/017/051。


### CONTRACTOR-A02｜形成投标方案与报价

- **触发与输入**：决定投入投标准备；获得允许用途的设计/性能要求、工程量或计价依据和市场信息。
- **本主体决定**：组织施工方案、资源计划、供应询价、风险取舍及报价；选择允许的商业条款和报价策略。
- **提交与交接**：形成有版本的报价、范围、排除项、币种、有效期、工期和假设，按采购程序提交。
- **异常与观察**：关键依据不足可澄清或退出；报价金额与内部成本预测分开，投标准备成本另记。

**函数与类型契约**

- **函数**：`roles.contractor.a02(ctx: ActionContext, input: ContractorA02Input) -> ActionResult<ContractorA02Payload>`。
- **输入记录**：`ContractorA02Input = {package_ref: Ref<ProcurementPackage>, deliverable_refs: List<Ref<ReleasedDeliverable>>, quantity_refs: List<Ref<QuantityBasis>>, cost_refs: List<Ref<CostBasis>>, capacity_ref: Ref<ContractorCapacity>, pricing_profile_ref: Ref<ContractorPricingProfile>, allowed_method_refs: List<Ref<WorkMethod>>}`。
- **输出分支**：`ContractorA02Payload`：`{choice: submit_bid / decline_bid, note: string}`；投标含 `bid: ContractorBidDraft, planned_tasks: List<ContractorTaskDraft>`。
- **来源、接收与核心效果**：采购成果/正式成本与自身计划 → Owner/QS/A03；可提出报价/计划，不自动锁队伍或宣称工程已放行。
- **分支前置与约束**：采购允许的性能要求/设计成熟度由 package_ref 决定，不要求所有招标已有施工放行成果。submit_bid 必须可计价且满足采购模板；planned_tasks 是报价方案，不能因创建任务草稿扣减施工可用量。
- **业务出口与验收**：缺工效/价量方法返回 `unsupported`；不完整范围先澄清或按模板明确限报。CHECK-CONTRACTOR-002/030/044/053。


### CONTRACTOR-A03｜处理澄清、修改和撤回

- **触发与输入**：收到补充文件、评审问题或发现自身报价错误；比较原文件与最新有效版本。
- **本主体决定**：解释、按规则修订、维持报价或提出撤回；评估变更对数量、工期和风险的影响。
- **提交与交接**：保存每版报价和收到通知的时间，向有权接收方提交；不得通过私聊直接替换正式投标。
- **异常与观察**：过期、迟交和撤回按适用模板处理；技术发送未知先核对同一提交 ID。

**函数与类型契约**

- **函数**：`roles.contractor.a03(ctx: ActionContext, input: ContractorA03Input) -> ActionResult<ContractorA03Payload>`。
- **输入记录**：`ContractorA03Input = {bid_ref: Ref<Bid>, clarification_refs: List<Ref<ClarificationRequest>>, package_ref: Ref<ProcurementPackage>, round_ref: Ref<TenderRound>, amendment_rule_ref: Ref<TenderAmendmentRule>, reservation_refs: List<Ref<ResourceReservation>>}`。
- **输出分支**：`ContractorA03Payload`：`{choice: explain / revise / maintain / withdraw, prior_bid_ref: Ref<Bid>, note: string}`；解释含 `answers: List<ContractorResponseDraft>`；修订含 `replacement_bid: ContractorBidDraft, changed_requirement_refs: List<Ref<Requirement>>`。
- **来源、接收与核心效果**：招标澄清/修订通知 → 采购方/QS/A04；可替换报价或撤回，保留旧版，不静默套新版条款。
- **分支前置与约束**：修订生成新报价内容，核验与旧采购包/轮次的替代关系；维持旧报价不能自动承诺未读的新范围。未知提交先按原 command_id/报价身份核对，再决定是否需要新业务修订。
- **业务出口与验收**：时限不符保留拒收结果；提交未知核对原身份；撤回只释放本次临时预留。CHECK-CONTRACTOR-002/031。


### CONTRACTOR-A04｜判断授标与形成合同承诺

- **触发与输入**：收到授标意向或最终合同条款；核对范围、报价版本、付款、工期、设计和风险责任。
- **本主体决定**：明确接受、请求修订或拒绝；在最终提交前重新核对跨项目资源及资金承受力。
- **提交与交接**：按适用合同形成规则登记有效接受，核心建立合同、承诺及条件；对方选择本企业不自动代表本企业接受新条款。
- **异常与观察**：动作名称与接受字段冲突、旧版接受或资源不足时不签约；记录可调整路径。

**函数与类型契约**

- **函数**：`roles.contractor.a04(ctx: ActionContext, input: ContractorA04Input) -> ActionResult<ContractorA04Payload>`。
- **输入记录**：`ContractorA04Input = {offer_ref: Ref<ContractOffer>, terms_ref: Ref<ContractTerms>, counterpart_acceptance_refs: List<Ref<PartyAcceptance>>, authority_ref: Ref<Authorization>, capacity_ref: Ref<ContractorCapacity>, funding_ref: Ref<FundingPosition>, formation_profile_ref: Ref<ContractFormationProfile>}`。
- **输出分支**：`ContractorA04Payload`：`{choice: accept / revise / reject, note: string}`；接受含 `offer_ref: Ref<ContractOffer>, terms_ref: Ref<ContractTerms>, proposed_allocations: List<ContractorAllocation>`；修订含 `requirement_changes: List<Ref<ContractChangeRequest>>`。
- **来源、接收与核心效果**：双方同版条款/实时容量 → 合同核心/采购方；己方接受仅在合同门槛满足后形成关系和承诺。
- **分支前置与约束**：counterpart_acceptance_refs 为空仅表示尚未收到对方有效接受，允许提出己方接受但不产生生效合同。接受范围、条款与拟分配必须属于同一报价版本；实际占用由核心按既定竞争协议提交。
- **业务出口与验收**：拒绝不残留接受字段；共享队伍竞争统一处理，不复制资源。CHECK-CONTRACTOR-003/004/030/031。


### CONTRACTOR-A05｜制定履约排期并采购供应

- **触发与输入**：获准开展相应准备工作；读取有效合同或独立准备授权、工作包前置关系、设计版本、交期和现场接收限制。
- **本主体决定**：提出队伍/设备投入和供应批次，向 [Supplier](supplier.md) 询价并从有效报价中选择。
- **提交与交接**：发出范围、数量、交付窗口、检验和付款条件明确的采购请求；核心成套绑定供应商及订单版本。
- **异常与观察**：供应商可拒绝；无人可供、交期冲突或替代方案需新批准时，调整受影响计划，不伪造供货。

**函数与类型契约**

- **函数**：`roles.contractor.a05(ctx: ActionContext, input: ContractorA05Input) -> ActionResult<ContractorA05Payload>`。
- **输入记录**：`ContractorA05Input = {work_basis: ContractorWorkBasis, authorized_scope_ref: ScopeRef, dependency_refs: List<Ref<Dependency>>, design_refs: List<Ref<ReleasedDeliverable>>, capacity_ref: Ref<ContractorCapacity>, supplier_offer_refs: List<Ref<SupplyOffer>>, work_method_refs: List<Ref<WorkMethod>>}`。
- **输出分支**：`ContractorA05Payload`：`{choice: plan / request_quote / accept_supply_offer / revise_plan, note: string}`；`plan/revise_plan` 含 `tasks: List<ContractorTaskDraft>`；`revise_plan` 另含 `prior_plan_ref: Ref<WorkPlan>`；询价含 `requirement_refs: List<Ref<SupplyRequirement>>, supplier_ids: List<EntityId<Organization>>`；接受含 `offer_ref: Ref<SupplyOffer>, order_terms_ref: Ref<SupplyTerms>, receiving_window_ref: Ref<TimeWindow>`。
- **来源、接收与核心效果**：合同/设计/供应报价 → 资源核心/Supplier A01/A04；可排任务、询价、己方接受，不代供应商接单或直接造库存。
- **分支前置与约束**：work_basis 可为施工合同或单独有效的前期工作授权；后者只允许授权范围内准备，不解锁施工或大额采购。request_quote 允许 supplier_offer_refs 为空；accept_supply_offer 才需有效报价，采购责任人与接收窗口仍须核验。
- **业务出口与验收**：无供给可改排；换供应商所有条款引用必须同源；循环依赖暴露责任。CHECK-CONTRACTOR-005/006/032/042/052。


### CONTRACTOR-A06｜核对动员与具体施工放行

- **触发与输入**：计划启动某工作包；检查现场交付、适用许可、可施工成果、必要资源、材料和授权。
- **本主体决定**：准备开工、请求补齐条件、调整先后顺序；D&B 下另协调其负责的设计与专业检查。
- **提交与交接**：提交就绪证据和投入请求；核心只放行满足条件的范围，其他独立工作包可继续。
- **异常与观察**：签约、供应商已选或发言“准备完成”不能替代就绪证据；缺必要投入的任务保持阻塞。

**函数与类型契约**

- **函数**：`roles.contractor.a06(ctx: ActionContext, input: ContractorA06Input) -> ActionResult<ContractorA06Payload>`。
- **输入记录**：`ContractorA06Input = {task_ref: Ref<Task>, readiness_requirement_refs: List<Ref<Requirement>>, permit_refs: List<Ref<Permit>>, design_release_refs: List<Ref<DeliverableRelease>>, site_refs: List<Ref<SiteReadiness>>, input_allocation_refs: List<Ref<ResourceAllocation>>, readiness_profile_ref: Ref<ReadinessProfile>}`。
- **输出分支**：`ContractorA06Payload`：`{choice: request_release / rectify_dependency / resequence, task_ref: Ref<Task>, note: string}`；放行含 `evidence_refs: List<Ref<Evidence>>`；补齐含 `issues: List<ContractorIssue>`；改序含 `replacement_task_refs: List<Ref<Task>>`。
- **来源、接收与核心效果**：许可/现场/实际投入证据 → 核心门控/A07/负责补件方；只能申请具体任务放行，不自行批准许可或替专业核验。
- **分支前置与约束**：permit_refs/design_release_refs 可为空表示尚未取得，本动作仍能输出 rectify_dependency/resequence；request_release 才要求所选任务必要证据齐备。核对任务就绪不将缺证一律写成法规不允许。
- **业务出口与验收**：必要依赖缺失只阻塞相关范围；没有资源不虚报就绪。CHECK-CONTRACTOR-007/008/032/053。


### CONTRACTOR-A07｜安排施工、报告进展并调整投入

- **触发与输入**：已放行任务进入执行窗口；读取实际到岗、设备、可用材料、前置完成量和外部条件。
- **本主体决定**：在许可范围内调配资源、选择可行施工方案、协调接口并报告障碍。
- **提交与交接**：履约模块据真实模型投入和待校准的生产规则计算完成量、消耗与成本，形成工程记录。
- **异常与观察**：LLM 不直接写进度百分比或实际成本；赶工选择的生产率、成本和质量后果需明确模型依据。

**函数与类型契约**

- **函数**：`roles.contractor.a07(ctx: ActionContext, input: ContractorA07Input) -> ActionResult<ContractorA07Payload>`。
- **输入记录**：`ContractorA07Input = {scope_ref: ScopeRef, execution_context: ContractorExecutionContext}`。
- **输出分支**：`ContractorA07Payload`：`{choice: execute / rebalance / report / reconcile, note: string}`；`execute/rebalance` 含 `task_ref: Ref<Task>, allocations: List<ContractorAllocation>, materials: List<ContractorMaterialUse>`；`report` 含 `report: ContractorProgressReportDraft`；`reconcile` 含 `execution_refs: List<Ref<WorkExecution>>`。
- **来源、接收与核心效果**：放行和真实投入 → 确定性工程计算/现场报告/QS；只提交投入意图，完成量、消耗、成本和实际配置由核心计算。
- **分支前置与约束**：execute/rebalance 仅匹配 ready；report 匹配 report；reconcile 匹配 existing。当前许可已暂停、没有新材料或旧任务已关闭，不阻止核对历史实际执行；报告施工受阻可以没有已完成 WorkExecution，不伪造完成量。
- **业务出口与验收**：零必要投入无产出；未知执行先核对；返工增加实际投入但净工程量不重计。CHECK-CONTRACTOR-008/009/033/034/038/049。


### CONTRACTOR-A08｜检查质量、安全并组织整改

- **触发与输入**：自检、通知检查或发现问题；读取具体工作包、材料批次、检查结果和适用要求。
- **本主体决定**：隔离问题范围、停止不安全作业、提交整改方案、申请复检；不能自称已获外部认可。
- **提交与交接**：记录缺陷、责任待定项、整改投入及复检；向有权顾问或 [Government](government.md) 提交相应证据。
- **异常与观察**：发现问题、技术合格、责任归属与费用承担分开；不以降低一个风险分代替整改完成。

**函数与类型契约**

- **函数**：`roles.contractor.a08(ctx: ActionContext, input: ContractorA08Input) -> ActionResult<ContractorA08Payload>`。
- **输入记录**：`ContractorA08Input = {scope_ref: ScopeRef, work_record_refs: List<Ref<WorkRecord>>, requirement_refs: List<Ref<InspectionRequirement>>, defect_refs: List<Ref<Defect>>, evidence_refs: List<Ref<InspectionEvidence>>, inspection_profile_ref: Ref<InspectionProfile>}`。
- **输出分支**：`ContractorA08Payload`：`{choice: self_check / request_external_check / isolate / rectify / request_recheck, scope_ref: ScopeRef, note: string}`；`self_check/request_external_check/request_recheck` 含 `method_ref: Ref<InspectionMethod>, evidence_refs: List<Ref<InspectionEvidence>>`；`request_recheck` 另含 `prior_inspection_ref: Ref<InspectionResult>, defect_refs: List<Ref<Defect>>`；隔离含 `issue_refs: List<Ref<Defect>>`；整改含 `tasks: List<ContractorTaskDraft>, defect_refs: List<Ref<Defect>>`。
- **来源、接收与核心效果**：施工事实/实际可见问题 → 检查核心/Engineer/有权检查方；建立检查、隔离及整改任务，不自行关闭未核验缺陷。
- **分支前置与约束**：只接受主体已经观察到的缺陷，不从隐藏质量真值推导检查结论。隔离/整改必须限定实际范围；返工与首次施工分开登记，合格净完成量按实物覆盖去重。
- **业务出口与验收**：无核验方法 `unsupported`；未复检不恢复；已安装报废不得全量返库。CHECK-CONTRACTOR-011/034/035/043/050。


### CONTRACTOR-A09｜处理设计接口、变更与索赔

- **触发与输入**：设计冲突、业主需求改变、不可预见条件或延期影响；引用具体合同、图纸和事件版本。
- **本主体决定**：请求澄清、提出替代/变更方案、估计费用和工期影响，按程序发出通知或索赔。
- **提交与交接**：向有权设计/合同主体提交；正式变更由授权和适用程序确认后影响合同与受影响工作包。
- **异常与观察**：建议、指令、已认可金额与争议项分开；既有有效义务和紧急处置按条款处理，不等于所有工作都等待一致同意。

**函数与类型契约**

- **函数**：`roles.contractor.a09(ctx: ActionContext, input: ContractorA09Input) -> ActionResult<ContractorA09Payload>`。
- **输入记录**：`ContractorA09Input = {contract_ref: Ref<Contract>, baseline_design_refs: List<Ref<Deliverable>>, instruction_refs: List<Ref<ContractInstruction>>, issue_refs: List<Ref<InterfaceIssue>>, actual_cost_refs: List<Ref<CostRecord>>, claim_profile_ref: Ref<ClaimProfile>}`。
- **输出分支**：`ContractorA09Payload`：`{choice: clarify / propose_change / submit_claim / respond / dispute, scope_ref: ScopeRef, note: string}`；澄清/回应含 `issues: List<ContractorIssue>`；变更/索赔含 `basis_refs: List<Ref<Evidence>>, proposed_amount: ValueState<Money>, time_impact: ValueState<Ref<TimeImpactAssessment>>, affected_task_refs: List<Ref<Task>>`；争议含 `claim_ref: Ref<Claim>`。
- **来源、接收与核心效果**：有效指令/实际影响 → Architect/Engineer/QS/Owner；仅申报请求或独立回应，不能单方改价/改法定许可。
- **分支前置与约束**：未知费用/工期可作为初始通知或待完善提案，但不能成为已确定价款/展期。正式变更必须含可解析的具体变更范围与受影响任务，不能只写金额；尚无实际支出时 actual_cost_refs 可为空，预估与已发生成本分列。
- **业务出口与验收**：估计缺额保留未知，不视为正式可结算索赔；变更只重查受影响范围。CHECK-CONTRACTOR-010/014/022/038。


### CONTRACTOR-A10｜申请计量、收款并支付下游

- **触发与输入**：计量或付款节点到期；读取实际工程记录、有效变更、合同计价及已付明细。
- **本主体决定**：提出工程款申请、回应核证意见、管理现金预测，并对自身到期供货/分包款发起支付。
- **提交与交接**：向有权 [QS](qs.md)/业主提交计量依据；资金入口按义务与可用资金执行，银行融资另按 [Bank](bank.md) 处理。
- **异常与观察**：申请、核证、到期、实际到账分开；上游拖欠不自动免除下游债务，停工或抵扣须有适用依据。

**函数与类型契约**

- **函数**：`roles.contractor.a10(ctx: ActionContext, input: ContractorA10Input) -> ActionResult<ContractorA10Payload>`。
- **输入记录**：`ContractorA10Input = {contract_ref: Ref<Contract>, work_record_refs: List<Ref<WorkRecord>>, certificate_refs: List<Ref<PaymentCertificate>>, obligation_refs: List<Ref<Obligation>>, account_refs: List<Ref<Account>>, execution_refs: List<Ref<PaymentExecution>>, settlement_rule_ref: Ref<SettlementRule>}`。
- **输出分支**：`ContractorA10Payload`：`{choice: apply_measurement / request_payment / authorize_payment / seek_finance / reconcile / dispute, note: string}`；`apply_measurement` 含 `request: ContractorMeasurementDraft`；`request_payment` 含 `basis_refs: List<Ref<Evidence>>, component_refs: List<Ref<SettlementComponent>>`；`authorize_payment` 含 `account_ref: Ref<Account>, lines: List<ContractorPaymentLine>`；`seek_finance` 含 `application: FinanceApplicationDraft`；`reconcile` 含 `execution_refs: List<Ref<PaymentExecution>>`；`dispute` 含 `obligation_refs: List<Ref<Obligation>>, issue_refs: List<Ref<Issue>>`。
- **来源、接收与核心效果**：工程/核证/账本 → QS/真实付款人/Bank/上游；核证、应收与现金分别提交，不穿透使用 Owner 现金。
- **分支前置与约束**：首次 apply_measurement 不要求付款证书或结算组成已经存在；请求草稿由计量服务/QS 核查后登记相应结果。seek_finance 生成申请再交 Bank A02；不要求银行已受理。request_payment 需既有可请款组成，authorize_payment 需本企业真实义务和账户，不使用业主余额。
- **业务出口与验收**：部分款仅清偿对应组成；未知先查原执行；迟付不免下游债务；抵扣不二次扣现金。CHECK-CONTRACTOR-012/013/024/025/026/027/028/029/039。


### CONTRACTOR-A11｜交付、缺陷责任与最终结算

- **触发与输入**：具备报验或分批交付条件；整理竣工资料、测试、未结问题、变更及收付款记录。
- **本主体决定**：申请检查/移交、提出结算、接受或质疑核定，并安排仍属本方责任的整改。
- **提交与交接**：向有权接收方交付；工程完成、使用许可、业主接收、缺陷关闭、结算与清偿分别形成状态。
- **异常与观察**：结算额不预设等于实际成本；移交后仍保留适用缺陷、保证和未付款义务。

**函数与类型契约**

- **函数**：`roles.contractor.a11(ctx: ActionContext, input: ContractorA11Input) -> ActionResult<ContractorA11Payload>`。
- **输入记录**：`ContractorA11Input = {contract_ref: Ref<Contract>, scope_ref: ScopeRef, as_built_refs: List<Ref<AsBuiltRecord>>, verification_refs: List<Ref<Verification>>, defect_refs: List<Ref<Defect>>, settlement_components: List<Ref<SettlementComponent>>, handover_profile_ref: Ref<HandoverProfile>}`。
- **输出分支**：`ContractorA11Payload`：`{choice: submit_handover / rectify / propose_final_account / respond_settlement, note: string}`；移交含 `scope_ref: ScopeRef, evidence_refs: List<Ref<Evidence>>, remaining_issue_refs: List<Ref<Issue>>`；整改含 `tasks: List<ContractorTaskDraft>`；结算含 `component_refs: List<Ref<SettlementComponent>>, disputed_refs: List<Ref<SettlementComponent>>`。
- **来源、接收与核心效果**：实际建成配置/核验 → Owner/有权接收方/QS；提交报验、结算提议，不代接收/财务清偿。
- **分支前置与约束**：submit_handover 可包含尚未通过的待验范围及尾项，不等于工程接收；rectify 只创建获授权整改任务。结算回应逐项列清认可和争议范围，移交/结算事件不直接清偿债务。
- **业务出口与验收**：混合配置按实际核验；工程移交不删下游欠款及缺陷责任。CHECK-CONTRACTOR-015/037/049/050。


### CONTRACTOR-A12｜暂停、退出、接续与经营反馈

- **触发与输入**：合法暂停/终止、资源或资金困难、项目取消、责任收尾或新业务机会。
- **本主体决定**：请求补救、恢复、替代履约或退出；处理现场保护、材料、资料与接续安排。
- **提交与交接**：核心按有效依据处理资源和合同；保留欠款、争议、历史成果和仍有效责任，再更新本企业判断。
- **异常与观察**：企业退出某项目不等于破产；仿真截止时仍未清义务继续列示，不能自动写“全部完成”。

**函数与类型契约**

- **函数**：`roles.contractor.a12(ctx: ActionContext, input: ContractorA12Input) -> ActionResult<ContractorA12Payload>`。
- **输入记录**：`ContractorA12Input = {scope_ref: ScopeRef, authority_basis_refs: List<Ref<Evidence>>, resource_commitment_refs: List<Ref<ResourceCommitment>>, material_position_refs: List<Ref<InventoryPosition>>, obligation_refs: List<Ref<Obligation>>, continuation_profile_ref: Ref<ContinuationProfile>, observation_refs: List<Ref<Observation>>}`。
- **输出分支**：`ContractorA12Payload`：`{choice: protect / suspend / resume / handover / exit / record_lesson, note: string}`；`protect/suspend/resume/handover/exit` 含 `scope_ref: ScopeRef, retain_resource_refs: List<Ref<ResourceCommitment>>, release_candidate_refs: List<Ref<ResourceCommitment>>, remaining_obligation_refs: List<Ref<Obligation>>`；移交含 `successor_id: EntityId<Organization>, transfer_evidence_refs: List<Ref<Evidence>>`；恢复含 `readiness_refs: List<Ref<Verification>>`；经验含 `source_refs: List<Ref<Observation>>, learning_method_ref: Ref<LearningMethod>`。
- **来源、接收与核心效果**：现场/权利/经营状态 → 雇主/资源核心/接续方/私有认知；逐项释放及交接，不能删除原执行或责任。
- **分支前置与约束**：record_lesson 不改变原合同、库存或剩余义务；业务接续的保留/释放列表只是请求，核心按实际占用与待核对执行计算。移交给 successor 还需其有效接受和职责授权，不以本方声明完成转移。
- **业务出口与验收**：恢复重查已调走资源；前任迟到结果仍核对，接续方只做余量。CHECK-CONTRACTOR-016/027/036/037/046。


### CONTRACTOR-A13｜可选参与前期可建造性与施工组织咨询

- **触发与输入**：收到有权主体对备选方案的咨询，核对业主建设目的、地区、规模区间、期望交付时间，以及可披露的专业方案和现场资料。
- **本主体决定**：在明确的有限服务范围内接受、约定付费研究、同意有边界的免费交流、提出补充要求或拒绝；可比较不同施工组织与投入方案。
- **提交与交接**：形成有版本的可建造性意见、施工顺序、投入和工期区间，交给有权委托方及获授权专业主体；正式记录受托范围、工作消耗与费用义务。
- **异常与观察**：没有完整设计仍可提供限定范围的意见，关键输入缺失则标明无法判断的部分；技术失败不编造成负面工程结论或有效报价。

**函数与类型契约**

- **函数**：`roles.contractor.a13(ctx: ActionContext, input: ContractorA13Input) -> ActionResult<ContractorA13Payload>`。
- **输入记录**：`ContractorA13Input = {brief_ref: Ref<OwnerBrief>, option_refs: List<Ref<ProjectOption>>, advisory_request_ref: Ref<AdvisoryRequest>, advisory_authority_ref: Option<Ref<AdvisoryAuthorization>>, capability_ref: Ref<ContractorCapability>, supplier_evidence_refs: List<Ref<SupplyAdvice>>, method_refs: List<Ref<ConstructabilityMethod>>}`。
- **输出分支**：`ContractorA13Payload`：`{choice: provide_advice / propose_paid_study / decline, note: string}`；意见含 `results: List<ContractorAdvisoryResult>`；付费研究含 `scope_ref: ScopeRef, effort: ValueState<Measured>, proposed_fee: ValueState<Money>, condition_refs: List<Ref<Requirement>>`。
- **来源、接收与核心效果**：简报/专业版本/有限供应意见 → Owner/Architect/Engineer/QS/Supplier；只提供前期意见或服务提议，不预留施工资源/自动授标。
- **分支前置与约束**：advisory_authority_ref=null 仅表示尚未形成开展咨询工作的授权，此时只能通过 needs_information 请求澄清、提议付费研究或拒绝。provide_advice 必须有有界且有效的已收费/明确免费任务授权及真实投入，不能因为收到咨询就自动免费研究。
- **业务出口与验收**：不具备方法可限定范围或 `unsupported`；无咨询安排不阻塞主链；报价估计不代供应承诺。CHECK-CONTRACTOR-018/019/020/021/022/023。


### 3.1 全行为执行与交接矩阵

矩阵中的正式输出须经提交校验；对方选择仍由其独立完成，例行核对和计算不要求重新调用 LLM。

| 行为 | 输入与合法选择 | 正式输出 | 资源与时间 | 失败、等待和交接 |
|---|---|---|---|---|
| A01 机会筛选 | 可见采购版本、自身任务；参投/澄清/等待/不参加 | 意向及依据，不生成施工合同 | 有授权的调查投入，读取有效期限 | 资格或资料不足注明原因；向 Owner 或实际采购方询问 |
| A02 方案报价 | 允许用途的成果、量价、排期；选择方案/条款/不提交 | 完整报价版本及假设 | 投标准备任务实际消耗，交付资源不自动锁定 | 缺关键依据可有限报价或退出，按允许程序交采购方 |
| A03 澄清修订 | 原报价及采购修订；解释/修改/维持/撤回 | 新版本、通知及原版关系 | 核对业务截止，不用调用耗时替代期限 | 提交未知先查原标识；失效或撤回释放适用临时预留 |
| A04 合同承诺 | 最终成套条款及实时资源/资金；接受/修订/拒绝 | 有效合同、明确条件及承诺 | 提交时统一核对交付窗口，不重复转换预留 | 条款/接受不一致不签约；向对方返回原因及可调整范围 |
| A05 排期采购 | 合同、依赖、设计、接收窗口；安排/询价/选择/调整 | 任务计划、有效采购请求或订单 | 队伍、设备、场地、材料按窗口匹配 | 供应商拒绝或无供给时重排；不直接替 Supplier 接单 |
| A06 动员放行 | 权限、场地、适用许可、成果及必要投入；就绪/补齐/改序 | 分范围放行或阻塞清单 | 检查实际就绪和资源有效期 | 缺一项必要依赖时阻塞相关任务，向负责方发起补充 |
| A07 施工调整 | 已放行任务、实际投入和条件；安排/调配/报告 | 核心计算的工作记录、消耗及成本 | 使用当期真实可用投入和明示工效 | 不满足投入不得产生对应完成量；异常交相应专业或资源方 |
| A08 检查整改 | 明确范围/批次及检查依据；自检/隔离/整改/复检 | 问题、投入、检查结果与放行关系 | 整改另记任务与实际工期，不免费瞬时恢复 | 无复核不自动解除相应限制；交有权 Engineer/其他检查方 |
| A09 变更索赔 | 版本冲突、指令、合同与事件；澄清/提案/申报/回应 | 有效决定或待决事项，关联影响范围 | 重评相关排期和投入，保留已发生成本 | 未认可部分保持争议；向有权设计、合同与 QS 方交接 |
| A10 收付款 | 实际工作、核证、到期义务与账本；申请/补证/付款/融资 | 核证引用、真实收付和剩余义务 | 现金执行与施工期间分开，预付款抵扣为非现金 | 余额不足或结果未知按原身份处理，交 QS/付款人/Bank |
| A11 交付结算 | 分范围竣工、测试、资料与未决项；报验/移交/结算/整改 | 各自接受、缺陷、结算及清偿记录 | 释放已完成任务投入，保留后续责任所需安排 | 未清缺陷/款项不因移交消失，交有权接收方及各债权人 |
| A12 暂停接续 | 有效依据、资源、现场资产、债务；保护/恢复/替代/退出 | 暂停范围、接续交接及余留责任 | 逐项决定保留/撤场，恢复重新核对窗口 | 不可立即召回不伪造资源；向雇主、供应方和接续主体交接 |
| A13 前期咨询 | 获授权简报、选项及条件；有限研究/澄清/拒绝 | 条件化可建造性意见及实际服务义务 | 有限任务与费用另计，不形成施工预留 | 无完整设计可给限定意见；不自动授标，交 Owner/专业/Supplier |

### 3.2 局部类型与共同约定

本节维护各行为卡共用的局部类型及约定，遵循[接口契约](../06_engineering/interface_contracts.md)；`ctx` 的身份、授权、可见候选与执行身份由宿主绑定。`completed` 表示产出可用，不表示已经签约、施工、验收或付款。具体动作可由模型选择或按已有授权例行执行，核心仍统一校验和提交。`note` 仅解释结构化选择，不能把数量、放行条件、变更范围或资源请求藏在文字中。

| 局部类型 | 字段与约束 |
|---|---|
| `ContractorAllocation` | `{resource_ref: Ref<ResourcePool>, task_scope_ref: ScopeRef, window_ref: Ref<TimeWindow>, quantity: Measured}`；拟投入与正式预留/实际使用分开 |
| `ContractorTaskDraft` | `{local_key: string, scope_ref: ScopeRef, work_method_ref: Ref<WorkMethod>, target_quantities: List<Measured>, dependency_refs: List<Ref<Dependency>>, allocations: List<ContractorAllocation>, window_ref: Ref<TimeWindow>}`；键仅在候选计划内唯一；方法须支持该工程类型/范围，目标量不是实际完成量 |
| `ContractorBidDraft` | `{package_ref: Ref<ProcurementPackage>, scope_ref: ScopeRef, price: Money, cost_basis_refs: List<Ref<CostBasis>>, programme_ref: Ref<ProgrammeProposal>, terms_ref: Ref<ContractTerms>, exclusion_refs: List<Ref<Requirement>>, validity_ref: Ref<TimeWindow>, proposed_resources: List<ContractorAllocation>}`；报价须可计价，缺必要金额不能用零；排除项不能隐含删范围 |
| `ContractorMaterialUse` | `{batch_ref: Ref<MaterialBatch>, allocation_ref: Ref<InventoryAllocation>, quantity: Measured, task_ref: Ref<Task>}`；只能请求使用可用且有权分配范围，实际消耗由核心确认 |
| `ContractorPaymentLine` | `{obligation_ref: Ref<Obligation>, payee_id: EntityId<Organization>, amount: Money, component_refs: List<Ref<SettlementComponent>>}`；预付款抵扣为非现金，部分支付不清除未付部分 |
| `ContractorIssue` | `{scope_ref: ScopeRef, requirement_ref: Ref<Requirement>, evidence_refs: List<Ref<Evidence>>, disposition: investigate / clarify / isolate / rectify / dispute, responsible: ValueState<EntityId<Organization>>}`；调查责任尚未确定用 unknown；主体提议的责任与已裁定责任分别记录 |
| `ContractorAdviceBasis` | `{kind: brief, brief_ref: Ref<OwnerBrief>} / {kind: option, option_ref: Ref<ProjectOption>}`；允许仅有需求简报的咨询 |
| `ContractorDurationRange` | `{lower: ValueState<Measured>, upper: ValueState<Measured>, method_ref: Ref<DurationEstimationMethod>}`；已知上下界同单位有序，未知不填零 |
| `ContractorAdvisoryResult` | `{basis: ContractorAdviceBasis, scope_ref: ScopeRef, work_method_refs: List<Ref<WorkMethod>>, duration: ContractorDurationRange, interface_issues: List<ContractorIssue>, assumptions: List<Ref<Assumption>>, permitted_use_ref: Ref<PermittedUse>, validity_condition_refs: List<Ref<Requirement>>}`；估计必须可追到方法，非正式交期承诺 |
| `ContractorResponseDraft` | `{question_ref: Ref<ClarificationRequest>, answer: string, evidence_refs: List<Ref<Evidence>>, changed_requirement_refs: List<Ref<Requirement>>}`；纯解释不更改报价；确需改价/范围时走 revise 及完整报价版本。 |
| `ContractorWorkBasis` | `{kind: contract, contract_ref: Ref<Contract>} / {kind: preparation, authorization_ref: Ref<WorkAuthorization>}`；准备授权明确范围、投入与采购权限，不能代替施工合同或现场放行。 |
| `ContractorExecutionContext` | `{kind: ready, task_ref: Ref<Task>, release_ref: Ref<TaskRelease>, work_method_ref: Ref<WorkMethod>, available_input_refs: List<Ref<ResourceAllocation>>, inventory_refs: List<Ref<InventoryPosition>>, condition_refs: List<Ref<SiteCondition>>, execution_window_ref: Ref<TimeWindow>, prior_execution_refs: List<Ref<WorkExecution>>} / {kind: existing, execution_refs: List<Ref<WorkExecution>>} / {kind: report, task_ref: Ref<Task>, observation_refs: List<Ref<Observation>>, execution_refs: List<Ref<WorkExecution>>}`；existing 的列表非空；report 可以尚无工程完成记录，ready 不能复用未知执行覆盖的投入。 |
| `ContractorProgressReportDraft` | `{task_ref: Ref<Task>, observation_refs: List<Ref<Observation>>, execution_refs: List<Ref<WorkExecution>>, issues: List<ContractorIssue>, reported_status: working / blocked / awaiting_check, requested_requirement_refs: List<Ref<Requirement>>}`；这是有来源申报，不含可直接覆盖工程真值的 actual_progress/actual_cost。 |
| `ContractorMeasurementLine` | `{scope_ref: ScopeRef, work_record_refs: List<Ref<WorkRecord>>, quantity: Measured, valuation_basis_ref: Ref<ValuationBasis>}`；计量申报量不能超过有据范围，数量与已核证量区分。 |
| `ContractorMeasurementDraft` | `{contract_ref: Ref<Contract>, measurement_window_ref: Ref<TimeWindow>, lines: List<ContractorMeasurementLine>, prior_application_refs: List<Ref<MeasurementApplication>>, basis_refs: List<Ref<Evidence>>}`；lines 非空，重复申报须引用原申请及覆盖，核心/QS 核验后形成计量结果，不提前要求证书。 |

各行为卡维护唯一的 Input/Payload 主定义。非当前 `choice` 的专用字段不得携带；空列表表示已知没有该类项，未知返回 `needs_information` 或 `ValueState<T>`。所有 `Ref<K>` 须解析到有版本的记录，不能只传无法解析的标题或自由文本。

**统一分支规则。** 每个 Payload 都是由 `choice` 判别的封闭联合：共同字段每个分支都必填，只有文字明确列到该分支的专用字段才可出现；无专用字段的分支只带共同字段。Input 默认必填，`Option<T>` 的 null 仅有逐字段声明的含义；列表可为空表示已知没有，未知不能塞空列表。输出的引用必须来自获授权输入或明确已登记的准备成果，不能引用本动作尚未创建的回执、合同或任务。新内容用已定义 Draft，由核心校验后赋予正式 ID/版本。

需要有权接收方、实际选择项、付款行、执行目标或工作范围的分支，相应列表非空；空候选仅允许忽略、拒绝全部、补资料或等待等有定义的出口。金额与实际量须遵守类型、单位和正值/上限规则；note 不携带隐式价格、条件或状态。核对/恢复保留原执行身份，真实新增范围或返工另有业务任务、授权和实际投入。

`FinanceApplicationDraft` 的唯一字段定义及申请登记入口见[系统接口](../06_engineering/system_interfaces.md)；本角色可作借款人或获授权代理，实际银行仍独立受理。


## 4. 专业工作与跨主体交互

### 4.1 跨主体输入与输出

| 对方 | 承包商交出什么 | 从对方接收什么及使用边界 |
|---|---|---|
| [Owner](owner.md) | 投标、条款回应、履约报告、变更及付款/移交申请 | 有效邀请、合同决定、授权指令、付款及接收；仅影响适用范围 |
| [Architect](architect.md) | 可建造性意见、设计澄清和变更请求 | 适用版本的建筑设计/答复；专业意见与商业授权分开 |
| [Engineer](engineer.md) | 专业接口、施工方案、检查证据 | 授权专业范围内的设计、检查与整改意见 |
| [QS](qs.md) | 报价、数量依据、变更计价和结算资料 | 授权范围内的评价/核证；不自动产生实际收款 |
| [Government](government.md) | 本企业有权提交的申请、检查资料、整改回应 | 适用许可、条件和正式决定；角色名不代表所有事项都有权 |
| [Supplier](supplier.md) | 采购需求、有效订单、收货/检验反馈和付款 | 报价、承诺、批次、交付及整改；供货方生产状态与现场完成量分开 |
| [Bank](bank.md) | 若本企业为借款人的申请、证据和偿还指令 | 本企业有效额度、提款与债务状态；不占用业主的私人账户 |

### 4.2 前期咨询与有限承诺

#### 前期输入与输出的语义字段

以下为咨询字段语义索引，具体字段及分支以第 3 节动作卡为准。咨询可附着业主评估档案或专业方案，不要求已选定总包或已进入正式施工采购。

| 方向 | 字段组 | 含义与使用边界 |
|---|---|---|
| 输入 | `consultation_id`、`commissioner_id`、`authority_ref` | 明确谁有权请求该服务及接收成果；顾问参与协调不自动拥有采购授权 |
| 输入 | `service_scope`、`fee_basis`、`work_authorization` | 记录有限工作、收费/明示免费安排、允许投入及成果使用范围，不从聊天自动生成无限工作义务 |
| 输入 | `owner_case_id`、`alternative_set_id`、`option_id/version` | 把意见绑定某一需求与方案，区分互斥方案与可并行工作包 |
| 输入 | `brief_version`、`design_refs`、`site_constraints` | 读取目的、候选地区、规模、交付目标、专业成果及现场条件，注明未调查或未知内容 |
| 输入 | `supplier_evidence`、`logistics_assumptions` | 区分供应商已确认内容、第三方资料与承包商估计；不自行确认工厂产能、路线许可或制造完工时间 |
| 输出 | `opinion_id/version`、`basis_versions`、`as_of` | 保留意见所依据的资料版本、观察时点、来源与适用范围 |
| 输出 | `work_sequence`、`resource_windows`、`site_readiness` | 表达拟议工序、队伍/设备窗口、场地准备及依赖，不能直接增加正式现场完成量 |
| 输出 | `duration_ranges`、`cost_ranges`、`quantity_basis` | 施工工期及估算采用单位、数量、生产率/报价来源和假设；说明是估算、预算性报价还是另行形成的正式报价 |
| 输出 | `interfaces`、`unknowns`、`review_triggers` | 列出设计、制造、运输、卸货、吊装、安装与检验接口，指定需哪类证据及何时重审 |
| 输出 | `commitment_status`、`use_scope` | 标明仅为咨询意见、是否有独立受托服务义务及用途；本次咨询不形成施工授标或产能预留 |

**CONTRACTOR-013｜提前参与是可选安排。** 业主可先委任建筑师、工程师与 QS，并从供应方取得信息；不能为每个场景强制增加总包前置条件。只有采购/服务模式需要且有适用授权时才调用本行为；未参与不自动使项目或专业论证无效。

**CONTRACTOR-014｜现场组织与制造能力分别判断。** 承包商评估劳力、设备、吊装、场地、临时设施、运输接驳和安装顺序，并记录其依据；供应商负责自己可承诺的制造范围、批次和交付能力。综合工期必须考虑两者的依赖、缓冲与现场接收窗口，不用工厂制造周期替代整个交付周期。

**CONTRACTOR-015｜早期服务不赋予后续授标。** 咨询、投标、施工合同和具体资源预留是不同对象；接受前期服务只形成该服务的明确义务。免费交流不意味着免费完整设计、无限改稿或施工履约；收费研究也不自动锁定承包商、供货方或未来采购价格。

**CONTRACTOR-016｜区间和版本可追查。** 工期、投入及施工成本区间引用数量、范围、生产率或可识别报价来源，标注不确定性和条件。没有依据时报告未知或采用明确场景假设，不生成貌似精确的保证；方案修改后只重查受影响部分，不能沿用失配版本声称已经验证。

#### 与专业主体和供应方的交接

向 [Architect](architect.md) 说明建筑布局、模块划分或现场空间对施工安排的影响；提出修改意见，不直接取得设计批准权。
向 [Engineer](engineer.md) 提出吊装、临时工程、连接与施工次序中的专业问题；需要专业验证的事项保留待核状态，不能以经验判断替代验证。
向 [QS](qs.md) 提供可核对的施工投入、数量、区间、排除项和风险假设；内部成本估计、向业主报出的价格及全项目预算分别记录。
向 [Supplier](supplier.md) 提供拟议批次、接收窗口、运输/卸货/安装接口，并接收其条件化答复；未确认的制造能力和运输安排仍是依赖项。
向 [Owner](owner.md) 交出可行范围、主要阻塞和调整建议，说明哪些问题可通过缩放规模、调整时间或改变专业方案解决；业主负责需求取舍与投资授权。

### 4.3 资金义务与执行

基础账本记录现金、应收应付、贷款与到期义务，使承包商的履约、收款和下游付款受到实际资金约束。
该确认不代表具体账户、收费/扣款、税务、外汇及融资产品已选定；本角色沿用[共同账本 OBJ-011、OBJ-012](../02_world/domain_objects.md)，不另定义余额权威。

#### 4.3.1 本企业的上下游义务

| 记录 | 本主体如何使用 | 与现金的关系 |
|---|---|---|
| 对业主或实际雇主的应收 | 引用合同、计量/核证依据、金额组成、争议和到期安排 | 尚未到账时不能当作可支配现金 |
| 向供应商、分包及人工支付的义务 | 按真实付款主体/收款主体、授权雇佣或采购关系记录到期责任；未单独建模者用明确外部接口 | 不因上游欠款自动减少或取消 |
| 核证与到期清单 | 引用同一义务及其认可/未认可组成、到期条件和版本 | 核证不是付款，到期不是到账 |
| 预付款、保留款及争议项 | 链接原义务、有效条款与分配/抵扣或释放依据 | 不在合同额、预付款、保留款中重复计算同一应收应付 |
| 支付与收款核对 | 引用 `settlement_id`、执行标识、义务分配、实际额及回执 | 只有核实的实际结果影响正式现金与清偿 |

**CONTRACTOR-017｜上下游债权债务分开。** 工程款应收和材料、服务、人工等应付分别记录真实对方及范围。上游付款延迟只改变本企业实际现金与后续判断，不自动抵销不同对方的债务；抵扣或代付须有明确授权、依据和关联记录。

**CONTRACTOR-018｜同一义务的组成不重复入账。** 核证、到期、保留、争议和清偿引用原义务与组成。已支付预付款只在合同明确时抵扣后续应付，并保留分配依据；保留款释放是同一已识别义务组成状态的变化，不再加一笔相同金额。实际成本与核证额仍按各自口径记录。

**CONTRACTOR-019｜付款安排先形成有效授权。** 余额不足时可请求补款、融资或协商；部分支付、分批安排及债权人之间的分配须有适用授权与条款依据。不能让代码遍历顺序决定先付谁，也不能静默平均分配；未授权的部分继续列为未清义务。

**CONTRACTOR-020｜缺钱不自动消除履约责任。** 现金不足可阻塞需要实际投入的新活动，但不删除合同、已发生费用、到期债务或已占用资源；暂停、释放、恢复及退出分别按已有行为与权限处理。工程成本增加并不等于当期已支付同额现金。

**CONTRACTOR-021｜核对结果后清偿。** 在途或未知付款保留对应未决占用并沿原标识核对；已确认部分只记一次。返款、更正或抵扣保留原交易及有效依据，不能为平衡账本删除历史或生成无来源现金。

#### 4.3.2 一次工程款与下游付款的交接

1. 承包商提交计量申请；有权主体核证或保留争议，按条款更新原应收义务的认可和到期部分。
2. 收到业主支付回执后核实实际到账及分配；付款通知、银行贷款批准或业主声称已付款都不能直接记入现金。
3. 本企业依据实际现金、到期清单及有效授权安排下游付款；各义务的付款对象与金额单独核对。
4. 同步登记实际清偿和剩余未清部分，并把可见资金变化反馈给施工/采购计划；不改写已经发生的工程事实。

示例：业主一笔到期工程款只实付部分时，承包商只增加实收现金，其余保留为应收；向供应商应付仍按原有效义务存在。
若贷款方直接代本企业清偿供应商货款，则通过 [Bank](bank.md) 的直接支付路径记录贷款及原交易义务变化，不重复给承包商增加现金。

### 4.4 施工、供货与资源接续

施工与供货覆盖内地九市、香港、澳门之间的业务联系；不把三类制度环境视为同一许可区，也不列未经核实的法规或通行期限。
候选工程方法采用有限参数化方案和代表性工作包，保留按部位组合现场施工、预制部件、设备及 MiC 的可能。具体代表产品、工序、生产率和计算方法仍待选定，支持范围由选定模板明确。

统一工程对象、有限模板和支持状态见 [工程类型与有限模板](../02_world/project_types.md)；Contractor 在该目录内组织参投、施工与交付。建筑、道路、桥梁、隧道分别选择相应工序/资源方法，混合项目可有多种子工程；一种项目标签不使企业具备全部施工能力。

#### 4.4.1 地点、资格与可执行范围

**CONTRACTOR-029｜组织归属和作业地点分别记录。** 企业注册地说明身份，不直接决定其项目、队伍或设备所在位置。资格与证据的适用性按任务、地点、用途、有效期和授权分别检查。

企业适配记录具体工程对象/部位、可执行工序及方法适用域、实际专业队伍/设备、目的地经验和相关证据。参投时可以声明需补充的专业支持或分包安排；未获承诺的伙伴不是已具备资源。地区归属、通用能力评分和总包称号不代替实际能力；超高层或未覆盖桥隧条件不能给普通建筑工效乘一个复杂度系数后直接施工。

| 地点引用 | 对本角色的含义 | 不可推断的事项 |
|---|---|---|
| `org.registration_region_id` | 承包企业注册地及对应身份来源 | 不能据此推定已获全部湾区城市的作业资格 |
| `facility.production_region_id` | 所用材料/构件实际生产设施所在地区，引用 Supplier 提供的有权证据 | 不能用供应企业注册地代替工厂所在地 |
| 项目及子工程/区段的所在地引用 | 按当前合同/工作包范围引用实际地区及事项，总项目可跨区 | 不用总项目单一地区替代每段条件，也不等于设计、制造、运输各任务的作业地点 |
| `execution.work_region_id`、`location_ref` | 本次施工、预组装、卸货、检测等实际作业地区与位置 | 队伍调动中不等于已到现场，也不产生现场可用工时 |

**CONTRACTOR-030｜跨城与跨制度安排逐任务核对。** 内地城市间、内地与香港/澳门间，以及香港与澳门间的安排，均引用具体路线和适用要求；不能统一附加一个“跨区惩罚”就代表全部手续。
企业资格、人员/设备可作业条件、设计或产品证据、运输条件及现场许可分别有适用范围；对其中一项认可不自动推定其他项认可。
证据保留发行/核验方、适用地区、对象/产品、用途、版本、有效窗口和来源；是否需要某手续由有依据的规则确定，未知不默认豁免，也不虚构禁止。
待核事项只阻塞依赖它的正式承诺或作业；咨询、补证及其他已满足条件的独立任务仍可开展。

#### 4.4.2 把方案落实为代表性工作包

| 输入与对象 | 目标契约 | 后续交接 |
|---|---|---|
| 方案依据 | `brief_ref`、`option_ref=(option_id, option_version)`、工程对象/子工程、`scope_id`及适用的`component_group_id`、`interface_refs`、观察截止时点 | 与获授权方案作者保持同一功能和范围；建筑或道路/桥梁/隧道分别接相应专业，不强制经过 Architect |
| 数量与费用依据 | `quantity_schedule_ref`、`cost_plan_ref`、数量单位、估算成熟度 | QS 估算不直接成为本企业报价、应付或现金支出 |
| 工作包定义 | `work_package_id/version`、位置、目标数量/单位、前置范围、必要投入、可分执行范围、检查门槛 | 采购行与供应批次只覆盖明确的材料需求，不能替代全部工作包 |
| 执行方法 | `method_ref/version`、适用工程对象/部位、技术/环境、输入输出单位、必要专业资源、工效/损耗/成本依据、未知项 | 选择部位方法与材料体系、生产地点分别记录；缺方法时只作限定比较，不按建造方式标签猜工效 |
| 资源与窗口 | 人员/设备/场地身份及时间窗、材料子范围、实际地点、迁移任务、能力与权限 | 进入共享资源与库存检查，不能按每项目复制一份区域容量 |

**CONTRACTOR-031｜材料可用和工作可做联合检查。** 采购承诺、工厂完工、在途和现场到货都不能替代现场可用材料。执行须同时满足适用设计/许可、前置工程、实际人机窗口、材料用途及场地条件。
可分工作包只执行已就绪范围；需要整体形成系统功能的后续检查仍等待全部必要子范围，不因“部分有货”自动产生整包性能或验收结果。
材料子范围从现场可用库存转为领用/安装/消耗时引用原批次及执行片段；未安装领料仍有实际位置和用途占用，退料需核实状态后才恢复可用。

**CONTRACTOR-032｜湾区资源竞争按实际身份和时间表达。** 同一队伍、设备、场地或可替代能力池面向全部项目核对；选择能力池时，池与其已列明个体不得再各算一份容量。
调动请求须计入出发地解除条件、途中时间、到达地资格/准备、费用和接收窗口。不能在佛山结束任务的同一记录中无依据出现在香港现场。
区域总量是场景约束或由底层资源汇总的视图，须注明哪一种；不额外赋予企业一份同名可用能力。竞争排序和资源迁移时长须有所选规则及依据，不能暗用项目遍历顺序。
订单或施工改派只处理有权调整的未执行范围；已有占用转移与新占用保持一致，未选方案的可解除预留释放，实际已消耗投入不能收回重用。

复合项目按“总项目—子工程/区段—工作包”绑定范围、承包责任和接口；同一实际工程、共同临时设施及共享队伍保持唯一身份。父级完成量是有口径的汇总，不与子工作量相加；桥梁同时属于通道项目及某地区，不生成第二份工程。跨区接口或整体功能需要多个子范围时，保留实际依赖及交接责任，不把某段完成直接推成全线/全项目可使用。父子成本与地区分摊按 QS 的同范围规则核对，真实合同义务仍独立存在。

#### 4.4.3 从工厂到现场的连续交接

**CONTRACTOR-033｜现场接收连接同一条实物链。** 现场引用 Supplier 的订单行、生产批次谱系、物流子批次、路线版本、实收片段及检验证据；承包商本地视图不能另造第二份到货数量。
运输完成、数量点收、质量接受、用途放行和安装分开；记录谁运输、谁保管、谁接收、谁检验，以及卸货/存储/吊装由谁承担。
改路线、改收货点或拆批次须重查窗口、适用证据及受影响费用；货物的实际位置沿真实移动变化，修改计划本身不瞬移货物。
超量、错误地点或错误规格的实际到货仍保留事实并隔离/待分配，不能为了满足原订单上限而删掉多到货物，也不能自动安装。

**CONTRACTOR-034｜接续和迟到结果保留原事实。** 任务被暂停、改派或承包商更换后，迟到回执沿原执行、发生时点及证据核对，不因当前承担者不同而丢弃真实到货或已做工作。
核实的旧执行只记一次，影响当前库存/剩余工作时形成显式调整；新承担者不能再次领取已消耗材料或把前任成果计为自己的新产出。
原结果未知时，受影响实物、工程范围及执行占用保持未决；不能先宣布未执行再改 ID 补做。确需其他独立范围继续时，必须能证明范围和投入不重叠。
拆除、返工、替代材料和复检分别有任务及投入；可回收、隔离、废弃、已安装范围互相可核对，净有效工程量不因修复重复增加。

**CONTRACTOR-035｜省略外部角色不能省略投入和责任。** 湾区内未独立建模的运输、检测、分包、能源或劳务服务，以明确对手、工作范围、来源、能力/供给限制、实际履约及费用依据表示。
湾区外投入如作为边界输入，只记录其有来源的数量、到达条件、价格/费用及责任，不扩展为研究范围外的项目或无限资源市场。
未支付不等于免费；发生工程成本、形成应付和实际现金支付分别处理。工资、采购、运输、等待、返工等成本覆盖关系须明确，已含在合同单价的同一项不能无依据再加一次。
项目采购支出与供应企业制造投入按各自口径保留；研究全链资源成本时要消除内部交易重复，不能把供应商制造成本和承包商购买同一产品的全部价格直接当两份资源消耗。

#### 4.4.4 示例 C3：一组供货批次进入同一工作包

以下与 [Supplier 供货数量示例](supplier.md#444-示例-s3从投入到现场消耗) 共用 `DEMO-GBA-P1` 和 `DEMO-WP1`。所有地点、数量和记录仅用于目标契约的守恒示例，不是实际项目、产能或生产率参数。
假定项目地和安装地为香港、生产设施在佛山；注册地另有字段，不能据此推定任何资格。路线和必要证据以示意引用表示，不宣称存在某个已核实的通行许可。
工作包 `DEMO-WP1/v1` 目标为 10 个示意安装单元；测试夹具明确每单元消耗 1 件 `P1/v1`，其他必要辅料、人机、场地和前置均须引用有效投入记录，不以这条简化关系代替工程方法。

| 环节 | 确定的示意记录 | 核对结果与继续条件 |
|---|---|---|
| 工厂产出 | 合法示意执行生成 10 件 P1，分为 T1=6、T2=4 | 现场库存仍为 0；工厂产出输入见 Supplier，共同引用同一批次 |
| T1 到达 | 实收 6，接受并放行 5，隔离 1；T2 尚在工厂 | 现场可用 5、隔离 1、工厂 4，不把“到货 6”再加到这三个分区 |
| 首次施工 | 合法执行 E1 消耗已放行的 4 件，产出 4 个安装单元 | 可用余量 1、已安装 4、隔离 1、工厂 4；净认可数量仍等待对应检查 |
| 后续供货 | T2 的 4 件实际到达并放行；缺陷 1 件实际返运隔离，另有新投入生产的替件 T3=1 到场放行 | 现场可用增至 6；替件关联原缺陷，原件仍在真实返运/隔离位置，不恢复为现场库存 |
| 剩余施工 | E2 消耗余下 6 件，完成剩余 6 个目标单元；检查按证据逐范围通过 | 原目标净有效量最终最多 10；全链共生产 11 件，10 件进入工程、1 件仍隔离，数量可核对 |

若 T1 中 1 件证据不足，隔离数量保持不可用；若 E1 未满足必要设备或适用许可，其产出必须为 0，不能沿用示意成功结果。
若 E1 已发生但结果未知，核对前不再以 E1 的同一投入重做；迟到确认只登记原来的 4 件消耗和 4 个产出。后发现安装缺陷则另建拆修范围，不自动增购或重复计价。
供货/工程成本、应付款、QS 核证和实际现金分别记录；本示例不假定到货就付款，也不推导贷款、税费或汇率。

具体工程参数、制度证据、规则选项及真实校准仍待补齐。

## 5. 状态转换、失败与恢复

### 5.1 提交、版本与持续约束

**CONTRACTOR-005｜合同成套绑定。** 每次报价、接受与修订关联相同对象和版本；供应商、条款、金额、日期和条件随合法改选一起更新。
**CONTRACTOR-006｜承诺需可执行。** 投标成本、可撤销预留与交付产能承诺分别定义；同一队伍/设备在重叠时段不能重复占用。
**CONTRACTOR-007｜正式工程事实由核心形成。** 主体选择方案与投入，核心验证权限、状态、必要材料及工作包依赖，再计算并提交正式完成量、消耗和成本。
**CONTRACTOR-008｜价格、成本与现金分开。** 报价、合同价、变更、实际成本、核证金额、欠款及收付款分别记录；生产率和成本系数保留来源及校准状态。
**CONTRACTOR-009｜提交后再反馈。** 只有成功提交的变化形成事实事件；按权限发给本企业及对方，不能把谈判文本直接传播为合同事实。
**CONTRACTOR-010｜技术失败不替代业务判断。** 超时、预算不足、输出无效和执行状态未知分别记录；不自动拒标、签约、接受索赔或生成工程量。
相同提交/支付 ID 去重；未知执行结果先查既有事实，再决定重试。模型预算与业务期限分别处理，错过期限的后果按既定场景规则执行。

### 5.2 对象转换与剩余责任

**CONTRACTOR-023｜报价不等于独占交付能力。** 投标准备占用自己的实际研究投入，报价中的拟投入队伍不自动形成排他施工占用。
若模板允许单独临时预留，须有身份、授权、范围、时段、成本及失效条件；未选中、有效撤回、拒绝或过期后按依据释放本次预留。
不得误释放该企业在其他项目的正式占用；已接受合同的资源变化通过有效调整，不能按“未中标清理”直接撤销。

**CONTRACTOR-024｜就绪是逐工作包、逐范围的判断。** 依赖指定何种前置成果、已认可数量或许可范围，不把“前一阶段完成”当作万能放行。
发现依赖循环、失配版本或空的必要投入时，记录阻塞对象和需解决者；不为推进仿真删除依赖、自动认定合格或赋予最低正进度。
分区、分期或并行执行只在已选模板允许且对应范围可分时采用，工程粒度由适用模板明确。

### 5.3 实际数量与停复工

| 对象 | 可审阅的转移 | 触发证据及等待/逆向边界 |
|---|---|---|
| 报价 | 草拟 → 已提交 → 有效/需补正 → 被选/未选/撤回/失效 | 收到有效结果后更新；技术未知维持未决，不猜对方选择 |
| 合同 | 待接受 → 条件未齐/已生效 → 调整/暂停/终止/履约收尾 | 按适用成立规则提交；生效不代表所有工作包已经可开工 |
| 工作包 | 未就绪 → 可执行 → 执行中 → 待核验 → 已认可范围 | 每次执行检查最新依赖；部分完成按范围保留，不整体冒进 |
| 质量问题 | 已发现 → 已隔离/待处理 → 整改中 → 待复检 → 有权关闭 | 失败可回到整改；承担费用与技术关闭分别判断 |
| 资源 | 可用 → 临时预留/正式分配 → 使用/待命 → 可释放/已释放 | 转换引用原分配，恢复工作须核实实际仍可用 |
| 暂停范围 | 待决定 → 生效暂停 → 条件补齐 → 重排/恢复/合法退出 | 已施工事实不倒退消失，保护和保持义务可继续 |

**CONTRACTOR-025｜施工产出由受控执行产生。** 主体提出投入及方法，核心按已确定模型核对投入、时段、工程量和依赖后计算产出与成本。
同一人机时段和材料数量只在允许的分配中使用一次；可用材料由正确批次与用途取得，不能同时留在未消耗库存并形成永久工程。
毛完成量、经检查认可的有效范围、返工量和可计价量分别记录；技术检查不自动确定合同计量或补偿权利。
进度汇总按有版本的工程范围计算，新增范围改变分母需留痕；不能静默重写历史百分比，或仅因分母变化报告新施工完成。

**CONTRACTOR-026｜返工不重复增加净完成量。** 返工保留原执行、问题、拆除/修复及复检链；新投入与成本实际累计，同一目标范围只被认可一次。
已认可后发现缺陷时，记录受影响范围及后续限制/调整，不删除原检查与付款历史；相关追回、抵扣或新增费用另走有效依据。
可回收材料按有依据的数量和状态进入对应库存，报废、损耗及已安装部分不能再作为全额可用材料。

修复结果引用 OBJ-022 的实物质量版本、实际新增投入和修复方法，不因创建返工任务或支付费用自动成功。施工造成的新损伤与原制造缺陷分别关联真实执行；移交或换队伍不重置质量。净完成量、实际功能、检查认可及可计价量各用自己的范围，贯通接线例见 [贯通场景](../07_experiments/reference_scenarios.md)。

**CONTRACTOR-027｜停复工和替代履约需要重新核对。** 暂停只影响指定范围，保护、保管和未受影响的合法活动按自身义务继续。
已撤场资源不能因恢复决定瞬时到位；重新检查人员设备窗口、材料状态、设计/许可有效性和新增资金需要。
换队伍或接续承包商时，移交已完成/未验/缺陷、现场材料及剩余范围；新主体不能把接收成果当作自己新完成的工程量。

**CONTRACTOR-028｜履约结束不是企业结束。** 合同工程、移交、缺陷责任、结算、现金和资料移交分别有结束条件。
周期经营按可见反馈更新未来报价、投标选择和资源计划；能力投资须另有任务、成本、耗时与结果，不因“学习”文字立即增加产能。
项目外的其他合同继续运行，资源只有实际解除相应约束后才能用于新业务。

### 5.4 正常路径与失败恢复

以下是检验契约是否闭合的假想场景，不设置默认价格、天数或产能，也不宣称已运行。

**情境 C1：从竞争投标到分范围交付。**
1. 企业读取采购版本并比较在手任务，授权投标准备；供应询价只取得对方允许披露的范围和条件。
2. 报价获选后双方核对最终条款，核心复核共享资源后形成有效合同；尚未就绪工作保留依赖。
3. 企业形成供应订单与排期，实际收货和检验只增加对应可用材料；放行工作包后按实际投入计算施工。
4. 有权方认可完成范围，承包商提交计量并获得相应核证；预付款按原已付未用余额非现金抵扣，余款实际执行后才清偿。
5. 分范围移交并处理剩余缺陷，结算和供应商债务单独核对；责任结束后释放资源，将实际反馈留在本企业认知。

**情境 C2：供应延误与返工后的恢复。**
1. 某必要批次未到，依赖工作包不产生工程量；企业可请求新交期、合法替代或调整其他已就绪工作。
2. 迟到批次仅部分合格，有缺陷部分隔离；已安装问题范围建立返工任务，不把整批货重复登记为新到货。
3. 暂停范围保留现场保护与债务，释放可释放资源；恢复前重新确认实际投入和适用版本，不直接沿用旧排期。
4. 返工消耗新投入并增加成本，复检后只恢复对应净有效范围；时间、费用责任和索赔另依有效决定处理。
5. 若支付响应未知，沿原执行身份核对；无法补救则按合法退出移交剩余工作、材料和欠款，保留失败结果。

## 6. 验收场景

下列场景规定实现应满足的结果，须以实际检查记录判定是否通过。流程一致性、真实决策行为、方法校准和现实工程或制度验证分别报告；示意数据不作为真实项目参数。

### 6.1 全生命周期边界

| 编号 | 场景 | 应检查的结果 |
|---|---|---|
| CHECK-CONTRACTOR-001 | 没有适用资格或有效邀请 | 不形成非法投标；可申请澄清或等待合法机会 |
| CHECK-CONTRACTOR-002 | 采购包修订后仍提交旧版报价 | 按版本/时限规则拒绝或补正，不静默套用新范围 |
| CHECK-CONTRACTOR-003 | 同期中标两个项目但资源只够一个 | 显式处理承诺冲突，不按遍历顺序超配 |
| CHECK-CONTRACTOR-004 | 动作表达接受但明确接受结果为否 | 不形成有效接受或正式签约，保留矛盾及原始决定 |
| CHECK-CONTRACTOR-005 | 最终拒绝选供应商但仍有候选引用 | 不据残留引用提交采购承诺或资源占用 |
| CHECK-CONTRACTOR-006 | 更换供应商 | ID、报价版本、批次、价格和交期同步绑定新报价 |
| CHECK-CONTRACTOR-007 | 合同已签但必要许可/设计未放行 | 依赖工作包不施工，无依赖的合法准备可继续 |
| CHECK-CONTRACTOR-008 | 关键材料或必要设备实际为零 | 对应任务不产生完成量，不以最低正进度绕过约束 |
| CHECK-CONTRACTOR-009 | 一条消息声称施工已完成 | 不直接修改工程量、验收或现金 |
| CHECK-CONTRACTOR-010 | 设计变更只影响一个工作包 | 回查受影响版本和承诺，保留其他合法成果 |
| CHECK-CONTRACTOR-011 | 问题已提出但没有整改投入/复检 | 不自动关闭缺陷或恢复相关作业 |
| CHECK-CONTRACTOR-012 | 上游付款逾期 | 记录实际缺口和主体响应，不自动取消下游到期义务 |
| CHECK-CONTRACTOR-013 | 付款执行响应丢失后重试 | 先核对原 ID，不重复到账或重复清偿 |
| CHECK-CONTRACTOR-014 | 业主未认可索赔金额 | 争议保留，不因承包商申报就增加合同价 |
| CHECK-CONTRACTOR-015 | 工程移交但仍欠供应商货款 | 工程与财务状态独立，后续偿付继续可追踪 |
| CHECK-CONTRACTOR-016 | 项目终止或承包商退出 | 处理资料、现场、材料、资源与责任，不删除债务和历史 |
| CHECK-CONTRACTOR-017 | 技术预算耗尽 | 保留技术延期与业务时钟，不伪造商业拒绝或承诺 |
| CHECK-CONTRACTOR-018 | 场景没有前期承包商咨询安排 | 不因缺少总包意见自动阻塞业主和专业团队的前期方案 |
| CHECK-CONTRACTOR-019 | 同意一次免费交流后被要求完整设计/反复改稿 | 超出范围的工作需另行明确授权，不自动产生无限免费义务 |
| CHECK-CONTRACTOR-020 | 提交可建造性意见并附工期区间 | 不自动授标、预留队伍或承诺正式完工日期，区间依据与条件可追查 |
| CHECK-CONTRACTOR-021 | 工厂可按期制造但现场无吊装/接收条件 | 综合方案保留接口阻塞，不将制造完成直接视为现场交付完成 |
| CHECK-CONTRACTOR-022 | 规模、结构或运输批次改变 | 定位受影响工序及证据，重新评估相关区间，不将旧意见静默绑定新方案 |
| CHECK-CONTRACTOR-023 | 承包商估计制造能力或报价但供应商未确认 | 标记来源为估计，不能形成供应方正式承诺或替代有效采购报价 |

### 6.2 供货与工作包

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-CONTRACTOR-040 | 企业注册地、工厂地和香港项目地不同 | 保留四类地点，按实际任务核对资格，不由注册地自动放行 |
| CHECK-CONTRACTOR-041 | 同一证据仅适用某产品/地区/用途 | 不自动覆盖其他工作或整个湾区；未知依赖有明确跟进人 |
| CHECK-CONTRACTOR-042 | 两地项目争用同一队伍或能力池 | 容量只计一次，调动有耗时、费用及到位条件 |
| CHECK-CONTRACTOR-043 | 到货 6 件但仅 5 件可用 | 库存分区不重复，依赖材料的执行最多使用已放行范围 |
| CHECK-CONTRACTOR-044 | 参数化方案缺少工效或转换方法 | 保留待定引用，不用通用进度系数自动施工 |
| CHECK-CONTRACTOR-045 | C3 中 T1、T2、T3 分批到场 | 同源数量贯通，10 件入工程、1 件隔离，原目标只认可一次 |
| CHECK-CONTRACTOR-046 | 换承包商后原执行迟到确认 | 按原执行核对事实，接续方仅执行尚未完成范围 |
| CHECK-CONTRACTOR-047 | 模型未设置独立运输或检测主体 | 服务仍有投入、限制、费用和证据，不自动免费即时完成 |
| CHECK-CONTRACTOR-048 | 报表汇总采购价与供应商制造成本 | 区分主体财务与全链资源成本，不把内部交易重复累加 |
| CHECK-CONTRACTOR-051 | 仅有建筑方法/队伍的企业被请求承诺桥梁或隧道专项 | 核对专业资源与支持方法，可提出有效补足/分包条件或拒绝；地区、总包称号和评分不生成能力 |
| CHECK-CONTRACTOR-052 | 跨区复合项目两子工程共用队伍/临时设施，父项目也汇总它们 | 资源按唯一身份分配，父子不重复计量；各段有实际地点和接口依赖，不把一段完成记为整体通行 |
| CHECK-CONTRACTOR-053 | 普通建筑施工模板被请求用于未覆盖超高层条件 | 保留未覆盖并请求相应方法/资源，不以复杂系数生成工期、完成量或安全放行 |

### 6.3 资金义务

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-CONTRACTOR-024 | 已核证或到期但未收到工程款 | 应收保留，现金不增加，不能用预测到账支付下游 |
| CHECK-CONTRACTOR-025 | 同一进度款含预付款抵扣、保留和争议组成 | 原义务及各组成可追查，抵扣/释放有据，不重复统计应收应付 |
| CHECK-CONTRACTOR-026 | 现金不足支付全部到期供应商或人工款 | 按有效授权决定安排，不能按程序遍历顺序静默决定优先级 |
| CHECK-CONTRACTOR-027 | 上游迟付导致停工申请或无力继续投入 | 债务与既有合同/资源状态保留，暂停和释放另按权限处理 |
| CHECK-CONTRACTOR-028 | 部分付款后收到重复回执或其余结果未知 | 实付部分只清偿一次，未决部分保留占用并核对 |
| CHECK-CONTRACTOR-029 | 有实际成本但尚未支付，或请求退款更正 | 成本与现金分列；更正引用原交易和凭据，不无依据调整余额 |

### 6.4 施工与恢复

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-CONTRACTOR-030 | 多个报价都列同一拟投入队伍 | 不因报价复制或永久锁定队伍；正式接受时统一复核 |
| CHECK-CONTRACTOR-031 | 未选中/拒绝后仍有该投标临时预留 | 按有效结果释放本次预留，不释放其他合同占用 |
| CHECK-CONTRACTOR-032 | 合同生效但某工作包存在循环依赖 | 暴露循环及责任方，相关范围不自动放行 |
| CHECK-CONTRACTOR-033 | 同一施工记录重试或重复到达 | 不再次计工程量、材料消耗、人机投入或成本 |
| CHECK-CONTRACTOR-034 | 问题范围返工后重新合格 | 增加真实返工投入，净有效工程量不重复增加 |
| CHECK-CONTRACTOR-035 | 已安装材料报废但请求全部返库 | 按实际可回收范围记录，不无依据恢复全额库存 |
| CHECK-CONTRACTOR-036 | 暂停期间队伍已转至其他项目 | 恢复先核对窗口，不自动同时占用或免费召回 |
| CHECK-CONTRACTOR-037 | 接续方接收前任已完成范围 | 保留来源，后续只记录自己的新增工作和合法计量 |
| CHECK-CONTRACTOR-038 | 批准变更新增范围导致进度比例变化 | 留存分母版本，不把比例变化当作新施工事实 |
| CHECK-CONTRACTOR-039 | 已付预付款在进度款中冲抵 | 仅消耗已付未用且未退款额度，不再扣现金或复用同一抵扣 |
| CHECK-CONTRACTOR-049 | A 区已按 V1/X 完成，V2 仅改 B 区且已按 V2/Y 实施 | 实际交付清单分别列 A/V1/X、B/V2/Y，不将 A 改写为最新方案的 Y |
| CHECK-CONTRACTOR-050 | 交付 X/Y 混合配置，但系统报告仅覆盖 X/X | 核对复用依据或补核验；未核实范围不自动放行，既有工程量不删除或重复增加 |

### 6.5 输入装配与分支接续

| 编号 | 情形 | 预期 |
|---|---|---|
| CHECK-CONTRACTOR-054 | 前期授权排期但尚未签订施工合同 | A05 preparation 仅安排获准范围，不要求假合同，也不提前施工或无权采购。 |
| CHECK-CONTRACTOR-055 | 首次计量/融资申请尚未产生证书或融资申请 ID | A10 提交具名草稿，核心登记后交相应主体；不先伪造核证/受理结果。 |
| CHECK-CONTRACTOR-056 | 施工未产出即遇障碍，或停工后旧执行结果迟到 | A07 report 可没有完成记录；existing 核对不要求当前再次放行，保留原实物、成本及未完成范围。 |


## 7. 参数、方法与配置依赖

**CONTRACTOR-011｜参数另行校准。** 不预设利润率、产能、工效、工期压缩、返工概率或停工阈值；引用数据、假设和检验范围分别保存。
**CONTRACTOR-012｜按本主体维护。** 承包商行为在本文保持完整；跨角色只链接对方职责，共享链条提供阶段索引，不替代本主体行为规范。

| 选择 | 对本角色的影响 |
|---|---|
| D-02 资金范围与待选细节 | 基础账本包含现金、应收应付、贷款与到期义务；账户结构、预付款/保留款条款、贷款产品、费率及币种转换仍需确定 |
| D-03/D-06 身份与模式 | 总包/专业承包、内部团队、分包及 D&B 设计责任 |
| D-04/D-05 时间与竞争 | 投标预留、产能窗口、同期授标冲突和调度方式 |
| D-07 工作包粒度 | 代表性工序、材料/设备不可替代性、投入产出和检查依据 |
| D-08/D-09 反馈与信息 | 报价响应、私有预测、供应信息和学习规则 |
| D-10/D-11 异常与决策 | 暂停/退出权、接续深度、模型允许动作与技术失败语义 |

模型决策见[配置选择](../07_experiments/model_decisions.md)。未选定的方法、阈值、时间粒度、资格或产品条件须显式保持待定；不得以示例值、角色标签或未覆盖范围补成正式结论。

D-03/D-06 仍需选择哪些采购模式采用早期承包商参与、是否影响后续投标资格及利益冲突处理；不预设统一禁止或自动优先中标。
D-04/D-05/D-07 仍需明确咨询工作量、资源估算粒度与工期依据；D-09 需确定报价保密、成果复用与获授权披露范围。

工效、法定期限及付款顺序不能使用隐含默认值。
