# GBA 建设项目多智能体仿真系统规范：Operation 函数契约

| 文档属性 | 内容 |
|---|---|
| 文档编号 | `GBA-MAS-SPEC-03` |
| 所属文档集 | [GBA 建设项目多智能体仿真系统技术规范总册](./gba_multi_agent_simulation_specification.md) |
| 文档状态 | 公开技术规范 |
| 规范版本 | `1.0` |
| 适用范围 | `AgentModulePort.propose()` 的 Operation 输入、输出与校验规则 |
| 机器可读定义 | `gba_construction_sim/backend/agents/operation_specs.py` |

本规范定义各角色 Operation 的输入字段、允许动作、响应结构、数据约束及一致性验证要求。`propose()` 用于形成专业判断；最终有限选择由后续 `AgentDecisionRequestV1` 提供允许动作和候选项。

本文使用“必须”“不得”表示强制性要求，使用“应”“建议”表示推荐性要求。机器可读定义与本文发生差异时，以与运行版本一致的机器可读契约为准。

## 1. 契约发现与调用

每个 `AgentProposalRequestV1` 均包含与当前角色匹配的 `operation_contract`。实现方应以该对象作为本次调用的权威契约：

```python
def propose(self, request):
    contract = request.operation_contract
    assert contract.operation == request.operation
    assert contract.role == request.agent.role

    handler = self.handlers[(contract.role, contract.operation)]
    result = handler(agent=request.agent, **request.inputs)
    return AgentProposalResponseV1(
        request_id=request.request_id,
        **result,
    )
```

本地实现也可通过注册表查询契约：

```python
from gba_construction_sim.backend.agents import get_operation_contract

contract = get_operation_contract("consider_tender", "Contractor")
print(contract.model_dump_json(indent=2))
```

全部已注册契约同时通过 `module.capabilities().operation_contracts` 发布。

机器可读契约模块提供以下公共函数。它们用于契约发现和边界校验，不执行主体决策，也不修改仿真状态。

| 函数 | 用途 | 输入 | 返回与失败语义 |
|---|---|---|---|
| `list_operation_contracts()` | 枚举当前运行版本支持的全部“角色 × Operation”契约，供启动检查、能力发布和自动生成客户端使用。 | 无。 | 返回按 `operation`、`role` 排序的 `list[AgentOperationContractV1]`。 |
| `get_operation_contract(operation, role)` | 精确查询某个角色的 Operation 契约。 | Operation 名称和角色名称。 | 返回 `AgentOperationContractV1`；组合未注册时抛出 `ValueError`。 |
| `validate_operation_inputs(contract, inputs)` | 在调用 handler 前检查必填字段、类型、枚举和数值范围。 | 契约及已转为 JSON 对象的输入字典。 | 校验成功无返回值；任何违约均抛出带字段路径的 `ValueError`。 |
| `validate_operation_response(contract, response, inputs)` | 在 handler 返回后检查 `action_type + accepted` 分支及该分支要求的 `data` 字段。 | 契约、响应对象和原始输入；原始输入用于解析动态动作名。 | 校验成功无返回值；非法动作、缺失字段、类型或范围错误抛出 `ValueError`。 |

## 2. 统一响应结构

所有 Operation 必须返回统一的 `AgentProposalResponseV1`，不得以非结构化文本替代响应对象：

```json
{
  "contract_version": "1.0",
  "request_id": "原样回传 request.request_id",
  "action_type": "该 operation 允许的动作",
  "accepted": true,
  "utility": 0.73,
  "probability": 0.68,
  "reason": "主体基于自身身份、记忆和当前情况形成的可审计理由",
  "factors": {
    "resource_fit": 0.81,
    "risk_level": 0.29
  },
  "data": {}
}
```

| 字段 | 类型 | 必填 | 规则 |
|---|---|---:|---|
| `contract_version` | string | 是 | 固定 `1.0` |
| `request_id` | string | 是 | 必须与请求完全一致 |
| `action_type` | string | 是 | 必须符合当前 `operation_contract.actions` |
| `accepted` | boolean | 是 | 必须与动作分支一致 |
| `utility` | number | 是 | `0-1`，主体对该选择的综合效用 |
| `probability` | number | 是 | `0-1`，采取该动作的行为概率 |
| `reason` | string | 是 | 自然语言理由，不得只写 `yes/no` |
| `factors` | object | 是 | 解释判断的中间因素，不产生正式状态变更 |
| `data` | object | 是 | 严格依照本节各 Operation 的动作分支返回 |

