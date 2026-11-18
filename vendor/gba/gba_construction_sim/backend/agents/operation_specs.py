"""Role-operation contracts shared by the simulator and external agent teams.

These specifications describe proposal generation. The later bounded-decision
request remains self-describing through ``allowed_actions``, candidate options,
and ``choice_contract``.
"""

from __future__ import annotations

from typing import Any, Iterable

from gba_construction_sim.backend.agents.contracts import (
    AgentOperationActionV1,
    AgentOperationContractV1,
    AgentOperationFieldV1,
)


def _field(
    name: str,
    value_type: str,
    description: str,
    example: Any,
    *,
    required: bool = True,
    enum: Iterable[Any] = (),
    minimum: float | None = None,
    maximum: float | None = None,
) -> AgentOperationFieldV1:
    return AgentOperationFieldV1(
        name=name,
        value_type=value_type,
        required=required,
        description=description,
        example=example,
        enum=list(enum),
        minimum=minimum,
        maximum=maximum,
    )


def _action(
    action_type: str,
    accepted: bool | None,
    description: str,
    *data_fields: AgentOperationFieldV1,
) -> AgentOperationActionV1:
    return AgentOperationActionV1(
        action_type=action_type,
        accepted=accepted,
        description=description,
        data_fields=list(data_fields),
    )


PROJECT = _field(
    "project",
    "object",
    "完整 ConstructionProject 只读快照；至少包含 project_id、region、project_type、current_stage、initial_budget、technical_complexity 和 performance。",
    {"project_id": "P001", "region": "Shenzhen", "current_stage": "Tendering"},
)
POLICY = _field(
    "policy",
    "object",
    "当前 PolicyRegime 只读快照，包含资格互认、透明度、程序不确定性和合规成本等参数。",
    {"cross_region_qualification_recognition": 0.7, "procedural_uncertainty": 0.2},
)
ENVIRONMENT = _field(
    "macro_environment",
    "object",
    "当前 MacroEnvironment 只读快照，包含 tick、市场需求、融资、材料、人工、政策稳定性和区域摩擦。",
    {"current_tick": 4, "market_demand_index": 1.05, "financing_condition_index": 0.92},
)
REQUIRED_RESOURCE = _field(
    "required_resource",
    "number",
    "本次任务需要占用的标准化资源量。",
    0.4,
    minimum=0.0,
)
PRIOR_FIT = _field(
    "prior_fit",
    "number",
    "基于历史合作记录计算的主体匹配度。",
    0.68,
    minimum=0.0,
    maximum=1.0,
)
LABEL = _field("label", "string", "用于事件流展示的简短动作名称。", "Screened investment pipeline")
DESCRIPTION = _field(
    "description",
    "string",
    "用于审计和界面展示的一句话自然语言说明。",
    "Reviewed candidate projects against current capacity and strategy.",
)


def _contract(
    operation: str,
    role: str,
    purpose: str,
    *,
    inputs: list[AgentOperationFieldV1],
    actions: list[AgentOperationActionV1],
    factors: list[AgentOperationFieldV1] | None = None,
    final_decision_types: list[str] | None = None,
    notes: list[str] | None = None,
) -> AgentOperationContractV1:
    return AgentOperationContractV1(
        contract_id=f"{role}.{operation}.v1",
        operation=operation,
        role=role,
        purpose=purpose,
        inputs=inputs,
        actions=actions,
        factor_fields=factors or [],
        final_decision_types=final_decision_types or [],
        notes=notes or [],
    )


