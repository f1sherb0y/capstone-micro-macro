from __future__ import annotations

from src.models import BidDocument, ParticipationDecision, SimulationState


def render_package_details(state: SimulationState) -> list[str]:
    lines = ["## 招标包详情", ""]
    awards = {item["package_id"]: item for item in state.simulated_award_result.get("package_awards", [])}
    for package in state.tender_packages:
        bids = [bid for bid in state.bid_documents if bid.package_id == package.package_id]
        discussions = [msg for msg in state.agent_discussion_history if msg.package_id == package.package_id]
        report = next((item for item in state.evaluation_report if item.package_id == package.package_id), None)
        award = awards.get(package.package_id, {})
        lines.extend(
            [
                f"### {package.package_id}",
                "",
                f"- 招标包名称：{package.package_name}",
                f"- 所需企业角色：{package.required_company_role}",
                f"- 范围：{package.scope}",
                f"- 已提交投标数：{len(bids)}",
                f"- 讨论记录数：{len(discussions)}",
                f"- 评标推荐：{report.recommended_winner if report else '暂无'}",
                f"- 模拟判给：{award.get('selected_bidder_name', '未判给')}",
                "",
                "投标参与决策：",
                "",
            ]
        )
        lines.extend(_participation_lines(state, package.package_id, bids))
        lines.extend(
            [
                "",
                "投标主体：",
                "",
            ]
        )
        lines.extend(_bidder_lines(bids))
        if report:
            lines.extend(["", f"评标摘要：{report.comparison_summary}", ""])
    return lines


def _bidder_lines(bids) -> list[str]:
    if not bids:
        return ["- 未收到投标文件。"]
    return [
        f"- {bid.bidder_id}：{bid.bidder_name}（{bid.bidder_type}），报价={_money(bid.quotation)}，摘要={bid.submission_summary}"
        for bid in bids
    ]


def _participation_lines(state: SimulationState, package_id: str, bids: list[BidDocument]) -> list[str]:
    decisions = [item for item in state.participation_decisions if item.package_id == package_id]
    if not decisions:
        return ["- 未记录投标参与决策。"]
    submitted_ids = {bid.bidder_id for bid in bids}
    company_bid_ids = {bid.bidder_id for bid in bids if bid.bidder_type == "company"}
    lines = []
    for decision in decisions:
        submitted = decision.company_id in company_bid_ids or _joined_submitted_consortium(state, decision, submitted_ids)
        status = "已提交投标" if submitted else "未提交投标"
        lines.append(f"- {decision.company_id}：{decision.decision}，{status}。原因：{decision.reason}")
    return lines


def _joined_submitted_consortium(state: SimulationState, decision: ParticipationDecision, submitted_ids: set[str]) -> bool:
    return any(
        item.package_id == decision.package_id
        and item.consortium_id in submitted_ids
        and decision.company_id in item.member_company_ids
        for item in state.consortiums
    )


def _money(value: float) -> str:
    return f"MOP {value:,.0f}"