`factors` 用于解释，`data` 用于后续程序读取。项目成本、进度、合同、资源占用和项目阶段不能在两者中直接修改。

## 3. 公共输入对象

| 名称 | 传输格式 | 说明 |
|---|---|---|
| `project` | object | `ConstructionProject` 的只读 JSON 快照；含 `project_id`、`region`、`project_type`、`current_stage`、`initial_budget`、`technical_complexity`、`performance`、当前参与方和投标等 |
| `policy` | object | `PolicyRegime` 只读快照；含资格互认、透明度、程序不确定性、合规成本和政策强度等 |
| `macro_environment` | object | `MacroEnvironment` 只读快照；含 `current_tick`、需求、融资、材料、人工、政策稳定性和区域摩擦矩阵 |
| Agent profile | object | 含 `agent_id`、角色、地区、能力、偏好、资源、背景和记忆摘要 |
| Agent decision | object | 含 `action_type`、`accepted`、`utility`、`probability`、`reason`、`factors`、`data` |
| `offers/candidates` | array | 每项按 `[Agent profile, Agent decision]` 传输，不是 Python tuple |

## 4. Operation 规范

当前版本共注册 25 个“角色 × Operation”契约。共享同一函数名的角色仍是独立契约，必须按精确 `contract_id` 分发。

| 注册契约 | 详细说明 |
|---|---|
| `Owner.evaluate_project_opportunity.v1` | 4.1 |
| `Bank.consider_financing.v1` | 4.2 |
| `Owner.select_financing_offer.v1` | 4.3 |
| `Architect.consider_appointment.v1` | 4.4 |
| `Engineer.consider_appointment.v1` | 4.4 |
| `QS.consider_appointment.v1` | 4.4 |
| `Owner.select_appointment.v1` | 4.5 |
| `Government.consider_review_assignment.v1` | 4.6 |
| `Government.decide_approval.v1` | 4.7 |
| `Owner.select_tender_invitees.v1` | 4.8 |
| `Contractor.consider_tender.v1` | 4.9 |
| `QS.evaluate_bid.v1` | 4.10 |
| `Owner.select_preferred_bid.v1` | 4.11 |
| `Owner.decide_contract_award.v1` | 4.12 |
| `Contractor.decide_contract_terms.v1` | 4.13 |
| `Supplier.consider_supply_order.v1` | 4.14 |
| `Contractor.select_supplier.v1` | 4.15 |
| `Owner/Architect/Engineer/QS/Contractor/Supplier/Government/Bank.decide_monthly_operation.v1` | 4.16；共 8 个角色契约 |

### 4.1 `Owner.evaluate_project_opportunity`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让一个具体业主判断给定项目机会是否符合其投资目标、资金能力、风险偏好和现有项目组合。 |
| 调用时机 | 项目机会生成后、`ConstructionProject` 尚未创建前；每个候选业主独立调用。 |
| 前置条件 | 候选概念字段完整，环境和政策为当前 tick 快照，`active_project_count` 与 `target_pressure` 已由仿真核心计算。 |
| 返回语义 | 返回“建议启动”或“不启动”的专业 proposal，并原样携带 `selected_concept`；最终是否启动仍由 `owner_project_opportunity` 有限决策确认。 |
| 状态影响 | 本函数不创建项目、不扣减资金、不占用资源。只有最终动作通过校验后，项目生成器才创建正式项目。 |

```python
evaluate_project_opportunity(
    opportunity: dict,
    macro_environment: dict,
    policy: dict,
    active_project_count: int,
    target_pressure: float,
) -> AgentProposalResponseV1
```

`opportunity` 必须包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 候选项目名称 |
| `project_type` | string | 项目类型 |
| `region` | string | 项目位置 |
| `scale` | string | 规模标签 |
| `budget` | number | 初始预算，必须大于 0 |
| `technical_complexity` | number | 技术复杂度，`0-1` |
| `planned_duration` | integer | 计划工期，月 |

允许返回：