_SPECS: list[AgentOperationContractV1] = [
    _contract(
        "evaluate_project_opportunity",
        "Owner",
        "判断业主是否应基于当前组合、环境和政策启动一个具体项目机会。",
        inputs=[
            _field(
                "opportunity",
                "object",
                "候选项目概念；必须包含 name、project_type、region、scale、budget、technical_complexity、planned_duration。",
                {
                    "name": "GBA Innovation Centre",
                    "project_type": "Commercial",
                    "region": "Shenzhen",
                    "scale": "medium",
                    "budget": 120000000,
                    "technical_complexity": 0.55,
                    "planned_duration": 30,
                },
            ),
            ENVIRONMENT,
            POLICY,
            _field("active_project_count", "integer", "该业主当前未关闭项目数量。", 2, minimum=0),
            _field("target_pressure", "number", "仿真项目生成目标带来的标准化压力。", 0.35, minimum=0, maximum=1),
        ],
        actions=[
            _action(
                "initiate_project",
                None,
                "形成启动项目的专业建议；accepted=false 表示专业建议不支持立即启动。",
                _field("selected_concept", "object", "原样返回被评估的项目概念。", {"region": "Shenzhen"}),
            )
        ],
        factors=[
            _field("region_fit", "number", "区位匹配度。", 0.72, required=False),
            _field("budget_capacity", "number", "资本对预算的覆盖能力。", 0.81, required=False),
            _field("project_load_penalty", "number", "现有项目负荷惩罚。", 0.14, required=False),
            _field("macro_support", "number", "宏观条件支持度。", 0.18, required=False),
            _field("risk_drag", "number", "复杂度和政策风险阻力。", 0.16, required=False),
        ],
        final_decision_types=["owner_project_opportunity"],
        notes=["最终 bounded decision 的动作集合为 initiate_project / defer_project。"],
    ),
    _contract(
        "consider_financing",
        "Bank",
        "银行判断是否提供项目融资并形成可比较的授信报价。",
        inputs=[
            _field("requested_amount", "number", "业主申请的融资金额。", 72000000, minimum=0),
            _field("borrower_financial_capacity", "number", "借款人的标准化财务能力。", 0.78, minimum=0, maximum=1),
            _field("project_risk", "number", "仿真核心计算的项目综合风险。", 0.32, minimum=0, maximum=1),
            _field("financing_condition_index", "number", "当前融资环境指数。", 0.92, minimum=0),
        ],
        actions=[
            _action(
                "approve_financing",
                True,
                "批准融资。",
                _field("requested_amount", "number", "申请金额。", 72000000),
                _field("approved_amount", "number", "批准金额。", 65000000),
                _field("interest_rate", "number", "年化利率，小数表示。", 0.0475, minimum=0),
                _field("conditions", "array", "融资附加条件列表。", ["monthly progress reporting"]),
            ),
            _action(
                "reject_financing",
                False,
                "拒绝融资，但仍返回测算报价供审计。",
                _field("requested_amount", "number", "申请金额。", 72000000),
                _field("approved_amount", "number", "模型上限金额，不代表已批准。", 0),
                _field("interest_rate", "number", "风险定价参考利率。", 0.081, minimum=0),
                _field("conditions", "array", "若重新申请可能需要满足的条件。", []),
            ),
        ],
        final_decision_types=["bank_project_financing"],
    ),
    _contract(
        "select_financing_offer",
        "Owner",
        "从已接受的银行报价中选择融资方，或明确采用业主自有资金。",
        inputs=[
            _field(
                "offers",
                "array",
                "银行报价数组；每项为 [AgentIdentity/Profile 快照, AgentDecision 快照]。",
                [[{"agent_id": "B001"}, {"accepted": True, "data": {"interest_rate": 0.045}}]],
            )
        ],
        actions=[
            _action(
                "self_finance_project",
                True,
                "业主明确采用权益资金，包括有银行报价时仍选择自筹。",
                _field("financing_mode", "string", "固定为 owner_equity。", "owner_equity", enum=["owner_equity"]),
                _field("selected_bank_id", "string|null", "自有资金时必须为 null。", None),
            ),
            _action(
                "select_project_finance",
                True,
                "选择一个已接受报价的银行。",
                _field("financing_mode", "string", "固定为 bank_finance。", "bank_finance", enum=["bank_finance"]),
                _field("selected_bank_id", "string", "被选银行 ID。", "B001"),
                _field("accepted_bank_ids", "array", "所有接受授信的银行 ID。", ["B001", "B004"]),
                _field("selected_offer", "object", "被选银行完整 proposal 结果。", {"interest_rate": 0.045}),
            ),
            _action(
                "select_project_finance",
                False,
                "业主拒绝当前融资安排，保留未融资状态等待后续判断。",
                _field("financing_mode", "string", "固定为 unfinanced。", "unfinanced", enum=["unfinanced"]),
                _field("selected_bank_id", "null", "未融资时不选择银行。", None),
            ),
        ],
        final_decision_types=["owner_financing_selection"],
        notes=["最终请求的 candidate_options 只包含 accepted=true 的银行。"],
    ),
]


def _appointment_contract(role: str) -> AgentOperationContractV1:
    role_key = role.lower()
    action_prefix = {"Architect": "design", "Engineer": "engineering", "QS": "qs"}[role]
    inputs = [PROJECT]
    if role in {"Architect", "QS"}:
        inputs.extend([POLICY, ENVIRONMENT])
    inputs.extend([REQUIRED_RESOURCE, PRIOR_FIT])
    return _contract(
        "consider_appointment",
        role,
        f"{role} 独立判断是否接受项目委任。",
        inputs=inputs,
        actions=[
            _action(f"accept_{action_prefix}_appointment", True, "接受委任。"),
            _action(f"decline_{action_prefix}_appointment", False, "拒绝委任。"),
        ],
        final_decision_types=[f"{role_key}_appointment_acceptance"],
        notes=["Architect/QS 需要 policy 和 macro_environment；Engineer 不需要这两个字段。"],
    )


_SPECS.extend(_appointment_contract(role) for role in ("Architect", "Engineer", "QS"))

_SPECS.extend(
    [
        _contract(
            "select_appointment",
            "Owner",
            "从已经接受委任的候选人中选择 Architect、QS 或 Engineer。",
            inputs=[
                _field(
                    "candidates",
                    "array",
                    "候选数组；每项为 [AgentIdentity/Profile 快照, AgentDecision 快照]。",
                    [[{"agent_id": "A001"}, {"accepted": True, "utility": 0.74}]],
                ),
                _field("purpose", "string", "委任类型。", "architect", enum=["architect", "qs", "engineer"]),
            ],
            actions=[
                _action(
                    "select_{purpose}",
                    True,
                    "选择一名已接受委任的候选人。",
                    _field("selected_agent_id", "string", "被选主体 ID。", "A001"),
                    _field("accepted_agent_ids", "array", "全部接受委任的候选主体 ID。", ["A001", "A004"]),
                ),
                _action("select_{purpose}", False, "没有候选人接受时返回拒绝结果。"),
            ],
            final_decision_types=["owner_select_architect", "owner_select_qs", "owner_select_engineer"],
            notes=["action_type 模板会按 purpose 展开，例如 purpose=architect 时必须返回 select_architect。"],
        ),
        _contract(
            "consider_review_assignment",
            "Government",
            "监管主体判断是否承接当前审批或检查任务。",
            inputs=[PROJECT, REQUIRED_RESOURCE],
            actions=[
                _action("accept_regulatory_review", True, "接受监管任务。"),
                _action("defer_regulatory_review", False, "因辖区或能力不足而暂缓。"),
            ],
            final_decision_types=["government_review_assignment"],
        ),
        _contract(
            "decide_approval",
            "Government",
            "监管主体根据项目质量、信息和政策规则作批准或修改决定。",
            inputs=[PROJECT, POLICY],
            actions=[
                _action("approve", True, "批准当前报审或完工验收。"),
                _action("request_revision", False, "要求修改后重新提交。"),
            ],
            final_decision_types=["government_design_approval", "government_completion_approval"],
            notes=["同一 operation 用于设计审批和完工验收，具体场景由 request.project.current_stage 与 final decision_type 标识。"],
        ),
        _contract(
            "select_tender_invitees",
            "Owner",
            "业主从仿真核心提供的合资格承包商中形成邀请名单。",
            inputs=[
                _field("candidates", "array", "合资格且可见的 Contractor profile 快照。", [{"agent_id": "C001"}]),
                PROJECT,
                POLICY,
                ENVIRONMENT,
                _field("limit", "integer", "最多邀请数量，至少为 1。", 5, minimum=1),
            ],
            actions=[
                _action(
                    "invite_contractors",
                    None,
                    "形成有序邀请名单。",
                    _field("selected_agent_ids", "array", "邀请的 Contractor ID。", ["C001", "C007"]),
                    _field("ranked_candidates", "array", "候选排序及分数。", [{"agent_id": "C001", "score": 0.78}]),
                )
            ],
            final_decision_types=["owner_tender_shortlist"],
            notes=["返回 ID 必须来自输入 candidates，且数量不得超过 limit。"],
        ),
        _contract(
            "consider_tender",
            "Contractor",
            "承包商判断是否投标，并形成报价、预期利润与风险依据。",
            inputs=[
                PROJECT,
                POLICY,
                ENVIRONMENT,
                _field("attractiveness", "number", "仿真核心计算的项目吸引力。", 0.72, minimum=0, maximum=1),
            ],
            actions=[
                _action(
                    "submit_bid",
                    True,
                    "提交投标。",
                    _field("bid_probability", "number", "投标概率。", 0.68, minimum=0, maximum=1),
                    _field("bid_price", "number", "投标价格。", 108000000, minimum=0),
                    _field("expected_profit", "number", "预期利润率。", 0.09, minimum=0),
                    _field("risk_level", "number", "交付风险。", 0.31, minimum=0, maximum=1),
                    _field("decline_reason", "string", "若拒绝时使用的最主要原因；接受时仍可返回备查。", "delivery risk above tolerance"),
                ),
                _action(
                    "decline_bid",
                    False,
                    "拒绝投标。",
                    _field("bid_probability", "number", "投标概率。", 0.21, minimum=0, maximum=1),
                    _field("bid_price", "number", "专业测算参考报价，并非正式投标。", 118000000, minimum=0),
                    _field("expected_profit", "number", "预期利润率。", 0.04, minimum=0),
                    _field("risk_level", "number", "交付风险。", 0.67, minimum=0, maximum=1),
                    _field("decline_reason", "string", "主要拒绝原因。", "insufficient available delivery capacity"),
                ),
            ],
            final_decision_types=["tender_decision"],
            notes=["正式成本、市场指数和项目状态由仿真核心计算；智能体只能返回选择和专业依据。"],
        ),
        _contract(
            "evaluate_bid",
            "QS",
            "QS 对单份投标进行标准化评审。",
            inputs=[
                _field("bid", "object", "投标快照；至少包含 contractor_id、bid_price、risk_level。", {"contractor_id": "C001", "bid_price": 108000000, "risk_level": 0.31}),
                _field("contractor", "object", "对应 Contractor profile 快照。", {"agent_id": "C001", "role": "Contractor"}),
                PROJECT,
                POLICY,
                PRIOR_FIT,
            ],
            actions=[
                _action(
                    "evaluate_bid",
                    True,
                    "返回标准化评标分数。",
                    _field("evaluation_score", "number", "0-1 评标分数。", 0.76, minimum=0, maximum=1),
                )
            ],
            final_decision_types=["qs_bid_evaluation"],
        ),
        _contract(
            "select_preferred_bid",
            "Owner",
            "业主依据 QS 结果和承包商能力选择首选投标人。",
            inputs=[
                _field("evaluated_bids", "array", "已评审投标，每项必须包含 contractor_id 和 evaluation_score。", [{"contractor_id": "C001", "evaluation_score": 0.76}]),
                _field("agents", "object", "agent_id 到完整 Agent profile 快照的映射。", {"C001": {"role": "Contractor"}}),
            ],
            actions=[
                _action(
                    "select_preferred_bidder",
                    True,
                    "选择首选投标人。",
                    _field("selected_contractor_id", "string", "被选承包商 ID。", "C001"),
                    _field("ranked_bids", "array", "加入 owner_selection_score 后的完整排序。", [{"contractor_id": "C001", "owner_selection_score": 0.79}]),
                ),
                _action("select_preferred_bidder", False, "没有有效投标时返回失败。"),
            ],
            final_decision_types=["owner_preferred_bidder_selection"],
        ),
        _contract(
            "decide_contract_award",
            "Owner",
            "业主判断是否接受首选投标人的最终授标条件。",
            inputs=[
                PROJECT,
                _field("preferred_bid", "object", "首选投标快照。", {"contractor_id": "C001", "bid_price": 108000000, "evaluation_score": 0.76}),
            ],
            actions=[
                _action("accept_contract", True, "接受授标条件。"),
                _action("request_contract_revision", False, "要求修改价格、交付或风险条款。"),
            ],
            final_decision_types=["owner_contract_award"],
        ),
        _contract(
            "decide_contract_terms",
            "Contractor",
            "承包商判断是否接受业主提出的最终合同条件。",
            inputs=[
                PROJECT,
                _field("preferred_bid", "object", "承包商自己的首选投标快照。", {"expected_profit": 0.09, "risk_level": 0.31}),
            ],
            actions=[
                _action("accept_terms", True, "接受合同条款。"),
                _action("request_revision", False, "要求修改合同条款。"),
            ],
            final_decision_types=["contract_negotiation"],
        ),
        _contract(
            "consider_supply_order",
            "Supplier",
            "供应商判断是否接受项目供货订单。",
            inputs=[
                PROJECT,
                _field("contractor_id", "string", "发出订单的承包商 ID。", "C001"),
                REQUIRED_RESOURCE,
                PRIOR_FIT,
            ],
            actions=[
                _action(
                    "accept_supply_order",
                    True,
                    "接受供货订单。",
                    _field("offer_score", "number", "供应方案综合匹配度。", 0.74, minimum=0, maximum=1),
                ),
                _action(
                    "decline_supply_order",
                    False,
                    "拒绝供货订单。",
                    _field("offer_score", "number", "供应方案综合匹配度。", 0.36, minimum=0, maximum=1),
                ),
            ],
            final_decision_types=["supplier_order_acceptance"],
        ),
        _contract(
            "select_supplier",
            "Contractor",
            "承包商从接受订单的供应商中选择一家。",
            inputs=[
                _field("offers", "array", "供应商报价数组；每项为 [Agent profile 快照, AgentDecision 快照]。", [[{"agent_id": "S001"}, {"accepted": True, "utility": 0.74}]]),
            ],
            actions=[
                _action(
                    "select_supplier",
                    True,
                    "选择一家供应商。",
                    _field("selected_supplier_id", "string", "被选供应商 ID。", "S001"),
                    _field("accepted_supplier_ids", "array", "全部接受订单的供应商 ID。", ["S001", "S004"]),
                ),
                _action("select_supplier", False, "没有供应商接受订单时返回失败。"),
            ],
            final_decision_types=["contractor_supplier_selection"],
        ),
    ]
)


