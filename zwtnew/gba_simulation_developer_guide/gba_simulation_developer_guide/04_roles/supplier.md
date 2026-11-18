# Supplier｜供应商主体主规范

定义供应企业在大湾区仿真中的咨询、报价、订单、制造采购、物流交付、收付款与责任收尾行为。本文是角色开发规范；方法支持范围和待选参数见第 7 节，实现与验证证据单独记录。

[总体运行框架](../02_world/world_runtime.md) · [共同对象与状态](../02_world/domain_objects.md) · [跨主体交接](../03_projects/collaboration_flow.md) · [模型决策](../07_experiments/model_decisions.md)

<!-- page-nav:start -->
**本页导航**

[1. 职责、目标与权限](#1-职责目标与权限) · [2. 信息、状态与业务对象](#2-信息状态与业务对象) · [3. 行为卡与执行契约](#3-行为卡与执行契约)

[4. 专业工作与跨主体交互](#4-专业工作与跨主体交互) · [5. 状态转换、失败与恢复](#5-状态转换失败与恢复) · [6. 验收场景](#6-验收场景)

[7. 参数、方法与配置依赖](#7-参数方法与配置依赖)
<!-- page-nav:end -->

## 1. 职责、目标与权限

### 1.1 主体身份与授权

**SUPPLIER-001｜供应企业独立经营。** 每个供应商有独立组织身份、客户组合、产品能力、产能或库存、资金状态和私有认知。
制造商、材料商、设备商与经销商可采用不同模板；经销商向上游采购不能自动视为本企业完成制造。

| 边界 | 本角色的目标语义 |
|---|---|
| 经营目标 | 争取可履约订单、保持现金和适当库存、按约交付并控制质量/履约风险；目标权重待定 |
| 供应范围 | 材料、设备、构件或模块等按产品和订单表达，单位、规格与交付条件须明确 |
| 决策权 | 报价、接受订单、安排生产/采购和运输、提出替代、处理异议与请求付款 |
| 权限边界 | 不直接改变总包施工进度、业主合同或监管许可；自报合格不替代约定接收和检查 |
| 扩展职能 | 设计、安装、调试或运输若由本企业承担，另有合同范围与能力授权，不由 Supplier 标签自动授予 |

**SUPPLIER-002｜采购方由订单确定。** 采购方可以是承包商、业主或其他获授权组织；最终项目业主不自动成为本订单付款人。
同一企业兼制造、经销或安装时，共享实际资金和投入；供应商退出单笔订单也不等于退出整个市场。

### 1.2 独立判断与经营取舍

**SUPPLIER-026｜经营选择面向全部客户与订单。** 企业同时考虑订单收益、现金、库存风险、交付可靠性、产线利用和客户关系。
提前备货可以支持交期，也会占用现金和库容；接更多订单可能挤压已承诺窗口，急单可能需要调整尚未承诺的计划。
企业可以拒绝订单、仅承诺部分数量、提出不同交期或不提供保密资料；不能因为模型希望完成项目就默认为客户无条件服务。
竞争预测与正式供货承诺分别保存，具体目标权重和适应机制待定；不以“经营优化”文字直接降低成本或提高能力。

| 供应业务类型 | 实际履约来源 | 不应生成的事实 |
|---|---|---|
| 制造型 | 在已定义工序下使用本企业实际材料、人员、产线等投入 | 未有必要投入不能凭接单增加成品，产线能力不自动等于物流能力 |
| 贸易/经销型 | 从明确上游采购，依有效交付取得对应货物或权利 | 下单不代表自产完成；不虚构本企业制造产能或已到库货物 |
| 混合型 | 按订单/产品范围分别记录自产和外购，再以实际物料衔接 | 不把同一上游成品同时记作外购成品与自己新产出的第二份成品 |

这些是同一 Supplier 角色内的业务模板，不新增主体角色；上游未独立建模时，需明确外部供货与履约接口。

## 2. 信息、状态与业务对象

### 2.1 可见信息与权限边界

**SUPPLIER-003｜按订单权限观察。** 使用收到的技术要求、询价/订单版本、客户窗口和本企业生产库存信息。
客户完整财务、竞争者报价、其他企业私有排期和隐藏质量真值不默认共享；客户预测量与正式订单量分别记录。

| 状态组 | 主体掌握或提出 | 正式状态的提交者与边界 |
|---|---|---|
| 私有经营判断 | 成本预测、最低可接受条件、客户风险、产能策略、上游选择 | 本企业认知；与公开报价及正式承诺分开 |
| 订单与报价 | 产品方案、价格、交期、例外条件、接受/拒绝 | 核心按权限、版本和适用程序形成合同或有效订单 |
| 产能与物料 | 生产/采购计划、批次安排和备货意向 | 资源/库存入口提交预留、占用、生产、采购与消耗 |
| 物流与质量 | 发货请求、批次证据、异常报告、整改提议 | 履约事件形成在途、到货、核验及问题状态 |
| 资金与责任 | 付款申请、退款/补货方案、争议和预测 | 合同及账本入口形成有效义务、实际收付和责任收尾 |

**SUPPLIER-004｜批次具有持续身份。** 区分预测、报价、订单、生产批次、库存、出库、在途、到货、接收、可使用与实际消耗。
同一批次拆分、合并、退回或更换时保留来源关系；同一件货不能同时作为可售库存、已发货及已安装数量重复计算。

### 2.2 正式状态与私有判断的所有者

| 状态 | 本企业可以做什么 | 正式所有者及信息边界 |
|---|---|---|
| 底价、需求预测、客户风险与库存策略 | 依可见资料判断、修订并选择披露 | 本企业私有认知，不成为其他主体已知事实 |
| 报价和订单回应 | 提出产品/价格/交期版本，接受或拒绝 | 合同入口校验有效接受和版本，客户选择不单方面创建承诺 |
| 产线/人员计划与库存分配 | 提出排期、预留、替代与释放请求 | 共享资源/库存入口处理跨订单冲突，避免项目副本各用全额 |
| 原料、在制品、成品与运输位置 | 提供生产、移动、检验和异常依据 | 核心计算并提交流转、消耗与损耗，文字报告不改正式数量 |
| 检验、接收与可使用性 | 自检、申请检查、回应拒收或整改 | 有权检验/接收入口按范围形成事实，不以厂内合格代替现场接受 |
| 货款与上游债务 | 申请、收付款、核对及提出调整 | 统一资金入口处理实际现金及配对义务，不因发货自动到账 |

核心的一致性校验可以掌握正式全量状态；对客户只披露获授权的报价、履约和能力范围，不公开其他客户的私有订单。

### 2.3 关键对象及字段

| 对象 | 至少保留的语义字段 | 约束 |
|---|---|---|
| 报价与订单行 | 订单/行身份、采购方/付款方、产品/规格版本、单位、数量、价格、批次/地点/日期、条件 | 允许部分供货时明确接受部分，不能只改供应商 ID |
| 材料与产品定义 | 类型/规格、单位、适用用途、允许替代、材料转换/投入依据版本 | 不同材料、规格和单位不可直接合计或无依据替代 |
| 资源分配 | 产线/人员/设备身份、能力适用范围、时段、数量、预留状态与来源 | 理论能力、停机和已承诺窗口分别核对 |
| 生产/采购任务 | 任务身份、来源订单或备货授权、模式、依赖、投入批次、范围和执行身份 | 贸易采购与自己制造分开，已完成任务重试不重复到货 |
| 批次谱系 | 批次身份、父/子批次、原料/上游来源、规格、数量/单位、质量状态 | 拆分、合并、返工及替换可追踪，不新增无来源数量 |
| 货物分配与位置 | 批次/子范围、所有权/保管方、实际地点、订单分配、数量和用途限制 | 所有权、位置、质量和预留是不同维度，不将其标签数量全部求和 |
| 检验与交接 | 检验身份/覆盖范围、证据、结论、发运身份、实收及拒收/短缺记录 | 厂内检验、实际到达、客户接受和可使用分别关联 |
| 退换与责任 | 原批次/订单行、问题、退回/报废/替换范围、责任决定、费用/退款引用 | 保留原事实，货物恢复与货款更正分别执行 |

## 3. 行为卡与执行契约

行为卡定义触发、选择和结果边界；执行矩阵集中说明跨行为的资源、时间、阻塞与接收方。正式输出均须经共同提交入口校验；模型回复不代替业务任务投入。

以下行为卡属于本供应商，每次与客户或监管的往来仅说明交接；对方决定由对方角色处理，不在本角色中代作。

<!-- action-nav:start -->
**动作定位**：[SUPPLIER-A01｜观察需求并判断是否响应](#supplier-a01观察需求并判断是否响应) · [SUPPLIER-A02｜审查规格与提出产品方案](#supplier-a02审查规格与提出产品方案) · [SUPPLIER-A03｜形成报价与交付计划](#supplier-a03形成报价与交付计划) · [SUPPLIER-A04｜接受订单并提交履约承诺](#supplier-a04接受订单并提交履约承诺) · [SUPPLIER-A05｜安排备料、采购与生产排期](#supplier-a05安排备料采购与生产排期) · [SUPPLIER-A06｜执行生产并管理库存](#supplier-a06执行生产并管理库存) · [SUPPLIER-A07｜检验产品并准备交付证据](#supplier-a07检验产品并准备交付证据) · [SUPPLIER-A08｜安排发运与处理运输异常](#supplier-a08安排发运与处理运输异常) · [SUPPLIER-A09｜配合收货、检验与可使用放行](#supplier-a09配合收货检验与可使用放行) · [SUPPLIER-A10｜提出收款并管理自身付款](#supplier-a10提出收款并管理自身付款) · [SUPPLIER-A11｜处理变更、退换、质量责任与争议](#supplier-a11处理变更退换质量责任与争议) · [SUPPLIER-A12｜暂停、取消、收尾与企业学习](#supplier-a12暂停取消收尾与企业学习) · [SUPPLIER-A13](#supplier-a13--评估需求简报并提供限定用途的供应意见)
<!-- action-nav:end -->

### SUPPLIER-A01｜观察需求并判断是否响应

- **触发与输入**：收到询价、框架采购需求或发现业务机会；读取产品范围、地区、数量、窗口和客户信息。
- **本主体决定**：响应、请求澄清、建议可供范围或不参与；核对产品能力与潜在排期。
- **提交与交接**：登记针对具体询价版本的意向和问题，向采购方反馈可继续评估的范围。
- **异常与观察**：预测需求不成为订单或强制库存；技术无结果不自动构成商业拒绝。

**函数与类型契约**

- **函数**：`roles.supplier.a01(ctx: ActionContext, input: SupplierA01Input) -> ActionResult<SupplierA01Payload>`。
- **输入记录**：`SupplierA01Input = {inquiry_refs: List<Ref<SupplyInquiry>>, market_refs: List<Ref<MarketObservation>>, capability_ref: Ref<SupplierCapability>, capacity_ref: Ref<SupplierCapacity>, screening_profile_ref: Ref<SupplyScreeningProfile>}`。
- **输出分支**：`SupplierA01Payload`：`{choice: respond / clarify / limited_scope / track_market / decline, basis_refs: List<Ref<Evidence>>, note: string}`；响应/限定范围含 `inquiry_ref: Ref<SupplyInquiry>, offered_scope_refs: List<ScopeRef>`；澄清含 `inquiry_ref: Ref<SupplyInquiry>, requirement_refs: List<Ref<Requirement>>`；仅市场跟踪含 `market_refs: List<Ref<MarketObservation>>`。
- **来源、接收与核心效果**：可见询价/市场/能力 → 实际采购方/A02；只登记意向或查询，预测不生成订单及产能占用。
- **分支前置与约束**：track_market 不要求已有客户询价；respond/limited_scope/clarify 必须引用实际收到的 inquiry_ref。明确拒绝保留针对的输入询价范围，不把沉默或技术失败记为拒绝。
- **业务出口与验收**：商业不参与是 `decline`，技术无结果独立；缺实际询价可继续观察，不伪造客户。CHECK-SUPPLIER-001/036/047。


### SUPPLIER-A02｜审查规格与提出产品方案

- **触发与输入**：询价需进一步定价；读取产品标准、接口、允许用途、设计版本和所需证明。
- **本主体决定**：确认可生产/采购范围、提出澄清或替代；如承担深化设计，按授权提供相应成果。
- **提交与交接**：向采购方及有权 [Architect](architect.md)/[Engineer](engineer.md) 提交产品数据和偏离项。
- **异常与观察**：未获接受的替代不能直接用于生产交付；未知适配或资格保持待核实，不凭性能评分自动通过。

**函数与类型契约**

- **函数**：`roles.supplier.a02(ctx: ActionContext, input: SupplierA02Input) -> ActionResult<SupplierA02Payload>`。
- **输入记录**：`SupplierA02Input = {inquiry_ref: Ref<SupplyInquiry>, requirement_refs: List<Ref<Requirement>>, design_refs: List<Ref<Deliverable>>, product_candidates: List<Ref<ProductSpecification>>, compatibility_method_ref: Ref<ProductCompatibilityMethod>, design_authority_refs: List<Ref<Authorization>>}`。
- **输出分支**：`SupplierA02Payload`：`{choice: propose_original / propose_substitute / clarify / decline, note: string}`；产品提议含 `lines: List<SupplierProductLine>, evidence_refs: List<Ref<ProductEvidence>>, unresolved_refs: List<Ref<Issue>>`；澄清含 `requirement_refs: List<Ref<Requirement>>`。
- **来源、接收与核心效果**：规格/用途/专业成果 → 采购方/Architect/Engineer；提交产品和偏离，不能自行改变设计或允许替代投入施工。
- **分支前置与约束**：产品目录可支撑有限产品提议，尚无设计成果时只对询价要求可核实的部分作答。propose_substitute 明示偏离及证据，未获设计/采购批准不得因此投入生产或安装。
- **业务出口与验收**：缺接口方法 `unsupported`；缺证据保持待核；换工厂/用途重新定位适用范围。CHECK-SUPPLIER-002/013/023/048/058。


### SUPPLIER-A03｜形成报价与交付计划

- **触发与输入**：具备可估价要求；查看本企业投入成本、可用库存、瓶颈产能、物流和既有订单。
- **本主体决定**：提出允许的价格、数量、分批交期、付款条件、有效期及必要先决条件。
- **提交与交接**：形成带版本的报价，区分出厂、运输、安装或其他已包含范围；发送给具体采购方。
- **异常与观察**：价格、币种、数量单位和交付责任不清时先澄清；交期预测不是已经预留运输或产能。

**函数与类型契约**

- **函数**：`roles.supplier.a03(ctx: ActionContext, input: SupplierA03Input) -> ActionResult<SupplierA03Payload>`。
- **输入记录**：`SupplierA03Input = {inquiry_ref: Ref<SupplyInquiry>, product_proposal_refs: List<Ref<ProductProposal>>, cost_basis_refs: List<Ref<CostBasis>>, inventory_ref: Ref<InventorySnapshot>, capacity_ref: Ref<SupplierCapacity>, logistics_refs: List<Ref<LogisticsAssessment>>, pricing_profile_ref: Ref<SupplyPricingProfile>}`。
- **输出分支**：`SupplierA03Payload`：`{choice: quote / decline_quote, note: string}`；报价含 `offer: SupplierOfferDraft, proposed_allocations: List<SupplierAllocation>`。
- **来源、接收与核心效果**：同版产品/自身投入/物流 → 采购方/A04；形成成套报价，可记录明确临时预留提议，不自动占用正式产能。
- **分支前置与约束**：报价可以针对尚待采购方确认的产品提议，并把该确认列为明确条件；不能把 product_proposal_refs 命名为已商定事实而要求报价前先成交。quote 的完整交付口径、数量、价格及适用期限必须可核验，decline_quote 不带虚构价格。
- **业务出口与验收**：缺价格或完整交付责任先澄清；估计改有约束报价需重核；相同产线不复制。CHECK-SUPPLIER-004/022/024/036/049。


### SUPPLIER-A04｜接受订单并提交履约承诺

- **触发与输入**：采购方选择报价或发出订单；对比最终规格、金额、交期、付款人和原报价版本。
- **本主体决定**：明确接受、提出修订、部分供货或拒绝；重新核对资金、库存及同期间产能。
- **提交与交接**：核心按有效接受和合同形成规则登记订单，建立计划批次、适用预留与履约义务；计划批次不增加实物库存。
- **异常与观察**：采购方选中本企业不自动构成新条款接受；最终拒绝、失效报价或超额承诺不能生成有效订单。

**函数与类型契约**

- **函数**：`roles.supplier.a04(ctx: ActionContext, input: SupplierA04Input) -> ActionResult<SupplierA04Payload>`。
- **输入记录**：`SupplierA04Input = {order_proposal_ref: Ref<OrderProposal>, offer_ref: Ref<SupplyOffer>, counterpart_acceptance_refs: List<Ref<PartyAcceptance>>, inventory_ref: Ref<InventorySnapshot>, capacity_ref: Ref<SupplierCapacity>, funding_ref: Ref<FundingPosition>, formation_profile_ref: Ref<SupplyFormationProfile>}`。
- **输出分支**：`SupplierA04Payload`：`{choice: accept / accept_partial / revise / reject, note: string}`；接受/部分接受含 `offer_ref: Ref<SupplyOffer>, accepted_lines: List<SupplierDeliveryLine>, terms_ref: Ref<SupplyTerms>, proposed_allocations: List<SupplierAllocation>`；修订含 `changed_requirement_refs: List<Ref<Requirement>>`。
- **来源、接收与核心效果**：采购方同版订单/真实资源 → 合同库存核心/采购方；满足双方条件才建立订单与承诺，计划批次不是实物。
- **分支前置与约束**：accept_partial 的范围必须是原提议的严格子集，未覆盖部分保持未接受；它是待对方同版确认的修改接受，不能单方制造部分有效订单。接受量为正，按订单行、实物和产能窗口统一核对，不能把拟批次当现货。
- **业务出口与验收**：部分接受明确数量且须采购方有效接受；拒绝不残留订单；冲突不超卖。CHECK-SUPPLIER-003/004/005/006/037。


### SUPPLIER-A05｜安排备料、采购与生产排期

- **触发与输入**：有效订单允许开展工作；读取客户版本、物料需求、上游承诺、库存和设备/人员窗口。
- **本主体决定**：自产、外购、分批、调整顺序或申请交期变更；贸易型供应商组织上游采购而非虚构自产。
- **提交与交接**：资源入口处理预留和冲突；向上游提交授权采购，形成到料、生产与交付之间的依赖。
- **异常与观察**：缺必要原料、图纸或设备时相关任务等待；未放行的投机备货须另有本企业授权和风险承担。

**函数与类型契约**

- **函数**：`roles.supplier.a05(ctx: ActionContext, input: SupplierA05Input) -> ActionResult<SupplierA05Payload>`。
- **输入记录**：`SupplierA05Input = {work_authority_ref: Ref<SupplyWorkAuthorization>, scope_ref: ScopeRef, requirement_refs: List<Ref<SupplyRequirement>>, design_refs: List<Ref<ReleasedDeliverable>>, inventory_ref: Ref<InventorySnapshot>, upstream_offer_refs: List<Ref<SupplyOffer>>, capacity_ref: Ref<SupplierCapacity>, method_refs: List<Ref<SupplyMethod>>}`。
- **输出分支**：`SupplierA05Payload`：`{choice: plan_manufacture / plan_purchase / split_plan / revise_plan / request_quote / accept_upstream_offer / seek_delivery_change, note: string}`；`plan_manufacture/plan_purchase/split_plan/revise_plan` 含 `tasks: List<SupplierTaskDraft>`；`revise_plan` 另含 `prior_plan_ref: Ref<SupplyPlan>`；`request_quote` 含 `supplier_ids: List<EntityId<Organization>>, required_lines: List<SupplierProductLine>`；`accept_upstream_offer` 含 `offer_ref: Ref<SupplyOffer>, terms_ref: Ref<SupplyTerms>, required_lines: List<SupplierProductLine>`；`seek_delivery_change` 含 `affected_line_refs: List<Ref<OrderLine>>, proposed_window_ref: Ref<TimeWindow>`。
- **来源、接收与核心效果**：有效订单或独立备货授权/实际投入 → 资源核心/上游/A06；拟排任务与采购，不代上游接受，不制造原料。
- **分支前置与约束**：计划阶段使用材料需求而非强制已到库批次；缺原料可先提出采购，计划不生成实物。request_quote 不要求上游已有报价，accept_upstream_offer 才向正式订单入口提交本方接受；有效上游订单经对方及核心确认后才成为 A06 的输入。投机备货需要独立 SupplyWorkAuthorization，不借客户未签订单启动。
- **业务出口与验收**：缺必要投入只阻塞依赖任务；投机备货须独立授权；未到上游货不计在库。CHECK-SUPPLIER-007/008/038/039/052。


### SUPPLIER-A06｜执行生产并管理库存

- **触发与输入**：生产任务已放行且投入到位，或上游实际交货；读取批次、工序和合格投入。
- **本主体决定**：在能力范围内组织生产、分配瓶颈、提出维护/替代与异常处理。
- **提交与交接**：履约模块据投入和待校准规则计算在制、待检产出、消耗及成本；合格范围另关联适用检查依据，库存账本记录实际变动。
- **异常与观察**：发言“已生产”不增加库存；生产损耗、返工品和合格品分别计量，不重复使用同一投入。

**函数与类型契约**

- **函数**：`roles.supplier.a06(ctx: ActionContext, input: SupplierA06Input) -> ActionResult<SupplierA06Payload>`。
- **输入记录**：`SupplierA06Input = {task_ref: Ref<SupplyTask>, available_input_refs: List<Ref<ResourceAllocation>>, inventory_ref: Ref<InventorySnapshot>, upstream_delivery_refs: List<Ref<ExternalDelivery>>, prior_execution_refs: List<Ref<ProductionExecution>>, execution_setup: SupplierExecutionSetup}`。
- **输出分支**：`SupplierA06Payload`：`{choice: execute / rebalance / reconcile_upstream / reconcile_execution / request_maintenance, note: string}`；生产/调配含 `task_ref: Ref<SupplyTask>, inputs: List<SupplierInputUse>, resources: List<SupplierAllocation>`；外购核对含 `delivery_refs: List<Ref<ExternalDelivery>>`；执行核对含 `execution_refs: List<Ref<ProductionExecution>>`；维护含 `resource_ref: Ref<ResourcePool>, issue_refs: List<Ref<Issue>>`。
- **来源、接收与核心效果**：正式放行/真实投入/外部交付 → 生产库存计算/A07；只请求投入和核对，产出、损耗、谱系和成本由核心确定。
- **分支前置与约束**：任务原记录决定 manufacture/purchase/rework，移除可与之冲突的重复 mode 字段。execute/rebalance 仅可用 production 上下文；reconcile_upstream 仅用 purchase；reconcile_execution 仅用 reconciliation；request_maintenance 依实际资源问题记录另建任务。外购核对使用上游实际交付，不能按下单量生成收货或自产记录。
- **业务出口与验收**：缺转换方法不按订单造产量；响应丢失核对原执行；外购不记自产。CHECK-SUPPLIER-007/008/039/040/041/046/052/055。


### SUPPLIER-A07｜检验产品并准备交付证据

- **触发与输入**：产品达到检验节点、发现异常或需见证检查；引用具体批次、要求和测试记录。
- **本主体决定**：自检、申请有权检查、隔离、返工、报废或提出偏差处理。
- **提交与交接**：提交可追踪的质量/来源证据，保留自报、外部核验及客户接受状态的区别。
- **异常与观察**：合格范围仅覆盖被检查对象和用途；模型隐藏缺陷不自动进入供应商认知。

**函数与类型契约**

- **函数**：`roles.supplier.a07(ctx: ActionContext, input: SupplierA07Input) -> ActionResult<SupplierA07Payload>`。
- **输入记录**：`SupplierA07Input = {batch_ref: Ref<ProductBatch>, scope_ref: ScopeRef, requirement_refs: List<Ref<InspectionRequirement>>, evidence_refs: List<Ref<InspectionEvidence>>, inspection_profile_ref: Ref<InspectionProfile>, known_defect_refs: List<Ref<Defect>>}`。
- **输出分支**：`SupplierA07Payload`：`{choice: self_check / request_external_check / isolate / rework / scrap / propose_deviation, note: string}`；检查含 `method_ref: Ref<InspectionMethod>, evidence_refs: List<Ref<InspectionEvidence>>`；隔离/报废含 `batch_ref: Ref<ProductBatch>, quantity: Measured, basis_refs: List<Ref<Evidence>>`；返工含 `tasks: List<SupplierTaskDraft>`；偏离含 `deviation_refs: List<Ref<SpecificationDeviation>>`。
- **来源、接收与核心效果**：批次/实际已知测试 → 检查核心/有权见证方/采购方；申请检查或处置，自检不替外检和客户接受。
- **分支前置与约束**：隔离/报废量为正且不超过本主体有权处置的实际批次范围；核心从批次谱系扣减一次，不能通过新批次 ID 重复报废/恢复。rework 建立实际任务及原缺陷关联，复检之前不把计划返工当已合格。
- **业务出口与验收**：没有复核不释放隔离；隐藏缺陷不进入决策输入；报废不恢复投入。CHECK-SUPPLIER-009/012/014/048。


### SUPPLIER-A08｜安排发运与处理运输异常

- **触发与输入**：批次可发运且满足订单条件；读取收货窗口、路线、装载、运输及必要通行/通关要求。
- **本主体决定**：选择可行运输安排、提出改期或分批发运，回应延误、破损和接收地不可用。
- **提交与交接**：核心记录实际出库、在途和运输事件；通知采购方批次、预计到达及异常。
- **异常与观察**：发货不等于到货，物流耗时不由对话轮次替代；风险与所有权转移点按订单条件表达。

**函数与类型契约**

- **函数**：`roles.supplier.a08(ctx: ActionContext, input: SupplierA08Input) -> ActionResult<SupplierA08Payload>`。
- **输入记录**：`SupplierA08Input = {order_ref: Ref<Order>, dispatchable_refs: List<Ref<DispatchableBatch>>, receiving_window_refs: List<Ref<ReceivingWindow>>, route_candidates: List<Ref<TransportRoute>>, capacity_refs: List<Ref<TransportCapacity>>, requirement_refs: List<Ref<TransportRequirement>>, shipment_refs: List<Ref<Shipment>>, position_refs: List<Ref<TransportPosition>>, logistics_profile_ref: Ref<LogisticsProfile>}`。
- **输出分支**：`SupplierA08Payload`：`{choice: dispatch / split / reroute / reschedule / reconcile, note: string}`；发运/拆分含 `plans: List<SupplierShipmentPlan>`；改道含 `shipment_ref: Ref<Shipment>, replacement_route_ref: Ref<TransportRoute>, current_position_ref: Ref<TransportPosition>`；改期含 `target: SupplierRescheduleTarget, proposed_window_ref: Ref<TimeWindow>`；核对含 `shipment_refs: List<Ref<Shipment>>`。
- **来源、接收与核心效果**：已放行实物/运输/接收条件 → 物流核心/采购方；核心才登记出库、在途和到达，不能由发言瞬移库存。
- **分支前置与约束**：首次 dispatch/reschedule 可尚无 Shipment；改期用订单行或已有运输任务的判别目标。reroute 的当前位置必须来自输入 position_refs，不能由主体重写；reconcile 不要求货物仍为 dispatchable，出库后原批次按在途/已到达位置核对，不能重复出库。
- **业务出口与验收**：缺运力/接收窗口延期；未知执行先核对；跨子工程共同段只占一次。CHECK-SUPPLIER-010/015/050/051/054/056/060。


### SUPPLIER-A09｜配合收货、检验与可使用放行

- **触发与输入**：货物到达约定地点；读取收货数量、状态、规格核对和接收方授权。
- **本主体决定**：回应短缺、破损、不符或检验问题，补交证明、补货或提出处置意见。
- **提交与交接**：与 [Contractor](contractor.md) 或其他采购方核对接收批次；核心分别登记到货、接收、隔离与可用量。
- **异常与观察**：客户签收不自动代表质量验收或所有用途获准；到货数量不能直接增加现场完成量。

**函数与类型契约**

- **函数**：`roles.supplier.a09(ctx: ActionContext, input: SupplierA09Input) -> ActionResult<SupplierA09Payload>`。
- **输入记录**：`SupplierA09Input = {shipment_ref: Ref<Shipment>, arrival_refs: List<Ref<ArrivalEvidence>>, receipt_refs: List<Ref<GoodsReceipt>>, inspection_refs: List<Ref<InspectionResult>>, discrepancy_refs: List<Ref<DeliveryDiscrepancy>>, receiving_party_refs: List<Ref<ReceivingParty>>}`。
- **输出分支**：`SupplierA09Payload`：`{choice: acknowledge_receipt / supplement_evidence / propose_replacement / contest_discrepancy, note: string}`；确认含 `receipt_ref: Ref<GoodsReceipt>, accepted_fact_refs: List<Ref<ReceiptComponent>>`；补证含 `evidence_refs: List<Ref<Evidence>>`；补货含 `issue_ref: Ref<DeliveryDiscrepancy>, replacement_lines: List<SupplierProductLine>`；异议含 `component_refs: List<Ref<ReceiptComponent>>, evidence_refs: List<Ref<Evidence>>`。
- **来源、接收与核心效果**：到达/接收方实际记录 → 采购方/Contractor/库存核心；可回应数量与问题，不代收货人签收或放行全部用途。
- **分支前置与约束**：本供应商无需拥有接收方的签收权限即可补证或回应差异；接收方身份与权限由收货记录及核心核验。acknowledge_receipt 只确认已收到的对方事实，不代对方签字。尚无收货回执时仍可补送证据或等待，不能伪造 GoodsReceipt。
- **业务出口与验收**：短缺/拒收/合格范围分列；重复回执不入库两次，补件与原问题关联。CHECK-SUPPLIER-011/012/013/042/043。


### SUPPLIER-A10｜提出收款并管理自身付款

- **触发与输入**：订单约定付款节点到期；读取预付款、交货/核验依据、到期义务与既有执行记录。
- **本主体决定**：请求付款、核对扣减、处理争议，并支付自身上游到期款或申请自身周转融资。
- **提交与交接**：向合同付款人提交依据；资金入口执行有效收付，[Bank](bank.md) 按借款人身份处理融资。
- **异常与观察**：项目业主未付款不自动免除采购方货款；无相应条款时不从项目总账直接给供应商划款。

**函数与类型契约**

- **函数**：`roles.supplier.a10(ctx: ActionContext, input: SupplierA10Input) -> ActionResult<SupplierA10Payload>`。
- **输入记录**：`SupplierA10Input = {order_refs: List<Ref<Order>>, obligation_refs: List<Ref<Obligation>>, delivery_evidence_refs: List<Ref<DeliveryEvidence>>, account_refs: List<Ref<Account>>, execution_refs: List<Ref<PaymentExecution>>, settlement_rule_ref: Ref<SettlementRule>}`。
- **输出分支**：`SupplierA10Payload`：`{choice: request_payment / authorize_payment / reconcile / dispute / seek_finance, note: string}`；请款含 `claim: SupplierPaymentClaimDraft`；支付含 `account_ref: Ref<Account>, lines: List<SupplierPaymentLine>`；核对含 `execution_refs: List<Ref<PaymentExecution>>`；争议含 `obligation_refs: List<Ref<Obligation>>`；融资含 `application: FinanceApplicationDraft`。
- **来源、接收与核心效果**：有效货款/自身账本/回执 → 合同付款人/Bank/上游/资金核心；应收、抵扣、现金及清偿各自提交，不穿透到项目业主账户。
- **分支前置与约束**：首次请款用订单行/交付依据和合同计价结果构造 claim，既有 obligation/component 仅在已成立时引用；不强制申请之前先产生应付。融资申请先登记再交 Bank A02。空 order_refs 不免除本企业其他已成立义务，账本付款仍依据真实债务人。
- **业务出口与验收**：客户迟付不免上游欠款；部分付款只分配已知实收；未知余量不重付；缺估值不填零。CHECK-SUPPLIER-015/016/029/030/031/032/033/034/057。


### SUPPLIER-A11｜处理变更、退换、质量责任与争议

- **触发与输入**：客户变更、批次问题、现场退货或适用保证请求；核对订单、生产阶段和事件依据。
- **本主体决定**：提出替代、返修、补货、退款、索赔或拒绝无依据要求，并识别未受影响的履约范围。
- **提交与交接**：由有权主体按条款确定正式变更及责任；核心记录退回、替换和费用，保留原批次历史。
- **异常与观察**：质量纠正和责任费用分开；已安装产品的处置需现场有权主体参与，不能由供应商远程删除消耗记录。

**函数与类型契约**

- **函数**：`roles.supplier.a11(ctx: ActionContext, input: SupplierA11Input) -> ActionResult<SupplierA11Payload>`。
- **输入记录**：`SupplierA11Input = {order_ref: Ref<Order>, batch_refs: List<Ref<ProductBatch>>, installed_use_refs: List<Ref<MaterialUse>>, change_refs: List<Ref<SupplyChangeRequest>>, defect_refs: List<Ref<Defect>>, authority_refs: List<Ref<Authorization>>, remedy_profile_ref: Ref<SupplyRemedyProfile>}`。
- **输出分支**：`SupplierA11Payload`：`{choice: propose_change / repair / replace / propose_refund / claim / decline_request, note: string}`；变更含 `lines: List<SupplierProductLine>, affected_line_refs: List<Ref<OrderLine>>`；修理/替换含 `tasks: List<SupplierTaskDraft>, source_defect_refs: List<Ref<Defect>>, disposition_scope_ref: ScopeRef`；`propose_refund` 含 `original_transaction_refs: List<Ref<Transaction>>, proposed_amount: ValueState<Money>, basis_refs: List<Ref<Evidence>>`；`claim` 含 `order_line_refs: List<Ref<OrderLine>>, proposed_amount: ValueState<Money>, basis_refs: List<Ref<Evidence>>`；`decline_request` 含 `request_ref: Ref<SupplyChangeRequest>`。
- **来源、接收与核心效果**：有权变更/实际批次与现场位置 → 采购方/专业核验/现场有权者/账本；只提出纠正及价款处理，核心依授权记实际退换与调整。
- **分支前置与约束**：退款须指向实际原交易，索赔可以尚无收款交易而依据订单/损失事实提出；不能强制先付款才允许索赔。退款提议不执行负付款，真实退款经付款入口按权限及原交易处理。已安装品的拆除、替换、运输与新增投入各自留痕。
- **业务出口与验收**：已安装品需现场权限；未知退款金额不执行；不删除原消耗，替换须新实际投入。CHECK-SUPPLIER-014/017/025/035/045。


### SUPPLIER-A12｜暂停、取消、收尾与企业学习

- **触发与输入**：订单暂停/取消、履约困难、全部交付或责任期结束；读取在制品、库存、欠款和未结承诺。
- **本主体决定**：提出补救、恢复、交付接续、余料处置或有效终止；依据观察更新客户与物流判断。
- **提交与交接**：核心按权限释放可释放产能，保留未清义务和适用质量责任；处理货物归属及处置款项。
- **异常与观察**：项目完工不自动关闭供应商全部订单或货款；仿真截止保存未完成生产、在途及未结争议。

**函数与类型契约**

- **函数**：`roles.supplier.a12(ctx: ActionContext, input: SupplierA12Input) -> ActionResult<SupplierA12Payload>`。
- **输入记录**：`SupplierA12Input = {scope_ref: ScopeRef, authority_basis_refs: List<Ref<Evidence>>, work_in_progress_refs: List<Ref<ProductionPosition>>, inventory_refs: List<Ref<InventoryPosition>>, shipment_refs: List<Ref<Shipment>>, obligation_refs: List<Ref<Obligation>>, commitment_refs: List<Ref<ResourceCommitment>>, continuation_profile_ref: Ref<ContinuationProfile>, observation_refs: List<Ref<Observation>>}`。
- **输出分支**：`SupplierA12Payload`：`{choice: protect / suspend / resume / handover / cancel / close_cleared_scope / record_lesson, note: string}`；`protect/suspend/resume/handover/cancel/close_cleared_scope` 含 `scope_ref: ScopeRef, release_candidate_refs: List<Ref<ResourceCommitment>>, retained_obligation_refs: List<Ref<Obligation>>, disposition_basis_refs: List<Ref<AssetRight>>`；恢复含 `readiness_refs: List<Ref<Verification>>`；移交含 `successor_id: EntityId<Organization>`；经验含 `source_refs: List<Ref<Observation>>, learning_method_ref: Ref<LearningMethod>`。
- **来源、接收与核心效果**：在制/在途/物权/责任 → 资源库存核心/客户/接续方/私有认知；分项释放，债务和质量义务不随项目结束消失。
- **分支前置与约束**：取消订单不等于删除实际在制/在途货物，disposition_basis_refs 必须覆盖本方处置权。接续方实际接受后才转移对应责任；release_candidate_refs 不能覆盖未知外部执行占用，剩余义务以核心读取为准。
- **业务出口与验收**：客户物料不可擅自转售；恢复重查材料及产线；取消后迟到事实仍核对。CHECK-SUPPLIER-017/018/037/044/045/055。


### SUPPLIER-A13 · 评估需求简报并提供限定用途的供应意见

- **触发与输入**：收到有权方的前期咨询，包含需求简报版本、候选地区、规模区间、期望交付时间及已有专业意见。
- **自主选择**：表达供给可能性、提出产品组合/规格假设、请求澄清、提供有限资料、评估付费研究或拒绝披露。
- **正式结果**：提交注明用途、成熟度、适用条件、可披露范围和有效性条件的意见，向授权接收者说明未知项。
- **等待与失败**：无需先具备完整设计或正式订单才可咨询；无响应、调用失败、资料不足和不愿参与分别保留，不生成接受订单事实。

**函数与类型契约**

- **函数**：`roles.supplier.a13(ctx: ActionContext, input: SupplierA13Input) -> ActionResult<SupplierA13Payload>`。
- **输入记录**：`SupplierA13Input = {brief_ref: Ref<OwnerBrief>, option_refs: List<Ref<ProjectOption>>, professional_advice_refs: List<Ref<ProfessionalAdvice>>, advisory_request_ref: Ref<AdvisoryRequest>, advisory_scope_ref: Option<Ref<AdvisoryAuthorization>>, capability_ref: Ref<SupplierCapability>, disclosure_profile_ref: Ref<DisclosureProfile>, feasibility_method_refs: List<Ref<SupplyFeasibilityMethod>>}`。
- **输出分支**：`SupplierA13Payload`：`{choice: indicative_advice / limited_disclosure / propose_study / decline, note: string}`；意见/有限披露含 `lines: List<SupplierAdvisoryLine>, withheld_requirement_refs: List<Ref<Requirement>>, unresolved_refs: List<Ref<Issue>>`；研究含 `scope_ref: ScopeRef, fee_estimate: ValueState<Money>, effort_estimate: ValueState<Measured>, condition_refs: List<Ref<Requirement>>`。
- **来源、接收与核心效果**：简报/允许可见的专业意见 → Owner/Architect/Engineer/QS/Contractor；只提供限定用途意见与研究提议，不成报价、订单、免费无限服务或产线预留。
- **分支前置与约束**：advisory_scope_ref=null 仅表示尚未授权开展工作，允许提议研究或拒绝；正式意见必须有有限工作授权及方法依据。limited_disclosure 明示未披露项，但不能用保密掩盖自己已对报价作出的必要承诺。
- **业务出口与验收**：无完整设计可限定意见；不愿披露是业务选择，资料未知独立；新地区/窗口须重评。CHECK-SUPPLIER-019/020/021/022/024/025/026/027/028。


### 3.1 全行为执行与交接矩阵

矩阵中的正式结果须经提交校验；例行生产计算、库存移动与已授权执行不要求每次重新调用 LLM。

| 行为 | 输入与合法选择 | 正式输出 | 资源与时间 | 失败、等待和交接 |
|---|---|---|---|---|
| A01 需求响应 | 可见询价/市场信息、自身能力；响应/澄清/不参与 | 意向及待解问题 | 调研投入按实际授权，预测不占正式交付资源 | 信息不足与拒绝不同，交实际采购方 |
| A02 规格方案 | 性能、接口和用途版本；原规格/替代/请求核实 | 产品意见、偏离和证据引用 | 方案研究有投入，专业核实另有窗口 | 不兼容不默认可用，交 Architect/Engineer/采购方 |
| A03 报价 | 数量、成本依据、资源和窗口；价格/批次/条件/不报价 | 成套报价及有效性 | 准备投入与正式交付预留分开 | 无依据价格/交期保持未知；发给有权接收方 |
| A04 订单接受 | 最终规格、报价、客户、付款及实际能力；接受/部分/修订/拒绝 | 有效订单、条件和匹配承诺 | 提交前统一复核库存、产线窗口及资金 | 冲突不复制资源，未选/拒绝释放本次适用临时预留 |
| A05 备料排期 | 有效工作授权、需求与前置；自产/外购/分批/调整 | 任务、采购及资源分配 | 匹配原料、人员/产线、库容与依赖 | 缺料/设计阻塞相应任务，向上游或专业方请求补齐 |
| A06 生产库存 | 已放行任务、实际投入、上游交付；执行/调配/维护 | 核心计算的在制/成品、消耗及成本 | 使用实际时间和可用投入，转换规则须有版本 | 技术未知核对原执行，不复制投入或产出 |
| A07 检验 | 批次/要求及记录；自检/隔离/返工/报废/外检 | 分范围结果、问题及用途限制 | 检验和返工消耗实际模型内投入 | 不合格部分保持隔离，交有权核验者/客户 |
| A08 发运 | 可发范围、接收窗口与运输条件；发运/分批/改期 | 出库、在途及异常事件 | 校验货物、运输与地点窗口，物流耗时另计 | 缺接收条件不得虚报到达，通知客户及受托物流接口 |
| A09 收货配合 | 到达批次、数量、检验与授权；补证/补货/回应拒收 | 实收、接受、隔离和可用范围 | 按实际批次处理，不按整单同时完结 | 签收不代表全部认可，交 Contractor/实际收货方 |
| A10 收付融资 | 条款、到期义务及真实执行；申请/核对/付款/融资 | 实收实付、分配与未清义务 | 预付款抵扣为非现金，客户预测回款不供自己支付 | 未知执行沿原标识核对，交付款人/Bank/上游 |
| A11 变更退换 | 原订单、批次、现场状态；修订/返修/补货/退款/异议 | 有效调整、退回/替换关系和责任 | 返工/补货另占投入与窗口，不复用已消耗量 | 已安装部分需现场有权处置，交专业/采购/接收方 |
| A12 暂停收尾 | 有效依据、在制/在途、欠款；保护/改排/恢复/取消 | 资源处理、物料归属和余留责任 | 按明细释放，恢复重新检查真实窗口 | 已交付、债务或质量责任不随订单关闭消失 |
| A13 前期咨询 | 有权简报和专业版本；有限意见/研究/澄清/拒绝 | 成熟度、条件和可披露范围明确的意见 | 咨询任务与费用按实际授权，不预留后续订单 | 资料不足保留未知，不自动授标或占产线 |

### 3.2 局部类型与共同约定

函数是目标接口而非已实现声明，公共字段、引用和返回包装见[接口契约](../06_engineering/interface_contracts.md)。宿主绑定身份、权限、可见版本和技术执行身份；`completed` 仅指产出可用。函数可由模型选择或按已有授权执行，实际生产量、位置、检验结果、交易状态和费用由核心计算/核对后提交。`note` 只说明理由，不能代替数量、范围、用途及条件字段。

| 局部类型 | 字段与约束 |
|---|---|
| `SupplierProductLine` | `{product_ref: Ref<ProductSpecification>, destination_scope_ref: ScopeRef, quantity: Measured, requirement_refs: List<Ref<Requirement>>, deviation_refs: List<Ref<SpecificationDeviation>>}`；替代规格仍需专业与采购授权 |
| `SupplierDeliveryLine` | `{product: SupplierProductLine, delivery_window_ref: Ref<TimeWindow>, destination_ref: Ref<Location>, included_service_refs: List<Ref<DeliveryService>>, price: Money}`；每行明确币种、数量/计价口径和交付责任 |
| `SupplierOfferDraft` | `{buyer_id: EntityId<Organization>, payer_id: EntityId<Organization>, lines: List<SupplierDeliveryLine>, terms_ref: Ref<SupplyTerms>, validity_ref: Ref<TimeWindow>, condition_refs: List<Ref<Requirement>>, cost_basis_refs: List<Ref<CostBasis>>}`；有约束报价不能用未知金额或参考价代替 |
| `SupplierAllocation` | `{resource_ref: Ref<ResourcePool>, scope_ref: ScopeRef, window_ref: Ref<TimeWindow>, quantity: Measured}`；请求量不是已预留量 |
| `SupplierInputUse` | `{batch_ref: Ref<MaterialBatch>, allocation_ref: Ref<InventoryAllocation>, quantity: Measured}`；制造投入必须有真实批次及可用范围 |
| `SupplierTaskDraft` | `{local_key: string, mode: manufacture / purchase / rework, scope_ref: ScopeRef, method_ref: Ref<SupplyMethod>, target: SupplierProductLine, dependency_refs: List<Ref<Dependency>>, resources: List<SupplierAllocation>, planned_inputs: List<SupplierPlannedInput>}`；`local_key` 只在候选计划内唯一，SupplyMethod 按 mode 登记 manufacture/rework 的生产方法或 purchase 的采购方法，外购方法不生成自产量 |
| `SupplierShipmentPlan` | `{batch_ref: Ref<ProductBatch>, quantity: Measured, source_ref: Ref<Location>, destination_ref: Ref<Location>, route_ref: Ref<TransportRoute>, receiving_window_ref: Ref<TimeWindow>, transport_allocation_refs: List<Ref<ResourceAllocation>>, condition_evidence_refs: List<Ref<Evidence>>}`；共享运输段用唯一能力池，计划不移动实物 |
| `SupplierExecutionSetup` | `{kind: production, release_ref: Ref<TaskRelease>, method_ref: Ref<ProductionMethod>} / {kind: purchase, purchase_order_ref: Ref<Order>, receipt_rule_ref: Ref<GoodsReceiptRule>} / {kind: reconciliation, execution_refs: List<Ref<ProductionExecution>>}`；生产请求仅匹配 production 分支，外购核对不要求制造放行，历史核对不要求当前重新放行 |
| `SupplierPaymentLine` | `{obligation_ref: Ref<Obligation>, payee_id: EntityId<Organization>, amount: Money, component_refs: List<Ref<SettlementComponent>>}`；同一资金执行/预付款抵扣不得重复分配 |
| `SupplierAdviceBasis` | `{kind: brief, brief_ref: Ref<OwnerBrief>} / {kind: option, option_ref: Ref<ProjectOption>}`；仅简报时不伪造正式方案 |
| `SupplierQuantityRange` | `{lower: ValueState<Measured>, upper: ValueState<Measured>, method_ref: Ref<QuantityEstimationMethod>}`；已知上下界同单位且有序 |
| `SupplierMoneyRange` | `{lower: ValueState<Money>, upper: ValueState<Money>, method_ref: Ref<PriceEstimationMethod>}`；已知上下界同币种且有序，未知不填零 |
| `SupplierLogisticsAdvice` | `{route_refs: List<Ref<TransportRoute>>, duration: ValueState<Measured>, delivery_cost: SupplierMoneyRange, condition_refs: List<Ref<Requirement>>, unresolved_refs: List<Ref<Issue>>}`；不支持的物流范围显式标记 |
| `SupplierAdvisoryLine` | `{basis: SupplierAdviceBasis, product_refs: List<Ref<ProductSpecification>>, quantity: SupplierQuantityRange, indicative_price: SupplierMoneyRange, manufacturing_duration: ValueState<Measured>, logistics: SupplierLogisticsAdvice, interface_issue_refs: List<Ref<Issue>>, evidence_refs: List<Ref<Evidence>>, permitted_use_ref: Ref<PermittedUse>}`；估计必须逐项标记已知/未知/不适用/不支持，不能用无值对象暗示可行 |
| `SupplierPlannedInput` | `{product_ref: Ref<ProductSpecification>, required: Measured, available_allocation_refs: List<Ref<InventoryAllocation>>, acquisition_requirement_refs: List<Ref<SupplyRequirement>>}`；计划需求可以尚无到库批次；执行时改用已核实 SupplierInputUse，计划不可直接消耗库存。 |
| `SupplierRescheduleTarget` | `{kind: order_lines, line_refs: List<Ref<OrderLine>>} / {kind: shipments, shipment_refs: List<Ref<Shipment>>}`；所选列表非空；未发运改期不要求运输任务先存在，已发运改期不改变真实位置。 |
| `SupplierPaymentClaimLine` | `{order_line_ref: Ref<OrderLine>, scope_ref: ScopeRef, claimed: Money, evidence_refs: List<Ref<Evidence>>, prior_component_ref: Option<Ref<SettlementComponent>>}`；null 仅表示该请款组成尚未登记，核心按合同节点/覆盖核验，不重复生成已存在义务。 |
| `SupplierPaymentClaimDraft` | `{payer_id: EntityId<Organization>, lines: List<SupplierPaymentClaimLine>, settlement_rule_ref: Ref<SettlementRule>, prior_claim_refs: List<Ref<PaymentClaim>>}`；lines 非空，请款金额可计算且有依据；证据未齐先补充，不把到货自动当已清偿。 |

各行为卡中的 Input/Payload 是本动作字段主定义。`choice` 为封闭枚举，分支不适用字段不得携带；列表为空仅表示已知没有该类项，未知用 `needs_information` 或 `ValueState<T>`。引用由输入服务提供并解析，不允许模型编造批次、回执或外部验收。

**统一分支规则。** 每个 Payload 都是由 `choice` 判别的封闭联合：共同字段每个分支都必填，只有文字明确列到该分支的专用字段才可出现；无专用字段的分支只带共同字段。Input 默认必填，`Option<T>` 的 null 仅有逐字段声明的含义；列表可为空表示已知没有，未知不能塞空列表。输出的引用必须来自获授权输入或明确已登记的准备成果，不能引用本动作尚未创建的回执、合同或任务。新内容用已定义 Draft，由核心校验后赋予正式 ID/版本。

需要有权接收方、实际选择项、付款行、执行目标或工作范围的分支，相应列表非空；空候选仅允许忽略、拒绝全部、补资料或等待等有定义的出口。金额与实际量须遵守类型、单位和正值/上限规则；note 不携带隐式价格、条件或状态。核对/恢复保留原执行身份，真实新增范围或返工另有业务任务、授权和实际投入。

`FinanceApplicationDraft` 的唯一字段定义及申请登记入口见[系统接口](../06_engineering/system_interfaces.md)；本角色可作借款人或获授权代理，实际银行仍独立受理。


## 4. 专业工作与跨主体交互

### 4.1 跨主体输入与输出

| 对方 | 供应商交出什么 | 从对方接收什么及使用边界 |
|---|---|---|
| [Contractor](contractor.md) | 报价、交期承诺、生产/物流状态、批次证据、付款请求 | 订单、接收窗口、检验反馈和实际付款；本企业不替其安排现场施工 |
| [Owner](owner.md) | 业主直接采购时的报价、交付及合同报告 | 对本订单有权的指令/接受与付款；不是所有供货的默认采购方 |
| [Architect](architect.md) | 适用产品数据、样品或替代提议 | 获授权的建筑接口与外观意见；不自动形成商业变更 |
| [Engineer](engineer.md) | 专业参数、试验和批次符合性资料 | 授权专业范围的核验和技术要求；不代表全部法定批准 |
| [QS](qs.md) | 约定范围的数量、报价和计价证据 | 授权核证或估价意见；不直接增加供应商现金 |
| [Government](government.md) | 依法/依模板由本企业提交的合规证据 | 适用事项的决定和限制；其他外部手续需单独表达 |
| [Bank](bank.md) | 本企业获授权的融资资料与还款请求 | 自身额度、提款和债务；客户融资批准不等于本企业收到货款 |

### 4.2 前期咨询与有限承诺

Owner 提出建设目的、候选地区、规模区间和期望交付时间；技术及建造方式先保留候选，再结合各专业及供应方意见细化。
供应商在授权范围提供制造、采购、运输和履约意见，说明证据与承诺程度。
SUPPLIER-A01—A03/A13 的咨询与专业核实分别交接；[Architect](architect.md)、[Engineer](engineer.md) 和 [QS](qs.md) 分别维护自己的核实与比较责任。

**SUPPLIER-013｜供应意见来自有自身利益的企业。** 供应商可优先推荐自身熟悉或有利润的产品，表达取舍和销售立场，不预设其意见中立或最优。
真实能力、对自身能力的判断及向客户声明的范围分别保存；不默认给客户读取隐藏库存、全部产线状态或内部最低价格。
本规则允许商业立场与信息不完整，不自动引入虚假声明策略；如需模拟欺瞒与查证，其行为、可观察证据及后果须另行定义。

**SUPPLIER-014｜咨询、报价和预留分别形成。** 概念适配、产能意向、参考价格与预计交期不等于有约束报价、有效订单或正式预留。
任何预留须通过相应授权、条件与资源入口另行建立；重复咨询或客户表达兴趣不能自动扣减正式可承诺产能。
客户要求付费研究、试制或样品时，以实际接受的有限服务/任务为依据；免费营销投入也消耗本企业资源，但不自动生成客户应付款。
咨询以后可以进入正式报价，须重新核对需求版本、共享产能、商业条件和有效期，不能直接把原意见改名为已接受合同。

**SUPPLIER-015｜成熟度与承诺程度分别标记。** 标明意见属于概念适配、参数/接口待核、预算参考或基于明确规格的正式报价等适用阶段。
上述阶段不是强制统一顺序；具体成熟度分类待接口设计，但必须使读者知道哪些要求已明确、哪些数据仍是假设。
价格或交期区间来自可追溯资料或明确情景假设，不能凭空生成；缺失依据可以输出无法估计以及需要补充的条件。
产能意见注明产品类型、数量单位、生产窗口及条件；“有生产线”或通用能力分不自动证明该订单窗口可交付。

**SUPPLIER-016｜替代与组合需专业核实。** 可提出材料、构件、模块、设备及现场工作组合，也可说明本企业只能覆盖其中一部分。
MiC 与其他技术可以并用；供应商推广主张不自动得到成本、工期、质量或合规优势，效果需对应项目范围及证据。
接口、荷载、尺寸、公差、性能、维护和适用证明等事项按实际产品需要列出，交有权建筑/工程主体核实。
供应商认可自身可生产不等于设计已兼容或监管已批准；技术接受也不直接变更采购合同、施工安排或付款责任。

| 输入/输出语义 | 必须能说明的内容 | 限制 |
|---|---|---|
| 需求引用 | 业主评估档案、简报版本、目的、候选地区、规模区间和期望时间 | 可在正式项目成立前存在，不自动生成订单 |
| 专业输入引用 | 可读取的建筑/工程选项、性能与接口版本、已知约束 | 未提供的细节标记假设或未知，不捏造设计 |
| 可供方案 | 产品/服务范围、适用数量单位、组合与替代、未覆盖项 | 销售意见不成为专业认可或排他设计要求 |
| 产能与交期意见 | 制造/采购窗口、瓶颈条件、备料及物流依赖、时间依据 | 不暴露无权读取的其他客户订单或等同预留 |
| 价格与责任范围 | 成熟度、币种/时点、范围、费用条件、有效期或更新触发 | 参考价格、正式报价、费用义务分别保存 |
| 证据及可用范围 | 来源、作者、核实状态、接收者、允许用途与再披露限制 | 咨询资料只按权限交给 QS 或其他专业方 |

**SUPPLIER-017｜交付责任逐项说清。** 生产/采购、出厂、运输、通关/相关手续、卸货、临时存储、安装、调试及接收可以由不同主体承担。
每份意见说明包含、排除与待分配部分；生产周期不能直接当作项目完工时间，出厂价也不能直接当作完整交付成本。
运输路线、吊装和接收窗口等约束与专业/施工组织意见交叉核实；本企业未负责的工作不能默认为免费或即时完成。
设计冻结、订单接受、预付款或场地准备等前置条件按相应方案列示，不能用咨询日期代替全部条件满足日期。

**SUPPLIER-018｜资料变化不静默沿用旧承诺。** 简报、专业接口、数量或窗口变化时，识别受影响意见，给出继续适用、待复核或失效状态及原因。
原意见与既有报价/订单分开维护；新咨询不能自动取消既有订单，旧咨询也不能被用作新版本的确定交付承诺。
意见相互矛盾时列明冲突与需核实方，可以提供附条件替代；不要求供应商代作专业裁定或为了继续流程隐藏矛盾。

**SUPPLIER-019｜多方咨询共享资料且保留权限。** 多个方案或专业方引用同一产品资料/已授权研究时，保留共同来源、版本和使用范围。
同一咨询执行重试不重复记投入或收费；增量研究按新范围另行授权，既有一笔收费不能因被多个方案引用而重复生成应付。
不同项目的适配工作可能是不同任务，不因使用同一产品目录就一律免费；复用资料不能泄露别的客户价格、订单、排期或商业秘密。

**SUPPLIER-020｜前期咨询不锁定后续采购。** 参与咨询不自动授予订单、排他资格或产能预留；未参与者也不自动失去后续参与资格。
采购方式、利益冲突及必要信息如何公平提供由适用 D-06 模板确定；本企业无权发布竞争者资料或替采购方豁免程序。

后续细化对应 D-02 咨询/试制费用、D-05 资源预留、D-06 采购程序、D-07 技术与物流粒度、D-09 披露、D-11 承诺和版本契约。

### 4.3 资金义务与执行

资金账本包含现金、应收应付、贷款和到期义务。
SUPPLIER-A04、A10—A12 沿用[共同资金与提交规则](../02_world/domain_objects.md) OBJ-011、OBJ-012，现金与债务统一由核心提交。

**SUPPLIER-021｜货款由有效订单识别责任主体。** 每笔货款关联订单、付款人、收款人、币种、成立依据、到期条件与未清余额。
采购方应付与本企业应收以同一正式义务身份配对；各主体可读取的证据仍按权限提供，不默认共享对方全部账本。
付款人依订单或有效责任转移确定，不因最终工程属于某业主就直接把货款记为该 Owner 的欠款。
订单总价、已交货金额、已成立应收与已到期货款分别维护；尚未交货也可能存在有效预付款义务，具体依条款决定。

**SUPPLIER-022｜预付款到账与后续抵扣分开。** 实际收到预付款时仅登记一次现金流及其订单归属，保留后续可抵扣余额和适用条件。
货款核算中的预付款抵扣引用原收款，另记非现金抵扣，不再次把同一现金分配给第二笔义务；每次抵扣不超过该笔已付、未使用且未退款的有效余额，累计抵扣和退款可核对。
合同终止时按有效依据判断已履行部分、可抵扣金额及应退款，实际退款另有执行记录，不能删除原到账事实。

**SUPPLIER-023｜交付不替代收款，分次清偿不重复。** 出库、到货、接收或安装记录可以成为约定付款证据，不能直接增加本企业现金。
每次付款引用执行身份及其清偿的具体义务；累计分配受有效未清金额约束，部分到账只减少实际清偿部分。
多笔货款合并支付或一笔货款分次支付均保留分配关系；不得因再次提交同一批次、申请或银行回执而重复形成应收或到账。
实际出现无法归属或超额到账时保留真实现金事实并待核对/退款，不强行计为超过义务的清偿，也不静默吞掉差额。

**SUPPLIER-024｜银行直接支付只构成一次收款。** 若 [Bank](bank.md) 依有效安排直接支付货款，记录真实出资方、合同债务人、收款人及清偿义务。
供应商收到的该笔资金清偿对应采购方货款；不能继续向采购方重复收取同一已清偿部分，也不能给采购方再增加一笔收到贷款的现金。
借款主体与银行之间的贷款记录按该安排同步建立或更新；供应商不因收到银行代付就自动成为该笔贷款借款人。

**SUPPLIER-025｜上游义务和客户回款分别管理。** 本企业向原料商、物流方或其他上游承担的义务关联各自合同与付款主体。
客户迟付会影响可用现金和本企业付款选择，但不自动免除上游到期义务；提出延期、融资或变更须走相应有效程序。
资金不足时保留未付和逾期状态，不把预计客户回款当作现有现金，也不以取消客户订单或关闭项目删除欠款。
取消、退款、减免或责任转移须引用有权依据和后续调整，尚未清偿的本金、费用及其他责任按各自记录保留。

预付款比例、到期条件、违约处置、汇兑和具体实现仍待 D-02、D-06、D-10、D-11 细化，不自行补入默认数值。

### 4.4 生产、运输与现场供货

研究对象为大湾区内生产、交易和建设的联系，区分内地九市、香港、澳门及各自城市/地点。路线可跨城、跨制度环境，是否需要某项资格或手续由可追溯规则和证据决定，不编造法定期限或统一互认结论。
候选工程方法把有限参数化方案与代表工作包连接到少量产品/工序模板；现场施工、预制部件、设备、MiC 可按部位组合。具体产品、转换方法、生产率和生产尺度待选择，本节不预定 MiC 优先，支持范围由选定模板明确。

统一工程对象、有限模板与支持状态见 [工程类型与有限模板](../02_world/project_types.md)。建筑、道路、桥梁、隧道的需求落实到具体材料/设备/构件及部位接口，不要求供应商仅服务某一类工程，也不因产品名称相同就认定用途相容。材料体系、部位建造方式、实际生产布局和订单目的地分别表达；项目“MiC 主”等汇总标签不替代本订单规格。

#### 4.4.1 四类地点和区域适用性

**SUPPLIER-034｜产品来源不由企业注册地推断。** 每一订单和执行分别引用组织、生产设施、目标项目与实际作业位置。制造商、贸易商和安装服务可以属于同一组织，但共用真实资源和资金。

| 引用 | 必须说明的内容 | 边界 |
|---|---|---|
| `org.registration_region_id` | 签约企业注册地及身份依据 | 不等于工厂、仓库、实际经营地点或全部湾区供货资格 |
| `facility.production_region_id`、`facility_id` | 实际制造设施与产线位置；贸易产品引用真实上游来源 | 未披露来源记为未知及披露限制，不用经销商注册地补造 |
| 工程对象/子工程的所在地引用、`destination_ref` | 最终用途所在地区、具体区段/现场与合同交货地点 | 跨区总项目不使用一个地址覆盖所有区段；中转仓交付不自动等于最终到货 |
| `execution.work_region_id`、`location_ref` | 生产、存储、检验、装卸、安装等本次实际作业位置 | 运输中按路线分段/位置记录，不同时作为起终点的可用库存 |

**SUPPLIER-035｜适用证据随产品、地点和用途变化。** 来源证明、质量/测试证据、生产或经营资格、运输和目的地使用条件分别引用发行方、适用对象、地区、用途、版本、时间及可披露范围。
企业差异按具体产品/规格、制造/外购/安装方法、设施及人员工具、目的地供货经验和证据记录；注册地区和通用评分不是产品能力。普通建筑供货经验不自动覆盖超高层、桥梁或隧道的特殊规格/接口，不能通过一个复杂度系数取得适用性。未知最终用途允许明确条件的询价/意见，但不能据此声明全部工程用途已通过。
厂内检查通过只说明其覆盖范围；目的地工程适用性由有权专业/监管主体核对。跨内地城市与跨内地—香港—澳门的规则需求分别选择，不由一个区域标签推断全部条件。
换工厂、换产品、换路线、换安装地点或改用途时，定位需要复核的证据；旧记录保留，不默认全套沿用，也不要求无关范围重新验证。
外部手续若未独立建模，由明确外部过程及内部跟进人处理；没有依据的条件保留未知，不能自设“自动互认”或无限等待期。

#### 4.4.2 把方案、工厂和多项目竞争连接起来

| 输入与对象 | 目标契约 | 交接与限制 |
|---|---|---|
| 方案和工程需求 | `brief_ref`、`option_ref=(option_id, option_version)`、工程对象/子工程、`scope_id`及适用的`component_group_id`、`interface_refs`、观察截止时点 | 对应获授权方案作者的部位与接口；建筑/基础设施按各自专业接续，咨询阶段允许不完整 |
| 数量与估价引用 | `quantity_schedule_ref`、`cost_plan_ref`、产品/材料数量、单位与成熟度 | QS 估算不生成订单、产能占用或应收；供应报价另有版本 |
| 制造/外购方法 | `method_ref/version`、输入材料、输出规格/用途范围、转换与损耗依据、适用设施/条件及必要专业资源 | 方法与数据未知时只保留条件化意见，不能凭订单量或项目类型标签自动生产 |
| 设施和资源 | `facility_id`、产线/设备/人员或能力池身份、兼容产品、停机/切换、时窗、既有承诺 | 同一底层资源跨客户统一核对；工厂位置不代替产品能力 |
| 物料谱系 | 原料、在制、成品的批次/子范围、数量/单位、质量、位置、权利、分配和执行片段 | 材料转换与同类货物搬移分别核对，不能跨单位简单相加 |
| 边界投入 | 对手及来源、数量/单位、履约时点、供给限制、费用/支付依据和证据 | 未建模原料/能源/服务仍有约束和费用，不默认为无限免费供给 |

**SUPPLIER-036｜生产能力按设施、产品和窗口分配。** 理论能力、停机、维护/切换、已承诺任务和真实可用窗口分别表达；同一产线或共享能力池不能为每个项目各产一份全额产品。
区域容量如由设施汇总，不能再作为另一份额外产能；如果所选模型只用能力池，须明确池的覆盖与单位，排除和已枚举设施的重复。
急单、跨城采购和项目改期可引发企业自主改排，但只调整有权改变的未执行任务；已开工/消耗范围保留事实，改派需重新检查来源、规格、资格、运输与现场窗口。
备货可先于客户订单，但须本企业有权承担投入与库存风险；报价或咨询本身仍不独占产线。扩产不即时生效，任务、资金、时间和效果依据分别记录。

同一产品服务不同子工程/地区时，订单行分别关联适用范围，产线、批次和运力仍共享实际身份。父项目的汇总采购量、子工程需求和订单分配不能作为三份独立需求投产；按唯一物料需求/分配关系排重。共同运输批次可拆到多个接收点，分段实际流转与费用有覆盖记录，不为每个地区复制整批货物、全额运力或全部运输成本；未交付范围仍保留原责任。

**SUPPLIER-037｜边界采购与费用不省略。** 制造型使用实际材料及设施投入，贸易型依真实上游履约接收货物，混合型逐范围区分；企业之间转售不再制造一份实物。
湾区外来源如被选作边界输入，仅以有来源的供货和费用条件进入湾区模型，不新增湾区外项目网络或无穷供应能力。湾区内未建模服务也须有明确履约过程。
原材料、能源、人工、物流、仓储、等待和返工等费用按方法和覆盖范围归集；缺价格依据记为待定估值，不能把未知成本写为零。
实际生产成本、对客户报价、对上游应付、客户应收和现金分别保存；同一运输费已含在采购包中时，不再无依据另计一遍。预付款抵扣继续作为非现金记录。

#### 4.4.3 路线、物流子批次与异常接续

**SUPPLIER-038｜跨区域物流是分段任务链。** 每次运输引用 `route_id/version`、起点/终点及中转点、分段运输方式与地区、物流子批次、装载限制、适用证据、运输/装卸责任与接收窗口。
内地城市间运输、内地与香港/澳门间运输、香港与澳门间运输分别由可行路线和规则配置；此分类不预设必经节点、具体通关制度、运价或时间。
路线时长应区分作业、旅行、排队、待手续及异常等待；不同时间段可能并行，须按依赖核算，不能把所有时长机械重复相加。缺数据使用明确方法/数据引用，不猜默认值。
生产放行、出库、在途、到达、点收、接受、用途放行是不同记录；跨节点移动成对更新位置，运输中的损失、拒收和退回另有范围和证据。
工厂产能、车辆/运力、装卸设备和现场接收能力分别核对；供应商负责运输时也不能从制造能力分自动生成运力。

**SUPPLIER-039｜拆批次和改派保存既有实物。** 物流子批次可引用一个或多个相容来源子范围；拆分、合并保留谱系，父批次已分出部分不再作为独立可售实物。
改承运安排、路线、仓库或客户先检查权利、未执行范围、现场窗口及新增条件，旧占用与新占用协调变更；已在途部分按实际位置接续，不能通过改订单地址直接到达。
拒收部分记录实际保管方和位置，经过真实退运/接收才能回库；返工耗用新投入并再检验，替件用新来源关联原缺陷，不能让原件和替件同时完成同一义务。
合格交付量、累计搬运量、净安装量及订单已满足量分别计量；一次退换可能增加搬运量，不因此增加净履约量。

**SUPPLIER-040｜迟到结果不因订单或承担者变化消失。** 已发运、生产或收货结果未知时，沿原执行及片段核对，受影响投入/货物不再次投产、发运或分配；独立无重叠范围可继续。
订单取消或改派后收到可靠迟到记录，先还原发生时点、原授权与真实数量，只登记未记录的事实；超出当前订单的到货作为异常实物待处理，不强塞为合格履约，也不删掉。
迟到失败不能覆盖已确认成功，多个回执不能重复增减货物；技术核对与重新发出有约束执行分开，重发须确定原范围未执行且当前条件仍满足。

#### 4.4.4 示例 S3：从投入到现场消耗

与 [Contractor 供货数量示例](contractor.md#444-示例-c3一组供货批次进入同一工作包) 使用同一组示意身份。`DEMO-GBA-P1` 是抽象装配产品，`DEMO-WP1` 是其用途范围；不代表任何真实工程产品，更不等同于 MiC。
假设生产设施位于佛山，项目和最终安装位于香港；注册地独立记录。工厂—中转/运输分段—现场使用一个带版本的示意路线，不填入未经核实的实际路线或许可。
为核对数量，夹具指定每件 P1 消耗 1 单位 A 和 2 单位 B，工厂期初有来源的 A=11、B=22。本例不设置过程损耗；真实产品的材料/质量平衡、工时、生产率和合格率须另取方法及数据，不能采用本比例校准。
下面每次“实际执行”都以前置、资源窗口和适用证据满足为条件；数值是给定的检验记录，不用于从未定生产率推出工期。

| 环节 | 确定输入与正式记录 | 输出、守恒和交接 |
|---|---|---|
| 生产 M1 | 任务授权、方法引用、A=10、B=20、有效人机/设施窗口 | 生成待检 P1=10；A 余 1、B 余 2。通过适用厂检后仅放行对应范围 |
| 分批 | 同一成品谱系划分 T1=6、T2=4 | 父批次汇总仍为 10；计划、预留和子批次数量不再相加成 20 |
| T1 运输 | 6 件真实出库，按路线逐段移动，到达并点收 6 | 工厂余 4；现场接受/可用 5、隔离 1，工厂合格不替代现场接收 |
| 首次使用 | Contractor 执行 E1 消耗可用的 4 件 | 现场余可用 1、已安装 4、隔离 1，工厂仍有 T2=4；Supplier 不另计算施工进度 |
| T2 与问题处理 | T2 的 4 件实际运抵并放行；隔离 1 件经有权处置实际返运到厂，仍隔离 | 现场可用 5、已安装 4、厂内隔离 1；仅改拒收标签不能把货物搬回工厂 |
| 替件 M2/T3 | 明确补货授权，消耗余下新投入 A=1、B=2，另有资源窗口，生产并检验 1 件；实际发运到场并放行 | T3 关联原缺陷，现场可用变 6；A/B 余 0，不能复用 M1 已消耗的投入 |
| 最后使用 | E2 消耗现场 6 件，检查按实际证据认可工作包 | 共生产 11 件，10 件进入工程、1 件厂内隔离；净目标仍为 10，隔离品不能再作为可售件 |

如路线证据缺失或现场无接收窗口，受影响子批次等待/改排，其位置不变；未影响的生产或其他订单按自身条件继续。
如 M1 响应丢失，已消耗 A/B 与已生产数量先核对，不能再完整投产 10 件；如运输记录迟到，按原片段补事实，不能再次出库 6 件。
拒收、责任认定、退款与替件供货分开；示例中的补货是有权决定后的路径，不假定任何供应商自动免费补货或客户自动免付原义务。
制造成本与上游义务按投入记录，发运及可用不产生现金；合同付款节点、实际支付和预付款非现金冲抵分别沿资金接口处理。

## 5. 状态转换、失败与恢复

### 5.1 提交、版本与持续约束

**SUPPLIER-005｜报价和订单完整绑定。** 产品/规格版本、数量、单位、价格、交付地点/日期、付款人、验收与责任条件一起形成有效承诺。
**SUPPLIER-006｜跨订单检查能力。** 已承诺产能、可售库存、在制品和在途货物分别核算；同一资源不能重复承诺给多个客户。
**SUPPLIER-007｜生产交付使用守恒记录。** 核心登记原料投入、产出、损耗、移动和退换；运输、生产或检验失败分别有结果，不能用可靠性分直接生成整批货物。
**SUPPLIER-008｜钱与货不互相替代。** 预付款、应收应付、到账、成本、库存价值和收入确认按所选模型口径分别记录，避免发货或签收自动等于收款。
**SUPPLIER-009｜替代有明确授权。** 商业同意、技术适配、法定适用和现场可用条件分别核验；供应商建议不直接改写设计或总包范围。
**SUPPLIER-010｜技术故障不形成业务事实。** 超时、模型调用预算不足和无效输出保持技术状态；不伪造接单、完工、发运、收款或拒绝。
相同订单/批次/支付执行 ID 去重；结果未知先核对已提交事实。补救、取消和重试均保留原承诺及处理历史。

### 5.2 对象转换与剩余责任

**SUPPLIER-027｜临时意向不抢占正式产能。** 报价和咨询不自动独占产线、库存或运输；若有授权临时预留，单独注明对象、期限和解除条件。
未选、有效拒绝、撤回或失效时，释放该次可解除预留；已承诺订单及其他项目占用不得被连带释放。
临时预留转为正式分配引用同一来源，不先保留原预留再增加第二笔占用；同刻冲突处理方式仍待 D-05。

**SUPPLIER-028｜可供数量与产能共同约束承诺。** 实际库存、已分配库存、预计在制完工和尚未接受的上游交期不是同一类可用量。
按产品相容性与时间窗口核对共享产线和必要投入，不能用全厂通用评分代替某规格可制造能力。
确认新订单前重新检查已承诺范围；超额需求可以拒绝、改期、部分承诺或请求合法替代，不能自动降低原客户数量。

### 5.3 实际数量与停复工

| 对象 | 可审阅的状态变化 | 不可跳过的边界 |
|---|---|---|
| 订单行 | 待接受 → 条件未齐/有效 → 部分履约 → 交付完成/变更/终止 | 交付完成与质量责任、应收结清分别判断 |
| 制造任务 | 待料/待版本/待资源 → 可执行 → 在制 → 待检/完成 | 生产完成量由核心计算，缺必要投入时不产出 |
| 外购任务 | 待接受 → 上游承诺 → 发运/到达 → 对应接收 | 上游承诺不当作实际在库，外部履约机制需明示 |
| 质量范围 | 待检 → 合格/限制用途/隔离 → 返工/报废 → 复检 | 返工不保证合格，不因订单催交自动放行 |
| 物流子批次 | 待发 → 实际出库 → 在途 → 到达 → 分范围接收/拒收 | 发运、短缺、破损和退回保留真实位置及来源 |
| 取消范围 | 待决定 → 有效取消 → 物料/费用处理 → 对应责任结束 | 不删除在制、在途、已交付事实或未清货款 |

**SUPPLIER-029｜生产投入与产出可追查。** 核心使用已定义的材料转换及生产规则，登记实际消耗、在制、合格产出、返工和损耗。
不同单位不能用“投入件数等于产出件数”强行配平；原料到成品的对应关系、工艺损耗和转换单位必须明示，参数未定时不猜测。
同一材料或工时不得同时用于多个任务的全额产出；生产记录重试沿原执行身份核对，不再次扣料、记成本或生成成品。

**SUPPLIER-030｜分批、移动和分配保持数量一致。** 同规格同单位的批次拆分后，子范围数量与父批次被转出范围相符；合并保留来源和相容条件。
位置移动成对减少来源并增加去向，在途损失/报废另有记录；数量不得因换批次名、仓库或保管方增加。
订单分配是货物上的承诺，不是第二份实物；同一可分配范围不能同时承诺多个客户，实际消耗/交付同步解除相应可分配数量。

**SUPPLIER-031｜分范围接受与拒收。** 到货记录保留实收、短缺、检验中、合格接受和拒收范围；同一子范围不能既可用又处于有效隔离。
拒收不等于货物瞬间回到供应商仓库，须明确临时保管、返运与后续接收；客户拒收也不自动确定费用责任或退款金额。
接受回执重送不重复增加客户库存、订单完成量或货款；替换交付引用原缺陷/退货，避免原件与替件同时计为履约成功。

**SUPPLIER-032｜暂停恢复与余料处置有边界。** 停产、订单暂停和运输延误影响不同范围；在制品保管、已承诺运费及上游债务继续按依据处理。
恢复先核对规格、原料/产品状态、实际产线和接收窗口；过期、损坏或被重新分配的资源不得自动恢复。
取消后自用、转售、返还或报废须先核对物料所有权和合同限制；转卖不是复制库存，收到处置款也需实际资金记录。

**SUPPLIER-033｜经营反馈不改写历史。** 企业据可见履约和收付更新客户、生产及路线预期，保存原预测与误差来源。
维护、扩产和流程改善若纳入模型，须有授权任务、资金/资源、持续时间与效果依据，不能月度发言后直接增产能。
上一订单失败不要求后续必然拒绝，经营目标与信息可导致不同选择，但合法资源与资金约束始终校验。

运行组合分别声明本企业是否只在既有设施分配订单、采用外生给定设施变化，或支持自主投资/扩产。后者需引用实际投资动作、持续时间、资金及投产/退出方法，未支持时不产生能力变化。合并订单是否节省准备、换线或重复工作，依据产品/接口相容性、批次和窗口方法计算；同厂采购或报价下降不自动降低实际资源成本。制造和运输损伤、检查、修复沿 [OBJ-022 的质量方法链](../02_world/domain_objects.md#工程转换与质量状态的方法链)保持同一实物身份，不以通过一次检查重新生成合格品。

### 5.4 正常路径与失败恢复

以下为假想检验场景，不设置通用产能、天数、损耗或费用，不代表真实制造/贸易结果。

**情境 S1：制造企业分批交付。**
1. 企业比较询价与已有订单，发出带规格和交付责任的报价；客户接受最终条款后提交统一资源检查并形成订单。
2. 有效预付款实际到账只记一次；必要资料、材料和产线窗口就绪后，核心按实际投入计算对应在制与产出。
3. 检验只放行合格范围，分拆子批次实际发运；客户分范围实收与认可，余量保持在正确位置和状态。
4. 货款按条款形成和到期，预付款另记非现金抵扣，后续收款只清偿未付部分；不因交付而再次增加现金。
5. 清理适用订单占用、剩余货物、质量责任和上下游欠款，企业保存观察继续参与新业务。

**情境 S2：贸易企业上游迟交并出现拒收。**
1. 本企业向明确上游采购；收到预计发运信息不记自产或在库，延误触发对客户的有条件更新与改期请求。
2. 实际到货部分符合规格，另一部分存在问题；两部分按范围处理，不能因一份签收记录把整单标成已完成。
3. 客户拒收的问题货物保留真实位置和临时保管责任；有效退运、返修或补货分别更新原批次链和费用事项。
4. 替件经实际交付和必要核验后只补足对应未满足范围，旧件的处置不重复生成可售库存或清偿货款。
5. 客户迟付时本企业上游债务仍存在；恢复不了则按有效终止处理余料、退款和剩余责任，不清空历史。

## 6. 验收场景

下列场景规定实现应满足的结果，须以实际检查记录判定是否通过。流程一致性、真实决策行为、方法校准和现实工程或制度验证分别报告；示意数据不作为真实项目参数。

### 6.1 全生命周期边界

| 编号 | 场景 | 应检查的结果 |
|---|---|---|
| CHECK-SUPPLIER-001 | 客户预测有需求但没有订单 | 不自动占用正式交付产能或生成货款义务 |
| CHECK-SUPPLIER-002 | 规格缺失或接口不兼容 | 请求澄清或限制报价，不默认产品可用 |
| CHECK-SUPPLIER-003 | 客户选中但本供应商拒绝新条款 | 不产生新有效订单或强制履约承诺 |
| CHECK-SUPPLIER-004 | 报价已失效或改选另一供应商 | 重新核对完整版本，不能混用金额/交期/条件 |
| CHECK-SUPPLIER-005 | 同批库存被两个订单请求 | 只按规则分配一次，未满足者获得冲突反馈 |
| CHECK-SUPPLIER-006 | 同期订单超出必要设备/产线能力 | 处理排期和承诺冲突，不复制产能 |
| CHECK-SUPPLIER-007 | 原料或制造所需版本未到位 | 依赖任务不产出，独立可做任务可继续 |
| CHECK-SUPPLIER-008 | 经销商向上游下单但尚未交货 | 不计作自产完成或可售到手库存 |
| CHECK-SUPPLIER-009 | 自检通过但约定外部核验未完成 | 不自动获得全部交付/使用放行 |
| CHECK-SUPPLIER-010 | 已出库仍在运输途中 | 从正确库存位置转为在途，不记客户已收货 |
| CHECK-SUPPLIER-011 | 到货短缺、破损或不符 | 分别记实收、隔离、争议与后续补货，不全额可用 |
| CHECK-SUPPLIER-012 | 部分批次接收合格 | 只放行对应数量和用途，不将整张订单视为完成 |
| CHECK-SUPPLIER-013 | 未获批准的替代产品抵达 | 不自动进入依赖原规格的施工任务 |
| CHECK-SUPPLIER-014 | 已装产品退换或发现缺陷 | 保留原批次与消耗历史，另建处置、责任和替换记录 |
| CHECK-SUPPLIER-015 | 同一发货/付款响应被重复处理 | 不重复扣库存、增加到货或清偿债务 |
| CHECK-SUPPLIER-016 | 项目业主资金不足 | 记录本企业可见信息与合同付款人义务，不自动免债或穿透取款 |
| CHECK-SUPPLIER-017 | 订单取消但存在在制品、预付款和欠款 | 按权利与责任处理资产、费用和退款，不能一键清零 |
| CHECK-SUPPLIER-018 | 所属项目完工但保证义务尚存 | 释放可释放产能，保留本订单应收与质量责任 |

### 6.2 实物与运输链

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-SUPPLIER-047 | 注册地、生产设施与交付地区不同 | 四地分别引用，不用注册地造产地、资格或库存 |
| CHECK-SUPPLIER-048 | 同一产品换工厂或目的地用途 | 定位受影响证据/接口复核，其他有效范围保留 |
| CHECK-SUPPLIER-049 | 多个城市项目争用同一产线/能力池 | 可用窗口只分配一次，区域汇总不再新增一份容量 |
| CHECK-SUPPLIER-050 | 工厂完工但缺运力或现场窗口 | 不直接生成到货，分段等待有责任与实际位置 |
| CHECK-SUPPLIER-051 | 湾区外原料或未建模运输服务进入模型 | 有来源、数量、履约、供给限制及费用，不免费无限生成 |
| CHECK-SUPPLIER-052 | 参数化产品缺材料转换或生产方法 | 正式计算保留缺口，不按订单数量直接产出 |
| CHECK-SUPPLIER-053 | S3 分批、拒收、返运、替件再交付 | 11 件产出最终对应 10 件进入工程和 1 件隔离，原料投入不复用 |
| CHECK-SUPPLIER-054 | 在途批次改路线、改目的地或改承运安排 | 重查适用条件并接续实际位置，不复制或瞬移库存 |
| CHECK-SUPPLIER-055 | 订单取消后收到可靠旧生产/到货结果 | 保留真实片段和异常物料，不重新执行或强行计完成 |
| CHECK-SUPPLIER-056 | 同一货物同时出现在父批次、子批次和分配记录 | 区分汇总与实物，库存不按标签累计 |
| CHECK-SUPPLIER-057 | 到货后无付款或成本依据仍缺失 | 现金不增加；未定估值不写零，既有上游义务保留 |
| CHECK-SUPPLIER-058 | 同名产品从普通建筑用途改供桥梁、隧道或未覆盖超高层接口 | 核对规格、用途、方法与证据；供应商地区/评分和复杂系数不能自动证明相容 |
| CHECK-SUPPLIER-059 | 总项目采购汇总与两个子工程订单引用同一需求/批次 | 按真实需求、分配和批次身份生产/交付一次，不因三层记录重复投产或增加库存 |
| CHECK-SUPPLIER-060 | 一厂同批产品经共同运输段送往两个地区的子工程 | 产线、实物及共同运力只计一次，目的地/接收窗口分别检查，分段费用不在各地区重复全额归集 |

### 6.3 前期咨询

| 编号 | 场景 | 应检查的结果 |
|---|---|---|
| CHECK-SUPPLIER-019 | 只有功能与规模区间，未完成设计 | 可给有限意见和待核条件，不强制完整设计或伪造细节 |
| CHECK-SUPPLIER-020 | 供应商推荐本企业 MiC 产品组合 | 保留商业立场和证据限制，不自动得到优越评分 |
| CHECK-SUPPLIER-021 | 产能咨询得到积极答复 | 不生成订单、预留或客户费用义务 |
| CHECK-SUPPLIER-022 | 参考价拟转为有约束报价 | 重新核对版本、范围、条件和共享资源，不直接改名提交 |
| CHECK-SUPPLIER-023 | 替代规格被供应商认可但专业接口未核实 | 保留待核状态，不改设计或据此使用产品 |
| CHECK-SUPPLIER-024 | 报告只写生产周期和出厂价 | 分列物流、安装及交付责任的未知项，不推导完整交付结果 |
| CHECK-SUPPLIER-025 | 简报改地区或生产窗口 | 标记受影响意见复核，保留原记录且不自动改变既有订单 |
| CHECK-SUPPLIER-026 | 多方共享资料或同一研究重复响应 | 引用和执行去重，收费按实际授权任务，不重复产生成本 |
| CHECK-SUPPLIER-027 | 其他主体请求竞争客户的私有排期 | 拒绝越权披露，可在权限内提供有条件能力范围 |
| CHECK-SUPPLIER-028 | 前期咨询结束后进入采购 | 不因早期参与自动授标，也不排除未参与咨询者 |

### 6.4 资金义务

| 验收编号 | 场景 | 应检查的结果 |
|---|---|---|
| CHECK-SUPPLIER-029 | 承包商下单，最终项目属于 Owner | 货款关联有效订单付款人，不默认向 Owner 记应付 |
| CHECK-SUPPLIER-030 | 预付款已到账，后续分批抵扣 | 原到账只记一次，抵扣按剩余可分配金额处理，不新增现金 |
| CHECK-SUPPLIER-031 | 产品到货但客户尚未付款 | 交付与符合条款的应收可更新，现金保持实际到账状态 |
| CHECK-SUPPLIER-032 | 同一货款分次支付且回执重送 | 按唯一执行与分配累计清偿，不重复记款或超额冲销 |
| CHECK-SUPPLIER-033 | 银行直接支付采购方所欠货款 | 供应商只收一次，对应货款减少；不重复增加采购方现金 |
| CHECK-SUPPLIER-034 | 客户迟付但本企业上游货款到期 | 保留独立上游义务，现金不足形成未付状态，不自动免债 |
| CHECK-SUPPLIER-035 | 取消订单时仍有预付款与未清货款 | 保留历史现金，按有效依据处理退款/调整和剩余义务 |

### 6.5 经营与恢复

| 编号 | 场景 | 预期 |
|---|---|---|
| CHECK-SUPPLIER-036 | 多份报价都引用同一产线/库存 | 不自动独占；正式承诺时统一检验产品和窗口冲突 |
| CHECK-SUPPLIER-037 | 临时预留后未选中或明确拒绝 | 释放本次适用预留，不误释放其他有效订单 |
| CHECK-SUPPLIER-038 | 贸易商获得上游交期承诺 | 不记自产或在库，等待明示外部实际履约 |
| CHECK-SUPPLIER-039 | 同一材料批次被两项生产重复使用 | 校验实际分配及消耗，不能各自获得全部原料 |
| CHECK-SUPPLIER-040 | 生产成功后响应丢失并重试 | 原执行产出/扣料/成本只记一次，先核对再恢复 |
| CHECK-SUPPLIER-041 | 批次拆分、移动及多订单分配 | 同单位数量和来源可核对，不把预留当新实物 |
| CHECK-SUPPLIER-042 | 到货一部分合格、一部分拒收 | 仅相应数量可用，拒收部分保持位置及待处理状态 |
| CHECK-SUPPLIER-043 | 同一收货回执重复或替件交付 | 不重复入库/计完成量，替件与原问题范围关联 |
| CHECK-SUPPLIER-044 | 恢复订单时产线已占用、材料已过期 | 重新核对和排期，不自动沿用全部旧资源 |
| CHECK-SUPPLIER-045 | 取消订单后试图转售客户所有物料 | 校验权利及有效处置依据，不自行变成可售库存 |
| CHECK-SUPPLIER-046 | 不同单位的材料转换缺少规则 | 保留无法计算，不以件数强行守恒或造出产量 |

### 6.6 输入装配与分支接续

| 编号 | 情形 | 预期 |
|---|---|---|
| CHECK-SUPPLIER-061 | 生产计划缺原料，且上游尚未报价 | A05 记录计划需求并发询价，正式接受上游报价另走订单门槛；不造在库原料或无限上游供货。 |
| CHECK-SUPPLIER-062 | 未发货需要改期，或发货后不再有可发运库存需核对 | A08 使用订单行/已有运输分支，不伪造 Shipment；历史核对不重复出库。 |
| CHECK-SUPPLIER-063 | 供应商需补证/首次请款/提出尚未收款的索赔 | A09 不要求供应商拥有收货人权限；A10 用请款草稿；A11 索赔不强制已有原支付交易，三者不宣称已经收到钱。 |


## 7. 参数、方法与配置依赖

**SUPPLIER-011｜生产与物流参数需证据。** 不预设统一产能、提前期、运价、损耗、合格率或缺陷期限；区分工程约束、数据和情景假设。
**SUPPLIER-012｜按本主体维护。** 本文保持供应商行为完整，采购方行为交由相应主体主规范，共享链条用于定位交接阶段。

| 选择 | 对本角色的影响 |
|---|---|
| D-02 资金范围与机制 | 基础账本包含现金、应收应付、贷款和到期义务；备货/预付款机制、价值口径及具体实现仍待细化 |
| D-03/D-06 身份与模板 | 制造/经销、构件/设备、设计安装与外部物流的覆盖范围 |
| D-04/D-05 时间与竞争 | 生产和运输尺度、接收窗口、库存分配与跨客户承诺 |
| D-07 工程粒度 | 产品单位、批次、库存位置、工序/材料替代与检验层级 |
| D-08/D-09 反馈与信息 | 报价响应、需求预测、客户信息及可靠性学习 |
| D-10/D-11 异常与决策 | 退换/召回、暂停取消、责任结束、合法动作与技术失败 |

模型决策见[配置选择](../07_experiments/model_decisions.md)。未选定的方法、阈值、时间粒度、资格或产品条件须显式保持待定；不得以示例值、角色标签或未覆盖范围补成正式结论。

参数表不预设法定期限、产能公式或自动免费补货。