| `action_type` | `accepted` | `data` 必填字段 |
|---|---:|---|
| `initiate_project` | true/false | `selected_concept: object`，原样返回被评估概念 |

最终决策类型为 `owner_project_opportunity`，最终请求会在 `initiate_project` 与 `defer_project` 中作有限选择。

### 4.2 `Bank.consider_financing`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让一家具体银行根据借款人能力、项目风险和融资环境形成独立授信意见及报价。 |
| 调用时机 | 项目正式创建后、设计团队委任前；对每家可见且满足硬约束的候选银行分别调用。 |
| 前置条件 | 融资需求和项目风险已由仿真核心计算；银行资源、风险偏好和自身记忆可用。 |
| 返回语义 | 返回批准或拒绝意见；批准时给出可批准金额、利率和条件，供业主比较。 |
| 状态影响 | 本函数不放款、不改变现金余额或债务。只有业主选择有效报价且状态引擎提交后才形成融资关系。 |

```python
consider_financing(
    requested_amount: float,
    borrower_financial_capacity: float,
    project_risk: float,
    financing_condition_index: float,
) -> AgentProposalResponseV1
```

| 输入 | 类型/范围 | 说明 |
|---|---|---|
| `requested_amount` | number, `>=0` | 申请融资额 |
| `borrower_financial_capacity` | number, `0-1` | 借款人财务能力 |
| `project_risk` | number, `0-1` | 仿真核心计算的项目风险 |
| `financing_condition_index` | number, `>=0` | 当前融资环境指数 |

| `action_type` | `accepted` | `data` 必填字段 |
|---|---:|---|
| `approve_financing` | true | `requested_amount`, `approved_amount`, `interest_rate`, `conditions: array` |
| `reject_financing` | false | 同上；此时金额和利率仅作为拒绝依据 |

最终决策类型：`bank_project_financing`。

### 4.3 `Owner.select_financing_offer`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让业主在已接受授信的银行报价与自有资金方案之间作融资模式选择。 |
| 调用时机 | 全部候选银行完成 `consider_financing` 后。 |
| 前置条件 | `offers` 只包含本轮银行 profile 与对应 proposal；银行融资候选必须 `accepted=true`。 |
| 返回语义 | 返回 `owner_equity` 或一家具名银行的 `bank_finance` 选择，并保留可审计的接受报价集合。 |
| 状态影响 | 本函数不转账、不记账。融资合同和项目现金状态由仿真核心校验并提交。 |

```python
select_financing_offer(
    offers: list[tuple[AgentProfile, AgentDecision]],
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | `data` 必填字段 |
|---|---:|---|
| `self_finance_project` | true | `financing_mode="owner_equity"`, `selected_bank_id=null` |
| `select_project_finance` | true | `financing_mode="bank_finance"`, `selected_bank_id`, `accepted_bank_ids`, `selected_offer` |

最终决策类型：`owner_financing_selection`。最终请求的 `candidate_options` 只包含已经接受授信的银行。

### 4.4 `consider_appointment`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让 Architect、Engineer、QS 候选主体分别判断是否接受当前项目的专业委任。 |
| 调用时机 | 项目融资路径确定后，在业主选择对应顾问之前；每个候选主体独立调用。 |
| 前置条件 | 项目满足候选可见性和资格硬约束；`required_resource` 和 `prior_fit` 已由仿真核心提供。 |
| 返回语义 | 返回与角色对应的接受或拒绝 proposal；三个角色共享 Operation 名称，但使用三个独立契约。 |
| 状态影响 | 本函数不建立委任关系、不占用资源。业主后续选择并经状态引擎提交后才形成正式参与关系。 |

这是同名但分角色的三个契约，不能用一个模糊 handler 猜字段。

```python
Architect.consider_appointment(
    project: dict,
    policy: dict,
    macro_environment: dict,
    required_resource: float,
    prior_fit: float,
) -> AgentProposalResponseV1

Engineer.consider_appointment(
    project: dict,
    required_resource: float,
    prior_fit: float,
) -> AgentProposalResponseV1

