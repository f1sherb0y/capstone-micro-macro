from gba_construction_sim.backend.agents.base_agent import BaseEnterpriseAgent
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject


class OwnerAgent(BaseEnterpriseAgent):
    def evaluate_project_opportunity(
        self,
        opportunity: dict,
        macro_environment: MacroEnvironment,
        policy: PolicyRegime,
        *,
        active_project_count: int,
        target_pressure: float,
    ):
        region = opportunity["region"]
        budget = max(float(opportunity["budget"]), 1.0)
        complexity = float(opportunity["technical_complexity"])
        local_bonus = 0.14 if self.profile.region == region else 0.0
        active_region_bonus = 0.08 if region in self.profile.active_regions else 0.0
        cross_region_bonus = 0.06 * self.profile.cross_region_experience if self.profile.region != region else 0.0
        region_fit = local_bonus + active_region_bonus + cross_region_bonus
        budget_capacity = min(1.0, (self.profile.financial_capacity * 720_000_000) / budget)
        project_load_penalty = min(0.22, active_project_count * 0.07)
        macro_support = (
            0.09 * macro_environment.market_demand_index
            + 0.07 * macro_environment.financing_condition_index
            + 0.04 * macro_environment.policy_stability_index
        )
        risk_drag = (
            0.12 * complexity
            + 0.08 * policy.procedural_uncertainty
            + 0.06 * max(0.0, 1.0 - self.profile.payment_reliability)
        )
        score = (
            0.28 * self.profile.financial_capacity
            + 0.22 * self.profile.payment_reliability
            + 0.18 * self.profile.decision_speed
            + 0.14 * self.profile.management_capability
            + 0.10 * min(1.0, self.profile.available_resource())
            + 0.10 * budget_capacity
            + region_fit
            + macro_support
            + 0.08 * target_pressure
            - risk_drag
            - project_load_penalty
        )
        probability = self.clamp(0.12 + 0.78 * score, 0.08, 0.92)
        factors = {
            "decision_process": "OwnerAgent.evaluate_project_opportunity",
            "project_region": region,
            "project_type": opportunity["project_type"],
            "project_scale": opportunity.get("scale", "custom"),
            "owner_region": self.profile.region,
            "local_region_bonus": round(local_bonus, 3),
            "active_region_bonus": round(active_region_bonus, 3),
            "region_fit": round(region_fit, 3),
            "budget_capacity": round(budget_capacity, 3),
            "active_owner_projects": active_project_count,
            "project_load_penalty": round(project_load_penalty, 3),
            "macro_support": round(macro_support, 3),
            "risk_drag": round(risk_drag, 3),
            "available_resource": round(self.profile.available_resource(), 3),
            "financial_capacity": round(self.profile.financial_capacity, 3),
            "payment_reliability": round(self.profile.payment_reliability, 3),
            "decision_speed": round(self.profile.decision_speed, 3),
            "project_complexity": round(complexity, 3),
            "target_pressure": round(target_pressure, 3),
        }
        return self.make_decision(
            "initiate_project",
            utility=score,
            probability=probability,
            reason=(
                f"Owner evaluated the {opportunity.get('scale', 'custom')} {opportunity['project_type']} "
                f"opportunity in {region} against capital, portfolio load, demand, policy, and delivery risk."
            ),
            factors=factors,
            data={"selected_concept": dict(opportunity)},
        )

    def select_appointment(self, candidates: list[tuple[EnterpriseAgentProfile, object]], purpose: str):
        accepted = [(profile, decision) for profile, decision in candidates if getattr(decision, "accepted", False)]
        if not accepted:
            return self.make_decision(
                f"select_{purpose}",
                utility=0.0,
                probability=0.0,
                accepted=False,
                reason=f"No {purpose} candidate independently accepted the appointment.",
            )
        selected_profile, selected_decision = max(
            accepted,
            key=lambda item: (
                getattr(item[1], "utility", 0.0),
                item[0].collaboration_preference,
                item[0].available_resource(),
                item[0].agent_id,
            ),
        )
        return self.make_decision(
            f"select_{purpose}",
            utility=getattr(selected_decision, "utility", 0.5),
            probability=1.0,
            accepted=True,
            reason=f"Owner selected {selected_profile.name} from candidates that accepted the {purpose} appointment.",
            factors={
                "decision_process": "OwnerAgent.select_appointment",
                "accepted_candidate_count": len(accepted),
                "candidate_count": len(candidates),
            },
            data={
                "selected_agent_id": selected_profile.agent_id,
                "accepted_agent_ids": [profile.agent_id for profile, _decision in accepted],
            },
        )

    def select_tender_invitees(
        self,
        candidates: list[EnterpriseAgentProfile],
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        limit: int,
    ):
        scored = []
        for contractor in candidates:
            local_bonus = 0.10 if contractor.region == project.region else 0.0
            active_region_bonus = 0.05 if project.region in contractor.active_regions else 0.0
            cross_region_penalty = 0.08 if contractor.region != project.region else 0.0
            score = (
                0.24 * contractor.construction_capability
                + 0.16 * contractor.quality_management_capability
                + 0.14 * contractor.safety_management_capability
                + 0.13 * contractor.financial_capacity
                + 0.10 * contractor.cross_region_experience
                + 0.10 * contractor.collaboration_preference
                + 0.07 * contractor.available_resource()
                + 0.06 * policy.cross_region_qualification_recognition
                + local_bonus
                + active_region_bonus
                - cross_region_penalty
            )
            if macro_environment.financing_condition_index < 0.85:
                score += 0.04 * contractor.financial_capacity
            scored.append((contractor, score))
        ranked = sorted(scored, key=lambda item: (item[1], item[0].agent_id), reverse=True)
        selected = ranked[: max(1, limit)]
        return self.make_decision(
            "invite_contractors",
            utility=sum(score for _candidate, score in selected) / max(len(selected), 1),
            probability=1.0,
            accepted=bool(selected),
            reason="Owner independently formed a tender shortlist from qualified and available contractors.",
            factors={
                "decision_process": "OwnerAgent.select_tender_invitees",
                "candidate_count": len(candidates),
                "invite_limit": limit,
            },
            data={
                "selected_agent_ids": [candidate.agent_id for candidate, _score in selected],
                "ranked_candidates": [
                    {"agent_id": candidate.agent_id, "score": round(score, 4)}
                    for candidate, score in ranked[: max(12, limit)]
                ],
            },
        )

    def select_preferred_bid(self, evaluated_bids: list[dict], agents: dict[str, EnterpriseAgentProfile]):
        if not evaluated_bids:
            return self.make_decision(
                "select_preferred_bidder",
                utility=0.0,
                probability=0.0,
                accepted=False,
                reason="No valid evaluated bids were available.",
            )
        owner_ranked = []
        for bid in evaluated_bids:
            contractor = agents[bid["contractor_id"]]
            owner_score = (
                0.76 * float(bid["evaluation_score"])
                + 0.10 * contractor.financial_capacity
                + 0.08 * contractor.management_capability
                + 0.06 * contractor.collaboration_preference
            )
            owner_ranked.append({**bid, "owner_selection_score": owner_score})
        owner_ranked.sort(key=lambda bid: (bid["owner_selection_score"], bid["contractor_id"]), reverse=True)
        selected = owner_ranked[0]
        return self.make_decision(
            "select_preferred_bidder",
            utility=selected["owner_selection_score"],
            probability=1.0,
            accepted=True,
            reason="Owner selected the preferred bidder after reviewing the QS evaluation and delivery capacity.",
            factors={"decision_process": "OwnerAgent.select_preferred_bid", "valid_bid_count": len(owner_ranked)},
            data={"selected_contractor_id": selected["contractor_id"], "ranked_bids": owner_ranked},
        )

    def select_financing_offer(self, offers: list[tuple[EnterpriseAgentProfile, object]]):
        accepted = [(bank, decision) for bank, decision in offers if getattr(decision, "accepted", False)]
        if not accepted:
            return self.make_decision(
                "self_finance_project",
                utility=self.profile.financial_capacity,
                probability=1.0,
                accepted=True,
                reason="No bank accepted the requested exposure; the owner retained the project on its own balance sheet.",
                factors={
                    "decision_process": "OwnerAgent.select_financing_offer",
                    "candidate_count": len(offers),
                    "accepted_offer_count": 0,
                },
                data={"financing_mode": "owner_equity", "selected_bank_id": None},
            )
        ranked = sorted(
            accepted,
            key=lambda item: (
                getattr(item[1], "utility", 0.0)
                - 1.5 * float(getattr(item[1], "data", {}).get("interest_rate", 0.0)),
                item[0].agent_id,
            ),
            reverse=True,
        )
        bank, decision = ranked[0]
        return self.make_decision(
            "select_project_finance",
            utility=getattr(decision, "utility", 0.5),
            probability=1.0,
            accepted=True,
            reason=f"Owner selected {bank.name} from banks that independently approved the financing request.",
            factors={
                "decision_process": "OwnerAgent.select_financing_offer",
                "candidate_count": len(offers),
                "accepted_offer_count": len(accepted),
            },
            data={
                "financing_mode": "bank_finance",
                "selected_bank_id": bank.agent_id,
                "accepted_bank_ids": [candidate.agent_id for candidate, _decision in accepted],
                "selected_offer": decision.to_event_data(),
            },
        )

    def decide_contract_award(self, project: ConstructionProject, preferred_bid: dict):
        contract_sum = float(project.contract_sum or preferred_bid.get("bid_price") or 0.0)
        budget_fit = self.clamp(1.15 - contract_sum / max(project.initial_budget, 1.0))
        delivery_fit = self.clamp(
            0.45 * float(preferred_bid.get("evaluation_score", 0.5) or 0.5)
            + 0.30 * (1.0 - float(preferred_bid.get("risk_level", 0.5) or 0.5))
            + 0.25 * self.profile.payment_reliability
        )
        utility = self.clamp(
            0.38 * budget_fit
            + 0.34 * delivery_fit
            + 0.18 * self.profile.management_capability
            + 0.10 * self.profile.risk_preference
        )
        accepted = utility >= 0.46
        return self.make_decision(
            "accept_contract" if accepted else "request_contract_revision",
            utility=utility,
            accepted=accepted,
            reason=(
                "Owner accepted the final award terms after reviewing price, delivery confidence, risk, and payment capacity."
                if accepted else
                "Owner requested revised award terms because price, delivery confidence, or risk allocation was inadequate."
            ),
            factors={
                "decision_process": "OwnerAgent.decide_contract_award",
                "budget_fit": round(budget_fit, 4),
                "delivery_fit": round(delivery_fit, 4),
                "contract_sum": round(contract_sum, 2),
            },
        )

    def decide_monthly_operation(self, macro_environment: MacroEnvironment):
        free_resource = self.profile.available_resource() / max(self.profile.total_resource_capacity, 1e-9)
        if macro_environment.market_demand_index > 1.05 and macro_environment.financing_condition_index > 0.9 and free_resource > 0.35:
            operation = (
                "screen_investment_pipeline",
                "Screened investment pipeline",
                f"Screened candidate GBA sites, project types, scale, and policy timing in {self.profile.region}.",
            )
        elif macro_environment.financing_condition_index < 0.85:
            operation = (
                "review_financing_capacity",
                "Reviewed financing capacity",
                "Checked capital, payment reliability, and debt exposure before adding another project.",
            )
        else:
            operation = self.stable_pick(
                macro_environment.current_tick,
                [
                    ("evaluate_market_demand", "Evaluated market demand", "Reviewed demand and absorption signals for the project pipeline."),
                    ("prepare_project_scope", "Prepared project scope", "Prepared a location, project type, scale, and budget shortlist."),
                    ("adjust_investment_strategy", "Adjusted investment strategy", "Rebalanced project timing against financing and policy uncertainty."),
                ],
            )
        return self.make_decision(
            operation[0], utility=free_resource, accepted=True, reason=operation[2],
            data={"label": operation[1], "description": operation[2]},
        )
