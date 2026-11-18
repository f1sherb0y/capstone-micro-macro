# Government：法定事项、审查、许可与持续监管

定义政府机关在大湾区仿真中的咨询、受理、审查、决定、许可及持续监管行为。本文是角色开发规范；方法支持范围和待选参数见第 7 节，实现与验证证据单独记录。

[总体运行框架](../02_world/world_runtime.md) · [共同对象与状态](../02_world/domain_objects.md) · [跨主体交接](../03_projects/collaboration_flow.md) · [模型决策](../07_experiments/model_decisions.md)

<!-- page-nav:start -->
**本页导航**

[1. 职责、目标与权限](#1-职责目标与权限) · [2. 信息、状态与业务对象](#2-信息状态与业务对象) · [3. 行为卡与执行契约](#3-行为卡与执行契约)

[4. 专业工作与跨主体交互](#4-专业工作与跨主体交互) · [5. 状态转换、失败与恢复](#5-状态转换失败与恢复) · [6. 验收场景](#6-验收场景)

[7. 参数、方法与配置依赖](#7-参数方法与配置依赖)
<!-- page-nav:end -->

## 1. 职责、目标与权限

### 1.1 主体身份与授权

**GOV-001｜每个机关具有独立身份。** Government 是角色类别，不是能处理所有事项的全知政府。
每个实例记录 `agent_id`、组织/授权身份、组织所在地、独立的辖区与事项范围、适用项目类型及权限有效期间；申请方注册/经营地和项目地另列，机关维持自己的案件、资源与认知。
规划机关、建筑监管机关、专业审查机构、公共业主和资助方不因同属公共部门而共享全部权限。
同一组织兼具多种身份时，分别记录职能、经办权限和信息隔离；公共投资决策见 [Owner](owner.md)。

**GOV-002｜主管权限先于资源与评分。** 有权机关由适用制度和授权决定，不能由报价、关系评分或辖区匹配分替代。
有权但繁忙的机关应按规则排队或合法转介；无权但空闲的机关不能接替签发许可。
允许选择获认可审查服务方时，先核查认可范围，再处理服务选择；专业意见不自动取得行政决定效力。

| 维度 | 建议表达 | 不应默认 |
|---|---|---|
| 目标 | 职责内的安全、环境、公共利益、程序一致性和服务效率 | 批准越多越好或项目利润最大化 |
| 资源 | 可分配人员、专业能力、检查设备、工作日历和已占用容量 | 无限并发，或所有专业可互换 |
| 预算 | 若纳入研究，记录有来源的预算、授权用途及执行边界 | 申请费自动增加审查能力 |
| 裁量 | 仅在适用规则允许范围内安排审查、取证及作出决定 | 为达成功率目标忽略条件 |
| 信息 | 收到的材料、合法查询、核验结果和有权限的内部记录 | 企业全部现金、私有记忆和未发现缺陷 |

**GOV-003｜制度模板与机关判断分开。** 模板记录地区、事项、依据版本、适用条件、生效及过渡安排。
政策明文、机制推断和情景设定分别标记；未知条件不能填成统一常数，也不能视为无需办理。
法律条件、专业事实与主体判断分别保留；LLM 的理由或综合分数不能直接生成工程合格事实。

### 1.2 独立判断与经营取舍

| 自身考虑 | 职责内可作的选择 | 不由该目标替代的条件 |
|---|---|---|
| 安全、环境及公共利益 | 选择有依据的核验、检查和后续处置重点 | 法定/模板事项权限、证据门槛和程序；不凭“有益”直接批准 |
| 程序一致性与可解释性 | 对相同适用条件给出一致处理，说明差异理由 | 具体版本、案件范围和裁量依据；不能把不同程序混成统一评分 |
| 处理能力与服务效率 | 按适用依据安排人员、分工、协作和待办 | 人员专业、负荷和必要程序；提速目标不删除审查工作 |
| 持续监管与机构学习 | 从可见案件、投诉、复查和统计改善职责内工作 | 不默认启用内生政策，不用后验结果重写已作决定 |

**GOV-020｜机构目标不替代事项裁决。** 审批数量、处理速度、区域建设需求和服务缺口可成为观察或调度依据，但不能自动决定个案批准。对本机关而言，合理拒绝、等待补件、转介或限定范围许可都可能是有效履职结果，不能把全部项目通过设成运行成功标准。

机关可在权限内安排工作、请求证据、作出有依据的决定；不能替公共业主筹款或决定建设，也不能因收到申请费就增加自身授权或专业能力。
具体激励、评价指标权重、风险抽检机制与资源配置算法尚未选定，不预设任意机关均拥有同样裁量。

Government 持续管理职责、人员、案件、存续许可和现场检查；独立事项不由单一业主项目的下一阶段统一驱动。

## 2. 信息、状态与业务对象

### 2.1 可见信息与权限边界

**GOV-004｜案件、决定和许可分别存在。** 沿用 OBJ-009 的事项框架，避免另外维护一份项目正式状态。
案件可关联前期评估档案、项目、区段、工作包或用途；正式项目登记不是所有前期咨询的必要前提。
收件、受理、审查分派、专业意见、正式决定和有效许可分别关联 ID、版本及作用范围。
同一项目可有多个并行案件；一个案件的咨询意见不自动构成被咨询机关的另一项许可。

| 状态组 | 政府侧保存内容 |
|---|---|
| 权限与程序 | 有权事项、授权链、适用模板、来源与版本 |
| 案件处理 | 收件/受理、队列、分派、问题、补件回应、下一触发及责任 |
| 审查证据 | 申请方陈述、专业意见、检查结果、核实程度及尚未知内容 |
| 决定与许可 | 签发者、结论、范围、条件、生效/到期及后续改变 |
| 内部经营 | 人员排期、投入、待命、释放、内部风险判断及机构经验 |
| 通知与披露 | 可公开内容、受限材料、通知对象、发送/送达及获知时点 |

**GOV-005｜机关不是全知主体。** 模型隐藏真值、申请自报、已核实事实和内部推断分开保存。
材料齐全不等于真实；漏检、虚假陈述或风险发现若进入研究，须另设可验证的发生与发现机制。
公众参与、跨部门咨询或检查未建模时，要标出缺口；不能自动填入“无异议”或“已经检查”。

**GOV-006｜行政决定不依赖商业接受。** 有权主体依法/按模板决定，不以申请人或全部企业同意为生效前提。
机关决定经核心校验后改变相应案件、许可或监管事项，不直接改变合同价、现金、债务或完成工程量。
申请人撤回、修改或提出复审的资格由对应程序确定，Government 不代其形成商业意愿。

### 2.2 正式状态与私有判断的所有者

| 状态类别 | 机关自身维护 | 正式事实由谁提交 |
|---|---|---|
| 职责和程序引用 | 查询辖区、事项、授权、规则版本及有效期 | 有权制度/授权入口维护，机关不能凭自述扩大职责 |
| 内部风险与工作判断 | 调查重点、对材料可信性的估计、机构经验 | 私有认知入口，不能直接写入工程真值或正式违法结论 |
| 收件、问题与审查任务 | 版本清单、缺项、分派、问题回应及可见证据 | 核心验证身份、权限、版本及资源后形成案件/任务记录 |
| 决定、条件和许可 | 提出有依据的结论、范围、适用条件及通知 | 统一提交入口形成有效决定与许可状态；不依赖申请人商业接受 |
| 检查、处置与复查 | 检查计划、取得的证据、需回应事项及复查意见 | 检查/事项入口按授权提交；实际整改由施工或供货责任方执行 |
| 汇总与共享观察 | 查询案件数量、工作量、许可范围及聚合需求 | 从可见记录及统计版本派生，不另造一份全知项目或区域状态 |

**GOV-021｜案件身份贯穿收件与续办。** 一次提交的收件回执引用稳定案件或可追查的提交记录；补正、补件、转介及依法/按模板另案均关联来源。技术重试不能重复收费、重复受理或复制资源占用；申请撤回也不删除已发生的检查、费用和历史决定。

### 2.3 关键对象及字段

对象共同保留 ID、来源、版本、权限、业务去重键和发生/生效/获知时点；表中状态是需要表达的语义，不预设数据库结构或法定程序名称。

| 对象 | 最小语义字段 | 状态迁移及必须检查的边界 |
|---|---|---|
| 权限引用 `authority_ref` | 机关、事项、辖区、对象/签发范围、有效期、规则来源 | 有效/失效/待核按授权事实；交接机关不自动继承全部权限 |
| 案件 `case_id` | 申请人/代理、事项、项目或前期档案、范围、当前提交、程序版本 | 收到 → 待补正/受理 → 队列/审查/待回应 → 决定；拒绝、撤回、转介和技术待处理分别表示 |
| 提交 `submission_id/version` | 材料清单、签署、提交/接收时间、引用成果、替代范围 | 已接收 → 检查/被部分替代/作为历史依据；新上传不自动使全部旧材料失效 |
| 分派 `assignment_id` | 专业任务、案件版本、责任人、预留/投入窗口、等待原因 | 待分派 → 进行/暂停/待资料 → 完成或有效转交；每次资源变化可追查 |
| 问题/征询事项 | 要求依据、作用范围、回应方、证据、时钟及状态 | 待回应 → 回应待核 → 关闭/继续待补/有权升级；无回应不是自动同意 |
| 决定与许可 | 决定 ID、签发权、申请版本、区段/用途/动作、条件、效力依据、到期 | 决定已作与许可待生效/有效/受限制/失效分别保存；变更另有引用和生效范围 |
| 条件 `condition_id` | 许可引用、被约束动作、范围、责任方、核验者、证据和适用时间 | 待履行 → 待核 → 满足/未满足/需重查；开工前、使用前与持续条件分别门控 |
| 通知 `notice_id` | 决定引用、合法接收人、内容版本、发送/送达/获知状态与证据 | 待发送 → 已发送 → 已送达或送达未知/失败；法律效力按模板判断，不靠界面已读猜测 |
| 检查/整改/复查事项 | 依据、抽查/检查范围、取得证据、问题、责任方、措施及关联复查 | 已计划 → 实施/未能实施 → 发现/待查 → 整改待核 → 关闭或继续处置；未检查范围保持未知 |

## 3. 行为卡与执行契约

行为卡先说明触发、选择、正式后果及等待/失败，再定义函数、具名输入、输出分支、接收者和验收。执行矩阵汇总资源与交接。卡内“正式结果”指相应命令成功提交后的效果；`ActionResult.completed` 只表示本主体输出已形成。

<!-- action-nav:start -->
**动作定位**：[GOV-A01](#gov-a01--确认职责并回应前期咨询) · [GOV-A02](#gov-a02--收件完整性检查与受理) · [GOV-A03](#gov-a03--排队分派与续办) · [GOV-A04](#gov-a04--专业审查与证据核验) · [GOV-A05](#gov-a05--组织部门咨询与公众参与) · [GOV-A06](#gov-a06--提出补件要求并检查回应) · [GOV-A07](#gov-a07--作出并通知正式决定) · [GOV-A08](#gov-a08--核验条件并提供许可依据) · [GOV-A09](#gov-a09--处理变更到期续期与复审) · [GOV-A10](#gov-a10--安排施工检查与后续处置) · [GOV-A11](#gov-a11--审理使用事项并保留持续责任) · [GOV-A12](#gov-a12--分析反馈与提出可选制度调整)
<!-- action-nav:end -->

### GOV-A01 · 确认职责并回应前期咨询

- **触发与输入**：收到拟开展活动、事项适用性或提交要求的咨询，或发现转介请求。 输入为：需求简报与候选方案的版本、地点、拟议用途/范围、当前程序、咨询授权和已公开指引；未知技术细节保持待定。
- **自主选择**：说明本机关职责、指出有依据的资料要求、澄清或合法转介；无法确认时标记待查。
- **正式结果**：有范围、引用版本及依据的咨询答复、适用性判断或待查事项，说明信息缺口与更新触发；答复不自动生成许可或确认方案满足全部要求。
- **等待与失败**：不代 [Owner](owner.md) 决定是否投资，也不替专业方完成设计；不适用与适用性未知分别记录。

**函数与类型契约**

- **函数**：`roles.government.a01(ctx: ActionContext, input: GovA01Input) -> ActionResult<GovA01Payload>`。
- **输入记录**：`GovA01Input = {scope:ScopeRef; consultation_ref:Ref<ConsultationRequest>; brief_ref:Option<Ref<Brief>>; option_refs:List<Ref<DesignOption>>; matter_ref:Ref<RegulatoryMatter>; jurisdiction_ref:Ref<Jurisdiction>; procedure_ref:Option<Ref<Procedure>>; evidence_refs:List<Ref<Evidence>>}`。来源：申请/咨询人获权资料、已公开且适用的程序及本机关职责辖区。
- **输出分支**：`GovA01Payload` 的 `choice` 与分支必填字段为：`advise{advice:GovAdvice}; clarify{questions:List<GovQuestion>}; refer{recipient_id:EntityId<Agent>,basis_ref:Ref<Rule>,questions:List<GovQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`procedure_ref=null` 只表示尚未确认适用程序，仍可澄清或合法转介；不得为使咨询可调用而假造程序。未知适用性保留 unknown，确认适用/不适用必须有来源和本机关权限范围内的判断依据。
- **接收与核心效果**：交申请人或真正有权机关及咨询记录服务；仅登记程序意见，不生成许可/投资批准。
- **业务出口与验收**：适用性未知显式unknown，不当not_applicable；CHECK-GOV-001、CHECK-GOV-019、CHECK-GOV-020、CHECK-GOV-041。

### GOV-A02 · 收件、完整性检查与受理

- **触发与输入**：收到申请方或获授权代理的一次有效提交。 输入为：提交标识、资料版本、申请人注册/经营地与项目地、事项/辖区、申请资格/授权、签署及适用版本的受理要求。
- **自主选择**：收件确认、受理、列明缺项、按程序不予处理或转介；每种结果具有独立语义。
- **正式结果**：稳定案件 ID、提交版本、受理结果、理由、计时依据和下一待办。
- **等待与失败**：接口失败先核对是否已收件；不重复建案、收费，不把材料缺项当作实质审查拒绝。

**函数与类型契约**

- **函数**：`roles.government.a02(ctx: ActionContext, input: GovA02Input) -> ActionResult<GovA02Payload>`。
- **输入记录**：`GovA02Input = {scope:ScopeRef; submission_ref:Ref<Submission>; applicant_id:EntityId<Agent>; agency_authority_ref:Option<Ref<Authority>>; matter_ref:Ref<RegulatoryMatter>; jurisdiction_ref:Ref<Jurisdiction>; procedure_ref:Ref<Procedure>; prior_case_ref:Option<Ref<RegulatoryCase>>}`。来源：真实提交登记、申请/代理身份授权、适用受理程序和已有案件链。
- **输出分支**：`GovA02Payload` 的 `choice` 与分支必填字段为：`acknowledge{submission_ref:Ref<Submission>}; accept_for_processing{check:GovCompleteness}; request_correction{check:GovCompleteness,questions:List<GovQuestion>}; decline_processing{reason:string,basis_refs:List<Ref<Rule>>}; refer{recipient_id:EntityId<Agent>,basis_ref:Ref<Rule>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交案件/通知服务及申请人；核心分配/复用案件身份和收件时间；受理、收件与实质决定分开。
- **业务出口与验收**：未知收件结果先核对；无权限合法转介；CHECK-GOV-003、CHECK-GOV-006、CHECK-GOV-030。

### GOV-A03 · 排队、分派与续办

- **触发与输入**：已受理案件可进入审查，或收到补件、人员变动及合法优先处理依据。 输入为：本机关案件队列、专业要求、可用资源、日历及有效排序规则。
- **自主选择**：分配有能力且获授权的审查任务、保留队列、调整合法排期或请求协作。
- **正式结果**：任务范围、责任人、投入窗口、排队原因与资源预留/释放事件。
- **等待与失败**：同一案件复用仍有效分派；不能因人员已被本案占用而判定无资源续办，也不能无限占用。

**函数与类型契约**

- **函数**：`roles.government.a03(ctx: ActionContext, input: GovA03Input) -> ActionResult<GovA03Payload>`。
- **输入记录**：`GovA03Input = {scope:ScopeRef; case_ref:Ref<RegulatoryCase>; queue_ref:Ref<CaseQueue>; task_refs:List<Ref<Task>>; capacity_ref:Ref<ResourceCalendar>; ordering_profile_ref:Ref<QueueProfile>; existing_assignment_refs:List<Ref<ReviewAssignment>>}`。来源：本机关合法队列、专业条件、有效排序依据及真实人员排期。
- **输出分支**：`GovA03Payload` 的 `choice` 与分支必填字段为：`assign{plan:GovTaskPlan}; reprioritize{case_ref:Ref<RegulatoryCase>,priority_basis_ref:Ref<PriorityBasis>,plan:GovTaskPlan}; request_cooperation{questions:List<GovQuestion>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交任务/资源服务到A04；排队保留原因和触发，续办复用现有分派；不以机关空闲取得事项权限。
- **业务出口与验收**：无适任资源deferred并保留队列；CHECK-GOV-002、CHECK-GOV-004、CHECK-GOV-031。

### GOV-A04 · 专业审查与证据核验

- **触发与输入**：审查任务具备必要材料、资源和适用前置条件。 输入为：指定版本、专业意见、适用规则、已核实事实及职责内可查询信息。
- **自主选择**：形成符合/不符合/未知结论，请求核验、补充说明或提出决定建议。
- **正式结果**：有责任、范围、依据及核验程度的审查记录、问题和建议条件。
- **等待与失败**： [Architect](architect.md)、[Engineer](engineer.md)、[QS](qs.md) 的意见按各自职责接收；综合质量分不替代必要证据。

**函数与类型契约**

- **函数**：`roles.government.a04(ctx: ActionContext, input: GovA04Input) -> ActionResult<GovA04Payload>`。
- **输入记录**：`GovA04Input = {scope:ScopeRef; case_ref:Ref<RegulatoryCase>; submission_ref:Ref<Submission>; task_ref:Ref<Task>; rule_refs:List<Ref<Rule>>; professional_refs:List<Ref<Assessment>>; verified_evidence_refs:List<Ref<Evidence>>; method_result_refs:List<Ref<MethodResult>>}`。来源：指定提交版、实际可见专业意见、依法/模板可查证据和适用方法。
- **输出分支**：`GovA04Payload` 的 `choice` 与分支必填字段为：`assess{assessment:GovAssessment}; request_verification{questions:List<GovQuestion>,method_ref:Ref<Method>}; propose_conditions{assessment:GovAssessment,conditions:List<GovCondition>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交审查/问题服务，接A05/A06/A07；只有范围内符合/不符合/未知意见，未经签发不成为决定。
- **业务出口与验收**：不使用隐藏真值判申请；未支持检查unsupported；CHECK-GOV-005、CHECK-GOV-029、CHECK-GOV-032。

### GOV-A05 · 组织部门咨询与公众参与

- **触发与输入**：适用程序要求征询、公开，或审查发现需由其他有权单位处理的问题。 输入为：可披露资料、应咨询范围、问题、回复及程序状态。
- **自主选择**：发送职责明确的咨询、公开允许内容、登记意见、分析回应或转交有权机构。
- **正式结果**：咨询/公开记录、意见与回应关联、待解决分歧及对本案审查的影响。
- **等待与失败**：公众意见不是统一否决权；无回复、反对与咨询未完成分别处理，不虚构一致同意。

**函数与类型契约**

- **函数**：`roles.government.a05(ctx: ActionContext, input: GovA05Input) -> ActionResult<GovA05Payload>`。
- **输入记录**：`GovA05Input = {scope:ScopeRef; case_ref:Ref<RegulatoryCase>; consultation_rule_ref:Ref<Rule>; disclosure_package_ref:Ref<DisclosurePackage>; recipient_refs:List<Ref<ConsultationRecipient>>; prior_consultation_ref:Option<Ref<Consultation>>; response_refs:List<Ref<ConsultationResponse>>}`。来源：适用程序规定、可披露资料、登记咨询对象/公众渠道及真实收到的意见。
- **输出分支**：`GovA05Payload` 的 `choice` 与分支必填字段为：`initiate{draft:GovConsultation}; register_response{consultation_ref:Ref<Consultation>,response_refs:List<Ref<ConsultationResponse>>}; analyze{consultation_ref:Ref<Consultation>,assessment:GovAssessment}; refer{questions:List<GovQuestion>,recipient_id:EntityId<Agent>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交咨询/披露/通知服务、其他机关/授权公众渠道；登记送达和意见分别处理；不虚构住户Agent或一致同意。
- **业务出口与验收**：无回复保持等待；程序未建模unsupported不能填完成；CHECK-GOV-008、CHECK-GOV-017、CHECK-GOV-028、CHECK-GOV-046。

### GOV-A06 · 提出补件要求并检查回应

- **触发与输入**：完整性检查、技术审查或咨询形成明确缺项与问题。 输入为：问题、原提交版本、已完成检查、回应资料和适用时钟规则。
- **自主选择**：说明补件内容与依据、核对回应、关闭已解决问题、保留未解决问题或按程序处理延误。
- **正式结果**：问题及回应版本、完成状态、继续审查范围和调整后的下一触发。
- **等待与失败**：设计修改由专业方执行，Government 不代其改图；有效既有审查不必全部清零，实质改变按模板另案或复审。

**函数与类型契约**

- **函数**：`roles.government.a06(ctx: ActionContext, input: GovA06Input) -> ActionResult<GovA06Payload>`。
- **输入记录**：`GovA06Input = {scope:ScopeRef; case_ref:Ref<RegulatoryCase>; issue_refs:List<Ref<Issue>>; original_submission_ref:Ref<Submission>; response_refs:List<Ref<Response>>; current_submission_ref:Ref<Submission>; reusable_assessment_refs:List<Ref<Assessment>>; clock_rule_ref:Ref<ClockRule>}`。来源：具体缺项/规则、申请人响应、新材料及仍有效审查、程序时钟。
- **输出分支**：`GovA06Payload` 的 `choice` 与分支必填字段为：`request_supplement{questions:List<GovQuestion>}; verify_response{resolutions:List<GovIssueResolution>}; process_delay{issue_refs:List<Ref<Issue>>,basis_ref:Ref<Rule>,next_trigger_ref:Ref<Trigger>}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交问题/案件任务服务和申请人/专业作者；只关闭有复核证据的事项并重开受影响范围；不代专业修改成果。
- **业务出口与验收**：没有有据沉默后果不得默认拒绝/通过；CHECK-GOV-004、CHECK-GOV-032、CHECK-GOV-035。

### GOV-A07 · 作出并通知正式决定

- **触发与输入**：案件达到适用决定条件，或出现依法/按模板应予决定的事由。 输入为：现行申请版本、审查记录、未解决问题、适用权限和制度依据。
- **自主选择**：批准、附条件批准、拒绝或程序允许的押后，明确理由、范围及适用后续路径。
- **正式结果**：决定 ID、签发者、依据、条件、效力时点与通知；核心校验后生成已提交事实。
- **等待与失败**：技术故障、预算耗尽和无模型结果只是平台处理状态，不是机关拒绝；积极意见或临时回复不是正式许可。

**函数与类型契约**

- **函数**：`roles.government.a07(ctx: ActionContext, input: GovA07Input) -> ActionResult<GovA07Payload>`。
- **输入记录**：`GovA07Input = {scope:ScopeRef; case_ref:Ref<RegulatoryCase>; current_submission_ref:Ref<Submission>; assessment_refs:List<Ref<Assessment>>; unresolved_issue_refs:List<Ref<Issue>>; procedure_completion_ref:Option<Ref<ProcedureCompletion>>; decision_basis_ref:Ref<DecisionBasis>}`。来源：当前申请版、有效审查、必要程序完成证据与真实签发依据。
- **输出分支**：`GovA07Payload` 的 `choice` 与分支必填字段为：`approve{draft:GovDecision}; approve_with_conditions{draft:GovDecision}; refuse{draft:GovDecision}; defer_by_procedure{draft:GovDecision}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`procedure_completion_ref=null` 表示尚无全部必要程序完成记录。approve/approve_with_conditions 必须符合其各自决定程序，附条件批准不能豁免批准前必要条件；refuse/defer_by_procedure 按所引程序判断是否允许在审查未全部完成时作出，不机械要求先有批准路径的完成记录。
- **接收与核心效果**：交正式决定服务，再通知申请人/相关机构；核心生成决定ID、签发与效力记录，不要求申请人同意；批准不自动清偿费用或启动项目。
- **决定内容约束**：外层 choice 与 draft.outcome 必须一致；refuse/defer_by_procedure 不附带产生许可效力的条件或批准字段。附条件批准列明责任方、核验职能和受约束动作；决定不要求申请人接受，合同同意不能套用于行政决定。
- **业务出口与验收**：approve不得带未满足的批准必要条件；附条件/拒绝/押后均引独立依据；技术故障不用refuse；CHECK-GOV-006、CHECK-GOV-007、CHECK-GOV-034、CHECK-GOV-039。

### GOV-A08 · 核验条件并提供许可依据

- **触发与输入**：收到条件履行证据，或下游拟执行某一受许可约束的动作。 输入为：许可版本、作用范围、具体动作、到期情况、条件及相应证据。
- **自主选择**：有权核验满足/不满足/待查，要求补证，或按规则处理条件变更。
- **正式结果**：条件核验记录及本次范围的有效许可依据；由核心执行入口继续核查所有适用前置条件。
- **等待与失败**：未来承诺不是已履行；A 区段通过不覆盖 B，使用前条件不无依据地冻结全部前期活动。

**函数与类型契约**

- **函数**：`roles.government.a08(ctx: ActionContext, input: GovA08Input) -> ActionResult<GovA08Payload>`。
- **输入记录**：`GovA08Input = {scope:ScopeRef; permit_ref:Ref<Permit>; intended_action_ref:Ref<ActionDefinition>; condition_refs:List<Ref<PermitCondition>>; evidence_refs:List<Ref<Evidence>>; verification_rule_ref:Ref<Rule>}`。来源：许可及效力范围、下游拟执行动作、真实条件证据与核验规则。
- **输出分支**：`GovA08Payload` 的 `choice` 与分支必填字段为：`verify{results:List<GovConditionResult>}; request_evidence{questions:List<GovQuestion>}; request_condition_change{condition_ref:Ref<PermitCondition>,basis_refs:List<Ref<Rule>>,reason:string}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：核验可明确报告待查，不必先有成功核验结果；undetermined 不生成条件满足事件。确认满足/不满足必须对应真实规则和证据，技术失败沿 technical_error，不能作为不满足的事实。
- **接收与核心效果**：交许可条件/门控服务及对应责任方；核验只更新该条件的状态，核心还检查工程、资金、资源等前置，不授予全范围执行权。
- **业务出口与验收**：承诺不等于已履行，跨区依赖不因拆分绕过；CHECK-GOV-009、CHECK-GOV-010、CHECK-GOV-033。

### GOV-A09 · 处理变更、到期、续期与复审

- **触发与输入**：收到修改、续期或适用复审申请，发生到期事件或出现有依据的监管改变事由。 输入为：原决定/许可、受影响版本、事实证据、权限及程序要求。
- **自主选择**：确认覆盖范围、要求新案/复审、维持或按权限改变决定；有依据时暂停、撤销、恢复或续期。
- **正式结果**：关联事项、新决定或有效性变化、作用范围、生效时间及通知；保存原历史。
- **等待与失败**：新草稿、续期/复审申请不自动撤销、暂停或延长原效力；既定到期可由核心执行，无须伪造新主体决定。

**函数与类型契约**

- **函数**：`roles.government.a09(ctx: ActionContext, input: GovA09Input) -> ActionResult<GovA09Payload>`。
- **输入记录**：`GovA09Input = {scope:ScopeRef; application_ref:Option<Ref<RegulatoryApplication>>; prior_decision_ref:Ref<Decision>; permit_ref:Option<Ref<Permit>>; affected_submission_ref:Option<Ref<Submission>>; evidence_refs:List<Ref<Evidence>>; transition_rule_ref:Ref<Rule>}`。来源：续期/复审/修改请求、原许可及有效监管事由、既定效力规则。
- **输出分支**：`GovA09Payload` 的 `choice` 与分支必填字段为：`confirm_coverage{covered_scope:ScopeRef,basis_refs:List<Ref<Rule>>}; open_review{questions:List<GovQuestion>,review_basis_ref:Ref<Rule>}; renew{draft:GovDecision}; suspend{draft:GovDecision}; revoke{draft:GovDecision}; restore{draft:GovDecision}; record_scheduled_expiry{permit_ref:Ref<Permit>,expiry_rule_ref:Ref<Rule>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：`permit_ref=null` 只表示原决定没有产生许可，例如拒绝后的复审；仍可依规则 open_review，不能伪造许可。renew/suspend/revoke/restore及到期记录必须有实际适用许可或对应可变更决定，效力依程序限定；既定到期由核心触发，此动作只登记获知/引用，不重复改变效力。
- **接收与核心效果**：交案件/决定/效力服务后通知；维护历史和新效力时点；scheduled_expiry只是引用核心到期事实，不伪造新机关裁量。
- **业务出口与验收**：申请不等于自动延期/停效；CHECK-GOV-012、CHECK-GOV-014、CHECK-GOV-036、CHECK-GOV-043。

### GOV-A10 · 安排施工检查与后续处置

- **触发与输入**：适用检查节点、例行计划、收到有依据的异常报告或公众反馈。 输入为：许可范围、检查计划、可查询资料和现场取得的证据。
- **自主选择**：安排检查、记录发现、要求回应或复查；采取限制/停工等措施须有相应事项权限和适用依据。
- **正式结果**：检查范围、发现问题、责任接口、后续核验及有权处置，不直接修改工程质量真值。
- **等待与失败**： [Contractor](contractor.md) 与 [Supplier](supplier.md) 负责自身整改和证明；复查不等于自动消除缺陷或承担其费用。

**函数与类型契约**

- **函数**：`roles.government.a10(ctx: ActionContext, input: GovA10Input) -> ActionResult<GovA10Payload>`。
- **输入记录**：`GovA10Input = {scope:ScopeRef; inspection_basis_ref:Ref<Rule>; permit_ref:Option<Ref<Permit>>; task_ref:Ref<Task>; access_ref:Option<Ref<SiteAccess>>; observation_method_ref:Ref<Method>; observation_refs:List<Ref<Observation>>; prior_issue_refs:List<Ref<Issue>>}`。来源：获权监管检查任务、准入/观测方法和实际现场证据。
- **输出分支**：`GovA10Payload` 的 `choice` 与分支必填字段为：`plan{plan:GovTaskPlan}; report{assessment:GovAssessment,observation_refs:List<Ref<Observation>>}; require_response{questions:List<GovQuestion>}; order_measure{measure:GovMeasure}; recheck{resolutions:List<GovIssueResolution>}`。完整判别联合及局部类型规则见 §3.2。
- **分支依赖**：plan/require_response 可以在现场证据尚未取得时提出；report 仅覆盖实际观察，recheck 只关闭已复核范围。已有可用档案证据的合法措施按其依据处理，不把缺现场准入一概等同缺监管权；措施仍不可修改隐藏工程真值。
- **接收与核心效果**：交检查/问题或措施服务及Contractor/Supplier；措施有权生效后限制相应行动；整改仍由责任方执行，不直接改质量真值。
- **业务出口与验收**：无准入不能生成检查完成；部分抽查不覆盖全部；CHECK-GOV-013、CHECK-GOV-037。

### GOV-A11 · 审理使用事项并保留持续责任

- **触发与输入**：收到适用使用/占用申请，或使用期间出现归本机关处理的条件与监管事项。 输入为：实际完成范围、专业证明、试验/检查记录、现有许可和未解除条件。
- **自主选择**：安排核验、补件、限定范围决定或按程序持续检查；复用案件机制，不复用前案批准结论。
- **正式结果**：使用决定、适用区段/用途、条件及持续义务；完成个案后释放不再需要的审查资源。
- **等待与失败**：施工完成不自动产生使用许可；使用批准不等于业主接收、结清工程款或清偿 [Bank](bank.md) 债务。

**函数与类型契约**

- **函数**：`roles.government.a11(ctx: ActionContext, input: GovA11Input) -> ActionResult<GovA11Payload>`。
- **输入记录**：`GovA11Input = {scope:ScopeRef; case_ref:Ref<RegulatoryCase>; use_application_ref:Ref<RegulatoryApplication>; completed_scope_refs:List<Ref<WorkFact>>; professional_proof_refs:List<Ref<Assessment>>; test_result_refs:List<Ref<MethodResult>>; permit_refs:List<Ref<Permit>>; remaining_condition_refs:List<Ref<PermitCondition>>; procedure_ref:Ref<Procedure>}`。来源：实际完工范围、所需专业/试验/检查证明及独立使用程序。
- **输出分支**：`GovA11Payload` 的 `choice` 与分支必填字段为：`request_evidence{questions:List<GovQuestion>}; plan_verification{plan:GovTaskPlan}; propose_use_decision{draft:GovDecision}; continue_supervision{condition_refs:List<Ref<PermitCondition>>,plan:GovTaskPlan}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：决定复用A07有权签发链；持续监管交A10；只处理使用许可/条件和相应资源释放，不自动实际交付、增加可用存量或清偿贷款。
- **业务出口与验收**：前案批准不代当前核验，运行结束仍保留持续条件；CHECK-GOV-011、CHECK-GOV-018、CHECK-GOV-038、CHECK-GOV-040。

### GOV-A12 · 分析反馈与提出可选制度调整

- **触发与输入**：收到合规投诉、案件经验或观察到权限内的监管信号；政策调整仅在场景显式启用时进入候选。 输入为：合法可见且注明来源的记录、统计口径、观察滞后及自身授权。
- **自主选择**：记录/核实反馈、调整权限内工作安排、提出制度建议；正式政策改变另验权限和程序。
- **正式结果**：反馈事项、观察或政策提案；启用调控时另记正式规则版本、发布/生效/过渡安排及作用入口。
- **等待与失败**：投诉不是已证实违法；发布指引文字不自动改法定条件，不能直接调高项目绩效以制造政策效果。

**函数与类型契约**

- **函数**：`roles.government.a12(ctx: ActionContext, input: GovA12Input) -> ActionResult<GovA12Payload>`。
- **输入记录**：`GovA12Input = {scope:ScopeRef; feedback_refs:List<Ref<Feedback>>; visible_statistic_refs:List<Ref<Statistic>>; observation_profile_ref:Ref<ObservationProfile>; working_authority_ref:Ref<Authority>; policy_control_profile_ref:Option<Ref<PolicyControlProfile>>}`。来源：可见案件/投诉/聚合需求，保留观测滞后、统计范围和本机关权限。
- **输出分支**：`GovA12Payload` 的 `choice` 与分支必填字段为：`record_feedback{feedback_refs:List<Ref<Feedback>>,interpretation:string}; investigate{questions:List<GovQuestion>,request:GovTaskRequest}; change_work_arrangement{plan:GovTaskPlan,basis_ref:Ref<Authority>}; propose_policy{proposal:GovPolicyProposal}`。完整判别联合及局部类型规则见 §3.2。
- **接收与核心效果**：交监管反馈/工作安排服务或政策提案入口；政策提案须另走量化、校验、冻结及发布生效链；不直接写政策参数、Owner项目/预算或绩效。
- **业务出口与验收**：缺报不填零，未启用内生政策只能保留建议；CHECK-GOV-016、CHECK-GOV-024、CHECK-GOV-025、CHECK-GOV-026、CHECK-GOV-027、CHECK-GOV-044、CHECK-GOV-045。

### 3.1 全行为执行与交接矩阵

| 行为 | 必要输入 | 可选动作 | 经校验的正式结果 | 时间与资源 | 失败/等待及交接 |
|---|---|---|---|---|---|
| GOV-A01 前期咨询 | 咨询事项、候选范围、资料版本和权限 | 答复、待查、补充或合法转介 | 有范围/依据的程序信息和适用性意见 | 咨询任务与观察时点 | 未知不记许可；交申请人或实际有权机关 |
| GOV-A02 收件受理 | 提交标识、资格/代理授权、签署和所需材料 | 收件、受理、补正、按程序不予处理 | 档案、回执、完整性结果及受理状态 | 收件/受理分别记时，消耗登记检查资源 | 技术未知先核对；缺件交申请人补正，不写实质审查拒绝 |
| GOV-A03 排队分派 | 有权待办、专业需求、已有分派和人员日历 | 排队、分派、合法调整或协作 | 有范围的审查任务和资源窗口 | 等待和实际投入分开 | 无适合人员保持有原因的队列；续办复用有效占用 |
| GOV-A04 证据审查 | 指定申请版本、适用规则、专业资料 | 核验、提问题、形成符合/不符合/未知意见 | 范围化审查记录及决定建议 | 审查投入与所需外部证据分别记录 | 不完整交补件或核验；专业意见不自动变成许可 |
| GOV-A05 部门/公众咨询 | 适用征询要求、可披露资料及对象 | 发出、登记、分析回应或转介 | 咨询事项、意见关联及程序状态 | 征询期间按具体程序，非模型发言次数 | 未回复/反对/不适用分别处理；不能虚构公众参与完成 |
| GOV-A06 补件续审 | 问题 ID、原检查、回应及新材料版本 | 核对、关闭问题、继续补充或按规则处置 | 回应与受影响审查范围、下一待办 | 是否暂停/重启计时由程序确定 | 重开受影响范围，保留有效部分；向专业方/申请人交接 |
| GOV-A07 正式决定 | 当前有效申请、必要程序、证据和签发权 | 批准、附条件、拒绝或有依据押后 | 决定、范围、条件、效力依据和通知任务 | 决定时点、效力时点和送达时点分列 | 未达门槛继续对应待办；无模型结果不生成行政拒绝 |
| GOV-A08 条件核验 | 许可版本、拟执行范围、条件证据 | 核验满足/不满足/待查，按权处理变化 | 本范围的条件状态和许可依据 | 每项核验有任务/证据时点 | 未满足只约束相关动作，交实际责任方补证及核心执行门控 |
| GOV-A09 效力变动 | 修改/续期/复审申请、原决定及新事实 | 确认覆盖、复审、续期或有权限制/恢复 | 关联事项及适用范围的新版本/状态 | 申请、到期、决定、生效分别调度 | 提交申请不自动续期或停效；依原有效状态处理下游 |
| GOV-A10 检查整改 | 检查依据、范围、人员、现场证据 | 检查、通知整改、复查及有权处置 | 发现、问题、措施及后续事项 | 检查与整改投入分别属于各责任方 | 无法取得证据保留待核；整改通知不直接消除缺陷 |
| GOV-A11 使用与持续监管 | 实际完成范围、必要证明和适用使用条件 | 补充、检查、限定范围决定或后续监管 | 使用许可/决定及持续条件，个案资源按范围释放 | 使用事项独立计时，持续责任继续存在 | 许可不代替交付/收款；向核心及有权接收方提供依据 |
| GOV-A12 反馈与建议 | 可见案件/投诉/区域统计及自身权限 | 核实、报告、工作调整、制度建议 | 反馈记录或有权工作安排；政策改变另验条件 | 获知后处理，不回溯注入过去审查 | 未启用自主政策时保留建议；对接职责内部门与公共业主 |

### 3.2 输入输出类型与提交边界

本节与每张行为卡共同构成函数契约。所有签名是目标开发接口，不表示已有同名函数或方法已实现。完整公共类型见[接口契约](../06_engineering/interface_contracts.md)。

- `ActionContext.task_ref` 标识宿主登记的本次决策调用任务；业务工作任务由各 Input 的 `task_ref/task_refs` 明确引用，两者不能互换。首次机会评估或工作申请不要求尚未创建的业务任务。
- 每个 `Input` 为封闭记录，均包含 `scope:ScopeRef`，加本卡列明字段；前期工作允许 `assessment_case`，不要求虚构项目。经营/发现行为可用 `organization`。身份、职能、授权、可见版本和候选由 `ActionContext` 绑定，不接受主体在输入里自行增权。
- 本卡写作 `choice{fields}` 的每一项表示独立分支 `{choice:"choice",fields...}`；合起来就是对应具名 `Payload` 的完整判别联合。各分支另共同包含 `scope:ScopeRef` 和 `note:Option<string>`。未声明字段禁止出现；不得在拒绝分支夹带接受、金额、资源占用或批准字段。
- `Option<T>` 可空且键仍存在，其他字段必填。输入列表为空只表示当前已获准可见的集合没有记录，不证明世界上不存在该事实；必需资料的覆盖另由要求清单核验。分支所需接收者、申请依据、实际方案/任务及费用条款不得为空。宿主无法装配必填输入时登记 `needs_information`；错误类型/漏键先走结构校验。`scope` 必须落在授权范围内且与输入对象一致。
- `completed(payload)` 仅表示行为输出完成。其后由应用服务拆分并提交必要原子命令，由核心回执确认正式效果；多条命令不默认为一个已全部成功的事务。接收者收到的是获授权的已提交对象投影。技术错误走 `technical_error`，业务拒绝是 `payload.choice`，资源/业务等待走 `deferred`；方法不支持走 `unsupported`，可独立完成的有限报告仍保留未覆盖项。
- 空值语义固定：`prior_*`/`parent_*` 表示没有适用前序；可空授权/签署/独立性依据表示当前没有可用记录，依赖该依据的分支必须返回缺项或权限拒绝；可空方法结果表示尚无适用执行结果，不能填通过；`learning_profile_ref=null` 表示没有启用学习规则。已知数值缺失仍用 `ValueState`，不能挪用空值或空列表表达零。本角色 `brief_ref=null` 仅指本咨询未引用简报，`application_ref=null` 仅用于无新申请的既定到期/监管触发，`access_ref=null` 指尚未取得准入，`expiry_rule_ref=null` 指该决定没有登记到期规则，`due_rule_ref=null` 指没有有据时限；这些空值不能补成默认期限或已获准入。
- `Ref<MethodResult>` 指已登记的具体方法执行记录（输入版本、方法版本、输出 schema、结果及来源），不是未提交的通用 `MethodResult<T>` 返回信封；需要使用其数值时先校验执行成功、支持范围和用途。输出中所有新引用均须可解析；尚未存在的对象使用本节封闭草案记录交责任服务创建。
- 文本用于解释、问答及专业理由。会影响后续门控的用途、数量、条件、缺项和受影响范围必须使用字段/引用表达。所有数值输出来自适用计算/观察方法；纯登记、转送、排期执行和去重可由确定性程序处理，不强制调用 LLM。
- 对尚未执行的数值计算、量取、观测或检查，先保留候选/问题并安排获授权方法执行；方法执行记录保存后，宿主才能在下一次装配中提供可解析引用。一个行为可由多个函数协作完成，不把一次模型回复等同全部任务执行。有限报告完成与其所评对象满足要求分别验收。
- 下表 `Ref<K>` 的 K 为有版本对象类别，含义由本角色 §2.3、§4 及[共同对象](../02_world/domain_objects.md)约束；不是自由附件或任意字典。已有对象的相容投影可以只读复用；尚未登记的准备对象须先由其责任服务创建并绑定 schema/method/profile，禁止编造一个引用绕过缺失实现。正式 `EntityId<K>` 由核心创建；草案内局部行键不能冒充正式业务 ID。

| 局部类型 | 完整字段或封闭取值 |
|---|---|
| `GovQuestion` | `scope:ScopeRef; target_refs:List<Ref<EvidenceTarget>>; question:string; recipient_refs:List<Ref<RegulatoryRecipient>>; requirement_ref:Ref<Rule>; response_requirement_ref:Ref<ResponseRequirement>; evidence_refs:List<Ref<Evidence>>`；问题必须有明确范围和要求依据，不能凭文字添加法定门槛 |
| `GovTaskRequest` | `scope:ScopeRef; purpose:preparation/service_delivery/investigation/training/remedy/policy_evaluation; input_refs:List<Ref<BusinessObject>>; output_requirement_refs:List<Ref<DeliverableRequirement>>; work_profile_ref:Option<Ref<WorkProfile>>; effort_estimate:ValueState<Measured>; desired_window:ValueState<TimeWindow>; authority_basis_refs:List<Ref<Authority>>; dependency_refs:List<Ref<Dependency>>; questions:List<GovQuestion>`；申请尚未创建的业务工作，不含虚构任务 ID；purpose 只可选本动作授权子集，正常报价容量使用 service_delivery，不因枚举存在而获得其他职能。估计引用受支持方法，未知保留。`work_profile_ref=null` 只表示未取得可执行工作方法，允许申请但不执行。经有权确认后创建业务 Task，再编制 TaskPlan；提交申请不占用资源、不形成收费 |
| `GovTaskPlan` | `work_profile_ref:Ref<WorkProfile>; items:List<{task_ref:Ref<Task>,resource_ids:List<EntityId<Resource>>,window:TimeWindow,effort:Measured,dependency_refs:List<Ref<Dependency>>,existing_assignment_ref:Option<Ref<ReviewAssignment>>}>`；分派只针对已获授权任务，审查与行政等待分别计时 |
| `GovAdvice` | `matter_ref:Ref<RegulatoryMatter>; jurisdiction_ref:Ref<Jurisdiction>; applicability:applicable/not_applicable/unknown; basis_refs:List<Ref<Rule>>; information_requirement_refs:List<Ref<InformationRequirement>>; known_gap_questions:List<GovQuestion>; update_trigger_refs:List<Ref<Trigger>>; explanation:string` |
| `GovCompleteness` | `submission_ref:Ref<Submission>; procedure_ref:Ref<Procedure>; checked_requirement_refs:List<Ref<InformationRequirement>>; missing_requirement_refs:List<Ref<InformationRequirement>>; unresolved_questions:List<GovQuestion>; scope:ScopeRef`；完整性通过不能填实质符合性结论 |
| `GovAssessment` | `target_ref:Ref<Submission> 或 Ref<RegulatoryCase> 或 Ref<Inspection> 或 Ref<Observation>; task_ref:Ref<Task>; checks:List<{rule_ref:Ref<Rule>,covered_scope:ScopeRef,evidence_refs:List<Ref<Evidence>>,method_result_ref:Option<Ref<MethodResult>>,finding:conforms/nonconforms/unknown/not_applicable}>; proposed_questions:List<GovQuestion>; explanation:string`；`not_applicable` 也需适用性依据，方法未执行不能填 `conforms` |
| `GovCondition` | `condition_rule_ref:Ref<Rule>; covered_scope:ScopeRef; responsible_party_ids:List<EntityId<Agent>>; verifier_binding_ref:Ref<FunctionAssignment>; affected_action_refs:List<Ref<ActionDefinition>>; required_evidence_refs:List<Ref<EvidenceRequirement>>; verification_method_ref:Ref<Method>; due_rule_ref:Option<Ref<ClockRule>>`；责任方、核验职能及被约束动作必须有确定绑定；没有证据的时限保持空，不由模型填固定天数 |
| `GovConsultation` | `case_ref:Ref<RegulatoryCase>; procedure_ref:Ref<Procedure>; disclosure_package_ref:Ref<DisclosurePackage>; recipient_refs:List<Ref<ConsultationRecipient>>; questions:List<GovQuestion>; clock_rule_ref:Ref<ClockRule>`；公众渠道是程序对象，不要求增加需求侧智能体 |
| `GovIssueResolution` | `issue_ref:Ref<Issue>; response_refs:List<Ref<Response>>; verification_result_ref:Option<Ref<MethodResult>>; resolution:resolved/partially_resolved/unresolved; retained_requirement_refs:List<Ref<InformationRequirement>>; affected_assessment_refs:List<Ref<Assessment>>; reusable_assessment_refs:List<Ref<Assessment>>`；verification_result_ref=null 表示尚无本次适用核验结果，此时只能 unresolved；resolved/partially_resolved 必须有成功核验及明确覆盖，保留未满足要求。受影响与可复用部分按范围/版本区分，不能对同一部分同时声明失效和有效 |
| `GovDecision` | `outcome:approve/approve_with_conditions/refuse/defer_by_procedure/renew/suspend/revoke/restore; case_ref:Ref<RegulatoryCase>; submission_ref:Ref<Submission>; covered_scope:ScopeRef; decision_basis_ref:Ref<DecisionBasis>; assessment_refs:List<Ref<Assessment>>; conditions:List<GovCondition>; reason:string; effect_rule_ref:Ref<EffectRule>; expiry_rule_ref:Option<Ref<ClockRule>>; notification_recipient_ids:List<EntityId<Agent>>; prior_decision_ref:Option<Ref<Decision>>; next_procedure_refs:List<Ref<Procedure>>`；A07/A09 的 `outcome` 必须与外层同名 `choice` 一致；A11 的使用决定只允许前四种值。新决定 ID、签发者及已生效状态只由核心生成 |
| `GovConditionResult` | `condition_ref:Ref<PermitCondition>; action_ref:Ref<ActionDefinition>; covered_scope:ScopeRef; result:satisfied/not_satisfied/undetermined; evidence_refs:List<Ref<Evidence>>; verification_result_ref:Option<Ref<MethodResult>>; remaining_questions:List<GovQuestion>`；verification_result_ref=null 表示尚无本次适用核验结果，此时只能 undetermined；satisfied/not_satisfied 须有成功执行、范围一致的核验依据，结果不覆盖其他范围或前置 |
| `GovMeasure` | `measure_type_ref:Ref<RegulatoryMeasureType>; authority_basis_ref:Ref<Authority>; rule_ref:Ref<Rule>; affected_scope:ScopeRef; affected_action_refs:List<Ref<ActionDefinition>>; evidence_refs:List<Ref<Evidence>>; effect_rule_ref:Ref<EffectRule>; review_trigger_ref:Ref<Trigger>; recipient_ids:List<EntityId<Agent>>`；仅允许该权限/程序目录内措施，不开放任意停工字符串 |
| `GovPolicyProposal` | `issue_refs:List<Ref<Feedback>>; statistic_refs:List<Ref<Statistic>>; observation_profile_ref:Ref<ObservationProfile>; proposed_instrument_refs:List<Ref<PolicyInstrument>>; target_scope:ScopeRef; mechanism_hypothesis:string; evidence_refs:List<Ref<Evidence>>; evaluation_request:GovTaskRequest`；字段表达提案，不包含可绕过政策量化和有效性检查的任意参数写入 |

## 4. 专业工作与跨主体交互

### 4.1 事项时间与跨主体接口

**GOV-007｜行政时间与计算时间分开。** 收件、受理、入队、开审、补件、决定、生效及通知分别记时。
排队等待、审查投入、申请回应和重叠历时分别统计；模型调用毫秒数不是行政或工程等待时间。
补件是否暂停/重启计时由程序说明；法定时限、服务目标及情景处理时长分开，未知超时后果不默认批准或拒绝。

**GOV-008｜多事项按依赖协调。** 依赖决定、征询意见与可并行关系分别建模，牵头机关不自动拥有全部签发权。
发现循环依赖时记录事项和条件，按有依据的程序澄清；不能自行删前置条件使流程成功。
资金、施工人员、场地与技术放行由对应执行入口检查；Government 只提供自己有权确认的依据。

**GOV-009｜版本与效力不追溯覆盖。** 决定绑定提交、范围和程序版本；变更先识别受影响部分。
新草稿不直接作废旧许可，拟采用新方案时重新检查覆盖；规则变化按生效和过渡安排处理，保留历史事实。
**GOV-010｜通知不等于生效。** 按模板分别记录正式生效、发送/送达和主体获知时点。
核心不能因主体尚未知情而允许已被有效禁止的动作；反馈只给该主体允许获知的信息。

| 角色接口 | Government 接收 | Government 提供；不代行的决定 |
|---|---|---|
| [Owner](owner.md) | 有权限的咨询、申请、回应或后续请求 | 本机关程序与决定；不代投资、接受合同或撤回申请 |
| [Architect](architect.md) / [Engineer](engineer.md) | 有资格及委任依据的设计、专业证明和回应 | 审查问题与决定；不代专业设计和签署 |
| [QS](qs.md) | 事项适用范围内的成本/计量证据 | 监管反馈；不裁定全部合同计价或付款 |
| [Contractor](contractor.md) / [Supplier](supplier.md) | 有权提交的施工、产品、检查与整改证据 | 有范围的监管要求；不代生产、履约或整改 |
| [Bank](bank.md) | 有授权的查询及融资相关证明请求 | 允许披露的许可状态；不代授信、提款和收债 |

### 4.2 辖区、事项与政策作用

大湾区研究不意味着各地区具有同一审批链、许可类型或政策生效方式。机关标签只说明角色；每个可执行动作仍须定位到明确地域、事项、对象、授权和制度版本。

政策文本→机制→参数→情景的准备流程见 [政策量化](../05_policy/quantification.md)，各工具的任务、期限、能力与资金契约见 [工具目录](../05_policy/instrument_catalog.md)。量化工作台属于研究与配置准备，不赋予本角色新增权力。Government 执行自己的有权事项；规定期限、实际工作能力和真实办理结果分开，补助还须另有拨付权限/来源。政策工具不能越过本文件的独立案件决定或自动开启内生调控。

**GOV-029｜机关辖区、组织所在地与项目地分别核对。** 机关办公/组织所在地不能替代法定或场景明示的辖区与事项权限；申请主体注册地、经营地和项目地也不互相替代。辖区可能覆盖特定区域、设施或事项范围，不能只凭同城、距离或地区分数选审批者。一个项目可同时触发不同有权机关的事项；协调或牵头关系不自动吸收其他机关的决定权。

| 对象或关系 | 建议最小语义 | 校验目的 |
|---|---|---|
| 机关身份与授权 | `authority_id`、组织、职能、授权来源/版本、有效期间 | 判断可收件、审查、决定、检查或发布哪类内容 |
| 辖区与事项覆盖 | `jurisdiction_ref`、`matter_type`、项目/活动类别及范围 | 地理范围与事项同时匹配；空闲不是权限，辖区相交不是授权相同 |
| 申请主体与代理 | 实际申请人、注册/经营地、代理、签署与授权引用 | 跨地区身份适用性有据，不由单一地区字段替代 |
| 项目/候选与成果 | 项目地、场地/区段、用途/活动、提交版本、专业成果引用 | 区分候选咨询与正式申请，定位受审对象及变更范围 |
| 程序模板 | 事项、适用条件、依赖关系、版本、生效/过渡及来源类别 | 只执行已选且有依据的流程，不补造统一期限或全湾区许可 |
| 政策作用记录 | 发布主体、政策版本、适用范围、发布/生效/失效、过渡条件与作用入口 | 区分政策文本、正式规则、资金机制与主体已获知的观察 |
| 通知与观察 | 接收对象/权限、公开范围、发送/送达、`known_at`、观察版本 | 发布不等于每个主体已读；保密材料不随跨部门协作全量公开 |

上述字段为共同对象的引用语义：案件/许可仍由 OBJ-009 维护，政策和观察使用各自权威记录，不在本角色内复制世界规则。身份或地点缺失不能自动取机关所在地，也不能被 LLM 补成已确认事实。

| 行为节点 | 机关可见输入与决定 | 正式结果 | 不具备条件时 |
|---|---|---|---|
| A01 职责咨询 | 候选地、用途、活动范围、已知身份及当前模板；判断可答复、需澄清或可转介 | 范围明确的程序答复/待查事项，可列多个独立主管事项 | 主管未知保留待确认；不指定无权替代者，不发许可 |
| A02/A03 收件与调度 | 事项覆盖、申请/代理资格、提交版本及本机关资源；分别决定收件、受理和排队 | 稳定提交/案件与资源任务；有依据的转介保留身份链 | 不属职责说明原因/接续路径；缺资料与繁忙分别等待，不变成同一种拒绝 |
| A04—A08 审查与许可 | 对该范围有效的制度、证据、专业意见和条件；决定补件、拒绝或合法限定范围许可 | 有签发者、范围、版本、条件与效力的决定；通知按权限送达 | 其他机关事项未满足时保持对应依赖；一个许可不代替全部开工条件 |
| A09—A11 变更、检查和使用 | 改址/改用途/改方案、有效许可及现场证据；判断续审、另案、检查或有权处置 | 只修改实际授权范围，明确原效力、后续依赖和可恢复条件 | 新申请不自动延期；转地区不带走原许可，原案费用和持续义务按规则处理 |
| A12 反馈与制度建议 | 职责内可见案件和地区 × 用途统计、口径、时点及政策权限；选择报告、调查或建议 | 观察/报告/提案进入有权接收方，不改变政策、许可或资金余额 | 自主调控未启用就保留建议；不能把市场信号直接提交成正式新政策 |

**GOV-030｜政策发布、生效、过渡与被获知是不同事实。** 每项政策明确谁有权发布、作用于哪些地区/主体/用途/事项、何时公布与生效、如何处理在途申请和存续许可。各主体只用其获知时点之前的可见资料作判断；制度正式生效可以改变适用规则，但不能伪造所有主体已经收到通知或预知变化。公告、个案决定和收费/资助执行不能混成一个“政策已应用”标记。

模板缺少过渡条款时，应列为待确定的适用性问题，不自动选择全部追溯适用或全部永久豁免。规则版本改变只重审受影响事项；规则本身、引用它的案件决定与实际工程结果各有提交依据。

**GOV-031｜需求和市场反馈不自动赋予调控权。** 地区 × 用途需求、存量、在建以及案件堵点可以触发本机关职责内的观察、工作安排和建议。公共服务建设仍由相应 Owner 评估及投资，融资由 Bank 独立判断。研究政策怎样促成项目，不等于启用 Government 自主制定政策；内生政策仍按 D-08 明确工具、权限、观察滞后、程序和实验边界后才可实施。

**GOV-032｜跨机关协作保留各自权限与证据范围。** 转介、征询、委托审查和联合事项分别声明接收者、问题、可披露材料、责任及返回要求。接收回执不等于审查同意；被征询方未回复不能填成无异议。若未建模公众参与、跨部门确认或某种实地检查，应记录覆盖缺口，不能虚构已完成以推进项目。

首批地区/事项映射、资格与授权来源、许可分割条件及政策生效/过渡模板仍待选择。这里不给出真实法定时限、统一审批概率、默认收费或普适法律判断；采用现实规则时须另外核验相应地域、事项和时点的依据。

### 4.3 前期咨询与资金接口

前期分工由 Owner 提出目的、候选地区、规模区间及期望交期，专业与供应方再细化方案；Government 在有权事项内提供适用性/程序信息。基础账本覆盖现金、应收应付、贷款和到期义务，但政府机构预算、收费、减免及归集账户的具体机制仍需选定模板，以下是设计建议。

**GOV-013｜咨询对象与正式事项分开。** 前期输入可以只有范围和候选，不要求已经取得全部设计与许可才能咨询。答复关联 `owner_case_id`、`brief_id/brief_version`、适用的 `option_id/option_version`、咨询事项、权限和来源；说明已知、未知、不适用及需要进一步核查的内容。

有依据的适用要求可以改变候选条件；“暂时不知道”不能自动当作禁止，也不能当作批准。需求或技术范围变更后检查原答复是否仍覆盖；未经程序确认，不把旧咨询的积极意见当作新方案许可。咨询次数、答复期限与费用不得凭空编造。

**GOV-014｜费用沿有权义务和实际账户处理。** 费用申请/核定、到期、实际支付和退款分别引用 OBJ-011/012。缴费人、收费权依据和真正收款方明确，款项可能归指定收款机构或外部财政账户，不因本机关经办就默认增加其可支配资金；用途限制按所选模板表达。

一次支付指令或回执重复到达只记一次；退费和有权减免关联原记录，已经发生的资金变动不能通过删除案件消失。支付费用是否为受理或后续处理条件须有依据，不把缴费完成写成审批通过。工作人员投入、机构预算、申请收费和项目工程成本分别有归属，不默认为同一资金来源。

**GOV-015｜公共建设资金不从监管身份自动产生。** 公共业主的投资、拨款申请及付款走其 Owner 授权和对应账本；监管案件通过不自动增加公共业主预算。补助、拨款、罚款或其他资金机制未在模板内定义时保留未覆盖，不用政策文字直接改正式余额。制度调整权限仍按 D-08 处理，最小账本确认不启用新的政策或处罚职能。

### 4.4 地区与用途的需求观察

需求侧按“地区 × 用途”表示需求与存量，不建模住户、使用企业等需求侧智能体。Government 可以在职能授权范围内读取相关聚合观察，具体指标、函数、阈值和更新频率须由所选方法明确，不设置隐含默认值。
该选择规定需求侧的表示方式，不把统计信号变成监管决定，也不将 Government 变成所有需求和供给的全知计算器。

#### 4.4.1 输入、口径与可见范围

| 语义输入 | Government 可如何使用 | 必须保留的口径 |
|---|---|---|
| 地区与用途的需求/服务缺口 | 在本职能范围内识别待调查问题或形成服务需求报告 | `region_id`、`use_type`、指标定义、需求估计方法及不确定性；不同用途不能无换算依据直接相加 |
| 现有存量与可用服务能力 | 理解已交付且满足使用条件的空间/设施，及已知不可用部分 | 数量单位、覆盖范围、可用条件、观察时点；建筑面积不自动等于服务能力 |
| 已知在建与拟建项目 | 对未来供给形成条件化观察，区别在建、尚未启动和未知进展 | 项目/区段、用途、状态版本、可能交付窗口、授权来源；不当作当前可用存量 |
| 本机关案件及可共享案件指标 | 分析受理、在审、补件、决定、未结及处理能力 | 事项类别、期间、分母、统计对象和去重规则；同一项目多案件不计为多个新项目 |
| 统计发布与可见性 | 决定本机关何时可使用某版数据，能向谁提供什么 | `metric_id/version`、单位、基准时点、统计期间、发布时间/获知时间、来源和披露权限 |

**GOV-016｜聚合观察仍有边界。** 正式统计、企业申报、模型估计、机关内部推断与隐藏真值分别标记。缺报、滞后或抽样范围不完整时保留缺口，不默认填零；本机关不能因核心掌握完整状态而直接读取全部主体私有数据。

**GOV-017｜统计改变判断，不自动启动公共项目。** 服务缺口可以触发职责内调查、报告、资源协调建议或向公共业主提供证据；建设目的、方案比较、投资、预算申请与项目发起仍由 [Owner](owner.md) 的有效身份和授权处理。监管身份不因缺口扩大就自动批准、创建项目或发放资金。

**GOV-018｜研究政策效果不等于启用自主制定政策。** 研究范围包含市场和政策如何促成新项目，但 Government 自主选择和调整政策是否启用仍待 D-08。未启用时只执行场景中合法适用的既定政策安排，并可形成职责内报告/建议；报告文字不能直接修改参数或生效规则。

**GOV-019｜建议、发布与生效分开。** 将来若启用自主调控，也须明确工具、权限、输入观察、决策依据、发布、生效及过渡规则，再由核心提交。统计口径修订保留版本与观察历史，不据最新数据改写过去许可或假定过去决策者已知。

#### 4.4.2 可交付的观察结果与后续动作

Government 可输出带有 `observation_id`、指标版本、职责范围、来源、未知项及可披露对象的观察报告，并注明“事实统计”“估计”或“建议”的性质。
报告可交由有权公共业主评估服务任务，也可用于本机关权限内的案件资源安排；对外公开和跨部门分享仍遵守资料范围及获知时点。
“当前服务不足”与“未来在建供给可能补足”可以同时成立，不能为消除统计缺口把在建量提前计入现有存量，或无依据保证其如期交付。
本接口不自动创建公众智能体；聚合需求也不代表已征询公众。依法/按模板需要的征询仍沿 GOV-A05 处理，尚未建模的部分保留缺口。

## 5. 状态转换、失败与恢复

### 5.1 提交、版本与持续约束

**GOV-011｜通过统一核心提交。** 校验主体、授权、事项、版本、证据、条件及重复执行后，登记决定与许可变化。
审查资源、费用义务和通知沿共享账本/事件入口更新；申请费义务、已支付与退费分开，不另造现金余额。
技术执行未知时核对已提交事实再重试；同一决定不得重复签发许可、扣款或占用资源。

| 记录/观察 | 最低要求 |
|---|---|
| 案件事实 | 案件、每次提交、问题/回应、分派、审查和决定之间可追踪 |
| 条件效力 | 条件约束的动作/范围、责任方、核验者、证据、时间与状态 |
| 资源与费用 | 投入窗口、待命/释放、费用依据及正式义务/结算关联 |
| 反馈 | 已提交事件、可接收主体、披露版本及接收时点；不自动共享机关私有推断 |
| 指标 | 按地区/事项/类型区分受理、补件、决定、排队和未结数量，明确分母 |

**GOV-012｜评价不能反向替代事实。** 审批速度、通过率、发现率与项目绩效分别观察，不能凭结果好坏改写决定。
风险高且加强检查导致发现更多问题，不自动等于监管更差；因果或预测解释需独立证据。
运行结束时保留未结案件、持续条件和资源责任，不为目标完工数自动批准或关闭。

### 5.2 对象转换与剩余责任

**GOV-024｜分范围许可须与真实依赖一致。** 允许分割的区段、工作包、用途及动作由适用模板明确；A 范围许可不外推到 B。即使 A 获准，若其实际执行依赖尚未满足的 B 条件，核心仍检查该依赖；不能通过拆分名称绕过共同前置条件。

**GOV-025｜生效、送达、到期与修订独立追踪。** 效力按模板规定的事件和条件计算；需要有效送达才生效的，发送尝试不够。模板未给法定时限或沉默后果时，不自行设定天数、自动批准或自动拒绝；续期申请不默认延长原许可。

**GOV-026｜检查闭环需要实际证据。** 检查发现关联具体范围及证据，整改由责任方实际执行，有权机关按适用条件复查。无法入场、检查未覆盖、报告未获验证和复查不合格分别保留；不能从“已通知整改”跳到“缺陷已消除”，也不把抽查通过扩成全项目无缺陷。

**GOV-027｜合法使用与存量变化沿各自条件提交。** 本机关只提交其有权确认的使用范围/条件；核心还需核对相应实际交付和可用性才更新地区×用途的可用存量。未交付、受限制、已许可但尚不可用的范围分别记录，不由许可数量直接生成面积或服务能力。

### 5.3 等待、续办与版本接续

“有权”同时检查事项、地域、对象范围、组织授权与当前有效期间。角色名、距离近或空闲均不足以证明有权。

**GOV-022｜队列不是另一个审批权。** 队列条目记录等待原因、所需专业、可用窗口和排序依据；本案已占用人员在续审时不被误判为外部无资源。优先处理、转介或换人都需适用依据，不能任意靠企业偏好/报价插队；具体排序算法与人员粒度待定。

**GOV-023｜版本补件只重开受影响事项。** 以问题、成果和范围的依赖关系检查新材料；既有检查只有在仍适用时复用。部分内容变化不必清空全案，但决定前必须确认被引用证据仍覆盖最终申请版本，不能把旧版无关结论拼成新方案合格。

待办至少记录 `blocked_by`、`responsible_party`、`next_trigger` 和有依据的复核时点；材料到达、人员可用、征询节点、有效到期及技术恢复分别触发续办。
每段等待保留起止和原因，实际审查投入另记；是否计入某项法定/服务时钟由具体程序决定，不能直接把所有等待相加称为法定超期。
机关有权掌握本机关的队列，不因此获得其他机关全部内部排期；跨部门协调使用明确共享的状态与交接请求。

### 5.4 正常路径与失败恢复

**情境一：有权受理、分范围许可、检查和投入使用。** 情境依赖所选模板允许相应程序，不代表各地区统一流程。

1. 机关核对申请事项/辖区及代理授权，确认收件；补正身份或材料缺项后按适用条件受理，保留原提交链。
2. 案件进入明确队列，合格资源可用时分派审查；已完成工作和申请方等待时间分别累积。
3. 对某区段发现问题，发出有依据的补件要求；回应仅改变受影响设计，未受影响检查经核实后继续有效。
4. 必要征询和核验完成，机关在授权内作出范围明确的决定；条件按开工、使用或持续责任分别关联。
5. 核实生效及相关条件后，核心放行满足全部依赖的具体动作；后续检查发现与整改在各自事项中闭合。
6. 相应区段达到使用申请条件时另行审理；许可、实际交付和可用性经共同门控后，才向区域存量提供新增依据。
7. 个案办结释放相应工作资源，持续条件与投诉处理继续存在；统计区分案件、许可区段与实际项目，避免重复计数。

**情境二：缺专业人员、补件到达及技术提交未知。** 无合格资源时案件保留队列和下一触发，不能改派无权机关制造审批进度。
补件到达后核对原分派是否仍有效，再复用或依法/按模板重派；不因旧任务持有人员而重复占用，也不把继续等待改记为拒绝。
决定提交响应未知时按同一业务标识查明是否已有事实；已提交就补齐允许的通知，未提交才按原合法条件重试，不能重复签发或收费。

**情境三：许可即将到期、变更待审且复查未通过。** 新方案提交不自动延长旧许可，机关和核心分别保留正在审理的变更与仍适用的原效力。
具体区段复查未通过，整改/限制按有权范围继续；无关且独立的合法活动可按适用规则推进，不把单个问题变成全项目永久终止。
待证据满足、变更或续期决定依法/按模板生效后，只恢复其覆盖范围；所有到期、受限和恢复事件留在历史中。

### 5.5 收尾、观察与经营反馈

**GOV-028｜案件办结不结束全部机构责任。** 决定作出、案件办结、持续条件解除、费用结清和档案归集分别记录；归档案件可成为新投诉/复审事项的证据。机关基于可见记录改善工作时保留统计口径和依据，未启用的自主政策仍不得由学习结果自动打开。

## 6. 验收场景

下列场景规定实现应满足的结果，须以实际检查记录判定是否通过。流程一致性、真实决策行为、方法校准和现实工程或制度验证分别报告；示意数据不作为真实项目参数。

### 6.1 事项全生命周期

| 编号 | 场景与应观察结果 |
|---|---|
| CHECK-GOV-001 | 空闲机关无事项/辖区权限：不能因高评分承接签发，保留合法转介或缺口。 |
| CHECK-GOV-002 | 有权机关繁忙：保留队列和原因，不允许业主随意购买另一机关的批准。 |
| CHECK-GOV-003 | 资料已收件但缺项：受理与实质审查结果分开，列出补件而非直接生成拒绝。 |
| CHECK-GOV-004 | 既有案件补件后续办：保留有效分派和已完成检查，不重复占用或阻塞自己的资源。 |
| CHECK-GOV-005 | 自报材料与隐藏事实不同：机关仅依据可见证据判断，不读取未发现缺陷。 |
| CHECK-GOV-006 | 技术故障、预算耗尽或提交结果未知：不记行政拒绝；核对后去重重试。 |
| CHECK-GOV-007 | 申请人不接受正式不利决定：决定按适用效力规则成立，救济另建事项。 |
| CHECK-GOV-008 | 咨询积极、公众反对或无人回复：分别记录，均不直接替代有权机关决定。 |
| CHECK-GOV-009 | 附条件批准：仅约束对应动作，未来承诺不当作已履行。 |
| CHECK-GOV-010 | A 区段可开工而 B 未获准：分范围检查；A 仍须满足资金、资源和技术条件。 |
| CHECK-GOV-011 | 图则通过、工程完成或使用许可之一成立：不能自动补齐其他状态或消除贷款。 |
| CHECK-GOV-012 | 修订、续期或复审申请刚提交：不自动改变旧许可效力，影响按程序确定。 |
| CHECK-GOV-013 | 现场发现问题：形成证据与有权处置，实际整改后复查，不直接降低缺陷数。 |
| CHECK-GOV-014 | 许可已有效失效但承包商尚未知：核心限制对应行动，保留认知与通知时差。 |
| CHECK-GOV-015 | 重复收到决定/支付/通知请求：不重复许可、扣款或投入，保留执行关联。 |
| CHECK-GOV-016 | 政策未启用内生调控或仅发布未生效：不改变当前条件，也不重写历史决定。 |
| CHECK-GOV-017 | 必要公众/部门程序未覆盖：报告缺口，不虚构完成；有依据不适用与未知分开。 |
| CHECK-GOV-018 | 运行截止仍有待审与持续义务：完整保留未结状态，不用结束仿真代替结案。 |

### 6.2 前期咨询与资金

| 编号 | 场景与预期 |
|---|---|
| CHECK-GOV-019 | 技术方案尚未确定但有明确前期问题：按有权范围答复或要求资料，不要求先获得本次咨询所要澄清的全部许可。 |
| CHECK-GOV-020 | 需求/方案版本变化：检查原咨询的覆盖与条件，不自动作为新方案正式许可。 |
| CHECK-GOV-021 | 申请费支付给指定外部收款方：记录正确对手、币种和用途，不默认本机关可支配现金增加。 |
| CHECK-GOV-022 | 重复缴费回执、案件撤回或批准退款：去重并关联调整，案件状态改变不直接删除原现金和费用义务。 |
| CHECK-GOV-023 | 收费完成或监管批准：只产生相应事实，不自动作出公共业主投资决定、不发放补助或增加公共业主预算。 |

### 6.3 需求观察

| 编号 | 场景与预期 |
|---|---|
| CHECK-GOV-024 | 某地区/用途数据缺失、滞后或权限不足：保留未知与观察时点，不读取隐藏全量状态或把缺报置零。 |
| CHECK-GOV-025 | 在建量增加、同一项目提交多个案件：当前可用存量不提前增加，案件数不当作新增项目数。 |
| CHECK-GOV-026 | 统计显示公共服务缺口：可以形成职责内报告/建议，但不自动启动 Owner 项目、批准投资或发放资金。 |
| CHECK-GOV-027 | 报告建议调整政策但 D-08 尚未启用自主调控：保留建议，不修改正式参数；已启用时仍检查发布、生效与适用范围。 |
| CHECK-GOV-028 | 聚合需求已存在但适用公众征询未完成：不自动增加需求侧智能体，也不把聚合指标当作公众意见或程序完成证据。 |

### 6.4 持续监管与恢复

| 编号 | 跨行为情形 | 应保留的结果 |
|---|---|---|
| CHECK-GOV-029 | 高建设需求或提速目标遇到不满足条件的申请 | 仍按案件证据和适用规则决定，不把多批准作为强制成功条件 |
| CHECK-GOV-030 | 相同提交重试、补正及后续撤回 | 身份链连续、去重，不删除已发生费用/检查或重复资源占用 |
| CHECK-GOV-031 | 原分派人员仍占用于本案但收到补件 | 复核并复用有效分派，不误判无资源或再占一份 |
| CHECK-GOV-032 | 只修改部分成果而决定引用最终申请版本 | 重开受影响检查，验证复用部分仍覆盖，不能拼接失效意见 |
| CHECK-GOV-033 | A 区段许可有效但实际依赖未满足的 B 范围 | 依赖执行仍阻塞，不因拆分许可绕过共同前置 |
| CHECK-GOV-034 | 规则要求送达后生效但仅记录发送成功 | 不直接记生效；按模板核对实际送达依据 |
| CHECK-GOV-035 | 没有有据时限/沉默后果且处理长期等待 | 保留队列、原因和触发，不擅自自动批准或拒绝 |
| CHECK-GOV-036 | 续期尚未决定、原许可达到既定到期条件 | 原效力按规则变化，申请存在不自动延长 |
| CHECK-GOV-037 | 已发整改通知、无法入场或抽查仅覆盖部分 | 缺陷不自动关闭，证据覆盖范围和未知范围分别保留 |
| CHECK-GOV-038 | 已签发使用许可但尚未实际交付/可用 | 不直接增加当前可用存量；保留许可与使用条件的差别 |
| CHECK-GOV-039 | 决定提交回执丢失后恢复 | 先核对正式事实，避免重复决定/收费，再续通知或合法重试 |
| CHECK-GOV-040 | 案件办结后仍有持续条件或出现新投诉 | 释放不再需要的工作资源，持续义务和新事项继续关联，不重写历史 |
| CHECK-GOV-041 | 本机关所在地匹配企业注册地，但不覆盖项目事项 | 不受理为本机关有权决定事项；按依据说明或转介，不以地区相近取得权限 |
| CHECK-GOV-042 | 两机关辖区重叠，但事项或授权不同 | 分别提交所需决定；牵头、征询和空闲均不替代另一机关的正式权限 |
| CHECK-GOV-043 | 政策已发布、未来生效，存在新申请和存续许可 | 按具体生效与过渡范围判断；缺规则列待定，不默认全部追溯或永久豁免 |
| CHECK-GOV-044 | 新政策生效但某主体尚未获知 | 规则按有效依据适用，主体认知保持真实获知边界，不注入未来消息或假通知 |
| CHECK-GOV-045 | 需求缺口或案件积压触发政策建议，D-08 尚未启用 | 生成职责内报告/建议或工作安排，不发布自主政策，不生成项目、拨款或许可 |
| CHECK-GOV-046 | 跨部门征询只有送达回执，尚无意见或流程未建模 | 保留等待/覆盖缺口，不伪造无异议、会签完成或群众已参与 |

### 6.5 分支输入与业务任务交接

| 编号 | 契约场景 | 预期 |
|---|---|---|
| CHECK-GOV-047 | A01 咨询目的正是确定适用程序，procedure_ref为空 | 可以保留未知、澄清或合法转介；不要求先捏造本次咨询要确定的程序 |
| CHECK-GOV-048 | A07 全部技术程序尚未完成，但适用程序允许正式押后 | 核对押后权限/依据后形成对应决定；不伪造批准路径完成记录或许可 |
| CHECK-GOV-049 | A09 原案拒绝且从未产生Permit，提出有效复审 | permit_ref=null 不阻止合法open_review；不得伪造许可或自动续期 |
| CHECK-GOV-050 | A08 条件证据待核，verification_result_ref为空 | 只可undetermined及补证；不能生成条件满足或把技术失败当不满足 |

## 7. 参数、方法与配置依赖

需按 [D-03—D-11](../07_experiments/model_decisions.md) 明确机关与事项模板、组织/人员粒度、队列优先级、投入单位、补件时钟、检查与核验深度、公众参与、复审/执法范围、统计函数及恢复机制。

自主政策调控是否启用、可用工具、观察滞后、发布/生效和过渡规则由 D-08 决定，不默认启用。可用具体地区和项目类型的事项检验“受理—排队—审查—补件/决定—条件—动作检查”，事项模板须先选定。

制度证据记录发布机关、资料地址/标识、规则版本、适用范围、发布/生效/失效与过渡条件、核验日期，以及政策明文/机制推断/情景设定标记；已有来源须核对具体地区和有效期间。

规则资料不能直接校准人员生产率、等待分布或行为偏好，这些需要独立数据或明确假设。流程验收不能替代现实法律合规、工程安全或政策效果验证。

未选定的方法、阈值、时间粒度、资格和产品条件须显式保持待定；不得以示例值、角色标签或未覆盖范围补成正式结论。具体选择登记在[模型决策](../07_experiments/model_decisions.md)，使用前绑定方法、数据和参数版本。