QS.consider_appointment(
    project: dict,
    policy: dict,
    macro_environment: dict,
    required_resource: float,
    prior_fit: float,
) -> AgentProposalResponseV1
```

| 角色 | 输入 | 允许动作 |
|---|---|---|
| Architect | `project`, `policy`, `macro_environment`, `required_resource:number>=0`, `prior_fit:0-1` | `accept_design_appointment` / `decline_design_appointment` |
| Engineer | `project`, `required_resource:number>=0`, `prior_fit:0-1` | `accept_engineering_appointment` / `decline_engineering_appointment` |
| QS | `project`, `policy`, `macro_environment`, `required_resource:number>=0`, `prior_fit:0-1` | `accept_qs_appointment` / `decline_qs_appointment` |

接受动作必须 `accepted=true`；拒绝动作必须 `accepted=false`。这三个分支均不要求额外 `data`。

最终决策类型分别为：

```text
architect_appointment_acceptance
engineer_appointment_acceptance
qs_appointment_acceptance
```

### 4.5 `Owner.select_appointment`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让业主从已愿意接受委任的候选人中选择 Architect、QS 或 Engineer。 |
| 调用时机 | 对应角色的全部 `consider_appointment` 调用完成后；三个 purpose 分别调用。 |
| 前置条件 | `purpose` 必须是支持的角色类型；候选 ID 来自本轮接受集合。 |
| 返回语义 | 返回与 purpose 匹配的选择动作和唯一 `selected_agent_id`；无有效人选时返回未接受。 |
| 状态影响 | 函数本身不写项目参与方。状态引擎验证候选 ID 后建立委任并处理资源占用。 |

```python
select_appointment(
    candidates: list[tuple[AgentProfile, AgentDecision]],
    purpose: Literal["architect", "qs", "engineer"],
) -> AgentProposalResponseV1
```

`action_type` 必须动态对应 `purpose`：`select_architect`、`select_qs` 或 `select_engineer`。

| `accepted` | `data` |
|---:|---|
| true | `selected_agent_id:string`, `accepted_agent_ids:array` |
| false | 可为空；表示无人接受或业主不选择 |

最终决策类型：`owner_select_architect`、`owner_select_qs`、`owner_select_engineer`。最终 `choice_contract.output_field` 为 `selected_agent_id`。

### 4.6 `Government.consider_review_assignment`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让一个具体政府监管主体判断当前是否有能力承接设计审查或完工验收任务。 |
| 调用时机 | 项目进入需要监管审查的阶段、正式审批判断之前。 |
| 前置条件 | 项目处于合法审查阶段；`required_resource` 由审查工作量计算得到。 |
| 返回语义 | 返回接受审查或暂缓审查。接受仅代表承担审查，不代表项目获批。 |
| 状态影响 | 不改变审批结果和项目阶段；审查分配由状态引擎另行提交。 |

```python
consider_review_assignment(
    project: dict,
    required_resource: float,
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | `data` |
|---|---:|---|
| `accept_regulatory_review` | true | `{}` |
| `defer_regulatory_review` | false | `{}` |

最终决策类型：`government_review_assignment`。

### 4.7 `Government.decide_approval`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让已承接审查的政府主体依据项目材料和当前政策作批准或要求修改的判断。 |
| 调用时机 | 设计报审或完工验收材料齐备，并完成审查分配后。 |
| 前置条件 | 项目阶段、必要文件和监管参与关系满足阶段规则；`policy` 为当前有效制度快照。 |
| 返回语义 | `approve` 表示本轮审查通过；`request_revision` 表示材料需修改后重新进入审查。 |
| 状态影响 | 本函数不直接推进阶段。状态引擎根据审批类型提交“设计批准”或“完工批准”事件。 |

```python
decide_approval(
    project: dict,
    policy: dict,
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | 含义 |
|---|---:|---|
| `approve` | true | 批准当前设计报审或完工验收 |
| `request_revision` | false | 要求修改后重新提交 |

无需额外 `data`。最终决策类型由项目阶段确定：`government_design_approval` 或 `government_completion_approval`。

### 4.8 `Owner.select_tender_invitees`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让业主从满足资格和可见性硬约束的承包商中形成邀请投标短名单。 |
| 调用时机 | 设计获批、招标条件形成后，承包商决定是否投标之前。 |
| 前置条件 | `candidates` 已由仿真核心完成资格、地区、能力和资源硬筛选；`limit` 为允许邀请上限。 |
| 返回语义 | 返回按偏好排序的 `selected_agent_ids` 和 `ranked_candidates`，仅表示邀请对象。 |
| 状态影响 | 不生成投标、不授标；通过校验后，仿真核心向入选承包商开放投标机会。 |

```python
select_tender_invitees(
    candidates: list[AgentProfile],
    project: dict,
    policy: dict,
    macro_environment: dict,
    limit: int,
) -> AgentProposalResponseV1
```

只能返回 `action_type="invite_contractors"`。`accepted` 表示名单是否非空。

```json
{
  "selected_agent_ids": ["C001", "C007"],
  "ranked_candidates": [
    {"agent_id": "C001", "score": 0.78},
    {"agent_id": "C007", "score": 0.72}
  ]
}
```

所有 ID 必须来自 `candidates`，数量不得超过 `limit`。最终决策类型：`owner_tender_shortlist`；最终选择字段为 `selected_agent_ids`，允许多选。

### 4.9 `Contractor.consider_tender`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让一个被邀请的承包商根据自身资源、利润要求、项目风险和政策环境决定是否投标。 |
| 调用时机 | 招标邀请发出后、投标截止前；每个受邀承包商独立调用。 |
| 前置条件 | 承包商属于邀请名单；项目、政策、宏观环境和吸引力输入均为同一 tick 快照。 |
| 返回语义 | 投标时返回行为概率、报价、预期利润和风险；拒绝时返回拒绝依据。 |
| 状态影响 | proposal 中的报价只是候选投标依据；最终提交投标并通过校验后才写入项目 bid 集合。 |

```python
consider_tender(
    project: dict,
    policy: dict,
    macro_environment: dict,
    attractiveness: float,
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | `data` 必填字段 |
|---|---:|---|
| `submit_bid` | true | `bid_probability`, `bid_price`, `expected_profit`, `risk_level`, `decline_reason` |
| `decline_bid` | false | 同上；`bid_price` 仅为专业测算参考，不形成正式投标 |

范围：`bid_probability` 和 `risk_level` 为 `0-1`；`bid_price>=0`；`expected_profit>=0`。最终决策类型：`tender_decision`。

### 4.10 `QS.evaluate_bid`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让已委任 QS 对一份具体投标进行独立商业与风险评估。 |
| 调用时机 | 有效投标提交后、业主选择优先投标人之前；每份投标分别调用。 |
| 前置条件 | bid 来自当前项目有效投标集合；contractor 与 `contractor_id` 一致；QS 已正式参与项目。 |
| 返回语义 | 返回 `0-1` 的 `evaluation_score`，作为业主选择的专业决策支持。 |
| 状态影响 | 不淘汰投标、不决定中标者；评估结果由仿真核心记录并交给业主。 |

```python
evaluate_bid(
    bid: dict,
    contractor: AgentProfile,
    project: dict,
    policy: dict,
    prior_fit: float,
) -> AgentProposalResponseV1
```

`bid` 至少包含 `contractor_id`、`bid_price`、`risk_level`。只能返回：

```json
{
  "action_type": "evaluate_bid",
  "accepted": true,
  "data": {"evaluation_score": 0.76}
}
```

`evaluation_score` 必须在 `0-1`。最终决策类型：`qs_bid_evaluation`。

### 4.11 `Owner.select_preferred_bid`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让业主综合 QS 评估和自身目标，从有效投标中选择优先谈判对象。 |
| 调用时机 | 全部有效投标完成 QS 评估后、合同条款谈判前。 |
| 前置条件 | 每个候选投标含合法 contractor ID 和 evaluation score；候选主体可在 agents 映射中查询。 |
| 返回语义 | 返回唯一 `selected_contractor_id` 和投标排序；没有可接受投标时返回未接受。 |
| 状态影响 | 仅确定优先投标人，不构成授标或合同。状态引擎提交选择后才进入谈判。 |

```python
select_preferred_bid(
    evaluated_bids: list[dict],
    agents: dict[str, AgentProfile],
) -> AgentProposalResponseV1
```

`evaluated_bids` 每项至少包含 `contractor_id` 和 `evaluation_score`。

| `action_type` | `accepted` | `data` |
|---|---:|---|
| `select_preferred_bidder` | true | `selected_contractor_id`, `ranked_bids` |
| `select_preferred_bidder` | false | 可为空，表示没有有效投标 |

最终决策类型：`owner_preferred_bidder_selection`；最终选择字段为 `selected_contractor_id`。

### 4.12 `Owner.decide_contract_award`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让业主判断优先投标对应的价格、交付安排和风险分配是否可作为授标条件。 |
| 调用时机 | 优先投标人确定后，与承包商合同条款决策配对执行。 |
| 前置条件 | `preferred_bid` 必须属于当前项目且仍有效；项目处于合同谈判阶段。 |
| 返回语义 | 返回接受授标条件或要求修订；接受只是业主一方同意。 |
| 状态影响 | 单方接受不创建合同。只有业主与承包商均接受且状态校验通过后才形成合同。 |

```python
decide_contract_award(
    project: dict,
    preferred_bid: dict,
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | 含义 |
|---|---:|---|
| `accept_contract` | true | 接受授标条件 |
| `request_contract_revision` | false | 要求修改价格、交付或风险分配 |

无需额外 `data`。最终决策类型：`owner_contract_award`。

### 4.13 `Contractor.decide_contract_terms`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让优先承包商独立判断合同价格、范围、工期和风险分配是否可接受。 |
| 调用时机 | 业主选定优先投标后，与 `Owner.decide_contract_award` 同一谈判轮次调用。 |
| 前置条件 | 调用主体必须是 `preferred_bid.contractor_id` 对应承包商；合同条件仍在有效谈判窗口内。 |
| 返回语义 | 返回接受条款或要求修订；不允许代表业主作决定。 |
| 状态影响 | 单方接受不创建合同。双方同意后由状态引擎生成正式合同与资源承诺。 |

```python
decide_contract_terms(
    project: dict,
    preferred_bid: dict,
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | 含义 |
|---|---:|---|
| `accept_terms` | true | 接受合同条款 |
| `request_revision` | false | 要求修改条款 |

无需额外 `data`。最终决策类型：`contract_negotiation`。

### 4.14 `Supplier.consider_supply_order`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让一个候选供应商根据订单规模、资源、物流和历史匹配度决定是否接单。 |
| 调用时机 | 施工承包关系生效、承包商组织供应链时；每个候选供应商独立调用。 |
| 前置条件 | 项目和 contractor ID 有效；`required_resource` 与 `prior_fit` 已由仿真核心计算。 |
| 返回语义 | 返回接受或拒绝以及 `offer_score`，供承包商比较。 |
| 状态影响 | 不创建采购订单、不锁定库存。承包商选择且状态引擎提交后才形成供应关系。 |

```python
consider_supply_order(
    project: dict,
    contractor_id: str,
    required_resource: float,
    prior_fit: float,
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | `data` |
|---|---:|---|
| `accept_supply_order` | true | `offer_score:number, 0-1` |
| `decline_supply_order` | false | `offer_score:number, 0-1` |

最终决策类型：`supplier_order_acceptance`。

### 4.15 `Contractor.select_supplier`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让承包商从愿意接单的供应商中选择一个供应伙伴。 |
| 调用时机 | 全部候选供应商完成 `consider_supply_order` 后。 |
| 前置条件 | `offers` 只包含本项目候选供应商及对应 proposal；可选 ID 必须来自接受集合。 |
| 返回语义 | 返回唯一 `selected_supplier_id` 和接受供应商集合；无人接受时返回未接受。 |
| 状态影响 | 函数不写采购合同或库存；状态引擎验证后建立供应关系并处理资源。 |

```python
select_supplier(
    offers: list[tuple[AgentProfile, AgentDecision]],
) -> AgentProposalResponseV1
```

| `action_type` | `accepted` | `data` |
|---|---:|---|
| `select_supplier` | true | `selected_supplier_id`, `accepted_supplier_ids` |
| `select_supplier` | false | 可为空，表示没有供应商接受 |

最终决策类型：`contractor_supplier_selection`；最终选择字段为 `selected_supplier_id`。

### 4.16 `decide_monthly_operation`

| 函数语义 | 规范 |
|---|---|
| 用途 | 让每个主体在没有关键项目决策时，根据自身角色、记忆和环境选择一项月度经营活动。 |
| 调用时机 | 每个仿真月的后台决策窗口；与项目关键路径决策分开调度。 |
| 前置条件 | 当前宏观环境可用；调用主体只能选择其角色契约列出的动作。 |
| 返回语义 | 返回一个角色合法动作、简短标签和说明，用于事件流、认知更新和后续策略形成。 |
| 状态影响 | 属于 `P3` 后台行为，不得直接推进项目阶段、签订合同或修改正式工程数值。 |

所有角色输入均为：

```python
decide_monthly_operation(
    macro_environment: dict,
) -> AgentProposalResponseV1
```

所有合法动作都必须返回：

```json
{
  "accepted": true,
  "data": {
    "label": "界面显示的简短名称",
    "description": "本月经营行为说明"
  }
}
```

各角色允许的 `action_type`：

| 角色 | 允许动作 |
|---|---|
| Owner | `screen_investment_pipeline`, `review_financing_capacity`, `evaluate_market_demand`, `prepare_project_scope`, `adjust_investment_strategy` |
| Architect | `seek_design_commission`, `build_cross_region_reputation`, `improve_design_capability`, `maintain_client_relationship` |
| Engineer | `review_technical_market`, `improve_engineering_capability`, `maintain_professional_qualifications` |
| QS | `update_cost_database`, `seek_consulting_work`, `review_cost_market`, `improve_cost_estimation` |
| Contractor | `scan_tender_opportunities`, `adjust_bid_strategy`, `evaluate_region_entry`, `seek_joint_venture_partner`, `maintain_supplier_relationship` |
| Supplier | `adjust_inventory`, `seek_supply_contract`, `monitor_material_prices`, `improve_supply_reliability` |
| Government | `publish_guidelines`, `monitor_compliance`, `adjust_regulatory_focus`, `review_policy_feedback` |
| Bank | `review_credit_pipeline`, `monitor_borrower_risk`, `adjust_credit_terms` |

最终决策类型统一为 `monthly_enterprise_operation`，优先级为后台 `P3`，不得直接推动项目阶段。

## 5. Proposal 与最终 Decision 的职责边界

```text
propose(operation)
  -> 角色专业分析、候选排序、报价或评审依据
  -> AgentProposalResponseV1

resolve_decision(...)
  -> 带身份、记忆、信念、当前状态、allowed_actions、candidate_options
  -> AgentDecisionResponseV1

simulation validation
  -> 校验动作和候选 ID
  -> 仿真核心正式修改状态
```

最终 `AgentDecisionResponseV1` 的格式固定为：

```json
{
  "contract_version": "1.0",
  "request_id": "原样回传",
  "agent_id": "必须等于 request.agent.agent_id",
  "action_type": "必须属于 request.constraints.allowed_actions",
  "decision": true,
  "reason": "最终独立判断理由",
  "confidence": 0.81,
  "data": {
    "selected_agent_id": "只有 request.choice_contract 要求时才返回"
  }
}
```

最终决策请求包含以下约束：

- `constraints.allowed_actions`：动作必须从该集合中选择。
- `candidate_options`：主体或方案必须从该集合中选择。
- `choice_contract.output_field`：选中 ID 应写到哪个字段。
- `choice_contract.multiple/limit`：是否多选以及数量上限。
- `constraints.forbidden_state_keys`：响应中不得包含的仿真状态字段。

## 6. 一致性验证

Operation handler 实现完成后，应运行以下契约测试：

```bash
pytest -q gba_construction_sim/backend/tests/test_agent_module_contracts.py
```

校验器会拒绝：

- 缺少必填输入。
- operation 与角色不匹配。
- 非法的 `action_type + accepted` 组合。
- 缺少动作分支要求的 `data` 字段。
- 数字范围或字段类型错误。
- 返回项目阶段、成本、合同或资源分配等仿真核心拥有的状态修改。

## 7. 规范导航

- 总册：[GBA 建设项目多智能体仿真系统技术规范总册](./gba_multi_agent_simulation_specification.md)
- 模型与环境：[GBA-MAS-SPEC-01 模型与运行环境规范](./simulation_model_specification.md)
- 上一册：[GBA-MAS-SPEC-02 智能体模块集成规范](./agent_module_integration_guide.md)
