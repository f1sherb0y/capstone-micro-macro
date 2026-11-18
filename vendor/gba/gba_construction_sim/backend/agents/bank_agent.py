from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.environment import MacroEnvironment


class BankAgent(BaseEnterpriseAgent):
    def consider_financing(
        self,
        *,
        requested_amount: float,
        borrower_financial_capacity: float,
        project_risk: float,
        financing_condition_index: float,
    ):
        amount_fit = min(1.0, (self.profile.financial_capacity * 900_000_000) / max(requested_amount, 1.0))
        utility = (
            0.35 * borrower_financial_capacity
            + 0.30 * amount_fit
            + 0.20 * self.profile.risk_preference
            + 0.15 * financing_condition_index
            - 0.35 * project_risk
        )
        accepted = self.profile.has_available_resource(0.10) and utility >= 0.45
        approved_amount = min(requested_amount, self.profile.financial_capacity * 900_000_000)
        interest_rate = self.clamp(
            0.032
            + 0.040 * max(0.0, 1.0 - financing_condition_index)
            + 0.045 * project_risk
            - 0.012 * borrower_financial_capacity
            + self.rng.uniform(-0.003, 0.003),
            0.018,
            0.12,
        )
        return self.make_decision(
            "approve_financing" if accepted else "reject_financing",
            utility=utility,
            accepted=accepted,
            reason="Bank independently evaluated borrower capacity, requested exposure, market finance, and project risk.",
            factors={
                "decision_process": "BankAgent.consider_financing",
                "amount_fit": round(amount_fit, 3),
                "borrower_financial_capacity": round(borrower_financial_capacity, 3),
                "project_risk": round(project_risk, 3),
            },
            data={
                "requested_amount": round(requested_amount, 2),
                "approved_amount": round(approved_amount, 2),
                "interest_rate": round(interest_rate, 5),
                "conditions": [
                    "monthly progress reporting",
                    "cost-overrun notification",
                    "drawdown linked to verified milestones",
                ],
            },
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        operation = self.stable_pick(
            macro_environment.current_tick,
            [
                ("review_credit_pipeline", "Reviewed credit pipeline", "Reviewed project and working-capital financing applications."),
                ("monitor_borrower_risk", "Monitored borrower risk", "Monitored delay, cost, and payment risks across borrowers."),
                ("adjust_credit_terms", "Adjusted credit terms", "Adjusted credit conditions to financing-market changes."),
            ],
        )
        return self.make_decision(
            operation[0], utility=self.profile.available_resource(), accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )
