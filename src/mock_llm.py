from __future__ import annotations

import json
import hashlib
import re

from src.mock_messages import mock_agent_message


class MockLLMClient:
    """Deterministic local LLM substitute for end-to-end prototype verification."""

    env_files: list[str] = []

    async def achat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        return self.chat(messages, temperature)

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        prompt = messages[-1]["content"]
        if "PROJECT_IDEA" in prompt:
            return self._json(
                project_name="澳门交通枢纽复合公共设施项目",
                project_type="urban_infrastructure_building",
                location="澳门",
                owner_intent="建设一个连接公共交通、商业配套和社区服务功能的综合公共设施。",
                scale_hint="中大型",
                budget_hint="MOP 18亿至26亿",
                schedule_hint="36个月",
                constraints=["城市用地紧凑", "公共安全要求高", "需要与交通设施接口协调"],
            )
        if "COMPANIES" in prompt:
            return self._json(companies=self._companies())
        if "AGENT_MESSAGE" in prompt:
            return self._json(**mock_agent_message(prompt))
        if "MANAGEMENT_DECISION" in prompt or prompt.startswith("RECONSIDER_AFTER_CONSORTIUM"):
            decision = "bid_with_consortium" if prompt.startswith("MANAGEMENT_DECISION") and "contractor_package" in prompt and "Company id: contractor_001" in prompt else "bid"
            return self._json(
                thoughts="我在综合判断项目适配度、风险、资源压力和商业价值，然后形成管理层决策。",
                decision=decision,
                reason="管理层基于内部讨论，综合考虑机会、能力、资源和风险后形成该决策。",
                content=f"最终管理层决策为：{decision}。",
                **self._condition_disposition(prompt),
            )
        if "ROSTER" in prompt:
            return self._json(
                members=[
                    self._member("技术负责人", "技术部", "技术负责人", ["判断技术适配性"], "medium"),
                    self._member("商务经理", "商务部", "商务经理", ["判断商业风险"], "medium"),
                    self._member("总经理", "管理层", "总经理", ["形成公司最终决策"], "final"),
                ]
            )
        if "OWNER_PACKAGE_BRIEF" in prompt:
            return self._json(
                project_scope="业主细化后的公共设施项目，包含设计、施工、供应和第三方监管服务需求。",
                functional_needs=["公共通行", "交通接口", "社区服务"],
                technical_needs=["BIM协同", "安全的城市物流组织", "质量报告"],
                budget_approach="以业主预算提示作为可承受边界。",
                schedule_approach="以业主工期提示作为目标交付窗口。",
                owner_control_needs=["业主审查节奏", "现场安全要求", "质量目标跟踪"],
                risk_priorities=["接口风险", "公共安全", "工期压力"],
                package_plan=self._packages(),
            )
        if "CONSORTIUM" in prompt:
            return self._json(
                status="formed",
                consortium_name="湾建-中城交通施工组合体",
                member_company_ids=["contractor_001", "contractor_002"],
                formation_reason="成员企业将本地交付能力与交通接口专业经验结合，提高承包包投标可信度。",
                role_split={
                    "contractor_001": "牵头施工协调和本地交付",
                    "contractor_002": "负责交通接口方法和专项技术支持",
                },
                agreement_summary="湾区建设与中城交通建设组成承包包组合体，共同承担投标责任。",
            )
        if "BID_DOCUMENT" in prompt:
            return self._json(**self._bid_document(prompt))
        if "EVALUATION" in prompt:
            return self._json(**self._evaluation(prompt))
        if "AWARD" in prompt:
            ids = re.findall(r"- ([^:]+):", prompt)
            recommended = self._line_value(prompt, "Evaluation recommended winner")
            selected = recommended if recommended in ids else ids[0] if ids else ""
            name_match = re.search(rf"- {re.escape(selected)}: ([^,\n]+)", prompt)
            name = name_match.group(1) if name_match else selected
            return self._json(
                thoughts="我在确认评标记录是否足以支撑业主作出负责任的模拟判给决定。",
                selected_bidder_id=selected,
                decision_reason=(
                    f"业主确认判给 {name}，因为评标记录显示该投标人在技术回应、交付信心、成本暴露和业主风险控制之间形成了较好的综合平衡。"
                ),
                content=f"最终业主模拟判给决定选择 {name}，并记录该招标包的判给责任依据。",
            )
        return self._json(thoughts="Mock内部推理。", content="Mock回应", recommendation="continue", decision_impact="neutral")

    @staticmethod
    def _json(**kwargs) -> str:
        return json.dumps(kwargs, ensure_ascii=False)

    def _bid_document(self, prompt: str) -> dict[str, object]:
        bidder_id = self._line_value(prompt, "Bidder id")
        bidder_name = self._line_value(prompt, "Bidder name")
        package_id = self._line_value(prompt, "Package id")
        tech_score = 55 + self._stable_number(bidder_id, package_id, "technical", modulo=36)
        risk_score = 55 + self._stable_number(bidder_id, package_id, "risk", modulo=36)
        control_score = 55 + self._stable_number(bidder_id, package_id, "owner_control", modulo=36)
        price_index = self._stable_number(bidder_id, package_id, "price", modulo=25)
        base_price = self._base_price(package_id)
        quotation = round(base_price * (0.88 + price_index / 100), 2)
        return {
            **self._condition_disposition(prompt),
            "technical_proposal": f"技术适配评分：{tech_score}。{bidder_name} 根据招标包要求提交对应角色的技术方案。",
            "implementation_plan": "组建专项团队，并通过阶段性里程碑管理交付。",
            "quotation": quotation,
            "schedule_commitment": "按照业主工期要求分阶段提交成果。",
            "owner_control_response": f"业主控制评分：{control_score}。回应业主审查、安全要求、质量目标和报告纪律。",
            "risk_response": f"风险控制评分：{risk_score}。通过接口会议和管理层复核控制主要风险。",
            "submission_summary": "本投标文件完整覆盖技术、商务、业主控制和风险回应要求。",
            "quotation_breakdown": [{"item": "完整招标包暂定总额", "amount": quotation, "basis": "mock确定性报价"}],
        }

    @staticmethod
    def _condition_disposition(prompt: str) -> dict[str, object]:
        marker = "Complete condition register (not truncated):\n"
        if marker not in prompt:
            return {}
        records, _ = json.JSONDecoder().raw_decode(prompt.rsplit(marker, 1)[1])
        pending = [r["condition_id"] for r in records if r["status"] != "verified"]
        return {
            "unresolved_condition_ids": pending,
            # Mock never manufactures a receipt or asserts verification.
            "verified_condition_ids": [],
            "bid_assumptions": ["本地测试：待核实事项保留为投标假设，未宣称已确认。"] if pending else [],
        }

    def _evaluation(self, prompt: str) -> dict[str, object]:
        bids = self._parse_bid_blocks(prompt)
        scored = []
        min_quote = min((bid["quotation"] for bid in bids), default=0.0)
        for bid in bids:
            price_score = self._price_score(bid["quotation"], min_quote)
            total = round(
                bid["technical_score"] * 0.45
                + bid["risk_score"] * 0.25
                + bid["control_score"] * 0.15
                + price_score * 0.15,
                2,
            )
            scored.append((total, bid["bidder_id"], bid, price_score))
        scored.sort(key=lambda item: (-item[0], item[1]))
        winner = scored[0][2]["bidder_id"] if scored else ""
        evaluations = []
        for total, _bidder_id, bid, price_score in scored:
            evaluations.append(
                {
                    "bid_id": bid["bid_id"],
                    "bidder_id": bid["bidder_id"],
                    "bidder_name": bid["bidder_name"],
                    "technical_view": f"mock技术适配分={bid['technical_score']}，综合分={total}。",
                    "cost_view": f"报价={bid['quotation']}，价格分={price_score}。",
                    "owner_control_view": f"业主控制分={bid['control_score']}。",
                    "strengths": [f"mock综合分 {total}"],
                    "concerns": [f"风险控制分 {bid['risk_score']}，需要后续复核真实依据"],
                }
            )
        return {
            "bid_evaluations": evaluations,
            "comparison_summary": "mock评标按技术适配、风险控制、业主控制和报价形成确定性综合分，并推荐综合分最高者。",
            "owner_review_notes": "该 mock 评分只用于消除顺序偏置和验证流程，不代表真实采购评标模型。",
            "recommended_bidder_id": winner,
        }

    def _parse_bid_blocks(self, prompt: str) -> list[dict[str, object]]:
        bids_text = prompt.split("Bids:", 1)[1] if "Bids:" in prompt else prompt
        blocks = re.split(r"\n\s*---\s*\n", bids_text)
        bids = []
        for block in blocks:
            bidder_id = self._line_value(block, "bidder_id")
            if not bidder_id:
                continue
            quotation = self._float_value(self._line_value(block, "quotation"))
            bids.append(
                {
                    "bid_id": self._line_value(block, "bid_id"),
                    "bidder_id": bidder_id,
                    "bidder_name": self._line_value(block, "bidder_name"),
                    "quotation": quotation,
                    "technical_score": self._embedded_score(block, "技术适配评分", default=65),
                    "risk_score": self._embedded_score(block, "风险控制评分", default=65),
                    "control_score": self._embedded_score(block, "业主控制评分", default=65),
                }
            )
        return bids

    @staticmethod
    def _line_value(text: str, label: str) -> str:
        match = re.search(rf"^{re.escape(label)}: ([^\n]+)", text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _embedded_score(text: str, label: str, default: int) -> int:
        match = re.search(rf"{re.escape(label)}[:：]\s*(\d+)", text)
        return int(match.group(1)) if match else default

    @staticmethod
    def _float_value(value: str) -> float:
        try:
            return float(value)
        except ValueError:
            return 0.0

    @staticmethod
    def _price_score(quotation: float, min_quote: float) -> float:
        if quotation <= 0 or min_quote <= 0:
            return 60.0
        premium = max(0.0, (quotation - min_quote) / min_quote)
        return round(max(40.0, 100.0 - premium * 100), 2)

    @staticmethod
    def _stable_number(*parts: str, modulo: int) -> int:
        payload = "|".join(parts).encode("utf-8")
        return int(hashlib.sha256(payload).hexdigest()[:8], 16) % modulo

    @staticmethod
    def _base_price(package_id: str) -> float:
        return {
            "design_package": 32000000.0,
            "supplier_package": 58000000.0,
            "contractor_package": 260000000.0,
            "supervision_package": 18000000.0,
        }.get(package_id, 100000000.0)

    @staticmethod
    def _packages() -> list[dict[str, object]]:
        return [
            MockLLMClient._package("design_package", "design", "设计服务包", "designer"),
            MockLLMClient._package("supplier_package", "supplier", "设备材料供应包", "supplier"),
            MockLLMClient._package("contractor_package", "contractor", "主施工承包包", "contractor"),
            MockLLMClient._package("supervision_package", "supervision", "第三方监管服务包", "supervisor"),
        ]

    @staticmethod
    def _companies() -> list[dict[str, object]]:
        return [
            MockLLMClient._company("owner_001", "港城公共发展业主有限公司", "owner", ["design_package", "supplier_package", "contractor_package", "supervision_package"]),
            MockLLMClient._company("designer_001", "顶峰综合设计有限公司", "designer", ["design_package"]),
            MockLLMClient._company("designer_002", "珠江工程设计院", "designer", ["design_package"]),
            MockLLMClient._company("designer_003", "港轴设计工作室", "designer", ["design_package"]),
            MockLLMClient._company("supplier_001", "智联系统供应有限公司", "supplier", ["supplier_package"]),
            MockLLMClient._company("supplier_002", "都会材料设备有限公司", "supplier", ["supplier_package"]),
            MockLLMClient._company("supplier_003", "城建设备供应有限公司", "supplier", ["supplier_package"]),
            MockLLMClient._company("contractor_001", "湾区建设有限公司", "contractor", ["contractor_package"]),
            MockLLMClient._company("contractor_002", "中城交通建设有限公司", "contractor", ["contractor_package"]),
            MockLLMClient._company("contractor_003", "城联营造有限公司", "contractor", ["contractor_package"]),
            MockLLMClient._company("supervisor_001", "诚信监管服务有限公司", "supervisor", ["supervision_package"]),
            MockLLMClient._company("supervisor_002", "城质安全顾问有限公司", "supervisor", ["supervision_package"]),
            MockLLMClient._company("supervisor_003", "顶点现场监测有限公司", "supervisor", ["supervision_package"]),
        ]

    @staticmethod
    def _company(company_id: str, name: str, role: str, packages: list[str]) -> dict[str, object]:
        return {
            "company_id": company_id,
            "company_name": name,
            "company_role": role,
            "profile": f"面向澳门建筑招投标仿真的{role}类型企业。",
            "strengths": ["交付记录可信", "具备与角色匹配的技术能力"],
            "weaknesses": ["紧凑城市条件下存在资源压力"],
            "capability_areas": [f"{role}相关能力"],
            "sim_experience_notes": ["城市公共设施项目经验"],
            "capacity": "中大型团队",
            "risk_signals": ["协调风险"],
            "eligible_packages": packages,
        }

    @staticmethod
    def _package(package_id: str, package_type: str, name: str, role: str) -> dict[str, object]:
        return {
            "package_id": package_id,
            "package_type": package_type,
            "package_name": name,
            "scope": f"{name}范围由业主方 agent 细化形成。",
            "required_company_role": role,
            "package_capability_needs": ["角色匹配能力", "可投入团队"],
            "bid_content_requests": ["技术回应", "报价", "工期", "风险应对"],
            "pricing_approach": "提交MOP报价。",
            "owner_comparison_focus": ["技术适配", "价格合理性", "交付信心"],
            "owner_decision_policy": "业主在定性评估后作出模拟判给选择。",
        }

    @staticmethod
    def _member(name: str, department: str, position: str, responsibilities: list[str], authority: str) -> dict[str, object]:
        return {
            "agent_name": name,
            "department": department,
            "position": position,
            "personal_profile": f"{name} 是务实的{position}，发言前会先判断本岗位相关的取舍。",
            "responsibilities": responsibilities,
            "decision_authority": authority,
            "communication_style": "直接、岗位导向、务实",
        }
