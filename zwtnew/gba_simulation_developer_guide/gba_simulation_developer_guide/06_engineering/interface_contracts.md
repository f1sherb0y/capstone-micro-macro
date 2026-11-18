# 类型、函数与输入输出契约

本文件定义目标程序共同采用的数据表达、调用结果、函数规范与提交协议。角色动作的业务字段在[角色主文档](../README.md#角色规范)，非角色函数及其专用数据结构在[系统接口目录](system_interfaces.md)。这些是重构目标，不是当前源码签名、已生成 schema 或实现证据。

[总入口](../README.md) · [软件架构](implementation_contracts.md) · [共同对象](../02_world/domain_objects.md) · [系统接口](system_interfaces.md) · [函数索引](function_catalog.md)

<!-- page-nav:start -->
**本页导航**

[1. 契约覆盖范围与唯一归属](#1-契约覆盖范围与唯一归属) · [2. 类型语言与字段规则](#2-类型语言与字段规则) · [3. 输入上下文与字段生产责任](#3-输入上下文与字段生产责任)

[4. 行为、计算、查询和执行结果](#4-行为计算查询和执行结果) · [5. 命令、准备、提交与回执](#5-命令准备提交与回执) · [6. 全部函数的登记标准](#6-全部函数的登记标准)

[7. 接口一致性与验收](#7-接口一致性与验收)
<!-- page-nav:end -->

## 1. 契约覆盖范围与唯一归属

契约覆盖资料进入、世界初始化、环境更新、政策生效、主体行为、项目推进、工程与经营执行、资金资源变化、观察反馈、运行恢复、结果分析和前端操作。世界更新器、规则提供者、Skill、LLM 和界面均不能绕过共同边界。

| 定义 | 唯一维护位置 | 使用方式 |
|---|---|---|
| 业务对象含义、状态与不变量 | 共同对象及其领域主文档 | 类型细化不能自行改变债务、批准、完成等业务语义 |
| 通用类型、结果与技术错误 | 本文件 | 输入、输出、事件及 DTO 复用；不为每角色另写一套余额或身份 |
| 各角色每个 A 动作的 Input/Payload | 对应角色文件 | 函数登记、模型返回与业务校验引用同一契约 |
| 非角色边界函数与专用类型 | 系统接口目录 | 环境、工程、政策、运行、查询等按职责接线 |
| HTTP/消息/数据库绑定 | 实现时的契约绑定记录 | 映射到同一用例与类型，不新增隐含规则 |
| 全部实际函数与检查证据 | 实现时生成的源码符号清单及绑定记录 | 公共函数、私有帮助函数、回调和异步处理器全部登记 |

**输入输出要固定到可校验的数据结构，但不固定主体必须选择什么。** 解释文本可说明理由；流程必须消费的范围、条件、金额、候选和状态必须有相应字段。两个字段的文字看起来相似，不构成程序转换依据。

一个 A 动作可以包含准备成果、形成决定、提交命令和等待观察等多个函数；不是每个行为对应一次 LLM 请求，也不是每个内部函数都需要独立 HTTP 接口。系统只执行已有授权的例行工作，不能用自动流程替代必要的主体判断。

## 2. 类型语言与字段规则

以下记法用于 MD 中定义可转写为语言类型和 schema 的契约：

| 记法 | 确定语义 |
|---|---|
| `string` / `bool` / `int` | 字符串、真正布尔值、整数；不把字符串 true 当布尔值，不自动把字符串数字转为整数 |
| `decimal` | 有限十进制数；金额和精确数量禁止 NaN/Infinity；传输用十进制字符串，精度与舍入由字段/方法声明 |
| `T[]` / `List<T>` | 元素均为 T 的有序列表；如语义为集合，另声明排重与规范排序；空列表不代表未知 |
| `Option<T>` / `T?` | T 或 null；字段仍存在。每字段声明 null 的单一含义；它不是任意缺失、未知、不适用的混合标记 |
| `A \| B` | 由明确 discriminator 分辨的联合；只允许对应分支字段；不能同时接受和拒绝 |
| `a / b / c` | 局部字段表的有限枚举简写，值必须精确属于列出的字面量；不是自由文本或一个包含斜线的字符串 |
| `{a:T,b:U}` | 封闭记录；字段默认必填，额外字段拒绝。局部定义的可选字段须明确标注 |
| `Ref<K>` | 对象种类、身份与确切版本；K 指业务种类，不是任意字符串别名 |
| `DraftRef<K>` | 仅供指定草稿字段引用同一具名草稿集合中的 ProposedIdentity；不具有读取权或业务效力；正式字段不能接受它 |
| `EntityId<K>` | 对象稳定身份；其读取必须另受运行、权限与读取版本约束 |
| `ValueState<T>` | 带状态的值，区分 known、unknown、not_applicable、not_supported，定义见下文 |

未逐项确定的专业数据，不准伪装为 `any`、`object`、任意 `dict` 或一个写着“完整成果”的文本。可以引用有版本、可解析且有登记 schema 的对象；引用不是免除定义的办法。`Ref<TimeWindow>` 与内联 `TimeWindow` 是不同类型，转换须读取明确版本。

### 2.1 身份、版本与范围

| 类型 | 必填字段及校验 |
|---|---|
| `VersionToken` | `string` 或 `int`；每种对象的 schema 固定其中一种序列化及比较规则，不允许同种对象混用或自动强转 |
| `Ref<K>` | `kind:string`（必须等于 K 的登记 kind）、`id:string`（非空）、`version:VersionToken`；必须在指定数据空间解析并检查访问权限 |
| `EntityId<K>` | 非空 string；运行内身份由 run 隔离，资料库身份由 workspace 隔离；名称不能代替 ID |
| `ScopeRef` | `{kind:assessment_case\|project\|organization, ref:Ref<对应种类>, coverage_refs:List<Ref<WorkScope>>}`；组织经营无工程范围时 coverage_refs 可为空，项目内范围按动作要求非空 |
| `EvidenceRef` | `Ref<Evidence>`；被引用记录具有 `source_kind:real_user\|real_public\|synthetic`、`basis_kind:observed\|inferred\|assumed`、`locator:string`、`content_hash:string`、`effective_window:Option<TimeWindow>`；补全字段另有字段级依据 |
| `MethodRef` / `ProfileRef` | `Ref<Method>` / `Ref<Profile>`；运行清单登记其内容摘要、支持域、输入输出 schema 与参数引用；名字相同而内容不同不算相同方法 |

`ScopedRef<K>={data_space:{kind:workspace|run,id:string},ref:Ref<K>}` 只用于受控导入、溯源和结果查找。普通业务函数的Ref只在其上下文data_space解析；禁止同名ID跨空间隐式命中。

`ReferenceImportPlan={source:ScopedRef<BusinessObject>,target_space:{kind:workspace|run,id:string},target:ProposedIdentity<BusinessObject>,content_hash:string,projection_ref:Ref<ImportProjection>}`，用于bootstrap初态或明确的导入草稿；source/projection按所声明源空间权限读取，提交后的不可变映射才用以下ReferenceImport。

`ReferenceImport={source:ScopedRef<BusinessObject>,target_space:{kind:workspace|run,id:string},target:Ref<BusinessObject>,content_hash:string,projection_ref:Ref<ImportProjection>}`。target_space须与导入命令空间一致。初始化按权限把所需资料、方法、政策和配置的冻结内容导入run，并登记映射及摘要；目标是run内不可变输入，来源保留但不动态追随工作区更新。ImportProjection声明准许字段及schema，不能导入凭据或无权私有资料。受控运行中政策变化同样显式导入新版本并走生效命令，不原地替换历史引用。 跨运行比较在工作区处理：运行清单可由工作区引用，各运行事实按其权限和冻结读点分别读取；结果以ScopedRef保存来源，或按同一ReferenceImport协议导入工作区的不可变结果输入。任何计算不得在一个run上下文解析另一个run的裸Ref。地图查看A/B分别使用对应run读取上下文，比较汇总使用固定工作区结果上下文。

`ProposedIdentity<K>={kind:string,id:string,proposed_version:VersionToken}` 是宿主按稳定创建键分配的待建身份，不是已持久化对象。`DraftRef<K>={kind:existing,ref:Ref<K>}|{kind:proposed,identity:ProposedIdentity<K>,draft_group_id:string}` 只允许出现在明确登记的具名 Draft 字段；proposed 必须指向同组、同拥有者许可的待建对象，其 schema 和依赖须可解析。不同组不得互引；涉及多领域的同组由协调者统一核对拥有权和同时提交条件。无相应领域 prepare/schema 的对象不能借 DraftRef 保存。

只有核心成功提交后，才能把同组身份解析为正式 `Ref<K>`；准备失败不产生这些 Ref。同一创建键重试复用身份，身份被占用或内容不一致报冲突，不能由随机换 ID 规避排重。需要已保存对象的函数仍只接受 Ref；尚未保存的输入另用具名 Draft，不把所有 Ref 改成可接受任意草稿。领域正文引用的“方案/任务/条款已存在”必须由相应创建回执证明。

`WorkScope` 引用 OBJ-005/006 的实际覆盖，不能通过不同 ID 重计同一实物或工作。评估档案未转项目时使用 assessment_case，不伪造项目。引用旧版本可能仍是合法业务输入，是否过期由用途与依赖规则检查，不统一替换为“最新”。

### 2.2 数值、未知与时间

| 类型 | 字段及解释 |
|---|---|
| `ValueState<T>` | `{state:known,value:T}`；或 `{state:unknown,reason_code:string,missing_refs:List<Ref<Evidence>>}`；或 `{state:not_applicable,rule_ref:Ref<Rule>}`；或 `{state:not_supported,capability_ref:Ref<Capability>}`。非 known 分支禁止 value |
| `Measured` | `{value:decimal,unit:string,basis_ref:Ref<Evidence>}`；unit 必须在量纲登记表中，正负范围由字段定义，换单位须显式方法 |
| `Money` | `{value:decimal,currency:string,basis_ref:Ref<Evidence>}`；currency 来自所用资金 profile，禁止未登记换汇；报价、估算、应付、实际收款的性质由所属对象决定 |
| `TimePoint` | `{clock_ref:Ref<ClockProfile>,offset:int}`；offset 的原点和单位由时钟 profile 声明，不默认一天或一个月 |
| `TimeWindow` | `{start:TimePoint,end:TimePoint,bounds:closed_open\|closed_closed\|open_closed\|open_open}`；同一 clock、start≤end；业务允许的边界类型由字段确定 |
| `Explanation` | `{summary:string,evidence_refs:List<EvidenceRef>,assumptions:List<string>}`；可读理由及证据，不能覆盖结构化条件，不能要求暴露模型内部推理过程 |

未知金额使用 `ValueState<Money>`；“未发生付款”是付款对象的状态，不是未知的现金零值。量、单价和总价分别带单位/币种与数量边界；不能从 LLM 文字中重新猜测数值。区间必须用显式上下界及单位，不能只交字符串“约 10—20”。

时间协议仍依 D-04 选择。系统墙钟用于运行监控与超时，不以响应耗时更新 TimePoint。按相同业务时点发生的命令由已选竞争协议排序，不使用网络快慢暗定先后。

## 3. 输入上下文与字段生产责任

### 3.1 共用上下文

| 类型 | 字段 |
|---|---|
| `ReadContext` | `data_space:{kind:workspace,id:string}\|{kind:run,id:string}`、`principal_ref:Ref<Principal>`、`viewpoint:operator\|agent\|researcher`、`authorization_refs:List<Ref<Authorization>>`、`read_token:string`、`source_mode:formal\|fixture` |
| `ServiceContext` | `data_space:{kind:workspace\|run,id:string}`、`principal_ref:Ref<Principal>`、`principal_kind:operator\|system\|agent`、`authorization_refs:List<Ref<Authorization>>`、`request_id:string`、`command_id:Option<string>`、`action_context_ref:Option<Ref<ActionInvocation>>`、`trigger_ref:Option<Ref<SystemTrigger>>`、`read_token:string`、`business_time:Option<TimePoint>`；仅纯预检可用null command_id，任何准备写入需已登记命令身份；工作区没有仿真时钟时business_time为null |
| `ActionContext` | `run_id:string`、`actor_id:EntityId<Agent>`、`function_ref:Ref<FunctionAssignment>`、`authorization_refs:List<Ref<Authorization>>`、`operation_id:string`、`contract_ref:Ref<ActionContract>`、`task_ref:Ref<DecisionTask>`、`scope:ScopeRef`、`business_time:TimePoint`、`read_token:string`、`visible_refs:List<Ref<BusinessObject>>`、`candidate_set_ref:Ref<CandidateSet>`、`execution_mode:llm\|rule\|routine\|offline_fixture` |
| `CandidateSet` | `operation_id:string`、`scope:ScopeRef`、`as_of:TimePoint`、`candidates:List<{ref:Ref<BusinessObject>,permitted_choices:List<string>}>`、`search_profile_ref:ProfileRef`；列表可以真实为空，不能据此制造替身主体或默认成交 |

`BusinessObject` 是登记的领域对象联合，其 kind/schema 必须可解析，不是任意 JSON。Principal 是平台访问身份，Agent 是仿真主体，FunctionAssignment 是业务职能，三者不得互换。系统动作使用明确的系统触发上下文，不假冒任一角色的 ActionContext。

ActionContext 是宿主内部可信信封；提供给模型的视图只包含该动作允许使用的信息。模型回复即便重复这些身份字段，也不得覆盖宿主绑定值。visible_refs 不能给主体打开全局隐藏真值；提供候选和正式提交可复用规则但使用各自授权视图。

ServiceContext用于应用和系统用例，不授予操作者任意扮演仿真主体的权力。principal_kind为agent时action_context_ref必须解析到已有ActionContext及其业务授权；其余主体该字段为null，表示不代入仿真主体。system时trigger_ref必须非空且为有效系统触发，operator无系统触发时该字段为null。运行内推进需要非空business_time；工作区准备不能伪造run_id或借另一运行的时间。每个系统接口声明允许的data_space。

ActionContext.task_ref 是宿主已登记的 **DecisionTask（决策调用任务）**，不是尚待申请或授权的 WorkTask。新调查、培训、营销、专业工作可在本组织 scope 下产生申请；未立项使用 assessment_case，成立后按实际项目范围另绑定。DecisionTask 的登记仅授予有限输出/可见输入，不授予工作、合同、资金或资源权限。任务请求→有权授权→业务 WorkTask 创建依[系统接口](system_interfaces.md)，不能要求申请时已有该 WorkTask 或有效委任。

`ReadContext.read_token` 是其 data_space 内一致读取边界，不能跨空间复用。Principal/Authorization 的引用在该空间解析为受控身份投影，平台访问认证与业务职能授权仍分别核验；新 run 的控制身份与初始化能力由工作区实例登记授予并固定来源，不从尚未创建的业务组织反向取得授权。无业务时间的 workspace 调用禁止混入 run 时钟；工作区比较按已导入的时间对齐定义消费各 run 的带来源时间。

### 3.2 字段责任矩阵

| 字段类别 | 生产者 | 谁核验/采纳 |
|---|---|---|
| 选择、报价条件、方案变量、专业判断、解释 | 有权主体或其获授权方法；限字段与候选域 | 动作校验与相应领域规则；专业意见并不保证现实正确 |
| 可见资料、候选、角色/职能、业务时间、任务/命令身份 | 宿主与已声明调度/授权规则 | 核心复核，模型不能自行增补权限 |
| 工程量计算、资源余额、现金变化、到期额 | 明确的工程/资金方法及领域执行 | 方法输入/单位/版本检查后通过正式提交 |
| 正式状态、事件、提交序号、投递身份 | 核心提交与投递模块 | 持久回执和投影消费；不能从文本提取“已通过”生成 |
| 页面摘要、排序、图层和解释 | 前端纯投影或服务端查询 | 引用同一读取上下文，不修改正式计算结果 |

### 3.3 角色输入的类型化映射

`TypedViewBinding={identity:ProposedIdentity<TypedViewBinding>,operation_id:string,input_schema_ref:Ref<Schema>,source_kind_refs:List<Ref<ObjectKind>>,mappings:List<ViewFieldMapping>,visibility_ref:Ref<VisibilityProfile>,version_policy_ref:Ref<VersionPolicy>}`；这是待保存映射，identity不是已有Ref。

`ViewFieldMapping={source_kind_ref:Ref<ObjectKind>,source_field_path:string,target_field_path:string,transform:identity|registered_method,method_ref:Option<Ref<Method>>,unit_rule_ref:Option<Ref<UnitRule>>,required:bool}`。与资料标准化所用 `FieldMapping` 是不同类型，不能同名强转。identity转换的method_ref为null；非数值字段不需单位规则时unit_rule_ref为null；每种其余情形按登记schema明确。源路径/目标路径分别必须存在于来源/角色Input schema；缺字段不能用null补过必填检查，禁止任意脚本。

`BindingCheck={binding_identity:ProposedIdentity<TypedViewBinding>,binding_hash:string,complete:bool,issues:List<FieldIssue>,checked_fixture_refs:List<Ref<ContractFixture>>}`；校验草稿时不要求映射已保存。contracts.prepare_view_binding检查hash及schema后保存，正式装配函数只读取已保存Ref<TypedViewBinding>。

## 4. 行为、计算、查询和执行结果

### 4.1 `ActionResult<T>`

角色 Input 和 T 在对应角色文件逐动作定义。共用外层为封闭联合：

| `kind` | 必有字段 | 业务含义 |
|---|---|---|
| `completed` | `payload:T` | 本次输出形成；不表示提交、对方收到、接受、付款或获批 |
| `needs_information` | `missing_fields:List<string>`、`requested_refs:List<Ref<BusinessObject>>` | 缺少必要信息；引用可为空但缺字段不能空；实际发起补查仍需有权命令 |
| `deferred` | `reason_code:string`、`resume_condition:ResumeCondition` | 本次主动或业务上等待；不能把模型超时写成主动等待 |
| `unsupported` | `capability_ref:Ref<Capability>` | 所需方法或范围未支持；不隐式采用另一方法 |
| `technical_error` | `error:TechnicalFailure`、`retryability:retryable\|non_retryable\|unknown` | 调用/解析等技术失败；不生成业务拒绝 |

`ResumeCondition={trigger:event\|time\|dependency_change, object_refs:List<Ref<BusinessObject>>, earliest_time:Option<TimePoint>, condition_code:string}`。earliest_time 的 null 仅表示没有指定最早时点。condition_code 由所用动作 profile 注册并可计算，不能只把“情况好转后”交给调度器。

Payload 内的 `choice` 表达提出、接受、拒绝、修订、撤回等业务选择，分支由动作卡定义；不同分支的必填字段不能共用一个 accepted 布尔值推测。身份真实且格式合法也不保证选择合法，需要当前条件校验。

输入装配时若上游尚未产生必要事实，宿主可登记needs_information并保留待办，不调用要求完整Input的处理函数，也不伪造必填引用。已经提交到类型边界但缺必填键、类型错误的JSON属于ValidationResult的格式错误；合法引用因资料未就绪而不能满足业务，则沿信息/等待分支处理。这两种情况不能仅凭同一句“字段缺失”合并。

### 4.2 `MethodResult<T>` 与 `QueryResult<T>`

| 类型/分支 | 字段与约束 |
|---|---|
| `MethodResult.ok` | `value:T`、`method_ref:MethodRef`、`input_digest:string`、`input_refs:List<ScopedRef<BusinessObject>>`、`basis_refs:List<EvidenceRef>`；保留输入版本和方法登记，返回值不是正式写入 |
| `MethodResult.needs_information` | `missing_fields:List<string>`；不得用空输入产生完整工程结果 |
| `MethodResult.invalid_input` | `issues:List<FieldIssue>`；类型、单位、范围、相互矛盾的引用等已知错误，不冒充仅缺资料 |
| `MethodResult.unsupported` | `capability_ref:Ref<Capability>`；仅阻止依赖该能力的工作 |
| `MethodResult.technical_error` | `error:TechnicalFailure`、`retryability:retryable\|non_retryable\|unknown` |
| `QueryResult.ok` | `data:T`、`read_token:string`、`source_mode:formal\|fixture`、`next_cursor:Option<string>`；null cursor 表示没有下一页 |
| `QueryResult` 其他分支 | `kind:not_found\|forbidden\|not_ready\|invalid_query\|stale_context\|technical_error`、`reason_code:string`、`error:Option<TechnicalFailure>`；仅 technical_error 要求非空 error，其余 null 表示没有技术异常 |

空列表、数值零和统计不可计算由 T 的业务字段表达，不等于 not_found。query 不得推进世界、创建项目、调用模型或改写主体记忆；投影未就绪返回 not_ready 或明确的旧读取版本，不能临时运行仿真“补出”未来记录。

方法实现可用语言的异常机制报告内部程序错误，但适配到公开边界时必须形成可识别的技术失败；不得吞异常返回正常空列表。私有函数如果抛异常，函数记录必须说明类型和调用方处理方式。

`FieldIssue={field_path:string,code:string,expected:string}`。面向不同访问者的诊断仍须裁剪，不在错误中泄露其他主体私有事实。纯方法输出的“可行/不可行”若是该专业问题的实质判断，放在其有类型value中；invalid_input只表达输入不合契约。

## 5. 命令、准备、提交与回执

### 5.1 共用结构

| 类型 | 字段及约束 |
|---|---|
| `CommandEnvelope<P>` | `run_id:string`、`command_id:string`、`command_type:string`、`contract_ref:Ref<CommandContract>`、`principal:{kind:agent,actor_id:EntityId<Agent>,function_ref:Ref<FunctionAssignment>,authorization_refs:List<Ref<Authorization>>}\|{kind:system,trigger_ref:Ref<SystemTrigger>}`、`task_ref:Ref<DecisionTask>\|Ref<SystemTask>`、`scope:CommandScope`、`business_time:TimePoint`、`expected_refs:List<Ref<BusinessObject>>`、`causation_refs:List<Ref<BusinessObject>>`、`parent_command_id:Option<string>`、`payload:P`、`payload_hash:string` |
| `WorkspaceCommandEnvelope<P>` | `workspace_id:string`、`command_id:string`、`command_type:string`、`contract_ref:Ref<CommandContract>`、`principal_ref:Ref<Principal>`、`authorization_refs:List<Ref<Authorization>>`、`task_ref:Ref<WorkspaceTask>`、`expected_refs:List<Ref<BusinessObject>>`、`parent_command_id:Option<string>`、`payload:P`、`payload_hash:string`；用于资料、政策/情景准备、实验作业创建等工作区写入，不含假run_id或仿真时间 |
| `PreparedChange` | `data_space:{kind:workspace\|run,id:string}`、`command_id:string`、`owner_module:string`、`expected_refs:List<Ref<BusinessObject>>`、`patches:List<DomainPatch>`、`business_keys:List<string>`、`event_drafts:List<EventDraft>`、`followups:List<FollowupDraft>`；只表示待提交，不向调用者暴露可修改的全局世界对象 |
| `DomainPatch` | `object_kind:string`、`operation:create\|update\|close`、`target_id:string`、`base_version:Option<VersionToken>`、`payload_schema_ref:Ref<Schema>`、`value:该schema定义的封闭记录`；仅登记的拥有者能提交对应 kind，不能通用任意字段补丁 |
| `EventDraft` | `event_type:string`、`payload_schema_ref:Ref<Schema>`、`payload:该schema的封闭记录`、`business_key:string`、`visibility_rule_ref:Ref<VisibilityRule>`；event_id/commit_seq由核心创建 |
| `FollowupDraft` | `followup_type:string`、`target_ref:DraftRef<BusinessObject>`、`resume_condition:ResumeCondition`、`business_key:string`、`payload_schema_ref:Ref<Schema>`、`payload:该schema的封闭记录`；消费者登记幂等消费键 |
| `CommandReceipt.committed` | `data_space:{kind:workspace\|run,id:string}`、`command_id:string`、`commit_seq:int`、`event_refs:List<Ref<CommittedEvent>>`、`object_refs:List<Ref<BusinessObject>>`；成功持久化后才能返回 |
| `CommandReceipt` 拒绝分支 | `kind:business_rejected\|version_conflict\|identity_conflict`、`data_space:{kind:workspace\|run,id:string}`、`command_id:string`、`reason_code:string`、`checked_refs:List<Ref<BusinessObject>>`；不能带伪造的成功事件 |

`CommandScope={kind:existing,scope:ScopeRef}|{kind:world,region_refs:List<Ref<Region>>}|{kind:creation,object_kind:string,creation_key:string,parent_scope:Option<ScopeRef>}`；world仅用于已授权世界任务，creation仅用于有对应类型/创建权限的首次创建。parent_scope=null只用于尚无任何运行业务对象的初始化；不能为已有对象的变更伪造creation以绕过范围授权。CommandEnvelope可引用DecisionTask或SystemTask，workspace信封引用WorkspaceTask，三者都由宿主登记，不要求先完成所要创建的业务工作。

parent_command_id 的 null 表示没有父命令；同次新建对象间的payload/event/followup依赖只在其已登记schema允许处使用DraftRef；核心提交时全部解析为正式引用。create 的 base_version 为 null 表示新对象，update/close 必须提供原版本。close 是业务对象关闭的受控操作，不是物理删除历史。DomainPatch、EventDraft 的 schema 分派是有限登记联合，不能借 schema_ref 字段接受未登记任意字典。

每份PreparedChange的data_space必须与命令一致，目标和普通依赖也在该空间解析；初始化和受控导入仅通过ReferenceImportPlan的ScopedRef读取源空间并核对摘要，不把源裸Ref放进目标expected_refs；准备结果来自其他空间时拒绝，不因ID相同拼接写集。command_id、commit_seq及业务排重在data_space内解释，不能把不同运行或工作区的同号回执混用。CommittedEvent随所属空间保存：工作区资料变更不是已发生的仿真事件；只有明确装配或有权政策应用才进入运行。运行时控制由操作者授权，经控制用例形成明确的系统触发，再使用run命令，不能给operator任意角色业务权限。

创建运行先在工作区保留稳定run_id及initializing登记，再由该run的初始化提交建立世界；成功后登记ready，失败记录failed/可核对状态。两个空间的持久步骤不能宣称同一原子事务，恢复按同一创建请求和run_id核对，不重复生成主体或把未装配实例视为活动世界。

`PrepareResult={kind:prepared,change:PreparedChange}|{kind:business_rejected,reason_code:string,checked_refs:List<Ref<BusinessObject>>}|{kind:needs_information,missing_fields:List<string>}|{kind:invalid_input,issues:List<FieldIssue>}|{kind:unsupported,capability_ref:Ref<Capability>}|{kind:technical_error,error:TechnicalFailure,retryability:retryable|non_retryable|unknown}`。prepare的结果尚未持久提交；业务拒绝需按原命令登记回执，不通过调用一次prepare就声明正式拒绝事实。一个用例需要多领域变化时收集多份PreparedChange，并声明必须同时成立的集合；不能只提交其中成功的一半。

一个成功命令可产生多个领域变化，但需要同时成立的变化必须一起提交。涉及外部结果的执行先登记意图，再按原身份核对实际发生，不能把数据库事务描述成覆盖外部世界的原子操作。详见[开发契约的提交边界](implementation_contracts.md#72-命令身份与一致提交)。

### 5.2 共用核心函数

| 目标函数与输入输出 | 调用关系、所有权及失败 |
|---|---|
| `core.register_invocation(ctx:InvocationContext, task:InvocationDraft, invocation_id:string) -> InvocationRegistration` | 宿主→技术任务登记；在workspace或已登记run控制空间持久登记DecisionTask/SystemTask/WorkspaceTask与命令身份、固定schema/权限；同ID同内容返回原登记，不创建业务WorkTask，不修改余额或时间 |
| `core.validate_action(ctx:ActionContext, input_schema:Ref<Schema>, input:该schema记录, output_schema:Ref<Schema>, result:ActionResult<该schema记录>) -> ValidationResult` | 角色宿主→校验器；纯检查返回字段/引用/choice约束，使用ctx的可信身份；结构通过不代表当前业务门控通过 |
| `core.bind_command(ctx:ActionContext, decision_ref:Ref<RecordedDecision>, binding_ref:Ref<CommandBinding>, command_id:string) -> BindingResult` | 宿主提供预先登记的ID；按动作与choice绑定命令，不调用另一个LLM改写决定；越权/无绑定返回诊断，不偷偷换分支 |
| `core.commit(command:CommandEnvelope<P>, preparations:List<PrepareResult>, writer_epoch:int) -> CommandAttemptResult` | 应用协调者→唯一提交协调者；最终权限/版本/业务排重和原子写集校验；核心独占正式提交记录。准备的业务拒绝按原身份登记拒绝回执；缺项/不支持/技术失败保留待办，不误登记为业务拒绝 |
| `core.commit_workspace(command:WorkspaceCommandEnvelope<P>, preparations:List<PrepareResult>, writer_epoch:int) -> CommandAttemptResult` | 工作区协调者→工作区提交存储；只提交该空间有权资料/配置/实验管理变化，使用本空间写入代次和序号；不得直接修改运行世界、已冻结情景或历史结果 |
| `core.read_receipt(ctx:ReadContext, command_id:string) -> ReceiptLookup` | 调用方超时核对原命令；纯读，不重新执行。必须检查读取者权限 |
| `core.record_decision(ctx:ActionContext, result:ActionResult<T>, provider_ref:Ref<DecisionProvider>, request_id:string) -> DecisionRecordResult` | 宿主登记采用输出及来源/内容摘要，属于技术和认知记录；不能因此改合同、余额或用途状态。同request_id异内容报冲突 |

`InvocationContext={data_space:{kind:workspace|run,id:string},principal_ref:Ref<Principal>,authorization_refs:List<Ref<Authorization>>,request_id:string}`；无需已存在的业务任务或仿真时点。`InvocationDraft={task_kind:decision|system|workspace,contract_ref:Ref<InvocationContract>,scope:Option<CommandScope>,input_schema_ref:Ref<Schema>,output_schema_ref:Ref<Schema>,input_basis_digest:string,command_ids:List<string>,parent_invocation_ref:Option<Ref<ActionInvocation>>}`；scope=null仅用于无业务scope的workspace技术准备。input_basis_digest固定已知来源、候选、映射与schema版本，无需先有依赖DecisionTask的完整角色Input；宿主装配Input后、提供者调用前另保存确切输入摘要及该任务引用。登记器绑定受信身份、允许的命令类型/字段及已有run初始化权；正文任意ID不能扩大权限。

`InvocationRegistration={kind:registered,invocation_ref:Ref<ActionInvocation>,task_ref:Ref<DecisionTask>|Ref<SystemTask>|Ref<WorkspaceTask>,command_ids:List<string>}|{kind:identity_conflict,invocation_id:string}|{kind:forbidden,reason_code:string}|{kind:technical_error,error:TechnicalFailure}`；登记结果不是业务命令回执。只有registered分支可进入需完整ActionContext/ServiceContext的后续准备。

`ValidationResult={valid:true,validated_schema_ref:Ref<Schema>}|{valid:false,issues:List<{field_path:string,code:string,expected:string}>}`；不以程序实现本身生成预期。业务条件另由拥有者在提交时核验。

`TechnicalFailure={kind:recorded,error_ref:Ref<TechnicalError>}|{kind:unrecorded,correlation_id:string,code:string}`。后者用于存储不可用等无法持久记录错误的情况，不冒充存在的对象引用。ActionResult、MethodResult、QueryResult、PrepareResult与核心调用的技术错误均通过error字段使用这一联合；不再在异常时返回未声明的第三种形状。保留原任务/命令身份供核对。

`BindingResult={kind:bound,command:CommandEnvelope<已登记命令payload>}|{kind:rejected,reason_code:string,field_paths:List<string>}|{kind:technical_error,error:TechnicalFailure}`。

`DecisionRecordResult={kind:recorded,decision_ref:Ref<RecordedDecision>}|{kind:identity_conflict,request_id:string}|{kind:technical_error,error:TechnicalFailure}`。

`PreparationBlock={kind:needs_information,missing_fields:List<string>}|{kind:invalid_input,issues:List<FieldIssue>}|{kind:unsupported,capability_ref:Ref<Capability>}`。

`CommandAttemptResult={kind:resolved,receipt:CommandReceipt}|{kind:blocked,command_id:string,blocks:List<PreparationBlock>}|{kind:failed_before_commit,command_id:string,error:TechnicalFailure,retryability:retryable|non_retryable|unknown}|{kind:pending,command_id:string}|{kind:unknown,command_id:string,error:TechnicalFailure}`。所有分支另含data_space，与原命令一致。blocked表示已知未就绪且未提交，不产生提交/拒绝事件；failed_before_commit须有证据证明本次失败前未执行正式提交。pending表示已知在处理；unknown表示不能确认结果。后三者不能替代持久业务拒绝。

核心先核对原命令身份与既有回执。无准备变化、无明确业务拒绝的空preparations不构成合法提交；写集拥有者、必要同时集合和payload摘要必须与原命令绑定。已有committed时返回原回执，不因为新一次准备缺项改写它；存在未决结果时先核对，不返回假定未发生的blocked或failed_before_commit。混合准备包含缺项、不支持或技术失败时不提交部分成功写集；确定的业务拒绝可以登记原命令拒绝回执，技术记录不冒充业务事实。

`ReceiptLookup={kind:found,receipt:CommandReceipt}|{kind:pending,command_id:string}|{kind:absent,command_id:string}|{kind:unavailable,command_id:string,reason_code:string}|{kind:forbidden,command_id:string}`。absent 仅表示在该查询一致性边界未找到；能否再执行须核对待派发登记与未决外部执行，不能仅因一次没查到就换命令ID。

`ExternalAttemptResult<T>={kind:completed,value:T,execution_id:string}|{kind:blocked,execution_id:string,issues:List<FieldIssue>}|{kind:failed_before_execution,execution_id:string,error:TechnicalFailure}|{kind:pending,execution_id:string}|{kind:unknown,execution_id:string,error:TechnicalFailure}`。仅用于确有外部/多步副作用的执行边界。failed_before_execution须能证明尚未派发，blocked也不能与未决旧派发并存；pending/unknown保留稳定原身份和核对入口，不能成为业务拒绝或重发许可。completed仅表示适配器取得可解释结果，是否执行/部分执行仍由T中的证据判断；实际资金后果仍需正式核对提交。

`CommandBinding` 登记 operation_id、choice、命令类型/schema、字段映射与授权条件；技术身份字段不从模型payload复制。候选输出校验失败允许保留错误并按任务协议重做决策，不允许解析器擅自选择最接近的有效候选。

## 6. 全部函数的登记标准

目标目录列跨模块能力及全部角色行为。实际编码时，**所有定义的函数和方法**均进入源码符号清单，包括私有辅助函数、UI handler、callback、adapter和后台worker；目标逻辑函数可以映射多个实现符号，不要求机械一对一。

| 登记项 | 必须写清的内容 |
|---|---|
| 身份与位置 | 稳定 function_id、目标契约、实际文件/符号/签名、可见性；未实现保持无绑定，不伪造行号 |
| 单一职责 | 做什么、明确不负责什么、关联规则/动作；辅助函数引用所属用例 |
| 输入 | 每个参数及其嵌套字段类型、必填、单位、范围、缺失含义、来源、可见性和版本 |
| 输出 | 返回联合的所有分支、字段含义、谁消费；对无返回副作用函数说明None/void及正式回执的取得途径 |
| 依赖与调用 | 上游调用者、下游函数/工具、所读状态、所需方法；不能只写“调用服务” |
| 副作用 | 纯计算/只读/准备/提交/外部执行/投影写入；精确到所拥有对象与入口，禁止全局隐式修改 |
| 失败 | 业务不满足、无候选、未知、权限/版本/单位错误、技术异常；调用方的等待/拒绝/核对路径 |
| 执行语义 | sync/async、业务时间与墙钟、资源使用、事务、业务/技术幂等键、随机输入和并发边界 |
| 检查 | 对应CHECK/样例与实际测试位置；正常、拒绝及关键恢复路径；方法正确性另有独立依据 |

纯私有帮助函数的记录可以很短，例如声明输入数值单位、返回值、纯计算、除零错误及所属方法；仍不能因为下划线命名而隐藏正式状态写入。匿名回调以所属符号与源码位置登记，可将简单表达式内联说明，不要求把每一行算式拆成接口。

实现绑定表使用 `function_id / contract_ref / source_symbol / input_schema_ref / output_schema_ref / caller_ids / callee_ids / effect_kind / owned_kinds / check_refs / status / evidence_refs`。schema文件是字段结构的机器主定义，MD维护语义、来源和不变量；实现后由schema生成字段参考并检查一致性，不人工维护两套不同的字段表。

### 6.1 HTTP、前端及事件绑定

| 边界 | 补充要求 |
|---|---|
| HTTP | endpoint/method、调用用例、请求/响应schema、认证与业务授权、状态码与领域结果映射、分页、版本/幂等传递。HTTP 200 不自动等于业务批准 |
| 前端 client | 对应一个登记用例；从界面输入到请求的校验、响应联合处理、取消/竞态和上下文失效明确；不得用界面默认值补缺失正式结果 |
| adapter/view model | 来源DTO与目标字段逐一映射，允许的格式/单位显示转换、未知显示、排序过滤；正式指标计算归结果层 |
| 事件消费者 | 事件版本、授权投影、可见时点、消费键、偏移/重试、失败队列、纠正信息处理；消息到达不代表业务被再次执行 |
| 外部模型/工具 | 输入裁剪、提供者/方法版本、预算、超时、结构校验和失败返回；供应方原始结构由adapter转换，不传播成领域类型 |

设计阶段不猜旧 URL 或为了表格给每个函数创建endpoint。确定绑定时补齐整个调用路径：页面操作→client→用例→领域prepare→core.commit→投影→页面；查询路径省略提交，不绕经动作决策。

## 7. 接口一致性与验收

函数能接收某种数据，不代表上游已经产生它。每条接线至少登记生产函数/动作、输出字段或对象schema、版本/范围/单位、授权可见时间、消费函数及其前置条件，见[项目交接表](../03_projects/collaboration_flow.md)。

| 情形 | 必须出现的可检查结果 |
|---|---|
| 上游合法输出交下游 | 同一对象版本、范围和单位可消费，不能靠下游LLM补出缺失正式字段 |
| 输出choice与payload不相容 | schema拒绝；不产生正式副作用 |
| 型别正确但选了不可见候选或无权操作 | 业务校验拒绝；不静默替换为另一个主体 |
| 两份成果使用不同依赖版本 | 标出依赖不相容或触发合法复核；不自动认为都是最新版 |
| 同命令ID、同内容重试 | 返回原处理结果或待核状态，不重复费用、资源、工程量或观察效果 |
| 同命令ID、不同内容 | identity_conflict；合法修订使用新身份与父引用，保留旧事实 |
| 提交后响应丢失 | 原command_id核对；不把未知当拒绝后再扣一次 |
| 模型输出解释“已获批”但没有有效批准引用 | 只保留为主张；流程不得放行 |
| 查询地图/Analysis、切换筛选 | 保持世界状态、账本、认知不变；读取版本和比较总体明确 |

契约覆盖检查包含：全部A动作有输入/分支输出定义；全部系统函数有签名、消费者和失败边界；类型/函数引用可解析；P01—P23与世界反馈链有生产消费映射；实际代码所有函数登记且无未声明写入。它们不替代工程公式、参数校准或现实政策效应验证。

尚未选择的模型通过明确profile/method依赖表达。未就绪功能保持unsupported/needs_information或未启用，不能把参数默认为0、概率设为1、随机通过率或固定时长后宣称契约完整。接口结构可以先明确，受研究选择影响的算法与取值须在启用前确定。
