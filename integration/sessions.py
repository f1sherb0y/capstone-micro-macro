"""Recoverable micro procurement sessions reusing the existing tender stages."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path

from src.agent_runtime import AgentRuntime
from src.run_audit import LLMCallAuditLogger, llm_client_metadata
from src.models import Consortium, SimulationState, TenderPackage, OwnerRequirements, dump, load_simulation_state
from src.stages.rosters import generate_member_agents
from src.stages.owner_requirements import owner_refine_requirements
from src.stages.participation import run_bid_participation
from src.stages.consortiums import form_consortiums
from src.stages.reconsideration import reconsider_after_failed_consortiums
from src.stages.bid_documents import generate_bid_documents
from src.stages.opening import open_bids
from src.stages.evaluation import evaluate_bids
from src.stages.award import make_award_decisions
from integration.contracts import ContractProposal, DecisionSnapshot, IntegrationError, digest
from src.coordination.negotiations import NegotiationJournal
from src.coordination.tasks import TaskIdentity, task_digest


STAGES = ("requirements", "participation", "consortiums", "reconsideration", "bids", "opening", "evaluation", "award", "signatures")
SAFE_RECOVERY = {"json_parse_retry", "response_contract_retry", "response_normalized"}
FINAL_CONTRACT_REVISION = 2


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def require_choice(data):
    if (not isinstance(data, dict) or set(data) != {"action", "reason"}
            or data["action"] not in {"accept", "reject", "revise"}
            or not isinstance(data["reason"], str) or not data["reason"].strip()):
        raise ValueError("Expected action accept/reject/revise and a reason: return exactly the two keys "
                         "action and reason, with any requested clause wording written inside the reason string")


class OrganizationRegistry:
    def __init__(self, simulation_id, directory):
        self.simulation_id = simulation_id
        self.path = Path(directory) / "organizations.json"
        self.rosters = {}
        self.memories = {}
        self.events_seen = set()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["simulation_id"] != simulation_id:
                raise IntegrationError("Organization store belongs to another simulation")
            self.rosters = load_simulation_state({"company_agent_rosters": data["rosters"]}).company_agent_rosters
            self.memories = data["memories"]
            self.events_seen = set(data["events_seen"])

    async def ensure(self, companies, runtime):
        missing = [c for c in companies if c.company_id not in self.rosters]
        if missing:
            before = len(runtime.recovery_events)
            generated = await generate_member_agents(missing, runtime)
            if any(e["kind"] not in SAFE_RECOVERY for e in runtime.recovery_events[before:]):
                raise IntegrationError("Roster generation degraded; retry without creating fallback identities")
            self.rosters.update(generated)
            self.save()
        return {c.company_id: deepcopy(self.rosters[c.company_id]) for c in companies}

    def observe(self, event_id, recipients, payload):
        if event_id in self.events_seen:
            return
        for recipient in recipients:
            self.memories.setdefault(recipient, []).append(deepcopy({"event_id": event_id, **payload}))
        self.events_seen.add(event_id)
        self.save()

    def save(self):
        atomic_json(self.path, {"simulation_id": self.simulation_id, "rosters": {key: dump(value) for key, value in self.rosters.items()},
                               "memories": self.memories, "events_seen": sorted(self.events_seen)})


class ProcurementSession:
    def __init__(self, dataset, spec, snapshot, buyer_id, registry, llm, directory, profile="smoke"):
        self.dataset, self.spec, self.snapshot = dataset, spec, snapshot
        self.buyer_id, self.registry = buyer_id, registry
        self.session_id = f"{snapshot.simulation_id}/{spec.package_id}/round-{snapshot.round_id}"
        self.path = Path(directory) / (digest(self.session_id) + ".json")
        self.negotiation_path = Path(directory) / (digest(self.session_id) + "_negotiations.sqlite")
        audit_dir = Path(directory) / (digest(self.session_id) + "_audit")
        audit_dir.mkdir(parents=True, exist_ok=True)
        attempt_file = audit_dir / "attempt.json"
        attempt = json.loads(attempt_file.read_text(encoding="utf-8"))["attempt"] + 1 if attempt_file.exists() else 1
        atomic_json(attempt_file, {"attempt": attempt})
        self.runtime = AgentRuntime(llm, profile=profile, audit_logger=LLMCallAuditLogger(audit_dir, self.session_id, llm, attempt))
        self.runtime.context_resolver = snapshot.for_entity
        self.next_stage = 0
        self.proposal = None
        self.status, self.error = "ready", None
        self.state = SimulationState(project_idea=dataset.project_idea(spec.project_id))
        # Scope contains only this buyer and eligible bidders. Other firms' private
        # state is supplied exclusively by the per-entity context resolver.
        def public_company(key):
            return replace(dataset.companies[key], weaknesses=[], risk_signals=[],
                           capacity="Private; consult your authorized own_state", past_project_experience=[])
        self.state.companies = [replace(public_company(buyer_id), company_role="owner")]
        self.state.companies += [public_company(key) for key in spec.candidate_ids]
        self.state.validation_context["integration"] = True
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema_version"] != "1.0" or digest(data["snapshot"]) != snapshot.version or data["spec"] != json.loads(json.dumps(asdict(spec))):
                raise IntegrationError("Checkpoint input/version conflict; start a new round")
            self.state = load_simulation_state(data["state"])
            self.next_stage, self.status = data["next_stage"], data["status"]
            self.proposal = ContractProposal(**data["proposal"]) if data["proposal"] else None
        self.runtime.restore_message_counter(self.state)

    def save(self):
        atomic_json(self.path, {"schema_version": "1.0", "session_id": self.session_id,
                               "snapshot": asdict(self.snapshot), "spec": asdict(self.spec),
                               "next_stage": self.next_stage, "status": self.status, "error": self.error,
                               "state": dump(self.state), "proposal": asdict(self.proposal) if self.proposal else None})

    async def advance_to(self, last_stage):
        # GBA's synchronous tick uses a fresh event loop for each decision
        # window. Recreate loop-bound throttling primitives between windows.
        from src.llm_throttle import LLMThrottle
        self.runtime.throttle = LLMThrottle()
        limit = STAGES.index(last_stage)
        while self.next_stage <= limit:
            old_state, old_proposal = deepcopy(self.state), deepcopy(self.proposal)
            before = len(self.runtime.recovery_events)
            stage = STAGES[self.next_stage]
            try:
                self.state.company_agent_rosters = await self.registry.ensure(self.state.companies, self.runtime)
                await getattr(self, f"_{stage}")()
                unsafe = [e for e in self.runtime.recovery_events[before:] if e["kind"] not in SAFE_RECOVERY]
                if unsafe:
                    raise IntegrationError(f"Technical degradation in {stage}: {unsafe}")
            except Exception as exc:
                self.state, self.proposal = old_state, old_proposal
                self.runtime.restore_message_counter(self.state)
                self.status, self.error = "failed", f"{type(exc).__name__}: {exc}"
                self.save()
                raise IntegrationError(f"Session {self.session_id}, stage {stage}: {exc}") from exc
            self.next_stage += 1
            self.status = "awaiting_commit" if self.next_stage == len(STAGES) and self.proposal else "ready"
            if self.next_stage == len(STAGES) and not self.proposal:
                self.status = "no_contract"
            self.error = None
            self.save()
        return self.proposal

    async def _requirements(self):
        spec = self.spec
        self.state.validation_context["authorized_packages"] = {spec.package_id: {
            "package_type": {"construction": "contractor", "cost_consulting": "supervision", "supply": "supplier"}.get(spec.kind, spec.kind),
            "required_company_role": spec.micro_role, "scope": spec.scope, "budget": spec.budget,
            "currency": spec.currency, "buyer_id": self.buyer_id}}
        self.state.owner_requirements = await owner_refine_requirements(self.state, self.runtime, self.runtime.profile)
        self.state.tender_packages = self.state.owner_requirements.tender_package_plan
        for package in self.state.tender_packages:
            package.scope = f"Authorized scope: {spec.scope}\nBuyer refinement: {package.scope}"
            package.pricing_requirements += f"\nBinding currency: {spec.currency}; package ceiling: {spec.budget}."

    async def _participation(self):
        await run_bid_participation(self.state, self.runtime)

    async def choice(self, company_id, marker, terms, revision=None):
        company = next(c for c in self.state.companies if c.company_id == company_id)
        text = json.dumps(terms, ensure_ascii=False)
        if marker == "CONTRACT_ACCEPTANCE":
            text += ("\nSIMULATION CONTRACT REVIEW: Attached bid commitments are part of the proposed contract. "
                     "Any negotiated_clauses are the current proposed amendments and supersede conflicting bid wording "
                     "only if every party accepts this exact revision. Price, currency, scope, members and resources "
                     "remain the canonical fields; text cannot silently change them. This stage authorizes executable "
                     "simulation obligations, not a claim that future engineering deliverables or statutory approvals "
                     "have already occurred. Evaluate future deliverables as obligations with review/acceptance conditions. "
                     "Do not invent missing external evidence. Reject or request revision for material unresolved risks.")
            if revision is not None:
                # The buyer used to request its own missing position three times and
                # exhaust every draft. State who decides what, and that drafts are bounded.
                text += (f"\nNEGOTIATION ROUND: this is draft revision {revision}; revision {FINAL_CONTRACT_REVISION} is the last. "
                         "An open question about a party's OWN position (for the buyer: whether an item is inside the "
                         "fixed price, its measurement or payment basis, its review periods) is that party's to decide: "
                         "state your decision in the reason so it can be written into the next draft. "
                         "Do not wait for a document from your own organization. Disclosed bid assumptions are proposed "
                         "risk allocations, not missing evidence: accept them, or name the exact clause you need instead.")
                if revision >= FINAL_CONTRACT_REVISION:
                    text += (" This is the FINAL draft. No further revision is possible: 'revise' now has the same effect "
                             "as 'reject' (no contract; the package is re-tendered with schedule delay). Choose accept when "
                             "the remaining open items are ordinary execution risks that the stated obligations, assumptions "
                             "and review or payment conditions allocate. Choose reject only for a material risk that these "
                             "terms leave unallocated.")
                else:
                    text += (" If you choose revise, write the exact clause wording or decision you require inside the "
                             "reason string; the answer has only the two keys action and reason.")
        await self.runtime.discuss_async(self.state, marker.lower(), company, self.spec.package_id,
                                         self.state.company_agent_rosters[company_id], [(1, "review"), (2, "authorization")], text)
        discussion = [asdict(message) for message in self.state.agent_discussion_history
                      if message.company_id == company_id and message.package_id == self.spec.package_id
                      and message.stage == marker.lower()][-12:]
        return await self.runtime.for_entity(company_id).ask_json_async(
            "Decide for your organization only. Return action accept/reject/revise and reason. "
            "Consider your members' discussion. Acceptance authorizes the exact supplied terms, resources and obligations.", marker,
            f"Company id: {company_id}\nTerms: {text}\nOwn internal discussion: {json.dumps(discussion, ensure_ascii=False)}", validator=require_choice)

    async def _consortiums(self):
        with self._negotiation_journal() as journal:
            identity = self._consortium_task_identity()
            task = journal.store.ensure(identity)
            if task["state"] == "output_formed":
                self._restore_consortium_batch(task["output"])
            else:
                task = journal.store.start(identity, task["revision"])
                before = len(self.runtime.recovery_events)
                try:
                    await form_consortiums(self.state, self.runtime)
                    if any(event["kind"] not in SAFE_RECOVERY for event in self.runtime.recovery_events[before:]):
                        raise IntegrationError("Degraded consortium generation cannot be saved as a draft")
                    for consortium in self.state.consortiums:
                        self._validate_consortium(asdict(consortium))
                    self._validate_consortium_set(self.state.consortiums)
                except Exception as exc:
                    journal.store.fail(identity, task["revision"], error_code=type(exc).__name__)
                    raise
                # This host-only audit checkpoint retains each organization's
                # own discussion plus shared exchanges. It is never passed as
                # a combined decision context to participants.
                journal.store.finish(identity, task["revision"], output=dump(self.state))
            accepted = []
            for consortium in self.state.consortiums:
                def validate(row):
                    self._validate_consortium_draft(row, identity.versions)
                row = journal.propose(negotiation_id=self._consortium_negotiation_id(consortium), revision=0,
                    proposer_id=consortium.lead_company_id, participants=consortium.member_company_ids,
                    terms=asdict(consortium), context=self._consortium_context(identity.versions),
                    authenticated_party=consortium.lead_company_id, revalidate=validate)
                decisions = {member: await self._journal_choice(journal, row, member,
                    marker="CONSORTIUM_ACCEPTANCE", validate_draft=validate, versions=identity.versions)
                    for member in consortium.member_company_ids}
                self.state.tender_process_log.append({"event_type": "consortium_authorizations",
                    "consortium_id": consortium.consortium_id, "decisions": decisions,
                    "terms_sha256": row["terms_sha256"], "negotiation_id": row["negotiation_id"]})
                if journal.unanimous(negotiation_id=row["negotiation_id"], revision=0,
                        terms_sha256=row["terms_sha256"], recipient_id=consortium.lead_company_id, revalidate=validate):
                    accepted.append(consortium)
            self.state.consortiums = accepted
            self.state.validation_context["consortium_acceptance_schema"] = "legacy-journal.v1"

    def _consortium_task_identity(self):
        versions = self._consortium_versions()
        return TaskIdentity(run_id=self.snapshot.simulation_id, organization_id=self.buyer_id, role="legacy-buyer",
            action_id="legacy:consortium-proposal-batch", request_id=self.session_id + "/consortium-proposals",
            purpose="host-audit-checkpoint", input_sha256=task_digest(dump(self.state)),
            context_sha256=task_digest(self._consortium_context(versions)), versions=versions)

    def _consortium_versions(self):
        root = Path(__file__).resolve().parents[1]
        source_paths = [*sorted((root / "src").rglob("*.py")), Path(__file__)]
        prompt_paths = sorted((root / "prompts").rglob("*.md"))
        def content(paths):
            return task_digest({path.relative_to(root).as_posix(): task_digest(path.read_text(encoding="utf-8"))
                                for path in paths})
        return {"client": content(source_paths), "skill": "legacy-consortium-stage.no-action-skill.v1",
            "prompt": content(prompt_paths), "contract": content([root / "src/models.py", root / "src/prompt_contracts.py"]),
            "method": "not-applicable.legacy-language-drafts.v1", "model": task_digest(llm_client_metadata(self.runtime.llm)),
            "strategy": task_digest({"strategy": "legacy-organization-discussion", "profile": self.runtime.profile})}

    def _consortium_context(self, versions):
        return {**self._negotiation_context(), "versions": versions, "phase": "legacy-consortium"}

    def _consortium_negotiation_id(self, consortium):
        return self.session_id + "/consortium/" + consortium.consortium_id

    def _validate_consortium(self, value):
        if not isinstance(value, dict) or set(value) != set(Consortium.__dataclass_fields__):
            raise IntegrationError("Consortium draft has unknown or missing fields")
        consortium = Consortium(**deepcopy(value))
        for name in ("consortium_id", "consortium_name", "package_id", "lead_company_id", "formation_reason", "agreement_summary"):
            if not isinstance(getattr(consortium, name), str) or not getattr(consortium, name).strip():
                raise IntegrationError("Consortium identity and shared terms must be nonempty")
        members = consortium.member_company_ids
        if (not isinstance(members, list) or len(members) < 2
                or any(not isinstance(member, str) or not member.strip() for member in members)
                or len(set(members)) != len(members) or consortium.lead_company_id not in members
                or not set(members) <= set(self.spec.candidate_ids) or self.buyer_id in members
                or consortium.package_id != self.spec.package_id or consortium.status != "formed"):
            raise IntegrationError("Consortium members, scope or local draft status are invalid")
        if (not isinstance(consortium.role_split, dict) or set(consortium.role_split) != set(members)
                or any(not isinstance(role, str) or not role.strip() for role in consortium.role_split.values())):
            raise IntegrationError("Consortium responsibilities must cover exactly its members")
        participating = {item.company_id: item.decision for item in self.state.participation_decisions
                         if item.package_id == self.spec.package_id}
        if (participating.get(consortium.lead_company_id) != "bid_with_consortium"
                or any(participating.get(member) not in {"bid", "bid_with_consortium"} for member in members)):
            raise IntegrationError("Consortium includes an organization outside the current participation decisions")
        for member in members:
            self.snapshot.for_entity(member)
        return consortium

    @staticmethod
    def _validate_consortium_set(consortiums):
        ids, members = set(), set()
        for consortium in consortiums:
            if consortium.consortium_id in ids or members.intersection(consortium.member_company_ids):
                raise IntegrationError("Consortium candidates duplicate identity or member participation")
            ids.add(consortium.consortium_id)
            members.update(consortium.member_company_ids)

    def _restore_consortium_batch(self, value):
        if (not isinstance(value, dict) or set(value) != set(dump(self.state))
                or not isinstance(value["consortiums"], list)):
            raise IntegrationError("Consortium checkpoint has missing or unknown state fields")
        for draft in value["consortiums"]:
            self._validate_consortium(draft)
        restored = load_simulation_state(deepcopy(value))
        # Only generation output may differ from the pre-stage checkpoint.
        immutable = dump(restored)
        current = dump(self.state)
        for field in ("consortiums", "agent_discussion_history", "tender_process_log"):
            immutable.pop(field)
            current.pop(field)
        if immutable != current:
            raise IntegrationError("Consortium checkpoint changed facts outside its stage")
        for consortium in restored.consortiums:
            self._validate_consortium(asdict(consortium))
        self._validate_consortium_set(restored.consortiums)
        self.state = restored
        self.runtime.restore_message_counter(self.state)

    def _validate_consortium_draft(self, row, versions):
        consortium = self._validate_consortium(row["terms"])
        if (row["negotiation_id"] != self._consortium_negotiation_id(consortium) or row["revision"] != 0
                or row["proposer_id"] != consortium.lead_company_id
                or set(row["participants"]) != set(consortium.member_company_ids)
                or row["context_sha256"] != task_digest(self._consortium_context(versions))):
            raise IntegrationError("Consortium draft identity, participants or current context mismatch")

    async def _reconsideration(self):
        await reconsider_after_failed_consortiums(self.state, self.runtime)

    async def _bids(self):
        self.verify_consortiums()
        await generate_bid_documents(self.state, self.runtime)

    def verify_consortiums(self):
        if not self.state.consortiums:
            return
        for consortium in self.state.consortiums:
            self._validate_consortium(asdict(consortium))
        self._validate_consortium_set(self.state.consortiums)
        if not self.negotiation_path.exists():
            if self.state.validation_context.get("consortium_acceptance_schema") == "legacy-journal.v1":
                raise IntegrationError("New consortium checkpoint is missing its independent member journal")
            self._verify_historical_consortiums()
            return
        versions = self._consortium_versions()
        with self._negotiation_journal() as journal:
            batch_tasks = journal.store.for_organization(run_id=self.snapshot.simulation_id,
                organization_id=self.buyer_id, include_host_audit=True)
            if not any(task["identity"]["request_id"] == self.session_id + "/consortium-proposals" for task in batch_tasks):
                if self.state.validation_context.get("consortium_acceptance_schema") == "legacy-journal.v1":
                    raise IntegrationError("New consortium checkpoint is missing its proposal batch journal")
                self._verify_historical_consortiums()
                return
            for consortium in self.state.consortiums:
                row = journal.latest(negotiation_id=self._consortium_negotiation_id(consortium),
                                     recipient_id=consortium.lead_company_id)
                if row is None or row["terms"] != asdict(consortium):
                    raise IntegrationError("Consortium differs from the independently reviewed draft")
                self._validate_consortium_draft(row, versions)
                for member in consortium.member_company_ids:
                    own = journal.get(negotiation_id=row["negotiation_id"], revision=0, recipient_id=member)
                    choice = own["choices"].get(member)
                    if choice is None or choice["context_sha256"] != task_digest({
                            "own_view": self.snapshot.for_entity(member), "versions": versions}):
                        raise IntegrationError("Consortium member decision is missing or has stale context")
                def validate(draft):
                    self._validate_consortium_draft(draft, versions)
                if not journal.unanimous(negotiation_id=row["negotiation_id"], revision=0,
                        terms_sha256=row["terms_sha256"], recipient_id=consortium.lead_company_id, revalidate=validate):
                    raise IntegrationError("Consortium lacks independent current member acceptance")

    def _verify_historical_consortiums(self):
        for consortium in self.state.consortiums:
            trace = [row for row in self.state.tender_process_log if row.get("event_type") == "consortium_authorizations"
                     and row.get("consortium_id") == consortium.consortium_id]
            if not trace or set(trace[-1]["decisions"]) != set(consortium.member_company_ids) or any(
                    choice.get("action") != "accept" for choice in trace[-1]["decisions"].values()):
                raise IntegrationError("Historical consortium lacks independent member decisions")

    async def _opening(self):
        await open_bids(self.state, self.runtime)

    async def _evaluation(self):
        await evaluate_bids(self.state, self.runtime)

    async def _award(self):
        await make_award_decisions(self.state, self.runtime)

    async def _signatures(self):
        with self._negotiation_journal() as journal:
            await self._signatures_with_journal(journal)

    def _negotiation_journal(self):
        return NegotiationJournal(run_id=self.snapshot.simulation_id,
                                  organization_ids=self.snapshot.private, path=self.negotiation_path)

    def _negotiation_context(self):
        return {"session_id": self.session_id, "snapshot_version": self.snapshot.version,
                "spec": asdict(self.spec), "buyer_id": self.buyer_id}

    def _validate_draft(self, row):
        proposal = ContractProposal(**row["terms"])
        if (row["context_sha256"] != task_digest(self._negotiation_context())
                or row["proposer_id"] != self.buyer_id
                or set(row["participants"]) != {self.buyer_id, *proposal.members}
                or proposal.snapshot_version != self.snapshot.version
                or proposal.session_id != self.session_id or proposal.buyer_id != self.buyer_id
                or proposal.signed_terms_hash != proposal.terms_hash() or proposal.signatures):
            raise IntegrationError("Negotiation draft identity, context or unsigned terms mismatch")

    async def _journal_choice(self, journal, row, party, *, marker="CONTRACT_ACCEPTANCE", validate_draft=None, versions=None):
        validate_draft = validate_draft or self._validate_draft
        view = journal.get(negotiation_id=row["negotiation_id"], revision=row["revision"], recipient_id=party)
        validate_draft(view)
        context = self.snapshot.for_entity(party)
        if versions is not None:
            context = {"own_view": context, "versions": versions}
        saved = view["choices"].get(party)
        if saved is not None:
            if saved["withdrawn"] or saved["context_sha256"] != task_digest(context):
                raise IntegrationError("Party choice was withdrawn or requires a new authorization context")
            return {"action": saved["action"], "reason": saved["reason"]}
        before = len(self.runtime.recovery_events)
        choice = await self.choice(party, marker, row["terms"],
                                   revision=row["revision"] if marker == "CONTRACT_ACCEPTANCE" else None)
        if any(event["kind"] not in SAFE_RECOVERY for event in self.runtime.recovery_events[before:]):
            raise IntegrationError("Degraded party choice cannot be saved as acceptance")
        def revalidate(draft, decision):
            validate_draft(draft)
            current = self.snapshot.for_entity(party)
            if versions is not None:
                current = {"own_view": current, "versions": versions}
            if decision["context_sha256"] != task_digest(current):
                raise IntegrationError("Party authorization context changed")
        journal.record_choice(negotiation_id=row["negotiation_id"], revision=row["revision"],
            party_id=party, operation_id=(f"{self.session_id}/acceptance/{row['revision']}/{party}"
                if marker == "CONTRACT_ACCEPTANCE" else f"{row['negotiation_id']}/choice/{row['revision']}/{party}"),
            terms_sha256=row["terms_sha256"], choice=choice, context=context,
            authenticated_party=party, revalidate=revalidate)
        return choice

    def verify_negotiation(self, proposal):
        """Verify local independent choices; the committer still checks current resources."""
        self.verify_consortiums()
        if not self.negotiation_path.exists():
            if self.state.validation_context.get("contract_acceptance_schema") == "legacy-journal.v1":
                raise IntegrationError("New contract checkpoint is missing its independent acceptance journal")
            # Historical checkpoints retain their original trace and are not
            # silently upgraded into newly authored acceptance records.
            records = [row for row in self.state.tender_process_log
                       if row.get("event_type") == "contract_authorizations"
                       and row.get("terms_hash") == proposal.signed_terms_hash]
            if not records or set(records[-1]["decisions"]) != {proposal.buyer_id, *proposal.members} or any(
                    value.get("action") != "accept" for value in records[-1]["decisions"].values()):
                raise IntegrationError("Historical checkpoint lacks independent same-version decisions")
            return
        with self._negotiation_journal() as journal:
            row = journal.latest(negotiation_id=proposal.proposal_id, recipient_id=self.buyer_id)
            expected = asdict(proposal)
            expected["signatures"] = {}
            if row is None or row["terms"] != expected:
                raise IntegrationError("Proposal differs from the independently reviewed draft")
            self._validate_draft(row)
            for party in row["participants"]:
                own = journal.get(negotiation_id=proposal.proposal_id, revision=row["revision"], recipient_id=party)
                choice = own["choices"].get(party)
                if choice is None or choice["context_sha256"] != task_digest(self.snapshot.for_entity(party)):
                    raise IntegrationError("Missing or stale independently authored party choice")
            if not journal.unanimous(negotiation_id=proposal.proposal_id, revision=row["revision"],
                    terms_sha256=row["terms_sha256"], recipient_id=self.buyer_id, revalidate=self._validate_draft):
                raise IntegrationError("Current draft does not have every party's independent acceptance")

    async def _signatures_with_journal(self, journal):
        award = self.state.simulated_award_result["package_awards"][0]
        if award["selected_bidder_id"] is None:
            return
        negotiation_id = self.session_id + "/contract"
        saved = journal.latest(negotiation_id=negotiation_id, recipient_id=self.buyer_id)
        if saved is not None:
            self._validate_draft(saved)
            proposal = ContractProposal(**saved["terms"])
            await self._review_contract_versions(journal, proposal, saved["revision"])
            return
        bid = next(b for b in self.state.bid_documents if b.package_id == self.spec.package_id and b.bidder_id == award["selected_bidder_id"])
        consortium = next((c for c in self.state.consortiums if c.consortium_id == bid.bidder_id), None)
        members = consortium.member_company_ids if consortium else [bid.bidder_id]
        lead = consortium.lead_company_id if consortium else bid.bidder_id
        def validate(data):
            shares = data.get("work_shares", {})
            if set(shares) != set(members) or any(isinstance(v, bool) or not isinstance(v, (float, int)) or not 0 < v <= 1 for v in shares.values()) or abs(sum(shares.values()) - 1) > 1e-8:
                raise ValueError("Positive work shares must cover exactly the members and sum to one")
        before = len(self.runtime.recovery_events)
        allocation = await self.runtime.for_entity(lead).ask_json_async(
            "Propose work shares for this contract. Return work_shares mapping member IDs to positive fractions summing to one. "
            "Every party will independently accept or reject these terms.", "CONTRACT_ALLOCATION",
            json.dumps({"members": members, "bid": asdict(bid), "resource_required": self.spec.resource_required,
                        "role_split": consortium.role_split if consortium else {lead: self.spec.scope}}, ensure_ascii=False), validator=validate)
        if any(event["kind"] not in SAFE_RECOVERY for event in self.runtime.recovery_events[before:]):
            raise IntegrationError("Degraded allocation cannot be persisted as draft terms")
        shares = allocation["work_shares"]
        proposal = ContractProposal(
            proposal_id=self.session_id + "/contract", simulation_id=self.snapshot.simulation_id,
            project_id=self.spec.project_id, package_id=self.spec.package_id, session_id=self.session_id,
            snapshot_version=self.snapshot.version, buyer_id=self.buyer_id, bid_id=bid.bid_id,
            bidder_id=bid.bidder_id, lead_id=lead, members=list(members), price=bid.quotation, currency=self.spec.currency,
            resource_commitments={key: self.spec.resource_required * value for key, value in shares.items()},
            work_shares=shares, signatures={}, signed_terms_hash="",
            terms={"schedule_commitment": bid.schedule_commitment, "risk_response": bid.risk_response,
                   "bid_document": asdict(bid),
                   "resource_unit": "normalized_enterprise_capacity; not a headcount or number of people",
                   "scope": self.spec.scope, "cost_inclusion": self.spec.cost_inclusion, "parent_package_id": self.spec.parent_package_id})
        framework = self.dataset.payload["assumptions"].get("contract_framework")
        if framework:
            proposal.terms["scenario_contract_framework"] = deepcopy(framework)
        # Two bounded clarification rounds before the existing re-tender policy.
        # Each revision invalidates EVERY earlier signature, including accepts.
        await self._review_contract_versions(journal, proposal, 0)

    async def _review_contract_versions(self, journal, proposal, starting_revision):
        for revision in range(starting_revision, FINAL_CONTRACT_REVISION + 1):
            proposal.signatures = {}
            proposal.signed_terms_hash = proposal.terms_hash()
            terms = asdict(proposal)
            row = journal.propose(negotiation_id=proposal.proposal_id, revision=revision,
                proposer_id=self.buyer_id, participants=[self.buyer_id, *proposal.members],
                terms=terms, context=self._negotiation_context(), authenticated_party=self.buyer_id,
                revalidate=self._validate_draft)
            decisions = {party: await self._journal_choice(journal, row, party)
                         for party in [self.buyer_id, *proposal.members]}
            self.state.tender_process_log.append({"event_type": "contract_authorizations", "decisions": decisions,
                                                  "revision": revision, "terms": terms,
                                                  "terms_hash": proposal.signed_terms_hash})
            proposal.signatures = {party: choice["action"] == "accept" for party, choice in decisions.items()}
            if all(proposal.signatures.values()):
                proposal.validate()
                if not journal.unanimous(negotiation_id=proposal.proposal_id, revision=revision,
                        terms_sha256=row["terms_sha256"], recipient_id=self.buyer_id, revalidate=self._validate_draft):
                    raise IntegrationError("Local contract choices are not unanimous on the same version")
                self.proposal = proposal
                self.state.validation_context["contract_acceptance_schema"] = "legacy-journal.v1"
                return
            if revision == FINAL_CONTRACT_REVISION or any(choice["action"] == "reject" for choice in decisions.values()):
                return
            await self._revise_contract(proposal, decisions, revision + 1)

    async def _revise_contract(self, proposal, decisions, revision):
        fields = {"scope_and_interfaces", "price_and_change_control", "payment_terms",
                  "delivery_and_review", "response_to_feedback"}
        def validate(data):
            if set(data) != fields or any(not isinstance(data[k], str) or not data[k].strip() for k in fields):
                raise ValueError("Return exactly five nonempty contract clarification fields")
        before = len(self.runtime.recovery_events)
        clauses = await self.runtime.for_entity(self.buyer_id).ask_json_async(
            "Draft a revised simulation contract on behalf of the buyer, using the parties' explicit feedback. "
            "Return JSON with exactly scope_and_interfaces, price_and_change_control, payment_terms, "
            "delivery_and_review, response_to_feedback; each value is a concise string of executable obligations. "
            "Resolve material ambiguities with clear responsibilities, deadlines and acceptance/payment conditions. "
            "You are the buyer: where feedback asks for the buyer's or owner's own position, decision or written "
            "confirmation, DECIDE it now and write it as a binding clause (for example: the item is included in the "
            "fixed price and is paid against stated milestones). Never answer that the buyer's position has not yet "
            "been obtained. Treat each bid assumption disclosed by the bidder either as an accepted, stated risk "
            "allocation or replace it with an explicit obligation and its acceptance condition. "
            "Do not claim external documents have been reviewed or real-world approvals obtained. "
            "Represent future engineering deliverables as binding obligations, not as already completed facts. "
            "Do not change price, currency, scope boundaries, parties, work shares or resource commitments; "
            "do not add uncapped price adjustment to the authorized scope. If a request would require such a change, "
            "state that it remains unresolved and needs re-tendering. Each party remains free to reject the draft.",
            "CONTRACT_CLARIFICATION",
            json.dumps({"revision": revision, "previous_terms": asdict(proposal), "party_feedback": decisions}, ensure_ascii=False),
            validator=validate)
        if any(event["kind"] not in SAFE_RECOVERY for event in self.runtime.recovery_events[before:]):
            raise IntegrationError("Degraded clarification cannot create a draft revision")
        proposal.terms["negotiated_clauses"] = clauses
        proposal.terms["clarification_revision"] = revision
        self.state.tender_process_log.append({"event_type": "contract_clarification_proposed",
                                              "revision": revision, "clauses": clauses})
