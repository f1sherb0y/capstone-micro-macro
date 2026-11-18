"""Simulation-side contract commit, kept outside the upstream GBA directory."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

from gba_construction_sim.backend.core.enums import EngagementStatus
from gba_construction_sim.backend.simulation.engagement_manager import EngagementManager
from integration.contracts import CommitRejected, digest


class ContractCommitter:
    def __init__(self, engine, dataset):
        self.engine, self.dataset = engine, dataset

    def commit(self, session, tick):
        proposal, spec = session.proposal, session.spec
        if proposal is None:
            raise CommitRejected("No accepted contract proposal")
        proposal.validate()
        project = self.engine.projects[spec.project_id]
        committed = project.flags.setdefault("package_contracts", {})
        if spec.package_id in committed:
            receipt = committed[spec.package_id]
            if receipt["proposal_hash"] != digest(asdict(proposal)):
                raise CommitRejected("Conflicting duplicate package contract")
            return receipt
        session.verify_negotiation(proposal)
        if proposal.simulation_id != self.engine.simulation_id or proposal.project_id != spec.project_id or proposal.package_id != spec.package_id:
            raise CommitRejected("Proposal identity mismatch")
        if proposal.session_id != session.session_id or proposal.snapshot_version != session.snapshot.version or proposal.buyer_id != session.buyer_id:
            raise CommitRejected("Proposal authorization/snapshot mismatch")
        if session.next_stage != 9 or not set(proposal.members).issubset(spec.candidate_ids):
            raise CommitRejected("Incomplete session or ineligible bidder")
        if proposal.currency != spec.currency or proposal.price > spec.budget:
            raise CommitRejected("Price/currency violates approved package")
        bids = [b for b in session.state.bid_documents if b.package_id == spec.package_id and b.bid_id == proposal.bid_id and b.bidder_id == proposal.bidder_id]
        if len(bids) != 1 or bids[0].quotation != proposal.price:
            raise CommitRejected("Contract price is not the submitted bid")
        if not set(spec.depends_on).issubset(committed):
            raise CommitRejected("Predecessor contracts not committed")
        if abs(sum(proposal.resource_commitments.values()) - spec.resource_required) > 1e-8:
            raise CommitRejected("Total resource promise differs from authorized requirement")
        if spec.parent_package_id:
            parent = committed[spec.parent_package_id]
            if proposal.buyer_id != parent["lead_id"]:
                raise CommitRejected("Only the parent contractor may buy included supply")
            siblings = sum(c["price"] for c in committed.values() if c["parent_package_id"] == spec.parent_package_id)
            if siblings + proposal.price > parent["price"]:
                raise CommitRejected("Included procurement exceeds parent contract price")
        elif spec.cost_inclusion == "owner_additional" and proposal.buyer_id != project.owner_id:
            raise CommitRejected("Owner expenditure needs the project owner's authorization")
        for member, amount in proposal.resource_commitments.items():
            agent = self.engine.agents[member]
            if agent.role != spec.macro_role or agent.available_resource() + 1e-9 < amount:
                raise CommitRejected(f"Resource/role conflict for {member}")
        owner_total = sum(c["price"] for c in committed.values() if c["cost_inclusion"] == "owner_additional")
        if spec.cost_inclusion == "owner_additional" and owner_total + proposal.price > project.initial_budget:
            raise CommitRejected("Project budget exceeded")
        # All validations precede all resource writes. The core invokes this on
        # one simulation thread; no member can be accepted independently.
        # Execute the native engagement operations on staged copies first.
        # Observers never see an intermediate half-signed consortium.
        pending_events = []
        class BufferedEvents:
            def record(self, *args, **kwargs):
                pending_events.append((args, kwargs))
        staged_project = project.model_copy(deep=True)
        staged_agents = {key: self.engine.agents[key].model_copy(deep=True) for key in proposal.members}
        manager = EngagementManager(BufferedEvents())
        manager._counter = self.engine.engagement_manager._counter
        for member, amount in proposal.resource_commitments.items():
            agent = staged_agents[member]
            engagement = manager.find(staged_project, member, spec.macro_role)
            if engagement and engagement.status == EngagementStatus.ACTIVE:
                manager.activate_engagement(engagement, agent, staged_project, tick, engagement.resource_allocation + amount)
            elif engagement and engagement.status in {EngagementStatus.INVITED, EngagementStatus.BIDDING}:
                manager.activate_engagement(engagement, agent, staged_project, tick, amount)
            elif engagement and engagement.status == EngagementStatus.STANDBY:
                manager.activate_engagement(engagement, agent, staged_project, tick, amount)
            else:
                manager.create_engagement(staged_project, agent, spec.macro_role, EngagementStatus.ACTIVE, tick, amount,
                                          can_be_recalled=spec.kind == "design")
        project.engagements = staged_project.engagements
        for member, agent in staged_agents.items():
            self.engine.agents[member].occupied_resource = agent.occupied_resource
        self.engine.engagement_manager._counter = manager._counter
        receipt = {**asdict(proposal), "contract_id": proposal.proposal_id, "kind": spec.kind,
                   "signed_tick": tick, "status": "committed", "proposal_hash": digest(asdict(proposal)),
                   "cost_inclusion": spec.cost_inclusion, "parent_package_id": spec.parent_package_id,
                   "price_indices_at_bid": deepcopy(session.snapshot.public["environment"])}
        committed[spec.package_id] = receipt
        project.contracts.append({**receipt, "contractor_id": proposal.lead_id, "contract_sum": proposal.price})
        for args, kwargs in pending_events:
            kwargs["project"] = project
            self.engine.events.record(*args, **kwargs)
        # Native design/administrative consumers retain compatibility IDs.
        if spec.kind == "design":
            project.selected_architect_id = project.selected_architect_id or proposal.lead_id
        elif spec.kind == "cost_consulting":
            project.selected_qs_id = project.selected_qs_id or proposal.lead_id
        elif spec.kind == "construction":
            project.selected_contractor_id = project.selected_contractor_id or proposal.lead_id
            project.contract_sum = sum(c["price"] for c in committed.values() if c["kind"] == "construction")
        elif spec.kind == "supply":
            project.selected_supplier_ids = sorted(set(project.selected_supplier_ids) | set(proposal.members))
        if spec.kind in {"design", "cost_consulting"} and spec.cost_inclusion == "owner_additional":
            # Explicit first-version accounting assumption: service fees booked
            # at signing; supply included in construction is never added again.
            project.performance.actual_cost += proposal.price
        project.flags["owner_procurement_total"] = sum(c["price"] for c in committed.values() if c["cost_inclusion"] == "owner_additional")
        self.engine.events.record(tick, "package_contract_committed", "Micro organizational decisions committed by GBA",
                                  project=project, agent_id=proposal.buyer_id,
                                  data={"package_id": spec.package_id, "contract_id": receipt["contract_id"],
                                        "buyer_id": proposal.buyer_id, "members": proposal.members,
                                        "price": proposal.price, "currency": proposal.currency})
        return receipt