_MONTHLY_ACTIONS = {
    "Owner": ["screen_investment_pipeline", "review_financing_capacity", "evaluate_market_demand", "prepare_project_scope", "adjust_investment_strategy"],
    "Architect": ["seek_design_commission", "build_cross_region_reputation", "improve_design_capability", "maintain_client_relationship"],
    "Engineer": ["review_technical_market", "improve_engineering_capability", "maintain_professional_qualifications"],
    "QS": ["update_cost_database", "seek_consulting_work", "review_cost_market", "improve_cost_estimation"],
    "Contractor": ["scan_tender_opportunities", "adjust_bid_strategy", "evaluate_region_entry", "seek_joint_venture_partner", "maintain_supplier_relationship"],
    "Supplier": ["adjust_inventory", "seek_supply_contract", "monitor_material_prices", "improve_supply_reliability"],
    "Government": ["publish_guidelines", "monitor_compliance", "adjust_regulatory_focus", "review_policy_feedback"],
    "Bank": ["review_credit_pipeline", "monitor_borrower_risk", "adjust_credit_terms"],
}

for _role, _actions in _MONTHLY_ACTIONS.items():
    _SPECS.append(
        _contract(
            "decide_monthly_operation",
            _role,
            "在没有阶段关键事件时选择该主体本月的低优先级经营活动。",
            inputs=[ENVIRONMENT],
            actions=[
                _action(action_type, True, f"{_role} 的合法月度经营动作。", LABEL, DESCRIPTION)
                for action_type in _actions
            ],
            final_decision_types=["monthly_enterprise_operation"],
            notes=["该操作属于 P3 background；不得改变项目正式状态。"],
        )
    )


