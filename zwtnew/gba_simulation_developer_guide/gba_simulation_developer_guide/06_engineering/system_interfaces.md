# 世界、项目与平台的函数接口目录

规范性质：目标函数边界与输入输出契约；本目录不表示已有同名代码或可执行方法。业务规则以所属主文件为准，未决算法、精度和参数依[模型决策](../07_experiments/model_decisions.md)选择，不由函数名称隐含决定。

[公共接口协议](interface_contracts.md) · [架构与提交](implementation_contracts.md) · [项目交接](../03_projects/collaboration_flow.md) · [生命周期](../03_projects/project_lifecycle.md) · [运行与结果](../07_experiments/run_and_results.md)

<!-- page-nav:start -->
**本页导航**

[1. 目录边界与读法](#1-目录边界与读法) · [2. 数据、证据与初态装配](#2-数据证据与初态装配) · [3. 世界条件、需求、背景负载与持续经营](#3-世界条件需求背景负载与持续经营)

[4. 时间、队列、行动机会与竞争](#4-时间队列行动机会与竞争) · [5. 政策证据、机制、编译及应用](#5-政策证据机制编译及应用) · [6. 项目、责任、成果、审查与合同](#6-项目责任成果审查与合同)

[7. 资源、批次、实际工程和资产交接](#7-资源批次实际工程和资产交接) · [8. 成本、债务、付款与外部核对](#8-成本债务付款与外部核对) · [9. 可见信息、候选、认知与技能宿主](#9-可见信息候选认知与技能宿主)

[10. 运行控制、检查点与恢复](#10-运行控制检查点与恢复) · [11. 网络、指标、实验样本与比较](#11-网络指标实验样本与比较) · [12. 页面查询、明确命令与版本导出](#12-页面查询明确命令与版本导出)

[13. 全链覆盖与调用责任](#13-全链覆盖与调用责任) · [14. 进入实现前的补齐与验收](#14-进入实现前的补齐与验收)
<!-- page-nav:end -->

## 1. 目录边界与读法

本文件是**非角色模块的目标逻辑函数及其局部传输类型**的唯一技术定义入口。八类角色的行为契约定义主体的选择、专业材料和允许命令；这里定义怎样把这些选择连接到真实任务、账本、工程、政策、实验与页面。函数名称是稳定的逻辑身份，未来 Python、HTTP 或前端方法可采用不同语言形式，但必须在实现登记中明确映射，不因包装层另造一份业务。

- `Ref<K>`、`EntityId<K>`、`ScopeRef`、`Money`、`Measured`、`ReadContext`、`ActionContext`、`ServiceContext`、`CommandEnvelope`、`CommandReceipt`、`QueryResult<T>`、`PreparedChange`、`MethodResult<T>`、`ExternalAttemptResult<T>` 使用[公共协议](interface_contracts.md)。同一状态引用必须带版本，不能只传显示名称。
- 下文 `Q<T>` 表示 `QueryResult<T>`；`M<T>` 表示 `MethodResult<T>`；所有准备函数返回公共 `PrepareResult`，其中 `prepared.change` 只是待校验变化，尚不是正式事实。表中“拟产物”限定成功变化写入的对象 schema，正式引用只从 `core.commit` 或 `core.commit_workspace` 的回执读取。业务拒绝、缺项、输入非法、不支持及技术失败沿公共联合返回，不另定义准备结果。
- `R` 是无业务副作用查询；`M` 是指定方法下的计算；`P` 仅准备变化；`X` 是获授权的外部适配器执行。所有 `P` 的正式写集按数据空间交公共 `core.commit` 或 `core.commit_workspace`，再读取正式回执；`ServiceContext` 不能假冒角色授权：资料/政策准备校验 workspace，世界执行校验 run；只读/计算仍按其输入所属数据空间校验，不因目录可读取就获得跨空间访问权；`P` 不能写数据库、扣款、预占容量或投递消息。跨拥有者变化必须同次校验并原子提交。
- `M` 不直接写正式状态；纯内存值计算无外部副作用，模型调用、技术日志或隔离临时文件必须在该函数列中另行声明并记录稳定任务身份，不能仅凭M标签认为无成本；使用模型或付费工具的计算还需要显式 `ExecutionPermit`，不能从只读页面触发。结果不足时返回 `needs_information`、`unsupported` 或 `technical_error`，不能返回成功的空成果或零成本。
- 表中的“键”是业务去重范围，不代替 `command_id`。同键同语义只产生一次后果；同身份不同内容走 `identity_conflict`；旧版本走 `version_conflict`；真实授权修订、补件、重评、执行分片用新的业务身份。未知结果先查询，不当作业务拒绝。
- 时间是带时钟引用的业务量；不预定日、周、月。`List<T>` 沿公共协议为有序列表；集合性质字段须按相应定义排重，不能把列表顺序隐含当业务优先级。`OrderedList<T>` 在这里是 `List<T>` 的别名，强调其顺序对业务有意义。除显式 `Option<T>`，字段均必填。禁止额外未登记字段；枚举扩展须更新 schema 版本。

所有带Ref而未逐项写ctx的纯结构检查只检查已经装配的值/schema，不自行访问全局存储；需要解析对象时必须通过明确ReadContext，不能偷用“当前运行”。

计算/准备中的新对象使用公共 `ProposedIdentity<K>`，跨对象待建依赖仅在下文显式标为 `DraftRef<K>` 的字段中允许；二者都不是可解析的正式 `Ref<K>`。表中“拟产物”的 Ref 只说明成功提交后的返回种类。方法和 prepare 不得先把拟身份交给下游当已有正式成果；必须等待提交回执，再以相同读点重新读取所需类型。已经存在的源输入继续使用 Ref。

按业务定位：资料/初态见第2节；环境/需求见第3节；调度见第4节；政策见第5节；工作与合同见第6节；实物与工程见第7节；资金见第8节；主体输入与技能见第9节；恢复见第10节；实验与比较见第11节；页面/导出见第12节。各节先给具名类型再列唯一入口，跨领域拥有者仍以[软件架构](implementation_contracts.md)为准。

含 `identity:ProposedIdentity<K>` 的下列计算值是 **K 的具名待提交数据形状**，不得直接作为读取接口的已保存 K 返回。对应 P 接口只接收本节声明的类型，并把同组待建对象、依赖和草稿检查一起提交；提交后查询使用正式Ref与登记的读取schema。未定义的领域完整字段必须由唯一所属对象/schema补齐后才能启用，不以通用schema_ref当作字段已齐的证明。

### 1.1 公共辅助类型

| 类型 | 必须提供的字段与边界 |
|---|---|
| `TimePoint` / `TimeWindow` | 复用公共时间类型；原点、单位、边界和允许零长窗口由引用的时钟/方法确定，不另定义本地时间协议 |
| `ContractIssue` | `code:IssueCode, field_path:string, related_refs:List<Ref<Entity>>, required_refs:List<Ref<Entity>>, explanation:string`；`IssueCode` 为 missing_input、unsupported_method、invalid_unit、out_of_scope、forbidden、stale_dependency、identity_collision、coverage_conflict、capacity_conflict、insufficient_funds、invalid_state、unresolved_result、method_failure |
| `ExecutionPermit` | `permit_ref:Ref<ExecutionPermit>, provider_ref:Ref<Provider>, mode:llm\|rule\|routine\|offline_fixture, max_calls:int≥0, max_tokens:Option<int≥0>, wall_timeout_ms:int≥0, allowed_tool_refs:List<Ref<Tool>>`；mode与ActionContext.execution_mode使用相同枚举；只是调用授权，wall_timeout_ms为墙钟超时，不能推进业务时钟；实际耗用另登记，不是企业现金 |
| `RandomSlice` | `stream_ref:Ref<RandomStream>, position_start:int≥0, draw_count:int≥0, purpose_key:string`；相同执行身份重试复用，不因为多一次日志再抽样 |
| `ParameterValue` | `parameter_ref:Ref<ParameterDefinition>, value:decimal\|bool\|string\|Ref<Entity>, unit:Option<string>, basis_refs:List<Ref<Evidence>>`；具体定义限制枚举/数值域与可空语义，不接受任意键值 |
| `ValueState<T>` | 复用公共 known、unknown、not_applicable、not_supported 联合；不能用 0 或空串代替未知 |
| `Readiness` | `ready:bool, issues:List<ContractIssue>, satisfied_refs:List<Ref<Entity>>, next_trigger_refs:List<Ref<Trigger>>`；不是法定批准，ready=false 不强制所有其他范围停用 |
| `FactSelection` | `run_ref:Ref<Run>, commit_from:int≥0, commit_to:int≥commit_from, scope_refs:List<ScopeRef>, fact_kinds:List<Ref<FactType>>`；明确选择同一运行已提交事实 |

`Ref<Entity>` 只用于已登记的跨类型引用集合，运行时验证 `kind`；不是任意 JSON 对象。下面局部类型是模块交接必备字段，实体的完整业务字段仍由[共同对象](../02_world/domain_objects.md)及对应角色契约拥有；实现时不能只存这份精简投影就声称完整恢复。

## 2. 数据、证据与初态装配

主规则：RUN-001—004、OBJ-020/021；验收见[期初与整次运行验收](../07_experiments/run_and_results.md#10-整次运行验收条件)、[对象验收](../02_world/domain_objects.md#10-业务验收场景)。

### 2.1 交接类型

| 类型 | 字段 |
|---|---|
| `SourceTimestamp` | `iso8601:string, timezone:string, precision:date\|second`；真实来源时间，只有通过明确映射才成为模拟TimePoint |
| `SourceRecord` | `record_id:string, source_ref:Ref<Source>, locator:string, content_hash:string, observed_at:ValueState<SourceTimestamp>, fields:List<SourcedField>` |
| `SourcedField` | `field_ref:Ref<FieldDefinition>, value:ValueState<ParameterValue>, provenance:real_user\|real_public\|synthetic, completion:observed\|inferred\|assumed, evidence_refs:List<Ref<Evidence>>` |
| `NormalizedBatch` | `identity:ProposedIdentity<DataBatch>, records:List<SourceRecord>, transformation_ref:Ref<Method>, issues:List<ContractIssue>` |
| `EntityMatch` | `identity:ProposedIdentity<EntityMatch>, source_record_ids:List<string>, organization_ref:Option<Ref<Organization>>, outcome:matched\|distinct\|unresolved, basis_refs:List<Ref<Evidence>>`；未确定不得自动合并 |
| `DataQualityAssessment` | `identity:ProposedIdentity<QualityReport>, batch_hash:string, match_hash:string, coverage_ref:Ref<CoverageDefinition>, check_profile_ref:Ref<DataCheckProfile>, passed:bool, issues:List<ContractIssue>`；检查描述支持范围，不把合成补全标成真实 |
| `DataReleaseDraft` | `identity:ProposedIdentity<DataRelease>, batch:NormalizedBatch, matches:List<EntityMatch>, coverage_ref:Ref<CoverageDefinition>, quality:DataQualityAssessment`；prepare同次保存必要批次、身份匹配、质量报告和发布记录，不先要求这些草稿拥有正式Ref |
| `InitialEntry` | `object_ref:DraftRef<Entity>, scope_ref:InitialScope, source_refs:List<Ref<Evidence>>, stock_or_flow:stock\|flow, physical_key:Option<string>, included_source_keys:List<string>`；金额/资源/存量实体以引用解析其单位与归属 |
| `InitialObjectDraft` | `identity:ProposedIdentity<由initial_kind确定的对象种类>, initial_kind:assessment_case\|work_scope\|agent\|organization\|account\|obligation\|resource\|inventory\|asset\|project\|agreement\|cognitive_state\|clock\|control\|queue, schema_ref:Ref<InitialObjectSchema>, initial_payload:RegisteredInitialPayload`；有限联合按OBJ-021逐类型声明字段和来源；只在bootstrap.prepare_run允许的初态对象拥有者范围使用，未登记成员拒绝 |
| `InitialScope` | `kind:assessment_case\|project\|organization, object:DraftRef<Entity>, coverage:List<DraftRef<WorkScope>>`；只用于初态组，提交后转正式ScopeRef |
| `InitialPlan` | `draft_group_id:string, run_instance_ref:ScopedRef<RunInstance>, manifest_ref:ScopedRef<RunManifest>, target_run_id:EntityId<Run>, reference_imports:List<ReferenceImportPlan>, initial_objects:List<InitialObjectDraft>, agent_refs:List<DraftRef<Agent>>, entries:List<InitialEntry>, cognitive_baseline_refs:List<ScopedRef<CognitiveBaseline>>, exclusions:List<ContractIssue>`；源侧引用带workspace空间；InitialObjectSchema按冻结初始化能力读取，target侧仅在指定初始化组解析 |
| `OpeningBalanceCheck` | `check_id:string, subject:DraftRef<Entity>, invariant_ref:Ref<InvariantDefinition>, passed:bool, issues:List<ContractIssue>`；对同一初态组的值检查，不要求对象已正式创建 |
| `OpeningAudit` | `plan_hash:string, balance_checks:List<OpeningBalanceCheck>, duplicate_keys:List<string>, missing_dependencies:List<ContractIssue>, ready:bool` |

运行装配中 `reference_imports` 使用公共 `ReferenceImportPlan`，提交完成生成 `ReferenceImport`，显式记录获授权 `ScopedRef` 来源→run本地Ref及内容摘要。workspace方法/政策/数据在初始化中不可变导入本run后，角色/工程/政策函数只接本空间Ref，不按同名ID跨空间查找。导入失败仅保留可追查的初始化实例，不能把未导入引用当可执行前置。

### 2.2 函数

| 唯一函数与签名 | 调用者 → 消费者；状态拥有者/边界 | 异常与业务键 |
|---|---|---|
| `data.normalize_sources(ctx:ReadContext, source_records:List<SourceRecord>, mapping_ref:Ref<FieldMapping>, method_ref:Ref<Method>) → M<NormalizedBatch>` | 数据导入 → 身份匹配/质量审核；数据准备/M | 缺原始字段、单位不相容、映射未支持；无写入，缓存键为来源哈希＋映射＋方法版本 |
| `data.resolve_entities(ctx:ReadContext, batch:NormalizedBatch, match_policy_ref:Ref<MatchPolicy>, confirmed_matches:List<EntityMatch>) → M<List<EntityMatch>>` | 数据准备 → 发布装配；数据准备/M | 名称相似但证据不足返回 unresolved，不制造组织现金；同一来源身份冲突报错 |
| `data.audit_release(ctx:ReadContext, batch:NormalizedBatch, matches:List<EntityMatch>, coverage_ref:Ref<CoverageDefinition>, check_profile_ref:Ref<DataCheckProfile>) → M<DataQualityAssessment>` | 发布装配 → 数据prepare；资料/M | 检查同版批次/匹配/覆盖及字段来源；输出检查值，不先要求已发布数据 |
| `data.prepare_release(ctx:ServiceContext, draft:DataReleaseDraft) → PrepareResult` | 数据维护命令 → 初态装配；数据目录/P；拟产物 `Ref<DataRelease>` 及同次保存的DataBatch/EntityMatch/QualityReport | 缺来源/覆盖说明；键为 release ID＋版本，冻结版本不得覆盖 |
| `bootstrap.prepare_instance(ctx:ServiceContext, manifest_ref:Ref<RunManifest>, requested_run_id:EntityId<Run>, creation_identity:string) → PrepareResult` | 明确创建请求 → 初始化协调者；workspace实例目录/P；拟产物 `Ref<RunInstance>` | 同名身份/不同清单冲突；键为creation_identity；只登记initializing及稳定run身份，不造活动世界 |
| `bootstrap.plan_initial_world(ctx:ReadContext, run_instance_ref:Ref<RunInstance>, manifest_ref:Ref<RunManifest>, data_ref:Ref<DataRelease>, scenario_ref:Ref<Scenario>, population_ref:Ref<PopulationSpec>, opening_ref:Ref<OpeningSpec>, cognition_ref:Ref<CognitionSpec>) → M<InitialPlan>` | 建立运行用例 → 期初审核；运行编排/M | 未声明补足、重复来源、未定覆盖；不为了补齐失败项目临时增企业 |
| `bootstrap.audit_opening(ctx:ReadContext, plan:InitialPlan, accounting_ref:Ref<AccountingProfile>, resource_ref:Ref<ResourceProfile>, coverage_ref:Ref<CoverageDefinition>) → M<OpeningAudit>` | 初始化 → 提交门控；各领域共同核验/M | 现金/债务不平、库存/资产重复、背景与显式主体重叠；不改输入以“修平” |
| `bootstrap.prepare_run(ctx:ServiceContext, plan:InitialPlan, audit:OpeningAudit) → PrepareResult` | 已在 workspace 登记实例身份后的初始化命令 → 运行控制/页面；运行编排及各账本/P；拟产物 `Ref<Run>` | 未通过必要初态检查、manifest 变化；键为运行创建命令业务身份，workspace预留与run初始化各自提交；失败保留initializing/failed实例供核对，完整初态提交后才可启动，不伪称跨数据空间原子 |
| `bootstrap.prepare_instance_status(ctx:ServiceContext, instance_ref:Ref<RunInstance>, initialization_result:CommandAttemptResult, initialized_run_ref:Option<ScopedRef<Run>>) → PrepareResult` | 初始化协调者 → workspace实例目录；目录/P；拟产物 `Ref<RunInstance>`新版本 | 核对该实例、原run创建命令与data_space；committed且初态可读才ready；unknown/pending保持核对，确定未提交的失败才标失败；null表示没有可确认的Run，不能据此造第二运行 |

## 3. 世界条件、需求、背景负载与持续经营

主规则：WORLD-001—005/017—021/025—029、OBJ-017；W1/W2/W3 和 D-01/08 仍限定方法支持范围。验收见[世界调度验收](../02_world/world_runtime.md#调度验收场景)及[跨周期验证](../07_experiments/verification_strategy.md)。

### 3.1 交接类型

| 类型 | 字段 |
|---|---|
| `EnvironmentSlice` | `region_ref:Ref<Region>, window:TimeWindow, parameter_values:List<ParameterValue>, path_ref:Ref<ExogenousPath>, source_refs:List<Ref<Evidence>>` |
| `DemandCell` | `identity:ProposedIdentity<DemandCell>, region_ref:Ref<Region>, use_ref:Ref<UseType>, service_population_ref:Ref<PopulationScope>, demand:ValueState<Measured>, available_stock:ValueState<Measured>, pipeline:ValueState<Measured>, fulfilled:ValueState<Measured>, basis_refs:List<Ref<Evidence>>`；各量分别有单位，不能默认可相加 |
| `MarketSignal` | `identity:ProposedIdentity<MarketSignal>, window:TimeWindow, cells:List<DemandCell>, price_refs:List<Ref<PriceObservation>>, information_cutoff:TimePoint, feedback_profile_ref:Ref<FeedbackProfile>` |
| `BackgroundClaim` | `claim_id:string, physical_resource_ref:Ref<Resource>, window:TimeWindow, amount:Measured, coverage_key:string, source_ref:Ref<BackgroundSource>, relation_to_explicit:excluded\|residual\|shared_allocation` |
| `UtilizationOutcome` | `asset_ref:Ref<Asset>, use_right_ref:Ref<Right>, demand_cell_ref:Ref<DemandCell>, window:TimeWindow, utilized:Measured, transaction_refs:List<Ref<Transaction>>, unmet:Measured`；利用不直接等于现金 |
| `OperatingCostDraft` | `identity:ProposedIdentity<CostAssessment>, organization_ref:Ref<Organization>, scope_ref:ScopeRef, amount:Money, incurred_window:TimeWindow, cost_kind_ref:Ref<CostKind>, basis_refs:List<Ref<Evidence>>` |
| `CapacityChangeDraft` | `identity:ProposedIdentity<CapacityChange>, resource_ref:Ref<Resource>, previous_capacity:Measured, next_capacity:Measured, effective_window:TimeWindow, basis_refs:List<Ref<Evidence>>`；不删除已成立承诺，冲击短缺另记录 |
| `OperatingOutcome` | `organization_ref:Ref<Organization>, window:TimeWindow, cost_assessments:List<OperatingCostDraft>, capacity_changes:List<CapacityChangeDraft>, obligation_basis_refs:List<Ref<Evidence>>, uncovered_mechanisms:List<Ref<Capability>>` |

### 3.2 函数

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `world.sample_exogenous(path_ref:Ref<ExogenousPath>, window:TimeWindow, region_refs:List<Ref<Region>>, random_slice:RandomSlice) → M<List<EnvironmentSlice>>` | 已授权调度 → 环境更新；环境/M | 超出数据窗口、冲击相关性/暴露未定返回缺项；不为每项目独立复制共同冲击 |
| `world.prepare_environment(ctx:ServiceContext, previous_ref:Ref<Environment>, slices:List<EnvironmentSlice>, policy_effect_refs:List<Ref<PolicyEffect>>) → PrepareResult` | 调度 → 候选/工程/市场方法；环境/P；拟产物 `Ref<Environment>` | 只消费已提交且适用的宏观参数效果；原子规则交各自拥有者。冲突覆盖或非法单位拒绝；键为路径/政策作用身份＋窗口＋地区，宏观与原子作用不重复 |
| `market.compute_signals(ctx:ReadContext, previous_ref:Ref<MarketSignal>, facts:FactSelection, environment_ref:Ref<Environment>, feedback_ref:Ref<FeedbackProfile>, method_ref:Ref<Method>) → M<MarketSignal>` | 调度汇总 → 观察投影；需求/M | 初态与内生量重复、服务单位不相容；缺方法不得自动调价格 |
| `market.prepare_signals(ctx:ServiceContext, signal:MarketSignal, consumed_fact_refs:List<Ref<Fact>>) → PrepareResult` | 环境反馈任务 → Owner 等的观察；需求/P；拟产物 `Ref<MarketSignal>` | 截止/反馈次序不符；键为信号定义＋窗口＋已消费事实身份集合 |
| `background.compute_claims(ctx:ReadContext, coverage_ref:Ref<CoverageDefinition>, explicit_commitments:List<Ref<Commitment>>, boundary_ref:Ref<BackgroundProfile>, window:TimeWindow, method_ref:Ref<Method>) → M<List<BackgroundClaim>>` | 初态/周期调度 → 资源竞争；环境/M | W1/W2 未齐、同一物理通道重复；输出主张，不直接占用或凭空扩容 |
| `assets.compute_utilization(ctx:ReadContext, asset_refs:List<Ref<Asset>>, rights:List<Ref<Right>>, demand_ref:Ref<MarketSignal>, window:TimeWindow, method_ref:Ref<Method>, random_slice:RandomSlice) → M<List<UtilizationOutcome>>` | 经营调度 → 资产/需求反馈；资产与需求/M | 缺使用权、重复需求满足、方法不支持；没有交易与支付依据不生现金 |
| `assets.prepare_utilization(ctx:ServiceContext, outcomes:List<UtilizationOutcome>, demand_ref:Ref<MarketSignal>) → PrepareResult` | 已授权经营执行 → 下期需求/结果；资产和需求/P；拟产物 `List<Ref<UtilizationRecord>>` | 同资产同服务量重复；键为资产＋需求归属＋实际使用分片身份 |
| `organizations.compute_operating_period(ctx:ReadContext, organization_ref:Ref<Organization>, operating_profile_ref:Ref<OperatingProfile>, window:TimeWindow, method_ref:Ref<Method>) → M<OperatingOutcome>` | 周期经营 → 能力/应付准备；组织经营/M | 未选闲置/维护/退出方法须标未覆盖；不默认无订单就零成本 |
| `organizations.prepare_operating_period(ctx:ServiceContext, outcome:OperatingOutcome, authorization_refs:List<Ref<Authorization>>) → PrepareResult` | 经营调度 → 资源/账本/观察；组织及各账本/P；拟产物 `Ref<OperatingRecord>`及同次CostAssessment/CapacityChange记录 | 成本依据不足、能力变更越权；键为组织＋期间＋经营方法身份，不在本函数自动付款 |

## 4. 时间、队列、行动机会与竞争

主规则：WORLD-009—012/014/022—024/027—028、FLOW-001/002/007；验收见[调度验收](../02_world/world_runtime.md#调度验收场景)、CHECK-FLOW-002/005/008/009。算法与时间精度依 D-04/05。

| 类型 | 字段 |
|---|---|
| `DueWork` | `work_ref:Ref<ScheduledWork>, scope_ref:ScopeRef, trigger_refs:List<Ref<Trigger>>, earliest:TimePoint, deadline:Option<TimePoint>, dependency_refs:List<Ref<Entity>>, responsible_agent:Option<EntityId<Agent>>` |
| `ActionSlot` | `identity:ProposedIdentity<ActionSlot>, agent_id:EntityId<Agent>, action_contract_ref:Ref<ActionContract>, scope_ref:ScopeRef, candidate_refs:List<Ref<Entity>>, observation_cutoff:TimePoint, expires_at:TimePoint` |
| `SchedulePlan` | `clock_ref:Ref<ClockState>, next_time:TimePoint, ordered_work:OrderedList<DueWork>, matter_clock_updates:List<MatterClockStatusDraft>, fairness_basis_ref:Ref<SchedulePolicy>, blocked:List<ContractIssue>, stop_reason:Option<string>` |
| `AllocationClaim` / `AllocationResult` | claim：`claim_id:string, owner_ref:Ref<Organization>, resource_ref:Ref<Resource>, window:TimeWindow, requested:Measured, priority_basis_refs:List<Ref<Evidence>>`；result：`allocation_id:string, claim_id:string, awarded:Measured, unserved:Measured, method_ref:Ref<Method>, explanation:string` |

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `scheduler.find_due_work(ctx:ReadContext, clock_ref:Ref<ClockState>, queue_ref:Ref<WorkQueue>, horizon:TimePoint) → Q<List<DueWork>>` | 调度器 → 排序；运行/R | 队列版本与时间不符；不能因 GET 被调用就消费队列 |
| `scheduler.plan_next_cycle(ctx:ReadContext, due:List<DueWork>, future_triggers:List<Ref<Trigger>>, clock_ref:Ref<ClockState>, policy_ref:Ref<SchedulePolicy>) → M<SchedulePlan>` | 运行推进命令 → 调度提交；运行/M | 循环依赖/无合法唤醒源显式输出；空队列不等于全部项目完成 |
| `scheduler.prepare_cycle(ctx:ServiceContext, plan:SchedulePlan, control_ref:Ref<RunControl>) → PrepareResult` | 显式推进命令 → 项目/世界执行器；运行/P；拟产物 `Ref<ScheduleCycle>` | 已暂停、旧时间位置、越过授权停止点；键为运行＋调度位置＋周期身份 |
| `scheduler.build_action_slots(ctx:ReadContext, cycle_ref:Ref<ScheduleCycle>, due:List<DueWork>, responsibility_refs:List<Ref<ResponsibilityBinding>>, exposure_profile_ref:Ref<ExposureProfile>) → M<List<ActionSlot>>` | 已提交调度 → 角色决策入口；运行/M | 未绑定实际 agent/授权、候选不可见；不能由调度替角色做选择 |
| `scheduler.prepare_action_slots(ctx:ServiceContext, cycle_ref:Ref<ScheduleCycle>, slots:List<ActionSlot>) → PrepareResult` | 调度机会装配 → 主体宿主；运行/P；拟产物 `List<Ref<ActionSlot>>` | 同周期/任务/主体机会键排重，登记机会不代表主体已行动；正式slot用于候选曝光与DecisionTask装配 |
| `resources.resolve_competition(ctx:ReadContext, claims:List<AllocationClaim>, background:List<BackgroundClaim>, resource_refs:List<Ref<Resource>>, allocation_method_ref:Ref<Method>, random_slice:RandomSlice) → M<List<AllocationResult>>` | 调度/合同准备 → 资源准备；资源/M | 单位/时段冲突、方法未支持；统一资源身份下裁决，不用代码遍历顺序当优先级 |

scheduler.plan_next_cycle按已选事项时钟方法及DueWork的受理/暂停/补件/停止事实，形成matter_clock_updates；缺方法返回unsupported。应用协调者把调度变化交scheduler.prepare_cycle、事项计时变化交matters.prepare_clock_status，再按必要同刻边界收集提交；scheduler不直接写事项状态。find_due_work只读查找，不因查询使案件逾期；真实逾期事实不要求先存在MatterDecision。

## 5. 政策证据、机制、编译及应用

主规则：POL-001—018、INST-001—019、WORLD-005/013/026；验收见[政策验收](../05_policy/quantification.md#10-政策量化验收条件)和[工具目录](../05_policy/instrument_catalog.md)。政策研究准备不属于 Government 默认行政权。

### 5.1 交接类型

| 类型 | 字段 |
|---|---|
| `PolicyClause` | `identity:ProposedIdentity<PolicyClause>, source_ref:Ref<Source>, locator:string, excerpt:string, actor_refs:List<Ref<Entity>>, target_refs:List<Ref<Entity>>, condition_refs:List<Ref<Condition>>, time_bounds:ValueState<TimeWindow>, quantified_fields:List<ParameterValue>, evidence_state:verified\|unverified\|assumption, unresolved_fields:List<string>` |
| `MechanismSpec` | `identity:ProposedIdentity<Mechanism>, clause_refs:List<Ref<PolicyClause>>, path:macro\|atomic\|mixed\|context_only, instrument_refs:List<Ref<Instrument>>, parameters:List<ParameterValue>, affected_scope_refs:List<ScopeRef>, coverage_keys:List<string>, transition_ref:Option<Ref<TransitionRule>>, missing_fields:List<string>` |
| `CompiledPolicy` | `identity:ProposedIdentity<CompiledPolicy>, draft_group_id:string, mechanism_refs:List<DraftRef<Mechanism>>, handler_refs:List<Ref<Handler>>, activation_windows:List<TimeWindow>, coverage_plan:PolicyCoveragePlan, support_report:PolicySupportReport, content_hash:string` |
| `PolicyCoveragePlan` | `rows:List<{mechanism_ref:DraftRef<Mechanism>,coverage_key:string,direct_variable_ref:Ref<ParameterDefinition>,path:macro\|atomic\|context_only}>, overlap_issues:List<ContractIssue>`；mixed逐作用行拆开，登记覆盖以防重复 |
| `PolicySupportReport` | `registry_ref:Ref<CapabilityRegistry>, supported:bool, checked_handler_refs:List<Ref<Handler>>, issues:List<ContractIssue>`；与编译内容摘要绑定，不是法定批准 |
| `PolicyEffectDraft` | `identity:ProposedIdentity<PolicyEffect>, application_id:string, instrument_ref:Ref<Instrument>, handler_ref:Ref<Handler>, target_ref:Ref<Entity>, effective_window:TimeWindow, coverage_key:string, effect:MacroParameterEffect\|AtomicRuleEffect` |
| `MacroParameterEffect` / `AtomicRuleEffect` | macro：`kind:macro_parameter,parameter_ref:Ref<ParameterDefinition>,value:ParameterValue`；atomic：`kind:atomic_rule,rule_ref:Ref<Rule>,parameter_values:List<ParameterValue>`；宏观量按参数定义的允许赋值语义，原子作用按已编译工具/handler白名单；不是任意状态补丁 |
| `GrantApplicationDraft` | `identity:ProposedIdentity<GrantApplication>, scheme_ref:Ref<GrantScheme>, applicant_id:EntityId<Organization>, scope_ref:ScopeRef, requested:ValueState<Money>, decision_ref:Ref<RecordedDecision>, eligibility_evidence_refs:List<Ref<Evidence>>`；申请与是否适用政策不同，未知金额不当0 |
| `PolicyApplication` | `application_id:string, compiled_ref:Ref<CompiledPolicy>, target_ref:Ref<Entity>, effective_at:TimePoint, outcome:applicable\|not_applicable\|undetermined, effect_drafts:List<PolicyEffectDraft>, basis_refs:List<Ref<Evidence>>, issues:List<ContractIssue>` |
| `PolicyGrantPlan` | `identity:ProposedIdentity<GrantRound>, scheme_ref:Ref<GrantScheme>, applications:List<Ref<GrantApplication>>, allocation_refs:List<Ref<AllocationResult>>, budget_ref:Ref<Budget>, obligation_basis_refs:List<Ref<Evidence>>` |

### 5.2 函数

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `policy.extract_clauses(ctx:ReadContext, source_records:List<SourceRecord>, extraction_schema_ref:Ref<Schema>, method_ref:Ref<Method>, permit:ExecutionPermit) → M<List<PolicyClause>>` | 明确证据整理任务 → 研究者/核验任务；证据/M | 原文缺失、限定语冲突、调用失败；不输出凭空阈值，不把模型提取称已核实 |
| `policy.prepare_evidence(ctx:ServiceContext, clauses:List<PolicyClause>, verification_refs:List<Ref<VerificationRecord>>) → PrepareResult` | 证据保存命令 → 机制准备；政策证据/P；拟产物 `List<Ref<PolicyClause>>` | 核验身份或来源不明；键为来源哈希＋定位＋条款版本，不覆盖既有引用 |
| `policy.structure_mechanisms(ctx:ReadContext, clause_refs:List<Ref<PolicyClause>>, instrument_catalog_ref:Ref<InstrumentCatalog>, modeling_choices:List<ParameterValue>) → M<List<MechanismSpec>>` | 量化工作台 → 编译器；政策准备/M | 缺依据/路径冲突；允许保存缺项草案，不默认转确定参数 |
| `policy.compile_configuration(ctx:ReadContext, mechanisms:List<MechanismSpec>, registry_ref:Ref<CapabilityRegistry>, scenario_ref:Ref<ScenarioDraft>, transition_refs:List<Ref<TransitionRule>>) → M<CompiledPolicy>` | 情景校验 → 冻结清单；政策准备/M | 未知工具/字段、重叠覆盖、过渡未定义；资金不足可作压力情景，缺机制不能装成可执行 |
| `policy.prepare_configuration(ctx:ServiceContext, mechanisms:List<MechanismSpec>, compiled:CompiledPolicy, scenario_ref:Ref<ScenarioDraft>, readiness:ConfigurationReadiness) → PrepareResult` | 明确保存/冻结 → 场景装配；workspace政策目录/P；拟产物 `Ref<CompiledPolicy>` 及其机制版本 | 源条款/编译内容变化、白名单检查未通过；键为机制内容哈希＋配置冻结身份；编译产物提交后才向运行清单交正式引用 |
| `policy.evaluate_applicability(ctx:ReadContext, compiled_ref:Ref<CompiledPolicy>, target_refs:List<Ref<Entity>>, at:TimePoint, transition_state_refs:List<Ref<Entity>>) → M<List<PolicyApplication>>` | 世界/事项/候选模块 → 应用准备；制度/M | 地区/事项未定输出 undetermined；生效不自动使主体获知 |
| `policy.prepare_applications(ctx:ServiceContext, applications:List<PolicyApplication>, prior_application_refs:List<Ref<PolicyApplication>>) → PrepareResult` | 调度/有效行政决定 → 规则条件及受影响待办；制度/P；拟产物 `List<Ref<PolicyApplication>>`及同次PolicyEffect记录 | 身份/版本/覆盖冲突；键为工具版本＋对象＋作用行＋有效窗口，不直接写成本/到账 |
| `policy.prepare_grant_application(ctx:ServiceContext, draft:GrantApplicationDraft, application_rule_ref:Ref<GrantApplicationRule>) → PrepareResult` | 有权申请主体 → Government/受控分配；政策申请/P；拟产物 `Ref<GrantApplication>` | 检查方案/申请授权与证据，缺项沿补件；键为申请身份，不以政策适用性记录冒充真实申请或获授 |
| `policy.prepare_grant_round(ctx:ServiceContext, plan:PolicyGrantPlan, authority_ref:Ref<Authorization>, allocation_method_ref:Ref<Method>) → PrepareResult` | 有权分配决定/受控机制 → 预算/义务准备；制度与资金/P；拟产物 `Ref<GrantRound>` | 预算超承诺、接受条件缺失；键为授予轮次＋申请＋工具。实际付款仍走 finance，不把获授当现金 |

PolicyApplication 的 applicable 只表达该工具对该目标适用，不代表申请、获授或付款。effect_drafts仅在applicable且必要生效条件满足时非空；undetermined保留缺项，不能产生正式有效作用。policy.prepare_applications校验工具、handler、规则/参数及coverage后同次生成正式PolicyEffect；world.prepare_environment读取已提交的宏观作用，原子规则由对应事项/候选/资金/工程拥有者消费。工具到handler及状态入口的映射见[工具目录](../05_policy/instrument_catalog.md)，没有已登记方法的工具只返回不支持；不因PolicyEffect记录存在就声明成本或现金已改变。

## 6. 项目、责任、成果、审查与合同

主规则：FLOW-001—018、OBJ-004—009/015/016/018/019/022；验收见[推进验收](../03_projects/project_lifecycle.md#9-推进验收场景)。角色怎样选择见对应角色行为，以下函数不替代主体同意。

### 6.1 交接类型

| 类型 | 字段 |
|---|---|
| `ProcurementPackageDraft` | `scope_ref:ScopeRef, technical_submission_refs:List<Ref<Submission>>, quantity_basis_ref:Ref<QuantityBasis>, procedure_ref:Ref<ProcurementProcedure>, requirement_refs:List<Ref<Requirement>>, submission_window_ref:Ref<TimeWindow>, evaluation_profile_ref:Ref<TenderEvaluationProfile>`；OwnerProcurementPackageDraft或有权承包商采购草稿经登记映射提供；DeliverableSubmission→Submission保留源身份，不直接强转 |
| `SupplyInquiryDraft` | `identity:ProposedIdentity<SupplyInquiry>, requester_id:EntityId<Organization>, scope_ref:ScopeRef, requirement_refs:List<Ref<Requirement>>, recipient_ids:List<EntityId<Organization>>, response_window:TimeWindow, decision_ref:Ref<RecordedDecision>`；询价不产生订单/资源承诺 |
| `OfferSource` | `{kind:tender,round_ref:Ref<TenderRound>}\|{kind:inquiry,inquiry_ref:Ref<SupplyInquiry>}`；按报价合同类型限制分支，直接询价无需虚构TenderRound |
| `ResponsibilitySlot` | `slot_ref:Ref<ResponsibilitySlot>, scope_ref:ScopeRef, function_ref:Ref<ProjectFunction>, role_contract_ref:Ref<RoleContract>, required_authority_refs:List<Ref<AuthorityRequirement>>, exclusivity_ref:Ref<ExclusivityRule>, independence_ref:Option<Ref<IndependenceRule>>` |
| `ResponsibilityBinding` | `identity:ProposedIdentity<ResponsibilityBinding>, slot_ref:Ref<ResponsibilitySlot>, agent_id:EntityId<Agent>, authority_refs:List<Ref<Authorization>>, effective_window:TimeWindow, acceptance_ref:Option<Ref<Decision>>` |
| `WorkRequestDraft` | `identity:ProposedIdentity<WorkRequest>, requester_id:EntityId<Agent>, scope_ref:ScopeRef, task_type_ref:Ref<TaskType>, purpose:string, input_refs:List<Ref<Entity>>, work_scope_refs:List<Ref<WorkScope>>, expected_output_schema_ref:Ref<Schema>, resource_plan_ref:Option<Ref<ResourcePlan>>, due_window:ValueState<TimeWindow>, effort_estimate:ValueState<Measured>, authorization_route_ref:Ref<AuthorizationRoute>, source_decision_ref:Ref<RecordedDecision>`；resource_plan_ref的null仅表示未附资源计划；desired_window按原ValueState映射为due_window，effort_estimate保留原状态/依据；unknown/not_applicable/not_supported不得合并null，执行所需缺项须等待，来源为角色XTaskRequest的登记映射 |
| `WorkAuthorizationDraft` | `identity:ProposedIdentity<WorkAuthorization>, request_ref:Ref<WorkRequest>, authority_ref:Ref<Authorization>, decision_ref:Ref<RecordedDecision>, authorized_scope_ref:ScopeRef, conditions:List<Ref<Condition>>, valid_window:TimeWindow`；按自有经营授权或外部有效委任等各自门控，不统一要求委任 |
| `TaskPlan` | `identity:ProposedIdentity<Task>, request_ref:Option<Ref<WorkRequest>>, authorization_refs:List<Ref<WorkAuthorization>>, scope_ref:ScopeRef, binding_refs:List<Ref<ResponsibilityBinding>>, input_refs:List<Ref<Entity>>, dependency_refs:List<Ref<Dependency>>, output_schema_ref:Ref<Schema>, completion_method_ref:Ref<Method>` |
| `WorkflowDelta` | `scope_ref:ScopeRef, satisfied_dependency_refs:List<Ref<Dependency>>, invalidated_dependency_refs:List<Ref<Dependency>>, ready_tasks:List<TaskPlan>, blocked_tasks:List<Ref<Task>>, issues:List<ContractIssue>` |
| `ArtifactBody` | `schema_ref:Ref<Schema>, structured_payload:RegisteredArtifactPayload, attachment_refs:List<Ref<Attachment>>, narrative:Option<string>, content_hash:string`；RegisteredArtifactPayload 是按schema_ref登记的有限工程/角色成果封闭记录联合；完整字段引用角色局部类型及工程模板的确定方法schema，未登记返回unsupported，任意文字不等于可消费方案 |
| `DraftCheck` | `draft_hash:string, schema_ref:Ref<Schema>, method_ref:Ref<Method>, passes_compilation_check:bool, issues:List<FieldIssue>, evidence_refs:List<Ref<Evidence>>`；仅核对待保存成果的编制要求，不要求成果已正式保存，避免循环前置 |
| `TaskCompletionAssessment` | `task_ref:Ref<Task>, execution_refs:List<Ref<WorkExecution>>, output_refs:List<Ref<Deliverable>>, method_ref:Ref<Method>, meets_compilation_standard:bool, missing_fields:List<string>, issue_refs:List<Ref<Issue>>, basis_refs:List<Ref<Evidence>>`；编制标准满足不等于审查通过或客户接受 |
| `DeliverableDraft` | `identity:ProposedIdentity<Deliverable>, task_ref:Ref<Task>, scope_ref:ScopeRef, body:ArtifactBody, dependency_refs:List<Ref<Entity>>, open_issue_refs:List<Ref<Issue>>, author_agent_id:EntityId<Agent>` |
| `SubmissionDraft` | `submission_id:string, deliverable_ref:Ref<Deliverable>, requested_use_ref:Ref<UsePurpose>, recipient_bindings:List<Ref<ResponsibilityBinding>>, scope_ref:ScopeRef, note:Option<string>`；申请用途不是用途放行 |
| `MatterClockStatusDraft` | `identity:ProposedIdentity<MatterClockStatus>, matter_ref:Ref<MatterCase>, clock_rule_ref:Ref<MatterClockRule>, at:TimePoint, status:not_started\|counting\|paused\|overdue\|stopped, elapsed:Measured, deadline:ValueState<TimePoint>, timing_fact_refs:List<Ref<Fact>>, method_ref:Ref<Method>`；单位/暂停/补件规则来自选定时钟方法；逾期不是批准 |
| `ReviewOutcome` | `identity:ProposedIdentity<Review>, submission_ref:Ref<Submission>, reviewer_binding_ref:Ref<ResponsibilityBinding>, conclusion:accepted\|returned\|conditional\|undetermined, finding_refs:List<Ref<Finding>>, condition_refs:List<Ref<Condition>>, evidence_refs:List<Ref<Evidence>>` |
| `UseReleaseDraft` | `identity:ProposedIdentity<UseRelease>, deliverable_ref:Ref<Deliverable>, scope_ref:ScopeRef, use_ref:Ref<UsePurpose>, effective_window:TimeWindow, required_review_refs:List<Ref<Review>>, authority_ref:Ref<Authorization>` |
| `AgreementAssembly` | `terms_ref:Ref<AgreementTerms>, scope_ref:ScopeRef, party_refs:List<Ref<Organization>>, acceptance_refs:List<Ref<Decision>>, verification_refs:List<Ref<VerificationRecord>>, commitment_refs:List<Ref<Commitment>>, superseded_terms_ref:Option<Ref<AgreementTerms>>` |
| `OptionEvaluation` | `option_ref:Ref<ProjectOption>, scope_ref:ScopeRef, output_schema_ref:Ref<Schema>, quantities:List<Measured>, cost_estimates:List<Money>, assessed_conditions:List<ParameterValue>, issue_refs:List<Ref<Issue>>, method_ref:Ref<Method>, basis_refs:List<Ref<Evidence>>`；每种专业 output schema 限定适用字段，方法只交值，正式 assessment 引用由成果提交生成 |
| `ClosureVector` | `scope_ref:ScopeRef, engineering:Readiness, acceptance:Readiness, lawful_use:Readiness, defects:Readiness, settlement:Readiness, discharge:Readiness, residual_obligation_refs:List<Ref<Obligation>>` |

角色 `ArchitectTaskRequest`、`EngineerTaskRequest`、`QSTaskRequest`、`GovTaskRequest`及其他角色已登记的新工作申请通过TypedViewBinding逐字段转换为WorkRequestDraft；请求并非TaskPlan，缺工作类型/输出schema/授权路线返回needs_information。

以下 `OwnerBriefDraft` 直接导入[Owner 局部字段类型](../04_roles/owner.md)，`BankA04Payload` 导入[Bank 行为契约](../04_roles/bank.md)。这些输入必须来自已登记决定，宿主按 operation/choice 的映射投影；不把两份同义字段表分别维护。

### 6.2 函数

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `opportunities.prepare_case(ctx:ServiceContext, decision_ref:Ref<RecordedDecision>, objective_ref:Ref<OwnerObjective>, source_observation_refs:List<Ref<Observation>>, existing_case_ref:Option<Ref<OwnerCase>>, equivalence_basis_ref:Ref<CaseIdentityRule>) → PrepareResult` | OWN-A01 → 本Owner提案/研究；主体私有档案/P；拟产物 `Ref<OwnerCase>` | 非本主体观察/缺档案身份依据；键为Owner＋机会归属＋合法建档/修订身份；不直接登记工程 |
| `proposals.prepare_briefs(ctx:ServiceContext, case_ref:Ref<OwnerCase>, drafts:List<OwnerBriefDraft>, prior_brief_refs:List<Ref<OwnerBrief>>, decision_ref:Ref<RecordedDecision>) → PrepareResult` | OWN-A16 → 有限专业研究；项目准备/P；拟产物 `List<Ref<OwnerBrief>>` | 候选空间越界、旧简报不对应、数据单位缺失；键为提案决定＋候选身份＋版本，不生成土地/资金权利 |
| `procurement.prepare_package(ctx:ServiceContext, draft:ProcurementPackageDraft, publication_decision_ref:Ref<RecordedDecision>, prior_package_ref:Option<Ref<ProcurementPackage>>) → PrepareResult` | OWN-A09的publish_package/有权CONTRACTOR-A05＋QS-A05资料 → 候选投标人；采购/P；拟产物 `Ref<ProcurementPackage>` | 成果用途/范围不符、无采购权限；首发prior_package_ref=null；修订指向原版，键为包件＋发布版本，不以缺最终设计自动放行或全禁 |
| `procurement.prepare_round(ctx:ServiceContext, package_ref:Ref<ProcurementPackage>, candidate_refs:List<Ref<EligibleBidder>>, decision_ref:Ref<RecordedDecision>, replaced_round_refs:List<Ref<TenderRound>>, parallel_allocation_ref:Option<Ref<ParallelAllocationRule>>) → PrepareResult` | OWN-A09/CONTRACTOR-A05 → 独立投标/评审；采购/P；拟产物 `Ref<TenderRound>` | 未声明并行排他覆盖、候选不合法；键为包件＋轮次身份，关闭旧轮不删除已成立事实 |
| `procurement.prepare_inquiry(ctx:ServiceContext, draft:SupplyInquiryDraft, inquiry_profile_ref:Ref<InquiryProfile>) → PrepareResult` | 有权采购方的询价决定 → SUPPLIER-A01/A02/A03；采购/P；拟产物 `Ref<SupplyInquiry>` | 范围/接收者/输入版本有权可见，询价身份排重，不要求已存在报价或合同 |
| `procurement.prepare_offer(ctx:ServiceContext, source:OfferSource, bidder_id:EntityId<Organization>, recorded_decision_ref:Ref<RecordedDecision>, offer_schema_ref:Ref<Schema>, validity:TimeWindow) → PrepareResult` | CONTRACTOR-A02/A03、SUPPLIER-A03 → 有权评审/购买者；采购/P；拟产物 `Ref<Bid>` 或 `Ref<SupplyOffer>` | choice与专属报价schema不符、超有效窗口；键为报价者＋来源询价/轮次＋报价版本；正式报价仍不等于合同 |
| `finance.prepare_application(ctx:ServiceContext, draft:FinanceApplicationDraft, decision_ref:Ref<RecordedDecision>, application_identity:string) → PrepareResult` | OWN-A05/CONTRACTOR-A10/SUPPLIER-A10 → BANK-A02；融资/P；拟产物 `Ref<FinanceApplication>` | 借款人/用途/申请字段不齐；键为application_identity，不混其他银行的案例 |
| `finance.prepare_offer(ctx:ServiceContext, application_ref:Ref<FinanceApplication>, quote:BankA04Payload, recorded_decision_ref:Ref<RecordedDecision>, authority_ref:Ref<Authorization>) → PrepareResult` | BANK-A04 → 借款人独立接受；融资/P；拟产物 `Ref<FinanceOffer>` | 无有权批准、报价分支字段不符；键为本行申请＋报价版本，不登记本金/现金 |
| `finance.prepare_arrangement(ctx:ServiceContext, offer_ref:Ref<FinanceOffer>, borrower_acceptance_ref:Ref<RecordedDecision>, lender_confirmation_ref:Ref<RecordedDecision>, condition_evidence_refs:List<Ref<Evidence>>) → PrepareResult` | OWN-A05与BANK-A05 → 提款任务；融资/P；拟产物 `Ref<FinanceArrangement>` | 同版接受未齐或条件不符；键为报价＋双方有效接受身份，只登记安排/承诺 |
| `finance.prepare_draw_request(ctx:ServiceContext, arrangement_ref:Ref<FinanceArrangement>, requester_decision_ref:Ref<RecordedDecision>, obligation_refs:List<Ref<Obligation>>, condition_evidence_refs:List<Ref<Evidence>>, draw_identity:string) → PrepareResult` | OWN-A06 → BANK-A06/A07；融资/P；拟产物 `Ref<DrawRequest>` | 错安排/用途、重复未决批次；键为draw_identity，批准后的实际转账仍走finance.prepare_transfer |
| `work.prepare_request(ctx:ServiceContext, request:WorkRequestDraft) → PrepareResult` | 主体申请调查/培训/营销/新专业工作 → 有权授权任务；项目与组织工作/P；拟产物 `Ref<WorkRequest>` | 组织/assessment_case/project各scope均可；不先要求待建Task或尚未签署的委任，申请不占资源、不证明获授权；键为申请身份 |
| `work.prepare_authorization(ctx:ServiceContext, draft:WorkAuthorizationDraft, required_agreement_refs:List<Ref<Agreement>>) → PrepareResult` | 本主体经营或有权委托方决定 → 任务依赖；工作/P；拟产物 `Ref<WorkAuthorization>` | 按authorization_route验证权限与所需协议，未满足条件不创建可执行任务；键为请求＋授权决定版本 |
| `project.evaluate_dependencies(ctx:ReadContext, scope_ref:ScopeRef, workflow_ref:Ref<WorkflowTemplate>, changed_fact_refs:List<Ref<Fact>>) → M<WorkflowDelta>` | 事件后续办/显式推进 → 任务准备；项目/M | 未定义必要前置、失效版本、依赖环；不能用阶段名称强制放行 |
| `project.prepare_task_graph(ctx:ServiceContext, delta:WorkflowDelta, trigger_refs:List<Ref<Trigger>>) → PrepareResult` | 组织/评估档案/项目的工作续办 → 调度；项目/P；拟产物 `List<Ref<Task>>`（业务WorkTask） | 必须有工作授权或模板明确系统工作依据；scope沿delta支持organization/assessment_case/project，不额外要求project_ref；重复触发、已失效责任；键为范围＋节点版本＋合法触发身份，重复事件不造重复任务 |
| `project.prepare_binding(ctx:ServiceContext, slot:ResponsibilitySlot, binding:ResponsibilityBinding, appointment_ref:Ref<Agreement>, replaced_binding_ref:Option<Ref<ResponsibilityBinding>>) → PrepareResult` | 有效委任/接续命令 → 具体 agent 任务；关系与项目/P；拟产物 `Ref<ResponsibilityBinding>` | 无授权、独立性/排他冲突；键为槽位＋委任＋生效窗口，不抹历史执行者 |
| `project.prepare_registration(ctx:ServiceContext, investment_decision_ref:Ref<Decision>, evaluation_case_ref:Ref<EvaluationCase>, selected_option_ref:Ref<Option>, registration_profile_ref:Ref<RegistrationProfile>) → PrepareResult` | Owner 合法投资决定 → 项目/管线；项目/P；拟产物 `Ref<Project>` | 权利/登记条件缺失；键为投资决定＋登记范围，不因为重评生成新项目 |
| `methods.evaluate_option(ctx:ReadContext, brief_ref:Ref<Brief>, option_ref:Ref<Option>, profile_ref:Ref<EngineeringProfile>, evidence_refs:List<Ref<Evidence>>, method_ref:Ref<Method>, random_slice:RandomSlice) → M<OptionEvaluation>` | 专业动作宿主 → 对应角色成果；计算/M | 缺单位/方案数量、适用域之外；不同候选按同一输入基准，估算不是工程实绩 |
| `work.check_draft(ctx:ReadContext, draft:DeliverableDraft, task_ref:Ref<Task>, execution_refs:List<Ref<WorkExecution>>, method_ref:Ref<Method>) → M<DraftCheck>` | 编制宿主 → 成果保存；项目工作/M | 以draft正文检查明确编制要求及投入，缺字段/方法分别返回，不先引用尚未提交成果 |
| `work.prepare_deliverable(ctx:ServiceContext, draft:DeliverableDraft, work_execution_refs:List<Ref<WorkExecution>>, draft_check:DraftCheck) → PrepareResult` | 专业任务宿主 → 提交/其他获授权任务；项目工作/P；拟产物 `Ref<Deliverable>` | 未达编制标准、成果依赖过期、正文 schema 不符；键为任务＋成果身份＋版本，不自动通过审查 |
| `work.evaluate_completion(ctx:ReadContext, task_ref:Ref<Task>, execution_refs:List<Ref<WorkExecution>>, output_refs:List<Ref<Deliverable>>, method_ref:Ref<Method>) → M<TaskCompletionAssessment>` | 工作宿主 → 编制完成准备；项目工作/M | 缺工作量/实际执行、成果schema不符、方法未支持；不能仅凭“文本已写完”形成完成证据 |
| `work.prepare_completion(ctx:ServiceContext, assessment:TaskCompletionAssessment, completion_identity:string) → PrepareResult` | 工作宿主 → 角色提交输入；项目工作/P；拟产物 `Ref<TaskCompletion>` | 依据/任务版本不符，标准未满足保留诊断；键为任务＋合法完成身份；真实返修新片段不作为旧完成重试 |
| `work.prepare_submission(ctx:ServiceContext, draft:SubmissionDraft, task_authority_ref:Ref<Authorization>) → PrepareResult` | Architect A07 等获授权提交 → 明确接收者审查待办；项目工作/P；拟产物 `Ref<Submission>` | 接收者/用途无权、引用不存在；键为 submission ID＋内容哈希，技术重试不生新费用 |
| `work.prepare_review(ctx:ServiceContext, outcome:ReviewOutcome, review_task_ref:Ref<Task>, authority_ref:Ref<Authorization>) → PrepareResult` | 有权审查动作 → 作者/下一审批用途；项目工作或事项/P；拟产物 `Ref<Review>` | 越权、旧版本、缺审查依据；键为合法审查任务＋结果身份，返修后新审查有新身份 |
| `work.prepare_use_release(ctx:ServiceContext, release:UseReleaseDraft, permission_refs:List<Ref<Permission>>) → PrepareResult` | 有用途发布权的决定 → 采购/施工前置；项目工作/P；拟产物 `Ref<UseRelease>` | 缺必要认可/许可、超范围；键为成果版本＋用途＋范围＋发布身份，不由提交成功触发 |
| `agreements.prepare_effectiveness(ctx:ServiceContext, assembly:AgreementAssembly, formation_profile_ref:Ref<FormationProfile>) → PrepareResult` | 所需独立接受及核验齐备 → 履约/资源/义务；关系及相关账本/P；拟产物 `Ref<Agreement>` | 版本失配、拒绝/过期、资源冲突；键为条款版本＋范围＋有效成立身份，迟到旧轮接受不新签 |
| `matters.prepare_case(ctx:ServiceContext, applicant_binding_ref:Ref<ResponsibilityBinding>, submission_refs:List<Ref<Submission>>, matter_profile_ref:Ref<MatterProfile>, jurisdiction_ref:Ref<Jurisdiction>) → PrepareResult` | 合法申请命令 → 具体 Government/有权事项队列；事项/P；拟产物 `Ref<MatterCase>` | 机关事项不匹配、缺材料；键为申请身份＋事项＋范围，补件沿原案版本 |
| `matters.prepare_clock_status(ctx:ServiceContext, draft:MatterClockStatusDraft, previous_status_ref:Option<Ref<MatterClockStatus>>) → PrepareResult` | 调度计划中的期限更新 → 事项状态/监管待办；事项/P；拟产物 `Ref<MatterClockStatus>` | 依据真实受理/暂停/补件/决定事实重验时钟方法；键为事项＋时钟规则＋计时片段/截止；到期没有决定仍可登记逾期，不伪造许可/拒绝 |
| `matters.prepare_decision(ctx:ServiceContext, matter_ref:Ref<MatterCase>, decision_ref:Ref<Decision>, evidence_refs:List<Ref<Evidence>>, deciding_authority_ref:Ref<Authorization>) → PrepareResult` | Government 的有权决定 → 申请人/任务条件；事项/P；拟产物 `Ref<MatterDecision>` | 越权、超时不自动批准、适用版本未定；键为案件＋决定身份，期限/实际工作分别记 |
| `project.evaluate_closure(ctx:ReadContext, scope_ref:ScopeRef, closure_profile_ref:Ref<ClosureProfile>, facts:FactSelection) → M<ClosureVector>` | 收尾/截点查询 → 接管、关闭、结果；项目/M | 不能判定的维度留缺项，不用工程完工替代资金清偿 |
| `project.prepare_closure(ctx:ServiceContext, vector:ClosureVector, authorized_closure_refs:List<Ref<Decision>>) → PrepareResult` | 有权分范围关闭 → 资源处置/档案/经营；项目及责任拥有者/P；拟产物 `Ref<ClosureRecord>` | 未取得必要权限或剩余义务未标责任人；键为范围＋关闭维度＋依据身份，不强制其他维度关闭 |

## 7. 资源、批次、实际工程和资产交接

主规则：OBJ-006/010/022、FLOW-005—011、TYPE-001—008；验收见[对象验收](../02_world/domain_objects.md#10-业务验收场景)、CHECK-FLOW-003/005—007/028—031 与[同范围贯通例](../07_experiments/reference_scenarios.md#41-同一物理范围的合成贯通例-f-gba-01)。

| 类型 | 字段 |
|---|---|
| `ResourceUse` | `resource_ref:Ref<Resource>, reservation_ref:Option<Ref<Reservation>>, scope_ref:ScopeRef, window:TimeWindow, amount:Measured, physical_key:string` |
| `MaterialUse` | `batch_ref:Ref<Batch>, work_package_ref:Ref<WorkPackage>, quantity:Measured, use_release_ref:Ref<MaterialRelease>` |
| `BatchMovement` | `movement_id:string, batch_ref:Ref<Batch>, from_ref:Ref<Location>, to_ref:Ref<Location>, route_ref:Ref<Route>, quantity:Measured, dispatch_evidence_refs:List<Ref<Evidence>>, receipt_evidence_refs:List<Ref<Evidence>>, window:TimeWindow` |
| `InspectionResult` | `identity:ProposedIdentity<Inspection>, batch_or_work_ref:Ref<Entity>, sampled_quantity:Measured, accepted_quantity:Measured, rejected_quantity:Measured, undecided_quantity:Measured, method_ref:Ref<Method>, evidence_refs:List<Ref<Evidence>>, inspector_binding_ref:Ref<ResponsibilityBinding>` |
| `WorkSlice` | `slice_id:string, task_ref:Ref<Task>, physical_scope_ref:Ref<PhysicalScope>, window:TimeWindow, resource_uses:List<ResourceUse>, material_uses:List<MaterialUse>, authorization_refs:List<Ref<Authorization>>` |
| `EngineeringOutcome` | `slice_id:string, gross_work:List<Measured>, accepted_net_work:List<Measured>, rework:List<Measured>, material_consumption:List<MaterialUse>, resource_consumption:List<ResourceUse>, incurred_costs:List<Money>, issue_refs:List<Ref<Issue>>, method_ref:Ref<Method>`；费用发生不直接扣款 |
| `HandoverDraft` | `handover_id:string, scope_ref:ScopeRef, as_built_ref:Ref<AsBuiltRecord>, asset_refs:List<Ref<Asset>>, deliverer_binding_ref:Ref<ResponsibilityBinding>, receiver_binding_ref:Ref<ResponsibilityBinding>, acceptance_ref:Ref<Decision>, remaining_obligation_refs:List<Ref<Obligation>>` |

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `resources.prepare_reservations(ctx:ServiceContext, allocations:List<AllocationResult>, commitment_refs:List<Ref<Commitment>>, reservation_window:TimeWindow) → PrepareResult` | 合同/排期/调度 → 履约；资源/P；拟产物 `List<Ref<Reservation>>` | 再验容量/时间/承诺；冲击后保留旧合法承诺并记录短缺，实际并发使用不超有效容量，新增承诺不得超配；键为实际承诺＋资源＋时段＋分配身份 |
| `resources.prepare_disposition(ctx:ServiceContext, reservation_refs:List<Ref<Reservation>>, disposition:release\|hold\|transfer, basis_refs:List<Ref<Evidence>>, successor_scope_ref:Option<ScopeRef>, effective_at:TimePoint) → PrepareResult` | 暂停/退出/接续 → 可用资源及待办；资源/P；拟产物 `List<Ref<ResourceDisposition>>` | 转移缺有权依据、召回条件未齐；键为预留＋处置身份，不抹历史占用/费用 |
| `inventory.prepare_movement(ctx:ServiceContext, movement:BatchMovement, order_ref:Ref<Order>, transport_allocation_refs:List<Ref<AllocationResult>>) → PrepareResult` | 已授权物流执行 → 在途/到场库存；实物/P；拟产物 `Ref<BatchMovement>` | 数量超发、路线不适用、重复回执；键为实际移动分片身份，发运不当到货/合格可用 |
| `inventory.prepare_inspection(ctx:ServiceContext, result:InspectionResult, inspection_task_ref:Ref<Task>) → PrepareResult` | 有权检验 → 放行/隔离/整改待办；实物/P；拟产物 `Ref<Inspection>` | 样本/数量范围冲突、越权；键为检验任务＋批次/工程版本＋结果身份 |
| `engineering.check_readiness(ctx:ReadContext, work_package_ref:Ref<WorkPackage>, slice:WorkSlice, profile_ref:Ref<EngineeringProfile>) → M<Readiness>` | 工作执行器 → 计算/阻塞；工程/M | 逐项检查成果用途、许可、人机料场和资金条件；无方法不可默认就绪 |
| `engineering.compute_slice(ctx:ReadContext, slice:WorkSlice, readiness:Readiness, environment_ref:Ref<Environment>, method_ref:Ref<Method>, random_slice:RandomSlice) → M<EngineeringOutcome>` | 合法工作机会 → 工程提交；工程/M | 投入缺失、单位不符、不支持工作类型；返工不重复增加净完成量 |
| `engineering.prepare_execution(ctx:ServiceContext, slice:WorkSlice, outcome:EngineeringOutcome, readiness:Readiness) → PrepareResult` | 履约执行器 → 工程/材料/资源/成本事件；工程及账本/P；拟产物 `Ref<WorkExecution>` | 提交前重验投入、旧执行片段、容量/库存冲突；键为 task＋slice ID，实际消耗与工程同次提交 |
| `assets.prepare_handover(ctx:ServiceContext, draft:HandoverDraft, closure:ClosureVector, rights_profile_ref:Ref<RightsProfile>) → PrepareResult` | 有权交付/接收 → 资产持有/使用/经营；资产、项目与关系/P；拟产物 `Ref<Handover>` | W3 权利接口缺失、接收者无权；键为物理交付范围＋接收身份，接管不自动许可/付款/免责 |

## 8. 成本、债务、付款与外部核对

主规则：OBJ-011/012、POL-010、FLOW-007/010/011；验收见[共同资金对象及验收](../02_world/domain_objects.md)、[Bank 行为与验收](../04_roles/bank.md)和[失败恢复算例](../07_experiments/reference_scenarios.md#5-失败传播与恢复)。D-02 未选产品/计息/币种不能用默认公式替代。

| 类型 | 字段 |
|---|---|
| `FinanceApplicationDraft` | `borrower_id:EntityId<Organization>, lender_id:EntityId<Organization>, scope_ref:ScopeRef, requested:Money, purpose_ref:Ref<FundingPurpose>, product_candidates:List<Ref<FinanceProductProfile>>, disclosure_refs:List<Ref<Evidence>>, applicant_authority_ref:Ref<Authorization>`；首次申请不要求尚不存在的FinanceApplication；宿主核验借款法人授权，金额与用途不由银行补猜 |
| `ObligationDraft` | `obligation_id:string, debtor_ref:Ref<Organization>, creditor_ref:Ref<Organization>, scope_ref:ScopeRef, amount:Money, due_at:TimePoint, basis_refs:List<Ref<Evidence>>, obligation_kind_ref:Ref<ObligationKind>, parent_obligation_ref:Option<Ref<Obligation>>` |
| `TransferDraft` | `instruction_id:string, payer_account_ref:Ref<Account>, payee_account_ref:Ref<Account>, amount:Money, allocation_lines:List<SettlementAllocation>, authorization_ref:Ref<Authorization>, executing_adapter_ref:Ref<ExecutionAdapter>` |
| `SettlementAllocation` | `obligation_ref:Ref<Obligation>, amount:Money, allocation_rule_ref:Ref<AllocationRule>`；总额与指令对应，不把同一贷款本金和到期表重复还款 |
| `ExecutionEvidence` | `instruction_ref:Ref<TransferInstruction>, external_execution_id:string, fragment_id:string, outcome:executed\|confirmed_not_executed\|unresolved, executed_amount:ValueState<Money>, occurred_at:ValueState<TimePoint>, evidence_ref:Ref<Evidence>` |
| `Reconciliation` | `instruction_ref:Ref<TransferInstruction>, evidence_refs:List<Ref<Evidence>>, outcome:resolved\|partial\|unresolved\|conflicting, new_fragment_ids:List<string>, prior_fragment_ids:List<string>, allocations:List<SettlementAllocation>, issues:List<ContractIssue>` |
| `AccrualAssessment` | `assessment_id:string, obligation_ref:Ref<Obligation>, window:TimeWindow, accrued:Money, product_ref:Ref<FinancialProduct>, method_ref:Ref<Method>, basis_refs:List<Ref<Evidence>>` |

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `finance.prepare_obligations(ctx:ServiceContext, drafts:List<ObligationDraft>, certification_refs:List<Ref<Certification>>, agreement_refs:List<Ref<Agreement>>) → PrepareResult` | 合同/计价/费用/实际业务 → 到期与付款任务；资金/P；拟产物 `List<Ref<Obligation>>` | 无成立依据、币种不符、相同费用重复；键为基础事实＋义务种类＋债权债务双方＋合法分片 |
| `finance.compute_accrual(ctx:ReadContext, obligation_refs:List<Ref<Obligation>>, window:TimeWindow, product_refs:List<Ref<FinancialProduct>>, method_ref:Ref<Method>) → M<List<AccrualAssessment>>` | 到期经营调度 → 应计提交；资金/M | 未定义计息基数/日历/舍入；未覆盖不按零利息 |
| `finance.prepare_accrual(ctx:ServiceContext, assessments:List<AccrualAssessment>) → PrepareResult` | 调度 → 正式应计与到期投影；资金/P；拟产物 `List<Ref<AccrualRecord>>` | 重叠期间/重复基础、旧产品版本；键为义务＋应计期间＋合法片段身份，不直接扣现金 |
| `finance.prepare_transfer(ctx:ServiceContext, draft:TransferDraft, condition_evidence_refs:List<Ref<Evidence>>, facility_ref:Option<Ref<Facility>>) → PrepareResult` | 实际有权付款方/Bank → 执行 outbox；资金/P；拟产物 `Ref<TransferInstruction>` | 资金不足、受限用途、条件未达；键为指令身份，不把提款批准当到账 |
| `payments.dispatch_instruction(ctx:ReadContext, instruction_ref:Ref<TransferInstruction>, adapter_ref:Ref<ExecutionAdapter>, dispatch_token:string, permit:ExecutionPermit) → ExternalAttemptResult<ExecutionEvidence>` | 已提交 outbox 的执行器 → 核对入口；外部适配器/X | 必须先验已提交指令和唯一 dispatch 身份；超时为未确定，不新建第二笔指令；外部幂等键为 instruction ID |
| `payments.query_execution(ctx:ReadContext, instruction_ref:Ref<TransferInstruction>, adapter_ref:Ref<ExecutionAdapter>, evidence_cutoff:TimePoint, permit:ExecutionPermit) → M<List<ExecutionEvidence>>` | 未决执行核对任务 → reconciliation；外部适配器/X | 只查原执行，不再付款；调用仍记录技术预算，前端普通 GET 不触发本函数 |
| `finance.reconcile_execution(ctx:ReadContext, instruction_ref:Ref<TransferInstruction>, evidence:List<ExecutionEvidence>, prior_fragments:List<Ref<SettlementFragment>>, allocation_rule_ref:Ref<AllocationRule>) → M<Reconciliation>` | 核对任务 → 正式清偿准备；资金/M | 回执冲突、超额、乱序不明；unresolved 保留待办，不伪造已失败 |
| `finance.prepare_settlement(ctx:ServiceContext, reconciliation:Reconciliation, transfer_ref:Ref<TransferInstruction>) → PrepareResult` | 已核实片段 → 双方现金、义务、贷款及事件；资金/P；拟产物 `List<Ref<SettlementFragment>>` | 重复片段/余额版本冲突；键为执行适配器＋原执行 ID＋片段 ID，直接付供方不另给借款人增现金 |
| `finance.prepare_adjustment(ctx:ServiceContext, original_fact_refs:List<Ref<Fact>>, adjustment_basis_ref:Ref<Evidence>, authorized_decision_ref:Ref<Decision>, adjustment_kind:correction\|refund_claim\|reschedule\|waiver, amount:Money, effective_at:TimePoint) → PrepareResult` | 有效更正/退款/重组/免债 → 资金及后续任务；资金/P；拟产物 `Ref<FinancialAdjustment>` | 无依据、无权限、原事实不明；键为有权调整身份；原支付不删除，退款主张不直接退款，核销不等于 waiver |

## 9. 可见信息、候选、认知与技能宿主

主规则：OBJ-003/013/014、WORLD-006/022、RUN-008、SKILL 规范；验收见[技能验收](skills.md#9-技能接入验收条件)、[运行追踪](../07_experiments/run_and_results.md#5-决定执行和可见观察的追踪)。具体角色返回体由角色契约拥有。

| 类型 | 字段 |
|---|---|
| `ObservationDraft` | `observation_id:string, recipient_agent_id:EntityId<Agent>, fact_refs:List<Ref<Fact>>, visible_field_refs:List<Ref<FieldDefinition>>, available_at:TimePoint, source_refs:List<Ref<Evidence>>, correction_of:Option<Ref<Observation>>` |
| `CandidateExposure` | `identity:ProposedIdentity<CandidateExposure>, agent_id:EntityId<Agent>, action_contract_ref:Ref<ActionContract>, candidate_refs:OrderedList<Ref<Entity>>, information_cutoff:TimePoint, search_method_ref:Ref<Method>, excluded_count:int≥0, ordering_basis_ref:Ref<Evidence>` |
| `BeliefDraft` | `identity:ProposedIdentity<Belief>, proposition_ref:Ref<Proposition>, assessment:ValueState<ParameterValue>, observation_refs:List<Ref<Observation>>, explanation:string`；主张类型由主体认知schema限定，不转正式真值 |
| `MemoryDraft` | `identity:ProposedIdentity<Memory>, observation_refs:List<Ref<Observation>>, summary:string, source_decision_refs:List<Ref<RecordedDecision>>` |
| `SubjectiveRelationDraft` | `identity:ProposedIdentity<SubjectiveRelation>, target_agent_id:EntityId<Agent>, assessments:List<ParameterValue>, observation_refs:List<Ref<Observation>>` |
| `CognitiveDelta` | `agent_id:EntityId<Agent>, baseline_ref:Ref<CognitiveState>, consumed_observation_refs:List<Ref<Observation>>, belief_drafts:List<BeliefDraft>, memory_drafts:List<MemoryDraft>, subjective_relation_drafts:List<SubjectiveRelationDraft>, method_ref:Ref<Method>` |
| `SkillInvocation` | `invocation_id:string, skill_ref:Ref<Skill>, host_task_ref:Ref<DecisionTask>\|Ref<SystemTask>\|Ref<WorkspaceTask>, mode:host_submit\|managed_steps, agent_id:Option<EntityId<Agent>>, input_schema_ref:Ref<Schema>, typed_input:RegisteredSkillInput, output_schema_ref:Ref<Schema>, authorized_source_refs:List<Ref<Entity>>, continuation_ref:Option<Ref<Continuation>>` |
| `ManagedStepReport` | `step_key:string, command_id:string, attempt:CommandAttemptResult`；保存所属data_space及原回执/未知身份，不隐含每步成功 |
| `ManagedSkillReport` | `invocation_id:string, step_reports:List<ManagedStepReport>, termination:completed\|waiting\|business_stop\|technical_stop, pending_step_keys:List<string>, final_output:Option<SkillOutput>, error:Option<TechnicalFailure>`；final_output为null表示未形成最终材料，error仅technical_stop非空；失败仍返回此前步骤 |
| `ManagedSkillAttemptResult` | `kind:reported,report:ManagedSkillReport`，或公共ExternalAttemptResult的blocked/failed_before_execution/pending/unknown分支；仅在无法取得可信步骤清单时unknown，调用方先核对原invocation，不能当零副作用重跑 |
| `SkillOutput` | `invocation_id:string, output_schema_ref:Ref<Schema>, typed_payload:RegisteredSkillOutput, narrative:Option<string>, tool_result_refs:List<Ref<ToolResult>>, unresolved_fields:List<string>, provenance_refs:List<Ref<Evidence>>` |

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `observations.project_visible(ctx:ReadContext, recipient_agent_id:EntityId<Agent>, facts:FactSelection, visibility_ref:Ref<VisibilityProfile>, delivery_method_ref:Ref<Method>) → M<List<ObservationDraft>>` | 已提交事件投递 → 主体收件；观察/M | 私有字段/未来知识排除，缺时滞规则返回缺项；全局审计权不能替代主体可见权 |
| `observations.prepare_delivery(ctx:ServiceContext, observations:List<ObservationDraft>, outbox_refs:List<Ref<OutboxEntry>>) → PrepareResult` | 消费者投递 → 本主体收件及后续任务；观察/P；拟产物 `List<Ref<Observation>>` | 提前可见、目标失配；键为事件＋接收者＋投影版本，投递重试不重做业务 |
| `candidates.expose(ctx:ReadContext, slot_ref:Ref<ActionSlot>, search_space_refs:List<Ref<Entity>>, exposure_profile_ref:Ref<ExposureProfile>, method_ref:Ref<Method>) → M<CandidateExposure>` | 决策宿主 → 角色输入；主体/M | 越界或不可见候选、排序未声明；空候选是明确结果，不补成功伙伴 |
| `candidates.prepare_exposure(ctx:ServiceContext, slot_ref:Ref<ActionSlot>, exposure:CandidateExposure) → PrepareResult` | 决策宿主 → ActionContext.candidate_set_ref；主体输入/P；拟产物 `Ref<CandidateExposure>`及`Ref<CandidateSet>` | 按已登记映射保存operation/scope/as_of/候选许可；空集保持空集；键为slot＋合法曝光身份，不触发模型选择 |
| `cognition.compute_update(ctx:ReadContext, agent_id:EntityId<Agent>, baseline_ref:Ref<CognitiveState>, observation_refs:List<Ref<Observation>>, method_ref:Ref<Method>, permit:ExecutionPermit) → M<CognitiveDelta>` | 本主体学习任务 → 认知准备；主体/M | 跨主体/跨运行引用拒绝，方法未支持；不能修改正式市场/关系事实 |
| `cognition.prepare_update(ctx:ServiceContext, delta:CognitiveDelta) → PrepareResult` | 本主体宿主 → 后续合法决定；主体/P；拟产物 `Ref<CognitiveState>`及本主体Belief/Memory/SubjectiveRelation记录 | baseline 过期、重复消费；键为主体＋学习执行身份＋输入观察集合 |
| `skills.invoke(ctx:ReadContext, invocation:SkillInvocation, permit:ExecutionPermit, method_ref:Ref<Method>) → M<SkillOutput>` | 明确任务宿主 → 角色/政策/计算消费者；技能执行/M | 不支持技能/工具、schema 不符、调用未知；输入输出都按 schema 验证，不传任意 dict；仅host_submit模式；无世界写权限，不能承担managed_steps |
| `skills.execute_managed(ctx:ReadContext, invocation:SkillInvocation, step_contract_ref:Ref<ManagedStepContract>, permit:ExecutionPermit) → ManagedSkillAttemptResult` | 显式managed_steps宿主 → 已执行/未决步骤报告；技能协调/X | 只派发白名单子命令，逐步复用原身份；技术中断保留已提交事实；报告再次返回不能再提交相同业务 |
| `skills.prepare_completion(ctx:ServiceContext, invocation:SkillInvocation, output:SkillOutput, validation:ValidationResult) → PrepareResult` | 技能宿主 → 后续行动/成果准备；主体/准备任务/P；拟产物 `Ref<SkillExecution>` | 错主体、输出不符、续办身份冲突；键为 invocation ID，不自动把技能意见提交为角色最终选择 |


### 9.1 正式对象与角色 Input 的显式投影

字段映射类型 `TypedViewBinding`、`ViewFieldMapping` 与 `BindingCheck` 统一定义在[公共协议](interface_contracts.md#33-角色输入的类型化映射)。映射本身先通过检查、保存为正式版本，再装配主体Input；不会自举要求它已是有效映射。

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `agents.build_action_input(ctx:ActionContext, operation_id:string, slot_ref:Ref<ActionSlot>, binding_ref:Ref<TypedViewBinding>, committed_source_refs:List<Ref<Entity>>) → M<RegisteredActionInput>` | 角色宿主 → 对应 `roles.*.aNN`；主体投影/M | operation、主体、scope、信息截止、候选版本逐项核验；缺上游字段返回needs_information，单位/类型不符invalid_input；不让下游LLM补正式值 |
| `contracts.validate_payload(ctx:ReadContext, schema_ref:Ref<Schema>, value:RegisteredPayload) → ValidationResult` | 技能/输入适配器 → 正式prepare门控；契约/M（结构检查） | RegisteredPayload仅已登记的角色/技能/领域记录联合；类型不符列FieldIssue，不接受any/dict或把结构通过当业务许可 |
| `contracts.validate_view_binding(ctx:ReadContext, binding:TypedViewBinding, producer_schema_refs:List<Ref<Schema>>, consumer_schema_ref:Ref<Schema>, test_case_refs:List<Ref<ContractFixture>>) → M<BindingCheck>` | schema装配/离线检查 → 能力支持登记；契约/M | 不完整/不相容映射返回具体FieldIssue，不将相近名称视作同类型 |
| `contracts.prepare_view_binding(ctx:ServiceContext, binding:TypedViewBinding, check:BindingCheck) → PrepareResult` | schema装配命令 → 角色输入投影；契约目录/P；拟产物 `Ref<TypedViewBinding>` | 只保存检查所对应内容/schema版本；不完整映射不能标支持；键为binding身份＋内容摘要 |

`RegisteredActionInput` 是**按 operation_id 判别的106个角色Input的有限联合**，成员字段完全复用八份角色文档，不是动态字典；编号与角色契约不对应即 invalid_input。

下表规定关键跨模块绑定的字段来源；实现时为每个operation及所需schema填足全部字段，而非只实现这些示例行。表中箭头要求登记投影schema，**不声明两种 Ref 可直接强转**。

| 生产对象/字段 | 角色消费字段 | 明确转换和门控 |
|---|---|---|
| 已提交 MarketSignal 的 cells、window、information_cutoff | OwnerA01Input.observations / OwnerA16Input.demand_refs | 按本Owner可见范围形成 DemandObservation 引用；保留地区、用途、人口口径、量纲及获知时间 |
| OWN-A16 → 已提交 OwnerBrief 的 purpose_ref、region_ids、scale、delivery_window_ref、alternatives | ArchitectA05/A13Input.brief_ref；Engineer/QS的对应brief输入 | 生成专业 `Brief` 投影并记录 owner_brief_ref；OwnerBrief≠Brief。规模边界不是确定工程量，缺数量时不能供QS直接计价 |
| 编制动作选择＋工程方法数量 → 已提交 DesignOption / EngineeringOption及数量依据 | OwnerA03Input.comparison_ref、QS的方案/quantity输入 | 项目OptionComparison必须保留各专业源option与同版brief；若形成ProjectOption，登记来源DesignOption/EngineeringOption及数量映射，不合并不同候选的有利数值 |
| agreements.prepare_effectiveness 所得协议条款/独立接受/责任范围 | Architect/Engineer/QS A03的appointment/terms/function输入 | 按服务型合同生成Appointment、ServiceTerms和FunctionAssignment有版本投影；不能从受邀记录投影出有效委任 |
| resources.prepare_reservations 的物理资源、窗口、数量及承诺 | 各角色capacity、allocation、reservation输入 | ResourceCalendar、ResourceAllocation、ResourceReservation是不同投影；排期可见值不等于全组织隐私；单位/共享物理ID保持一致 |
| work.prepare_deliverable 所得成果＋真实WorkExecution完成依据 | ArchitectA07Input.deliverable_ref、task_completion_ref | 成果引用直接使用；TaskCompletion按该任务完成方法形成有版本证据，编制者note不能生成完成证明 |
| work.prepare_submission 的成果版本、requested_use_ref、接收者binding | ArchitectA08Input.review_request_ref、target_ref；OwnerA07Input的提交输入 | Submission生成对应ReviewRequest/DeliverableSubmission投影；UsePurpose→ArchitectUse枚举必须有显式映射，不自动认为已用途放行 |
| finance.prepare_offer 生成的同版FinanceOffer | OwnerA05Input.offers；BankA05Input的报价/接受字段 | 金额、币种、用途、条件、有效期和真实银行ID同一；不得映射为到账记录 |
| procurement.prepare_offer 生成Bid/SupplyOffer与轮次/包件 | OwnerA09Input.bid_refs；QS-A06；Contractor供应选择 | `Bid`、`Offer`、`SupplyOffer`的适用投影分别登记，单一Offer包装不能丢掉有效轮次及报价者 |
| 已提交Inspection/WorkExecution与实际材料结果 | Engineer检查、QS计量、Contractor验收/付款相关输入 | 按必要权限生成Verification/WorkFact/Measurement投影，隐蔽质量真值不直接暴露；工程发生与有权核证仍分开 |
| finance.prepare_settlement 已核实片段、义务分配及账户当事人 | 各角色PaymentReceipt/ReceiptEvidence/Bank偿还核对输入 | 同一执行片段保留原身份、币种及义务；回执别名不造第二笔现金，未知执行不能生成已付投影 |
| matters.prepare_decision 与权限/有效范围、条件 | Owner/Government的Permit/RegulatoryNotice输入；工程readiness | MatterDecision→Permit仅在有权限且该结果确实成立许可时形成；受理、补件、拒绝不得转换为Permit |

`RegisteredSkillInput`按skill_ref/input_schema_ref有限分派到对应角色Input或系统准备/方法输入，值可以先于调用记录保存；输入schema及内容摘要随invocation登记，不要求尚未保存输入先有TypedPayload Ref。

`RegisteredSkillOutput` 依据 skill_ref/output_schema_ref 有限分派到角色Payload、政策条款或已登记方法成果的封闭记录；没有schema及实际字段定义的技能输出返回unsupported。输出是值，正式引用由宿主准备/提交后取得，不让模型填一个不存在的“成果ID”。

## 10. 运行控制、检查点与恢复

主规则：RUN-003—007/011/015、WORLD-015/016/024；验收见[运行验收](../07_experiments/run_and_results.md#10-整次运行验收条件)及 CHECK-FLOW-009/012—014。

| 类型 | 字段 |
|---|---|
| `ControlIntent` | `operation:start\|advance\|pause\|resume\|stop, run_ref:Ref<Run>, until:Option<TimePoint>, max_cycles:Option<int≥1>, reason:Option<string>`；advance 必须有明确上界，start/resume 不覆盖配置 |
| `CheckpointManifest` | `identity:ProposedIdentity<Checkpoint>, run_manifest_ref:Ref<RunManifest>, commit_sequence:int≥0, state_partition_refs:List<Ref<StatePartition>>, queue_ref:Ref<WorkQueue>, clock_ref:Ref<ClockState>, receipt_index_ref:Ref<ReceiptIndex>, outbox_ref:Ref<OutboxState>, cognitive_refs:List<Ref<CognitiveState>>, random_refs:List<Ref<RandomState>>, unresolved_execution_refs:List<Ref<TransferInstruction>>, content_hash:string` |
| `RecoveryPlan` | `checkpoint_ref:Ref<Checkpoint>, verified_partitions:List<Ref<StatePartition>>, replay_fact_refs:OrderedList<Ref<Fact>>, pending_reconciliation_refs:List<Ref<TransferInstruction>>, can_continue:bool, limitations:List<ContractIssue>` |
| `RunStopAssessment` | `stop:bool, reason:observation_end\|control_stop\|technical_budget\|blocked_no_wakeup\|technical_failure\|continue, at:TimePoint, residual_task_refs:List<Ref<Task>>, residual_obligation_refs:List<Ref<Obligation>>` |

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `runs.prepare_control(ctx:ServiceContext, intent:ControlIntent, current_control_ref:Ref<RunControl>) → PrepareResult` | 显式用户/作业控制命令 → 调度；运行/P；拟产物 `Ref<RunControl>` | 状态不允许/权限不足，重复同命令幂等；暂停有在途时按停止边界处理，不谎称外部执行撤销 |
| `runs.assess_stop(ctx:ReadContext, run_ref:Ref<Run>, clock_ref:Ref<ClockState>, queue_ref:Ref<WorkQueue>, budget_ref:Ref<TechnicalBudget>, stop_profile_ref:Ref<StopProfile>) → M<RunStopAssessment>` | 周期边界 → 控制/结果；运行/M | 未知执行/剩余义务继续报告；停止不等于项目业务完结 |
| `checkpoints.prepare_capture(ctx:ServiceContext, run_ref:Ref<Run>, committed_read_token:string, capture_profile_ref:Ref<CheckpointProfile>) → PrepareResult` | 明确保存或已配置调度 → 可恢复记录；运行/P；拟产物 `CheckpointManifest` | 跨分区读点不一致、缺认知/随机/未决身份；键为运行＋提交序号＋捕获身份，不把展示快照当检查点 |
| `checkpoints.plan_recovery(ctx:ReadContext, checkpoint_ref:Ref<Checkpoint>, available_partition_refs:List<Ref<StatePartition>>, runtime_capability_ref:Ref<CapabilityRegistry>) → M<RecoveryPlan>` | 明确恢复用例 → 恢复提交；运行/M | 哈希/版本/能力不匹配，can_continue=false；不随机重置遗漏状态 |
| `checkpoints.prepare_recovery(ctx:ServiceContext, plan:RecoveryPlan, target_run_ref:Ref<Run>, recovery_identity:string) → PrepareResult` | 已校验恢复命令 → 调度/原身份核对；运行及状态拥有者/P；拟产物 `Ref<RecoveryRecord>` | 活跃双执行者、错运行、不可恢复；键为 recovery_identity，核对外部未决后续办，不重复付款 |

## 11. 网络、指标、实验样本与比较

主规则：RUN-009—019、POL-011/012/016—018；验收见[运行验收](../07_experiments/run_and_results.md#10-整次运行验收条件)及[研究验证策略](../07_experiments/verification_strategy.md)。方法/样本与结果版本独立，地图选看不改统计集合。

比较任务运行在workspace时，RunSet/Pairing中的Run引用指向workspace运行登记的投影，不能直接用于访问该run内世界。比较工作器按每个run分别构建获授权ReadContext，在各自固定read_token读取；跨run来源保存ScopedRef及内容摘要，或通过ReferenceImport冻结为workspace本地不可变输入。MetricValue.source_fact_refs明确使用ScopedRef溯源；普通业务裸Ref不跨空间解析。每个RunReadPoint绑定自己的源read_token与导入ClockProfile映射；MetricValue/AlignedTimeWindow中的TimeWindow在比较workspace中引用该导入时钟，对齐到共同日历/相对轴须由alignment明确定义，不能直接比较原run的裸offset。比较输出的run_set/metric/contrast/result等Ref在workspace中解析，单run结果先按有权投影导入；晚到事实不能静默改旧比较版本。

### 11.1 交接类型

| 类型 | 字段 |
|---|---|
| `NetworkEdge` | `source_organization_ref:Ref<Organization>, target_organization_ref:Ref<Organization>, layer:contact\|offer\|agreement\|realized_work, fact_refs:List<Ref<Fact>>, scope_refs:List<ScopeRef>, occurred_window:TimeWindow, region_basis_refs:List<Ref<Evidence>>, weight:ValueState<Measured>` |
| `MetricValue` | `metric_ref:Ref<MetricDefinition>, sample_ref:Ref<SampleDefinition>, window:TimeWindow, value:ValueState<Measured>, numerator:Option<Measured>, denominator:Option<Measured>, source_fact_refs:List<ScopedRef<Fact>>, valid_count:int≥0, missing_count:int≥0, censored_count:int≥0, issue_refs:List<Ref<Issue>>` |
| `RunReadPoint` | `run_ref:Ref<Run>, data_space:{kind:run,id:string}, read_token:string, manifest_hash:string, clock_source:ScopedRef<ClockProfile>, imported_clock_ref:Ref<ClockProfile>`；run_ref属于workspace目录，源读取权限逐run核验，导入时钟映射显式固定 |
| `ExecutionSlot` | `slot_id:string, scenario_ref:Ref<Scenario>, repetition_id:string, block_ref:Option<Ref<RandomBlock>>, manifest_ref:Ref<RunManifest>, technical_budget_ref:Ref<TechnicalBudget>` |
| `RunSetEntry` | `slot_id:string, run_ref:Option<Ref<Run>>, execution_status_ref:Ref<ExecutionStatus>, inclusion_basis_ref:Ref<SampleRule>, data_cutoff:Option<TimePoint>, exclusion_reason:Option<string>` |
| `InvariantCheckValue` | `invariant_ref:Ref<InvariantDefinition>, left_source:ScopedRef<Entity>, right_source:ScopedRef<Entity>, holds:ValueState<bool>, issues:List<ContractIssue>` |
| `PairingRow` | `pair_id:string, left_run_ref:Ref<Run>, right_run_ref:Ref<Run>, block_ref:Option<Ref<RandomBlock>>, comparability:eligible\|ineligible\|undetermined, pairing:paired\|unpaired\|undetermined, checked_invariants:List<InvariantCheckValue>, differences:List<ContractIssue>` |
| `AlignedTimeWindow` | `run_ref:Ref<Run>, calendar_window:ValueState<TimeWindow>, relative_window:ValueState<TimeWindow>, anchor_fact_ref:Option<ScopedRef<Fact>>, alignment_ref:Ref<TimeAlignment>` |
| `UncertaintyValue` | `statistic_ref:Ref<StatisticDefinition>, metric_ref:Ref<MetricDefinition>, sample_ref:Ref<SampleDefinition>, estimate:ValueState<Measured>, lower:ValueState<Measured>, upper:ValueState<Measured>, method_ref:Ref<Method>`；无区间方法时返回not_supported，不伪造置信区间 |
| `SampleCoverageValue` | `metric_ref:Ref<MetricDefinition>, planned_slot_ids:List<string>, included_slot_ids:List<string>, excluded:List<{slot_id:string,reason_code:string}>, unavailable:List<{slot_id:string,reason_code:string}>`；状态计数与指标纳入分开，集合按SampleDefinition核验，不隐删技术失败 |
| `ComparisonResult` | `identity:ProposedIdentity<ComparisonResult>, contrast_ref:Ref<Contrast>, run_set_ref:Ref<RunSet>, pairing_rows:List<PairingRow>, metric_refs:List<Ref<MetricDefinition>>, sample_ref:Ref<SampleDefinition>, alignment_ref:Ref<TimeAlignment>, group_values:List<MetricValue>, effect_values:List<MetricValue>, uncertainty:List<UncertaintyValue>, coverage:List<SampleCoverageValue>, method_ref:Ref<Method>` |

### 11.2 函数

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `networks.derive_edges(ctx:ReadContext, facts:FactSelection, network_definition_ref:Ref<NetworkDefinition>, population_ref:Ref<PopulationScope>) → M<List<NetworkEdge>>` | 显式结果任务 → 网络/指标；结果/M | 关系层混用、地域未知、分母不含有效边报诊断；不从消息数写真实信任 |
| `metrics.compute(ctx:ReadContext, definition_ref:Ref<MetricDefinition>, facts:FactSelection, sample_ref:Ref<SampleDefinition>, window:TimeWindow, method_ref:Ref<Method>) → M<MetricValue>` | 显式结果任务 → 分析/比较；结果/M | 单位不符、零分母、未完/未知按口径表达，不静默删样本或填零 |
| `results.prepare_projection(ctx:ServiceContext, fact_cutoff:FactSelection, metric_values:List<MetricValue>, edges:List<NetworkEdge>, definition_refs:List<Ref<Entity>>) → PrepareResult` | 明确计算任务 → 纯查询；结果/P；拟产物 `Ref<ResultVersion>` | 来源/定义变化、混运行；键为事实读点＋结果定义版本＋计算身份，不改基础账本 |
| `experiments.plan_runs(ctx:ReadContext, experiment_ref:Ref<Experiment>, contrast_refs:List<Ref<Contrast>>, repetition_plan_ref:Ref<RepetitionPlan>, manifest_refs:List<Ref<RunManifest>>, budget_ref:Ref<TechnicalBudget>) → M<List<ExecutionSlot>>` | 实验执行用例 → 作业准备；运行/M | 缺比较控制项/预算定义/方法支持；不把选中多个情景称已完成比较 |
| `experiments.prepare_job(ctx:ServiceContext, experiment_ref:Ref<Experiment>, slots:List<ExecutionSlot>, execution_identity:string) → PrepareResult` | 明确执行命令 → 作业调度；运行/P；拟产物 `Ref<ExecutionJob>` | 重复身份异参、预算/控制冲突；键为 execution_identity，不因刷新重新派发 |
| `experiments.prepare_run_set(ctx:ServiceContext, job_ref:Ref<ExecutionJob>, entries:List<RunSetEntry>, sample_definition_ref:Ref<SampleDefinition>) → PrepareResult` | 已提交运行/作业事件 → 比较；结果/P；拟产物 `Ref<RunSet>` | 计划/实际 run 混淆、遗漏失败样本；键为作业事件＋运行集合新版本 |
| `comparisons.check_pairing(ctx:ReadContext, contrast_ref:Ref<Contrast>, run_set_ref:Ref<RunSet>, pairing_definition_ref:Ref<PairingDefinition>) → M<List<PairingRow>>` | 结果计算任务 → 时间/统计方法；结果/M | 相同 seed 不自动配对，允许干预后项目内生分化；有效性与配对分别记录 |
| `comparisons.align_time(ctx:ReadContext, run_refs:List<Ref<Run>>, alignment_ref:Ref<TimeAlignment>, requested_window:TimeWindow, source_read_points:List<RunReadPoint>) → M<List<AlignedTimeWindow>>` | 比较任务 → 指标窗口；结果/M | 事件锚点未发生返回 unknown；不能按相同施工进度替代共同业务时间 |
| `comparisons.compute(ctx:ReadContext, contrast_ref:Ref<Contrast>, run_set_ref:Ref<RunSet>, pairing_rows:List<PairingRow>, windows:List<AlignedTimeWindow>, metric_values:List<MetricValue>, method_ref:Ref<Method>) → M<ComparisonResult>` | 显式比较任务 → 比较保存/页面；结果/M | 不足样本、口径/单位不齐、方法不支持；不从组合中筛选A当作A独立政策效应 |
| `comparisons.prepare_result(ctx:ServiceContext, result:ComparisonResult, input_result_refs:List<ScopedRef<ResultVersion>>) → PrepareResult` | 结果任务 → 地图/Analytics/报告；结果/P；拟产物 `Ref<ComparisonResult>`及同次PairingManifest/UncertaintyResult/CoverageReport；读取schema使用这些正式引用 | 输入版本改变、结果身份冲突；键为比较定义＋实际样本/配对＋结果版本 |

## 12. 页面查询、明确命令与版本导出

主规则及验收：完整[前端规范](frontend.md)，尤其 CHECK-UI-001—045；RUN-018/019。所有 `views.*` 只读**已有**状态/投影，缺结果返回 not_ready，不推进 tick、不计算未来结果、不调用模型、不补演示数据。正式命令由应用用例校验后调用对应 `P` 和公共提交接口；前端适配器只做格式/显示转换。

### 12.1 查询与导出类型

| 类型 | 字段 |
|---|---|
| `OrganizationDraft` | `identity:ProposedIdentity<Organization>, display_name:string, source_record_refs:List<Ref<SourceRecord>>, role_profile_refs:List<Ref<RoleProfile>>, field_values:List<SourcedField>`；每字段都有来源/补全标记，不直接改变运行实例现金 |
| `ClusterDraft` | `identity:ProposedIdentity<Cluster>, member_refs:List<Ref<Organization>>, selection_basis_ref:Ref<SelectionProfile>, initial_relation_refs:List<Ref<InitialRelation>>, coverage_ref:Ref<PopulationScope>`；集群不拥有成员现金或复制资源 |
| `ConfigurationReadiness` | `draft_ref:Ref<ScenarioDraft>, registry_ref:Ref<CapabilityRegistry>, checked_content_hash:string, ready:bool, issues:List<ContractIssue>, required_method_refs:List<Ref<Method>>`；ready不证明现实有效，已知资源不足按情景规则处理 |
| `WorkflowCheck` | `workflow_identity:ProposedIdentity<Workflow>, checked_content_hash:string, valid:bool, issues:List<FieldIssue>` |
| `WorkflowDraft` | `identity:ProposedIdentity<Workflow>, scenario_ref:Ref<ScenarioDraft>, time_profile_ref:Ref<ClockProfile>, scheduled_trigger_refs:List<Ref<ScheduledTrigger>>, phase_refs:List<Ref<WorkflowPhase>>, stop_profile_ref:Ref<StopProfile>` |
| `PreferenceDraft` | `identity:ProposedIdentity<UserPreference>, setting_scope:display\|new_draft_defaults, parameter_values:List<ParameterValue>, preference_schema_ref:Ref<Schema>`；不得含凭据或改既有run |
| `PageRequest` | `cursor:Option<string>, limit:int>0, sort_ref:Ref<SortDefinition>`；limit 上界由分页 schema 固定，cursor 绑定上下文与筛选 |
| `CatalogFilter` | `kind:organization\|cluster\|policy\|scenario\|workflow\|capability, region_refs:List<Ref<Region>>, role_refs:List<Ref<Role>>, search_text:Option<string>, status_refs:List<Ref<StatusDefinition>>` |
| `ComparisonContext` | `portfolio_ref:Ref<Portfolio>, experiment_ref:Ref<Experiment>, contrast_ref:Ref<Contrast>, run_set_ref:Ref<RunSet>, result_ref:Option<Ref<ComparisonResult>>, pairing_ref:Option<Ref<PairingManifest>>, metric_refs:List<Ref<MetricDefinition>>, sample_ref:Ref<SampleDefinition>, alignment_ref:Ref<TimeAlignment>, window:TimeWindow, source_read_points:List<RunReadPoint>`；属于workspace，两个null分别表示结果未生成及未发布配对；不由同seed猜配对 |
| `MapSelection` | `comparison_result_ref:Option<Ref<ComparisonResult>>, displayed_run_refs:List<Ref<Run>>, pair_id:Option<string>, layer_refs:List<Ref<MapLayer>>, selected_object_ref:Option<ScopedRef<Entity>>, viewport_ref:Option<Ref<Viewport>>`；只作局部查看 |
| `WorldView` | `run_ref:Ref<Run>, snapshot_ref:Ref<Snapshot>, at:TimePoint, project_refs:List<Ref<ProjectView>>, agent_refs:List<Ref<AgentView>>, event_refs:List<Ref<EventView>>, metric_values:List<MetricValue>, missing_layers:List<Ref<MapLayer>>` |
| `ComparisonView` | `context:ComparisonContext, result_ref:Ref<ComparisonResult>, selection:MapSelection, displayed_values:List<MetricValue>, displayed_scope:whole_sample\|selected_runs, selected_run_result_ref:Option<Ref<ResultVersion>>, full_sample_ref:Ref<RunSet>, selection_is_valid_pair:ValueState<bool>` |
| `DetailView` | `object_ref:Ref<Entity>, detail_schema_ref:Ref<Schema>, detail_payload_ref:Ref<TypedPayload>, event_refs:List<Ref<EventView>>, dependency_refs:List<Ref<Entity>>, visibility_basis_ref:Ref<VisibilityProfile>`；按 object kind 使用确定 schema，不能返回未定字段字典 |
| `ExportRequest` | `result_refs:List<ScopedRef<ResultVersion>>, comparison_refs:List<Ref<ComparisonResult>>, manifest_refs:List<ScopedRef<RunManifest>>, window:TimeWindow, section_refs:List<Ref<ReportSection>>, format:json\|csv\|markdown\|pdf, redaction_ref:Ref<RedactionProfile>` |
| `ArtifactFileDraft` | `identity:ProposedIdentity<ArtifactFile>, staging_locator:string, content_hash:string, media_type:string, size_bytes:int≥0`；仅隔离临时产物，交付前不可作为正式下载引用 |
| `ExportManifest` | `identity:ProposedIdentity<Export>, input_refs:List<ScopedRef<Entity>>, files:List<ArtifactFileDraft>, hashes:List<FileHash>, omitted_sections:List<ContractIssue>, source_mode:formal\|fixture, export_schema_ref:Ref<Schema>`；`FileHash(path:string,sha256:string)`，不包含凭据 |

### 12.2 函数

| 唯一函数与签名 | 调用者 → 消费者；拥有者/边界 | 异常与业务键 |
|---|---|---|
| `views.query_catalog(ctx:ReadContext, filter:CatalogFilter, page:PageRequest) → Q<List<Ref<Entity>>>` | Overview/Agent/Policy/Workflow/Setting → 页面列表；目录/R | 禁止越权/未知筛选，空列表不替换为 fixture；无业务去重键 |
| `views.query_detail(ctx:ReadContext, object_ref:Ref<Entity>, projection_ref:Ref<ProjectionDefinition>) → Q<DetailView>` | 对象侧栏/Agent认知/决定追踪 → 页面；状态投影/R | 跨运行/版本/权限不匹配，按投影 schema 返回，不给全知认知输入 |
| `views.query_world(ctx:ReadContext, run_ref:Ref<Run>, snapshot_ref:Ref<Snapshot>, layer_refs:List<Ref<MapLayer>>) → Q<WorldView>` | Simulation 历史/当前定位 → 地图；结果/R | snapshot 不存在/图层未准备，返回缺项；播放速度不改变业务时钟 |
| `views.query_comparison(ctx:ReadContext, comparison:ComparisonContext, selection:MapSelection) → Q<ComparisonView>` | Simulation/Analytics → 两页共同比较；结果/R | 不在全集的run、非法配对/指标版本、过期上下文；地图选择不写样本集合；局部运行差值尚未正式计算时返回not_ready，不在查询中计算 |
| `views.query_job(ctx:ReadContext, job_ref:Ref<ExecutionJob>, page:PageRequest) → Q<List<RunSetEntry>>` | 执行进度/分析可用性 → 页面；运行投影/R | 未完成/失败条目保留，查询不派发新任务 |
| `views.query_command(ctx:ReadContext, command_id:string) → Q<ReceiptLookup>` | 提交未知后的页面核对 → 操作反馈；提交/R | 未找到不等于已拒绝；Q.ok.data承载公共ReceiptLookup，允许found/pending/absent/unavailable/forbidden；外层只处理查询结果，具体回执语义与core.read_receipt一致，不新执行业务 |
| `catalog.prepare_organization(ctx:ServiceContext, draft:OrganizationDraft, prior_ref:Option<Ref<Organization>>, identity_evidence_refs:List<Ref<Evidence>>) → PrepareResult` | Agent明确编辑 → 样本/装配；workspace资料目录/P；拟产物 `Ref<Organization>` | 组织身份冲突、字段来源/权限缺失；键为资料修改身份＋版本，真实记录的补全不变真实观测 |
| `catalog.prepare_cluster(ctx:ServiceContext, draft:ClusterDraft, prior_ref:Option<Ref<Cluster>>) → PrepareResult` | Cluster明确创建/修改 → Workflow样本；workspace目录/P；拟产物 `Ref<Cluster>` | 成员失效/排重或覆盖不符；键为集群修订身份，不自动声明完整湾区总体 |
| `workflows.check_definition(ctx:ReadContext, draft:WorkflowDraft, schedule_profile_ref:Ref<ScheduleProfile>) → M<WorkflowCheck>` | Workflow预检 → 保存门控；工作流/M | 检查当前草稿时钟/触发/停止与scope，不要求已保存Workflow或ValidationReport |
| `workflows.prepare_definition(ctx:ServiceContext, draft:WorkflowDraft, prior_ref:Option<Ref<Workflow>>, check:WorkflowCheck) → PrepareResult` | Workflow明确保存 → 情景/运行清单；workspace目录/P；拟产物 `Ref<Workflow>` | 时钟/时序/作用范围缺定义；键为工作流修订身份，保存不执行其中事件 |
| `settings.prepare_preferences(ctx:ServiceContext, draft:PreferenceDraft, prior_ref:Option<Ref<UserPreference>>) → PrepareResult` | Setting明确保存 → 页面/新草案初始化；workspace偏好/P；拟产物 `Ref<UserPreference>` | 未知字段/越界/作用域不符；键为偏好修订身份，不覆盖冻结方法或正在运行参数 |
| `drafts.prepare_revision(ctx:ServiceContext, draft_ref:Option<Ref<ScenarioDraft>>, base_scenario_ref:Option<Ref<Scenario>>, changed_parameter_values:List<ParameterValue>, selected_profile_refs:List<Ref<Entity>>, change_reason:string) → PrepareResult` | Policy/Workflow明确保存 → 草案/校验；准备目录/P；拟产物 `Ref<ScenarioDraft>` | 未知参数/引用/版本冲突；键为草案修订身份，编辑不覆盖冻结运行 |
| `contracts.assess_configuration(ctx:ReadContext, draft_ref:Ref<ScenarioDraft>, registry_ref:Ref<CapabilityRegistry>, compiled:CompiledPolicy) → M<ConfigurationReadiness>` | 配置编译 → 保存/冻结；契约/M | 依据固定输入哈希检查schema/方法/覆盖与未决能力；未支持不默认0或1，检查不写运行状态 |
| `drafts.prepare_freeze(ctx:ServiceContext, draft_ref:Ref<ScenarioDraft>, compiled_policy_ref:Ref<CompiledPolicy>, readiness:ConfigurationReadiness) → PrepareResult` | 明确冻结命令 → 创建运行/实验；准备目录/P；拟产物 `Ref<Scenario>` | 依赖未齐、校验过期；键为冻结身份＋内容哈希，不以保存成功代替可运行 |
| `runs.prepare_manifest(ctx:ServiceContext, scenario_ref:Ref<Scenario>, data_ref:Ref<DataRelease>, population_ref:Ref<PopulationSpec>, opening_ref:Ref<OpeningSpec>, cognition_ref:Ref<CognitionSpec>, execution_profile_ref:Ref<ExecutionProfile>, random_plan_ref:Ref<RandomPlan>, manifest_identity:string) → PrepareResult` | 已冻结配置 → 实例预留/实验计划；workspace运行清单/P；拟产物 `Ref<RunManifest>` | 冻结schema/方法/数据/预算/代码身份及支持诊断；缺依赖不创建ready运行；键为manifest_identity，不要求运行已存在 |
| `exports.prepare_job(ctx:ServiceContext, request:ExportRequest, export_identity:string) → PrepareResult` | Reports 明确导出 → 导出工作器；结果/P；拟产物 `Ref<ExportJob>` | 输入不齐/权限不符/格式未支持；键为 export_identity，保持旧结果版本 |
| `exports.render(ctx:ReadContext, job_ref:Ref<ExportJob>, request:ExportRequest, renderer_ref:Ref<Renderer>) → M<ExportManifest>` | 已提交导出工作 → 文件登记；导出/M（允许隔离临时文件副作用，禁止正式写入） | 渲染/哈希/脱敏失败，缺项明确列出；只写隔离临时产物，不改世界/旧结果，重试按原 job 续办 |
| `exports.prepare_delivery(ctx:ServiceContext, job_ref:Ref<ExportJob>, manifest:ExportManifest, artifact_validation_ref:Ref<ArtifactValidation>) → PrepareResult` | 导出工作器 → 文件查询/下载；结果/P；拟产物 `Ref<Export>` | 文件缺失/哈希不符，不能把“已建任务”当文件可取；键为 job＋文件集哈希 |

创建依赖的确定顺序为：创建/修订ScenarioDraft → 条款提交 → 机制/编译草稿 → policy.prepare_configuration提交机制与编译包 → drafts.prepare_freeze形成Scenario → runs.prepare_manifest → bootstrap.prepare_instance → InitialPlan/OpeningAudit → bootstrap.prepare_run → bootstrap.prepare_instance_status。没有新增政策时仍需显式空机制集合与覆盖检查，不能伪造政策引用。draft_ref=null表示新草案，base_scenario_ref=null表示不从既有情景复制；冻结不先要求RunManifest，编译不先要求冻结Scenario。

工作创建依赖为：已登记DecisionTask → 角色XTaskRequest → work.prepare_request → 独立有权决定 → work.prepare_authorization → project.evaluate_dependencies/prepare_task_graph → 正式Task → 实际WorkExecution → 成果草稿/编制检查 → 成果提交 → 任务完成证据。任务尚未创建时禁止生成角色XTaskPlan中的既有task_ref；系统TaskPlan本身是有权创建任务的具名草稿；已存在任务的XTaskPlan只修改授权范围内的安排。

所有资料编辑使用实体专属schema；`drafts.prepare_revision`只负责情景草案，不允许用 `save_anything(payload:dict)` 绕过其他实体的字段/权限约束。新增资料种类、页面用例和外部适配器须先登记其函数、类型与失败分支，再进入实现清单。

## 13. 全链覆盖与调用责任

| 逻辑链 | 生产者 → 接口 → 消费者 | 贯通验收入口 |
|---|---|---|
| 来源到初态 | 来源记录 → data.* → bootstrap.* → 各正式期初状态 | RUN-001—004；OBJ-021；初始化不得复制现金/能力 |
| 外生/政策到可见机会 | world.* / policy.* → market.* → observations.* / candidates.* → Owner 行为 | WORLD-017—021；POL-014；P01—P05 |
| 组织经营和未模拟市场 | organizations.* / background.* / assets.* → 统一资金与资源 → 下一周期信号 | W1—W3；D-08；无订单仍按支持方法处理 |
| 主体建议到正式事实 | ActionSlot → 角色契约/技能 → 对应领域 P → core.commit → 回执/事实 | 公共协议；RUN-008；建议不直接修改工程/余额 |
| 具体项目与专业工作 | project.* → work.* / methods.* → 明确接收者 → 审查/用途发布 | P03—P10；CHECK-FLOW-006/016—018 |
| 委任/采购/许可/合同 | 角色独立选择 → agreements.* / matters.* → 责任/资源/任务 | P06—P13；CHECK-FLOW-004/015/017/022—027 |
| 制造到安装 | resources.* → engineering.* / inventory.* → 检验/可用材料 → 现场工程 | P14—P17；CHECK-FLOW-003/005/007/028—031 |
| 使用/接管/缺陷 | work.* / matters.* → assets.* / project.* → 残余任务/责任 | P18—P20；FLOW-010/011；W3 |
| 核证/义务/现金清偿 | 角色材料/有效依据 → finance.* → payments.* → finance.* → 共同账本 | P08/P16/P21/P22；OBJ-011/012 |
| 运行/技术故障 | runs.* → checkpoints.* → 原命令/原执行核对 → 调度继续 | RUN-005—007；CHECK-FLOW-009/012/013 |
| 事件到认知与下一行动 | 已提交事实 → observations.* → cognition.* → 候选/角色输入 | WORLD-006/022；RUN-008；不得共享私有认知 |
| 实验/网络/统计 | experiments.* → 实际 run 集 → networks.* / metrics.* → comparisons.* | RUN-009—019；POL-011/012/017/018 |
| 页面与可共享结果 | views.* 读取冻结投影；显式命令进入准备/提交；exports.* 固定结果交付 | CHECK-UI-001—045；查询不能推进世界 |

所有workspace入口（data、policy准备、catalog/workflows/drafts/settings、experiments、comparisons、配置登记和导出）不要求已有run或仿真时钟；运行入口（world/market/scheduler、业务工作/工程/资金/观察/认知）使用run空间；contracts可在其schema登记空间执行；skills按任务空间。bootstrap跨空间仅使用显式初始化协议，views按查询对象选择空间；同名ID不跨空间解析。

项目 P01—P23 的具体**生产者—数据—消费者**见[项目接线表](../03_projects/collaboration_flow.md#8-p01p23-的接口接线表)。下列样例检查接口衔接，不替代未选择的真实工程、时间或市场方法。

### 13.1 正常贯通：可消费成果到实际交付

1. 按选定模型建立 `DataRelease → RunManifest → RunInstance → InitialPlan → OpeningAudit`；各自提交及初始化核对后读取正式 `Run`。下列为完整能力的接线要求；[F-GBA-01](../07_experiments/reference_scenarios.md#41-同一物理范围的合成贯通例-f-gba-01)仅核对其中已明示的履约切片，其专业成果与合同是期初输入，不证明本节的投资、编制和市场环节已经执行。
2. 已授权调度形成 `MarketSignal → Observation → ActionSlot`；Owner 的私有选择进入角色契约。核心按本次任务的组织/档案/项目范围处理工作请求与有权授权，再创建业务Task及具体 `ResponsibilityBinding`；已有任务才编排 `TaskPlan`，不能要求申请时已有该工作。
3. 编制方把同版方案及数量输入提交给 `methods.evaluate_option`；有限方法确实支持时输出对应专业成果。`work.prepare_deliverable` 后提交；`work.evaluate_completion / prepare_completion` 形成正式编制完成证据，再以 `SubmissionDraft` 引用该成果送明确接收者。QS 不从 note 猜数量，Engineer 不从客户接受猜技术通过。
4. 有权审查与用途发布分别提交；合同双方分别接受相同条款。`agreements.prepare_effectiveness` 联合资源/义务准备同次提交，不能单方选中即占用对方全部产能。
5. 供应和施工按真实 `WorkSlice` 计算，正式生产、发运、收货、检验与消耗分别留事实；WorkExecution覆盖已支持的专业/行政/经营工作投入，不把“工程”函数名理解成只允许现场施工。最终 `EngineeringOutcome` 与资源/材料同次提交；合同费用经依据形成义务，实际付款另走指令和片段。
6. 实际接管引用 as-built、接收权限和剩余责任。真实使用进入资产/需求反馈；`metrics.compute → results.prepare_projection → views.query_world` 只显示同一事实来源，页面不再算正式成本。

### 13.2 失败恢复：提交成功但回执丢失，随后收到旧版审查

1. Architect 的提交 S1 已由 `core.commit` 形成成果提交与审查待办，但客户端未收到回执。宿主保留 command ID 和 S1；`views.query_command`/公共回执查询核对。不能把技术超时变成“未提交”，不能换 ID 重造 S2、费用或审查任务。
2. 已确认同一请求正式结果后重投通知，仅重试原 outbox 消费。若成果确有授权修订，创建 D2 和新的提交 S2，而非修改旧 D1 内容；实际返修投入与费用有自己的任务/片段依据。
3. 审查者迟到返回针对 D1/S1 的认可；`work.prepare_review` 保留其真实引用，不能放行 D2。受影响任务据 `project.evaluate_dependencies` 等待 D2 的有效审查，未受影响范围继续。
4. 同时某笔付款执行未知时，核对原 `instruction_ref`，只将新核实的实际片段交 `finance.prepare_settlement`。即使项目暂停或换承包商，旧真实支付仍记到原当事人/义务，不因旧轮关闭删除。
5. 恢复入口按检查点核对认知、队列、资源、随机和未决身份，缺任一必要分区就报告不能继续的范围；不能借“重新跑一遍”复制已发生工作。对应 CHECK-FLOW-006/007/010/012/019/026，及[既有失败传播与恢复算例](../07_experiments/reference_scenarios.md#5-失败传播与恢复)。

## 14. 进入实现前的补齐与验收

每个选定函数必须同时有：输入 schema 的确定字段与单位、输出联合的各分支、权限/状态拥有者、必要依赖版本、明确调用点、与提交/恢复的关系、成功和失败的独立样例、具体实现/测试映射。若引用的方法尚未选定，接口可以先实现 `unsupported` 与诊断，不得把类型齐全当方法成功。

本目录覆盖世界与平台的主要模块边界；角色全部行动及实体专属编辑分别由其主目录登记。未来发现遗漏的边界函数时先补对应目录再编码。私有 helper 的参数、返回、异常、副作用及调用关系仍须按[公共接口协议](interface_contracts.md)的实现登记要求维护，不要求把每个循环变量变成跨模块公共接口。
