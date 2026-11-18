from __future__ import annotations


def mock_agent_message(prompt: str) -> dict[str, str]:
    if "External negotiation requirement:" in prompt or "external negotiation meeting" in prompt:
        return {
            "thoughts": "我在保护本公司的角色边界、风险暴露和谈判位置。",
            "content": (
                "**谈判意见：** 如果责任边界清楚，本公司可以考虑联合投标。\n\n"
                "- 其他公司需要明确各自的交付责任和商业边界。\n"
                "- 只有当分工能提升业主信心时，我们才应共享投标主体身份。"
            ),
            "recommendation": "negotiate_with_conditions",
            "decision_impact": "mixed",
        }
    return {
        "thoughts": "我在权衡项目机会、工作负荷、交付风险，以及我的岗位能否支撑这个招标包。",
        "content": (
            "**我的意见：** 这个机会具备参与价值，但是否支持投标取决于我们如何处理交付风险。\n\n"
            "- 招标包整体与公司能力匹配，但紧凑场地和接口工作可能拉紧资源。\n"
            "- 我需要同事复核工期假设，并确认是否需要合作伙伴支持。"
        ),
        "recommendation": "support_with_conditions",
        "decision_impact": "mixed",
    }