OPERATION_CONTRACTS: dict[tuple[str, str], AgentOperationContractV1] = {
    (spec.operation, spec.role): spec for spec in _SPECS
}


def list_operation_contracts() -> list[AgentOperationContractV1]:
    return sorted(OPERATION_CONTRACTS.values(), key=lambda item: (item.operation, item.role))


def get_operation_contract(operation: str, role: str) -> AgentOperationContractV1:
    try:
        return OPERATION_CONTRACTS[(operation, role)]
    except KeyError as exc:
        raise ValueError(f"No operation contract for role={role!r}, operation={operation!r}.") from exc


def _matches_type(value: Any, value_type: str) -> bool:
    if "|" in value_type:
        return any(_matches_type(value, member) for member in value_type.split("|"))
    if value_type == "null":
        return value is None
    if value_type == "object":
        return isinstance(value, dict)
    if value_type == "array":
        return isinstance(value, list)
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _validate_fields(
    values: dict[str, Any],
    fields: list[AgentOperationFieldV1],
    *,
    location: str,
) -> None:
    for field in fields:
        if field.required and field.name not in values:
            raise ValueError(f"{location} is missing required field {field.name!r}.")
        if field.name not in values:
            continue
        value = values[field.name]
        if not _matches_type(value, field.value_type):
            raise ValueError(
                f"{location}.{field.name} must be {field.value_type}, got {type(value).__name__}."
            )
        if field.enum and value not in field.enum:
            raise ValueError(f"{location}.{field.name} must be one of {field.enum!r}.")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if field.minimum is not None and value < field.minimum:
                raise ValueError(f"{location}.{field.name} must be >= {field.minimum}.")
            if field.maximum is not None and value > field.maximum:
                raise ValueError(f"{location}.{field.name} must be <= {field.maximum}.")


def validate_operation_inputs(
    contract: AgentOperationContractV1,
    inputs: dict[str, Any],
) -> None:
    _validate_fields(inputs, contract.inputs, location=f"{contract.contract_id}.inputs")


def validate_operation_response(
    contract: AgentOperationContractV1,
    response: Any,
    inputs: dict[str, Any],
) -> None:
    action_type = getattr(response, "action_type", None)
    accepted = getattr(response, "accepted", None)
    data = getattr(response, "data", {}) or {}
    matching_actions = []
    for action in contract.actions:
        expected_action = action.action_type.format(**inputs)
        if action_type == expected_action and (action.accepted is None or action.accepted == accepted):
            matching_actions.append(action)
    if not matching_actions:
        allowed = sorted({action.action_type.format(**inputs) for action in contract.actions})
        raise ValueError(
            f"{contract.contract_id} returned invalid action/accepted pair "
            f"({action_type!r}, {accepted!r}); allowed actions are {allowed!r}."
        )
    _validate_fields(
        data,
        matching_actions[0].data_fields,
        location=f"{contract.contract_id}.response.data",
    )
