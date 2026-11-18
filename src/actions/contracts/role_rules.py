"""Input-dependent branch checks for non-professional role action cards."""
from decimal import Decimal

from src.actions.contracts.common import Known
from src.actions.contracts.semantic import disjoint


def _nonempty(payload, fields):
    for field in fields:
        if not getattr(payload, field):
            raise ValueError(f"Selected branch requires nonempty {field}")


def validate_decision(action_id, action_input, payload):
    choice = payload.choice
    if action_id == 'SUPPLIER-A12':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice == 'record_lesson':
            unique_refs(payload.source_refs)
            if not payload.source_refs or not {r.key() for r in payload.source_refs} <= {r.key() for r in action_input.observation_refs}:
                raise ValueError('Supplier lesson requires original received private observations')
        else:
            if payload.scope_ref != action_input.scope_ref:
                raise ValueError('Supplier continuation must preserve original specific scope')
            for refs in (payload.release_candidate_refs, payload.retained_obligation_refs, payload.disposition_basis_refs):
                unique_refs(refs)
            if (not {r.key() for r in payload.release_candidate_refs} <= {r.key() for r in action_input.commitment_refs}
                    or {r.key() for r in payload.retained_obligation_refs} != {r.key() for r in action_input.obligation_refs}):
                raise ValueError('Supplier continuation must preserve original commitments and remaining obligations')
            if (action_input.work_in_progress_refs or action_input.inventory_refs or action_input.shipment_refs) and not payload.disposition_basis_refs:
                raise ValueError('Supplier goods require original disposition rights')
            if choice == 'resume':
                unique_refs(payload.readiness_refs)
                if not payload.readiness_refs: raise ValueError('Supplier resume requires current readiness')
            if choice == 'close_cleared_scope' and (payload.retained_obligation_refs or payload.release_candidate_refs):
                raise ValueError('Closing supplier scope requires actually cleared obligations and resources')
    if action_id == 'CONTRACTOR-A12':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice == 'record_lesson':
            unique_refs(payload.source_refs)
            if not payload.source_refs or not {r.key() for r in payload.source_refs} <= {r.key() for r in action_input.observation_refs}:
                raise ValueError('Contractor lesson must retain original private observed sources')
        else:
            if payload.scope_ref != action_input.scope_ref:
                raise ValueError('Contractor continuation must preserve original input scope')
            for refs in (payload.retain_resource_refs, payload.release_candidate_refs, payload.remaining_obligation_refs):
                unique_refs(refs)
            retained = {r.key() for r in payload.retain_resource_refs}
            released = {r.key() for r in payload.release_candidate_refs}
            if (retained & released or retained | released != {r.key() for r in action_input.resource_commitment_refs}
                    or {r.key() for r in payload.remaining_obligation_refs} != {r.key() for r in action_input.obligation_refs}):
                raise ValueError('Contractor continuation must preserve distinct original resources and all remaining debts')
            if choice == 'resume':
                unique_refs(payload.readiness_refs)
                if not payload.readiness_refs: raise ValueError('Resume needs new original readiness verification')
            if choice == 'handover':
                unique_refs(payload.transfer_evidence_refs)
                if not payload.transfer_evidence_refs: raise ValueError('Contractor succession needs independent original transfer evidence')
    if action_id == 'BANK-A12':
        from src.actions.contracts.owner_study_objects import unique_refs
        unique_refs(payload.source_refs)
        if not {r.key() for r in payload.source_refs}<={r.key() for r in action_input.observation_refs}:
            raise ValueError('Bank learning must use original private observations')
        if choice!='retain_judgment':
            _nonempty(payload,('source_refs',))
            if action_input.learning_method_ref is None:
                raise ValueError('Bank lesson/strategy update requires selected learning method')
        if choice=='record_lesson':
            _nonempty(payload,('affected_dimension_refs',));unique_refs(payload.affected_dimension_refs)
        elif choice=='revise_strategy' and payload.strategy_ref not in action_input.allowed_strategy_refs:
            raise ValueError('Learned strategy must be an originally allowed candidate')
    if action_id == 'BANK-A11':
        from src.actions.contracts.owner_study_objects import unique_refs
        _nonempty(payload,('basis_refs',))
        for refs in (payload.retained_refs,payload.release_candidate_refs,payload.basis_refs): unique_refs(refs)
        if not {r.key() for r in payload.release_candidate_refs}<={r.key() for r in action_input.unused_commitment_refs}:
            raise ValueError('Finance release candidates must be original unused commitments')
        if choice=='retain' and payload.release_candidate_refs:
            raise ValueError('Retaining finance cannot propose capacity release')
        if choice=='close_unused' and not payload.release_candidate_refs:
            raise ValueError('Unused closure must identify original unused commitments')
    if action_id == 'BANK-A10':
        from src.actions.contracts.owner_study_objects import unique_refs
        _nonempty(payload,('basis_refs',));unique_refs(payload.basis_refs)
        if choice=='request_remedy':
            _nonempty(payload,('required_items',))
            if len({i.local_key for i in payload.required_items})!=len(payload.required_items):
                raise ValueError('Bank remedy requirement identity repeated')
            for item in payload.required_items:
                if not item.basis_refs: raise ValueError('Remedy requires concrete original clause basis')
                unique_refs(item.basis_refs)
        elif choice=='accept_restructure':
            _nonempty(payload,('acceptance_refs',));unique_refs(payload.acceptance_refs)
        elif choice=='enforce':
            _nonempty(payload,('right_refs',));unique_refs(payload.right_refs)
        elif choice=='accounting_writeoff' and payload.authority_ref!=action_input.authority_ref:
            raise ValueError('Accounting writeoff must use original bank authority')
        elif choice=='decline_remedy' and payload.proposal_ref not in action_input.remedy_refs:
            raise ValueError('Decline must use original borrower remedy proposal')
    if action_id == 'OWN-A15':
        from src.actions.contracts.owner_study_objects import unique_refs
        # Learning is conditional on the resolved preference profile. The
        # operating processor checks requires_learning and its method/report;
        # the closed action input cannot distinguish policy from learning.
        unique_refs(payload.basis_refs)
        if not {r.key() for r in payload.basis_refs}<={r.key() for r in action_input.observation_refs}:
            raise ValueError('Owner operating basis must be original visible observations')
        if choice=='revise_research_budget' and Decimal(payload.proposed_limit.value)<0:
            raise ValueError('Owner research authorization limit cannot be negative')
        if choice=='rebalance_tasks':
            _nonempty(payload,('allocations',));identities=set()
            for allocation in payload.allocations:
                if Decimal(allocation.quantity.value)<=0:
                    raise ValueError('Owner allocation must be positive in original resource units')
                target=allocation.task_target
                task=(target.task_ref.kind,target.task_ref.id) if target.kind=='existing' else ('proposed',target.local_key)
                identity=(allocation.resource_ref.key(),allocation.window_ref.key(),task)
                if identity in identities: raise ValueError('Owner task/resource/window allocation repeated')
                identities.add(identity)
    if action_id == 'OWN-A14':
        from src.actions.contracts.owner_study_objects import unique_refs
        if not payload.scope.basis_refs:
            raise ValueError('Asset choice requires explicit original scope basis')
        unique_refs(payload.scope.basis_refs);unique_refs(payload.scope.condition_refs)
        if choice in {'offer_sale','offer_lease','transfer'}:
            if payload.revenue_forecast.state not in {'known','unknown'}:
                raise ValueError('Asset forecast must retain known or unknown state')
            if isinstance(payload.revenue_forecast,Known) and Decimal(payload.revenue_forecast.value.value)<0:
                raise ValueError('Declared asset revenue cannot be negative')
        elif choice=='reconcile_receipt':
            _nonempty(payload,('receipt_refs',));unique_refs(payload.receipt_refs)
            if not {r.key() for r in payload.receipt_refs}<={r.key() for r in action_input.receipt_refs}:
                raise ValueError('Asset receipt query must use original receipt evidence')
    if action_id == 'OWN-A13':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if not payload.scope.basis_refs or not scope_covers(action_input.scope_ref,payload.scope.scope_ref):
            raise ValueError('Continuation requires concrete original scoped basis')
        for refs in (payload.scope.basis_refs,payload.scope.condition_refs,payload.retained_obligation_refs): unique_refs(refs)
        if {r.key() for r in payload.retained_obligation_refs}!={r.key() for r in action_input.obligation_refs}:
            raise ValueError('Continuation declaration must retain every original input obligation')
        if choice in {'suspend','terminate'}:
            unique_refs(payload.protection_task_refs);unique_refs(payload.release_candidate_refs)
            if not {r.key() for r in payload.release_candidate_refs}<={r.key() for r in action_input.resource_refs}:
                raise ValueError('Continuation release candidates must be original commitments')
        elif choice in {'replace','transfer'}:
            _nonempty(payload,('transfer_basis_refs',));unique_refs(payload.transfer_basis_refs)
        elif choice=='resume':
            _nonempty(payload,('readiness_refs',));unique_refs(payload.readiness_refs)
    if action_id == 'OWN-A12':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if choice == 'accept_scope':
            if payload.handover_ref not in action_input.handover_refs:
                raise ValueError('Owner acceptance requires original corresponding handover submission')
            if not payload.accepted_scope.basis_refs or not payload.accepted_scope.scope_ref.coverage_refs or not scope_covers(action_input.scope_ref,payload.accepted_scope.scope_ref):
                raise ValueError('Owner acceptance requires concrete supported original sub-scope and basis')
            for refs in (payload.accepted_scope.basis_refs,payload.accepted_scope.condition_refs,payload.remaining_issue_refs):
                unique_refs(refs)
        elif choice == 'request_rectification':
            _nonempty(payload,('defect_refs',));unique_refs(payload.defect_refs)
            if not {r.key() for r in payload.defect_refs}<={r.key() for r in action_input.defect_refs}:
                raise ValueError('Owner rectification requires original visible defects')
        else:
            _nonempty(payload,('component_refs','basis_refs'));unique_refs(payload.component_refs);unique_refs(payload.basis_refs)
            if not action_input.settlement_refs:
                raise ValueError('Owner settlement requires original proposals; handover is optional')
    if action_id == 'SUPPLIER-A11':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if choice == 'propose_change':
            _nonempty(payload,('lines','affected_line_refs'));unique_refs(payload.affected_line_refs)
            for line in payload.lines:
                if Decimal(line.quantity.value)<=0 or not line.requirement_refs:
                    raise ValueError('Supply change requires concrete positive products and original requirements')
                unique_refs(line.requirement_refs);unique_refs(line.deviation_refs)
        elif choice in {'repair','replace'}:
            _nonempty(payload,('tasks','source_defect_refs'));unique_refs(payload.source_defect_refs)
            if not {r.key() for r in payload.source_defect_refs}<={r.key() for r in action_input.defect_refs}:
                raise ValueError('Remedy must reference original visible defects')
            if len({t.local_key for t in payload.tasks})!=len(payload.tasks):
                raise ValueError('Remedy task identities must be unique')
            for task in payload.tasks:
                if not scope_covers(payload.disposition_scope_ref,task.scope_ref) or Decimal(task.target.quantity.value)<=0:
                    raise ValueError('Remedy task changes original disposition scope or quantity')
                if choice=='repair' and task.mode!='rework':
                    raise ValueError('Repair must preserve original physical batch')
        elif choice in {'propose_refund','claim'}:
            field='original_transaction_refs' if choice=='propose_refund' else 'order_line_refs'
            _nonempty(payload,(field,'basis_refs'));unique_refs(getattr(payload,field));unique_refs(payload.basis_refs)
            if payload.proposed_amount.state not in {'known','unknown'}:
                raise ValueError('Remedy amount must retain known or unknown state')
            if isinstance(payload.proposed_amount,Known) and Decimal(payload.proposed_amount.value.value)<=0:
                raise ValueError('Known remedy proposal must be positive')
        elif choice=='decline_request' and payload.request_ref not in action_input.change_refs:
            raise ValueError('Decline must refer to original received supply change request')
    if action_id == 'SUPPLIER-A10':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice == 'request_payment':
            claim=payload.claim
            if claim.settlement_rule_ref!=action_input.settlement_rule_ref or not claim.lines:
                raise ValueError('Supplier claim requires original settlement rule and concrete lines')
            unique_refs(claim.prior_claim_refs)
            for line in claim.lines:
                if Decimal(line.claimed.value)<=0 or not line.evidence_refs:
                    raise ValueError('Supplier claim amount must be positive and independently sourced')
                unique_refs(line.evidence_refs)
        elif choice == 'authorize_payment':
            if payload.account_ref not in action_input.account_refs or not payload.lines:
                raise ValueError('Supplier payment requires original actual own account and lines')
            unique_refs([l.obligation_ref for l in payload.lines]);unique_refs([r for l in payload.lines for r in l.component_refs])
            for line in payload.lines:
                if line.obligation_ref not in action_input.obligation_refs or not line.component_refs or Decimal(line.amount.value)<=0:
                    raise ValueError('Supplier payment requires existing original debt and positive component amount')
        elif choice in {'reconcile','dispute'}:
            field='execution_refs' if choice=='reconcile' else 'obligation_refs'
            refs=getattr(payload,field);_nonempty(payload,(field,));unique_refs(refs)
            if not {r.key() for r in refs}<={r.key() for r in getattr(action_input,field)}:
                raise ValueError('Supplier cash query/dispute must use original existing record IDs')
        elif choice == 'seek_finance':
            from src.actions.contracts.owner_financing_objects import FinancingApplicationDraft
            FinancingApplicationDraft.model_validate(payload.application.model_dump())
    if action_id == 'SUPPLIER-A09':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice == 'acknowledge_receipt':
            if payload.receipt_ref not in action_input.receipt_refs or not payload.accepted_fact_refs:
                raise ValueError('Receipt acknowledgment requires original existing customer receipt and specific facts')
            unique_refs(payload.accepted_fact_refs)
        elif choice == 'supplement_evidence':
            _nonempty(payload,('evidence_refs',));unique_refs(payload.evidence_refs)
        elif choice == 'contest_discrepancy':
            _nonempty(payload,('component_refs','evidence_refs'))
            unique_refs(payload.component_refs);unique_refs(payload.evidence_refs)
            if not action_input.discrepancy_refs:
                raise ValueError('Receipt contest requires original delivery discrepancies')
        elif choice == 'propose_replacement':
            if payload.issue_ref not in action_input.discrepancy_refs or not payload.replacement_lines:
                raise ValueError('Replacement proposal requires original existing issue and concrete products')
            for line in payload.replacement_lines:
                if Decimal(line.quantity.value) <= 0 or not line.requirement_refs:
                    raise ValueError('Replacement product requires positive quantity and original specifications')
                unique_refs(line.requirement_refs);unique_refs(line.deviation_refs)
    if action_id == 'SUPPLIER-A05':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if choice in {'plan_manufacture', 'plan_purchase', 'split_plan', 'revise_plan'}:
            if not payload.tasks or len({t.local_key for t in payload.tasks}) != len(payload.tasks):
                raise ValueError('Supply plan requires nonempty unique task drafts')
            if choice == 'plan_purchase' and any(t.mode != 'purchase' for t in payload.tasks):
                raise ValueError('Purchase plan cannot generate own manufacture')
            if choice == 'plan_manufacture' and any(t.mode == 'purchase' for t in payload.tasks):
                raise ValueError('Manufacture branch must preserve original task modes')
            if choice == 'split_plan' and len(payload.tasks) < 2:
                raise ValueError('Split plan requires multiple explicit tasks')
            for task in payload.tasks:
                if (task.method_ref not in action_input.method_refs or not scope_covers(action_input.scope_ref, task.scope_ref)
                        or not scope_covers(task.scope_ref, task.target.destination_scope_ref)
                        or Decimal(task.target.quantity.value) <= 0):
                    raise ValueError('Supply task changes original method/scope or positive target')
                unique_refs(task.dependency_refs); unique_refs([r.resource_ref for r in task.resources])
                unique_refs([i.product_ref for i in task.planned_inputs])
                if task.mode == 'purchase' and (task.resources or task.planned_inputs):
                    raise ValueError('Purchase task cannot consume manufacturing stock or capacity')
                for allocation in task.resources:
                    if allocation.scope_ref != task.scope_ref or Decimal(allocation.quantity.value) <= 0:
                        raise ValueError('Supply resource intention requires original task scope and positive input')
                for planned in task.planned_inputs:
                    unique_refs(planned.available_allocation_refs); unique_refs(planned.acquisition_requirement_refs)
                    if Decimal(planned.required.value) <= 0 or not {r.key() for r in planned.acquisition_requirement_refs} <= {r.key() for r in action_input.requirement_refs}:
                        raise ValueError('Planned supply inputs require positive original material requirements')
        elif choice in {'request_quote', 'accept_upstream_offer'}:
            if not payload.required_lines or any(Decimal(line.quantity.value) <= 0 for line in payload.required_lines):
                raise ValueError('Upstream request requires concrete positive product lines')
            if choice == 'request_quote' and (not payload.supplier_ids or len(set(payload.supplier_ids)) != len(payload.supplier_ids)):
                raise ValueError('Quote request requires distinct explicit upstream recipients')
            if choice == 'accept_upstream_offer' and payload.offer_ref not in action_input.upstream_offer_refs:
                raise ValueError('Upstream acceptance must use a received original offer')
        elif choice == 'seek_delivery_change':
            _nonempty(payload, ('affected_line_refs',)); unique_refs(payload.affected_line_refs)
    if action_id == 'CONTRACTOR-A11':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if choice == 'submit_handover':
            if payload.scope_ref != action_input.scope_ref or not payload.evidence_refs:
                raise ValueError('Handover must preserve original scope and actual evidence')
            unique_refs(payload.evidence_refs); unique_refs(payload.remaining_issue_refs)
        elif choice == 'rectify':
            if not payload.tasks or len({t.local_key for t in payload.tasks}) != len(payload.tasks):
                raise ValueError('Remedy requires nonempty uniquely identified task drafts')
            for task in payload.tasks:
                if not scope_covers(action_input.scope_ref, task.scope_ref) or not task.target_quantities:
                    raise ValueError('Remedy task leaves original scope or omits quantities')
                if any(Decimal(q.value) <= 0 for q in task.target_quantities):
                    raise ValueError('Remedy task quantities must be positive')
                unique_refs(task.dependency_refs); unique_refs([a.resource_ref for a in task.allocations])
        else:
            accepted, disputed = {r.key() for r in payload.component_refs}, {r.key() for r in payload.disputed_refs}
            unique_refs(payload.component_refs); unique_refs(payload.disputed_refs)
            if (accepted & disputed or accepted | disputed != {r.key() for r in action_input.settlement_components}
                    or not (accepted | disputed)):
                raise ValueError('Final-account response must partition every original settlement component')
    if action_id == 'CONTRACTOR-A10':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice == 'apply_measurement':
            request = payload.request
            if request.contract_ref != action_input.contract_ref or not request.lines or not request.basis_refs:
                raise ValueError('Measurement requires original contract, concrete work and evidence')
            unique_refs(request.prior_application_refs); unique_refs(request.basis_refs)
            refs = [r for line in request.lines for r in line.work_record_refs]
            unique_refs(refs)
            if {r.key() for r in refs} != {r.key() for r in action_input.work_record_refs}:
                raise ValueError('Measurement changes original work record coverage')
            for line in request.lines:
                if not line.work_record_refs or Decimal(line.quantity.value) <= 0:
                    raise ValueError('Measurement requires positive quantities and actual work')
        elif choice == 'authorize_payment':
            if payload.account_ref not in action_input.account_refs or not payload.lines:
                raise ValueError('Payment requires original own account and explicit lines')
            unique_refs([line.obligation_ref for line in payload.lines])
            unique_refs([r for line in payload.lines for r in line.component_refs])
            for line in payload.lines:
                if line.obligation_ref not in action_input.obligation_refs or not line.component_refs or Decimal(line.amount.value) <= 0:
                    raise ValueError('Payment requires existing obligations and positive component allocations')
        elif choice == 'request_payment':
            _nonempty(payload, ('basis_refs', 'component_refs'))
            unique_refs(payload.basis_refs); unique_refs(payload.component_refs)
        elif choice == 'reconcile':
            _nonempty(payload, ('execution_refs',)); unique_refs(payload.execution_refs)
            if not {r.key() for r in payload.execution_refs} <= {r.key() for r in action_input.execution_refs}:
                raise ValueError('Reconciliation must query original execution IDs')
        elif choice == 'dispute':
            _nonempty(payload, ('obligation_refs', 'issue_refs'))
            unique_refs(payload.obligation_refs); unique_refs(payload.issue_refs)
            if not {r.key() for r in payload.obligation_refs} <= {r.key() for r in action_input.obligation_refs}:
                raise ValueError('Dispute requires existing original obligations')
        elif choice == 'seek_finance':
            from src.actions.contracts.owner_financing_objects import FinancingApplicationDraft
            FinancingApplicationDraft.model_validate(payload.application.model_dump())
    if action_id == 'CONTRACTOR-A09':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice in {'clarify', 'respond'}:
            if not payload.issues:
                raise ValueError('Interface response requires concrete original requirements')
            unique_refs([i.requirement_ref for i in payload.issues])
            for issue in payload.issues:
                unique_refs(issue.evidence_refs)
        elif choice in {'propose_change', 'submit_claim'}:
            if not payload.basis_refs or not payload.affected_task_refs:
                raise ValueError('Change/claim requires original evidence and explicit affected tasks')
            unique_refs(payload.basis_refs); unique_refs(payload.affected_task_refs)
            if payload.proposed_amount.state not in {'known', 'unknown'} or payload.time_impact.state not in {'known', 'unknown'}:
                raise ValueError('Initial impact must remain unknown or original assessed value')
    if action_id == 'CONTRACTOR-A08':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if payload.scope_ref != action_input.scope_ref:
            raise ValueError('Quality request changes original inspection scope')
        if choice in {'self_check', 'request_external_check', 'request_recheck'}:
            unique_refs(payload.evidence_refs)
            if {r.key() for r in payload.evidence_refs} != {r.key() for r in action_input.evidence_refs}:
                raise ValueError('Quality request drops or invents original received inspection evidence')
        if choice in {'rectify', 'request_recheck'}:
            unique_refs(payload.defect_refs)
            if not payload.defect_refs or {r.key() for r in payload.defect_refs} != {r.key() for r in action_input.defect_refs}:
                raise ValueError('Remedy/recheck must preserve original observed defect identities')
        if choice == 'isolate':
            unique_refs(payload.issue_refs)
            if not payload.issue_refs or {r.key() for r in payload.issue_refs} != {r.key() for r in action_input.defect_refs}:
                raise ValueError('Isolation must preserve original observed defect identities')
        if choice == 'rectify':
            if not payload.tasks or len({t.local_key for t in payload.tasks}) != len(payload.tasks):
                raise ValueError('Remedy requires locally unique original task drafts')
            for task in payload.tasks:
                if not scope_covers(action_input.scope_ref, task.scope_ref) or not task.target_quantities or not task.allocations:
                    raise ValueError('Remedy task lacks original local scope, explicit targets or resources')
                unique_refs(task.dependency_refs); unique_refs([a.resource_ref for a in task.allocations])
                if any(Decimal(q.value) <= 0 for q in task.target_quantities):
                    raise ValueError('Remedy target quantity must be positive')
                if any(a.task_scope_ref != task.scope_ref or a.window_ref != task.window_ref or Decimal(a.quantity.value) <= 0 for a in task.allocations):
                    raise ValueError('Remedy allocation changes original task/window or positive quantity')
    if action_id == 'CONTRACTOR-A06':
        from src.actions.contracts.owner_study_objects import unique_refs
        if payload.task_ref != action_input.task_ref:
            raise ValueError('Readiness request must preserve the original selected task')
        if choice == 'request_release':
            if not payload.evidence_refs:
                raise ValueError('Task release request requires original readiness evidence')
            unique_refs(payload.evidence_refs)
        elif choice == 'rectify_dependency':
            if not payload.issues:
                raise ValueError('Readiness remedy requires concrete original unresolved requirements')
            unique_refs([i.requirement_ref for i in payload.issues])
            for issue in payload.issues:
                if issue.requirement_ref not in action_input.readiness_requirement_refs:
                    raise ValueError('Readiness remedy invents an undeclared original requirement')
                unique_refs(issue.evidence_refs)
        else:
            if not payload.replacement_task_refs or action_input.task_ref in payload.replacement_task_refs:
                raise ValueError('Resequencing requires distinct original replacement tasks')
            unique_refs(payload.replacement_task_refs)
    if action_id == 'CONTRACTOR-A05':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if choice in {'plan', 'revise_plan'}:
            if not payload.tasks or len({t.local_key for t in payload.tasks}) != len(payload.tasks):
                raise ValueError('Work plan requires nonempty locally unique task drafts')
            for task in payload.tasks:
                if not scope_covers(action_input.authorized_scope_ref, task.scope_ref) or task.work_method_ref not in action_input.work_method_refs:
                    raise ValueError('Work plan task changes original authorized scope or method')
                unique_refs(task.dependency_refs)
                if not {r.key() for r in task.dependency_refs} <= {r.key() for r in action_input.dependency_refs}:
                    raise ValueError('Work plan invents undeclared original dependencies')
                if not task.target_quantities or not task.allocations or any(Decimal(q.value) <= 0 for q in task.target_quantities):
                    raise ValueError('Work plan requires positive original targets and explicit resources')
                unique_refs([a.resource_ref for a in task.allocations])
                if any(a.task_scope_ref != task.scope_ref or a.window_ref != task.window_ref or Decimal(a.quantity.value) <= 0 for a in task.allocations):
                    raise ValueError('Work allocation changes original task/window/scope or positive resource amount')
        elif choice == 'request_quote':
            unique_refs(payload.requirement_refs)
            if not payload.requirement_refs or not payload.supplier_ids or len(set(payload.supplier_ids)) != len(payload.supplier_ids):
                raise ValueError('Supply inquiry requires original requirements and distinct actual suppliers')
        elif payload.offer_ref not in action_input.supplier_offer_refs:
            raise ValueError('Supply acceptance invents an undeclared original offer')
    if action_id == 'BANK-A06':
        if len({(condition.requirement_ref.kind, condition.requirement_ref.id) for condition in payload.conditions}) != len(payload.conditions):
            raise ValueError('Draw decision repeats an original condition')
        for condition in payload.conditions:
            if condition.outcome == 'satisfied' and not condition.evidence_refs:
                raise ValueError('Satisfied draw conditions need original independent evidence')
        if choice == 'approve_draw':
            if Decimal(payload.approved_amount.value) <= 0 or not payload.transfer_lines:
                raise ValueError('Draw approval requires positive principal and nonempty original transfers')
            if any(condition.outcome != 'satisfied' for condition in payload.conditions):
                raise ValueError('Draw approval cannot bypass unknown or failed conditions')
            destinations, obligations = set(), set()
            for line in payload.transfer_lines:
                if Decimal(line.requested.value) <= 0 or line.requested.currency != payload.approved_amount.currency:
                    raise ValueError('Approved draw transfers need positive same-currency amounts')
                if (line.destination_ref.kind, line.destination_ref.id) in destinations:
                    raise ValueError('Draw approval repeats a physical destination account')
                destinations.add((line.destination_ref.kind, line.destination_ref.id))
                for ref in line.obligation_refs:
                    if (ref.kind, ref.id) in obligations: raise ValueError('Draw approval pays one obligation twice')
                    obligations.add((ref.kind, ref.id))
    if action_id == 'OWN-A11':
        if choice in {'instruct', 'verify', 'remedy'}:
            if not payload.requested_requirement_refs or not payload.scope.basis_refs:
                raise ValueError('Contract instruction requires original explicit scope, evidence and requirements')
            for refs in (payload.requested_requirement_refs, payload.scope.basis_refs, payload.scope.condition_refs):
                if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                    raise ValueError('Contract instruction repeats a physical source/requirement')
        if choice in {'dispute', 'accept_undisputed'}:
            if not payload.component_refs or len({(ref.kind, ref.id) for ref in payload.component_refs}) != len(payload.component_refs):
                raise ValueError('Claim decision requires distinct original components')
    if action_id == 'OWN-A08':
        if choice == 'authorize_agent':
            if payload.delegate_id == action_input.applicant_id or not payload.delegated_scope.basis_refs:
                raise ValueError('Regulatory agency proposal needs a distinct delegate and scoped original basis')
        if choice == 'submit':
            application = payload.application
            if (application.requirement_ref.key() != action_input.regulatory_requirement_ref.key()
                    or application.applicant_id != action_input.applicant_id or application.scope_ref != action_input.scope_ref
                    or payload.authority_ref.key() not in {ref.key() for ref in action_input.authority_candidates}
                    or not application.requested_matter_refs):
                raise ValueError('Regulatory application changes original applicant, scope, requirement or authority')
            if not {ref.key() for ref in application.submission_refs} <= {ref.key() for ref in action_input.submission_refs}:
                raise ValueError('Regulatory application adds undeclared professional submissions')
            for refs in (application.submission_refs, application.evidence_refs, application.requested_matter_refs):
                if len({(ref.kind, ref.id) for ref in refs}) != len(refs): raise ValueError('Regulatory application repeats an original material/matter')
        if choice in {'supplement', 'withdraw', 'request_review'}:
            if payload.case_ref.key() not in {ref.key() for ref in action_input.case_refs}:
                raise ValueError('Regulatory follow-up must preserve an original declared case')
            if choice == 'withdraw' and not payload.basis_refs: raise ValueError('Case withdrawal needs original explicit basis')
        if choice in {'supplement', 'request_review'}:
            if payload.authority_ref.key() not in {ref.key() for ref in action_input.authority_candidates} or not payload.response_items:
                raise ValueError('Case response needs original receiving authority and structured items')
            if len({item.local_key for item in payload.response_items}) != len(payload.response_items):
                raise ValueError('Case response local identities repeat')
            for item in payload.response_items:
                if not item.request.strip() or (not item.requirement_refs and item.issue_ref is None):
                    raise ValueError('Case response must name original requirement or dispute')
                if not {ref.key() for ref in item.evidence_refs} <= {ref.key() for ref in payload.evidence_refs}:
                    raise ValueError('Case response evidence is absent from its submission')
    if action_id == 'OWN-A07':
        if choice == 'confirm_need' and payload.brief_ref.key() != action_input.brief_ref.key():
            raise ValueError('Need confirmation must preserve the original brief version')
        if choice == 'choose_option' and payload.comparison_ref.key() not in {ref.key() for ref in action_input.comparison_refs}:
            raise ValueError('Option choice must retain an original declared comparison')
        if choice == 'request_revision':
            if not payload.requirement_refs or not payload.change_scope.basis_refs:
                raise ValueError('Owner revision needs explicit scoped basis and original change requirements')
            if len({(ref.kind, ref.id) for ref in payload.requirement_refs}) != len(payload.requirement_refs):
                raise ValueError('Owner revision repeats an original requirement')
        if choice in {'accept_service', 'authorize_use'}:
            if payload.submission_ref.key() not in {ref.key() for ref in action_input.submission_refs} or not payload.scope.basis_refs:
                raise ValueError('Service/use decision must retain original submission and scoped evidence')
            for refs in (payload.scope.basis_refs, payload.scope.condition_refs):
                if len({(ref.kind, ref.id) for ref in refs}) != len(refs): raise ValueError('Owner scoped decision repeats original evidence/conditions')
    if action_id == 'OWN-A06':
        if choice == 'draw_request':
            if payload.arrangement_ref.key() not in {ref.key() for ref in action_input.arrangement_refs} or Decimal(payload.amount.value) <= 0:
                raise ValueError('Draw request must preserve the original arrangement and positive amount')
            if not {ref.key() for ref in payload.condition_refs} <= {ref.key() for ref in action_input.evidence_refs}:
                raise ValueError('Draw request changes original received condition evidence')
        if choice in {'pay', 'repay'}:
            if payload.account_ref.key() not in {ref.key() for ref in action_input.account_refs} or not payload.lines:
                raise ValueError('Payment must use original account and nonempty lines')
            dues, components = set(), set()
            for line in payload.lines:
                if line.obligation_ref.key() not in {ref.key() for ref in action_input.due_refs} or line.obligation_ref.key() in dues:
                    raise ValueError('Payment duplicates or changes an original obligation')
                dues.add(line.obligation_ref.key())
                if Decimal(line.amount.value) <= 0 or not line.component_refs: raise ValueError('Payment needs positive amount and original settlement components')
                for ref in line.component_refs:
                    if (ref.kind, ref.id) in components: raise ValueError('Payment counts an original component twice')
                    components.add((ref.kind, ref.id))
        if choice in {'dispute', 'negotiate'}:
            if not payload.obligation_refs or not {ref.key() for ref in payload.obligation_refs} <= {ref.key() for ref in action_input.due_refs}:
                raise ValueError('Debt dispute/negotiation must preserve original obligation references')
        if choice == 'reconcile':
            if not payload.execution_refs or len({(ref.kind, ref.id) for ref in payload.execution_refs}) != len(payload.execution_refs):
                raise ValueError('Reconciliation needs distinct original payment executions')
    if action_id == 'SUPPLIER-A13':
        if choice in {'indicative_advice', 'limited_disclosure'}:
            if action_input.advisory_scope_ref is None or not payload.lines:
                raise ValueError('Supply advice needs original bounded-work authority and lines')
            if (choice == 'indicative_advice' and payload.withheld_requirement_refs
                    or choice == 'limited_disclosure' and not payload.withheld_requirement_refs):
                raise ValueError('Supply withholding must match the explicit disclosure branch')
            bases = []
            for line in payload.lines:
                ref = line.basis.brief_ref if line.basis.kind == 'brief' else line.basis.option_ref
                if line.basis.kind == 'brief' and ref.key() != action_input.brief_ref.key():
                    raise ValueError('Supplier advice changes original brief version')
                if line.basis.kind == 'option' and ref.key() not in {r.key() for r in action_input.option_refs}:
                    raise ValueError('Supplier advice changes original option version')
                bases.append(ref.key())
                for lower, upper in ((line.quantity.lower, line.quantity.upper), (line.indicative_price.lower, line.indicative_price.upper),
                                     (line.logistics.delivery_cost.lower, line.logistics.delivery_cost.upper)):
                    for bound in (lower, upper):
                        if bound.state == 'known' and Decimal(bound.value.value) < 0: raise ValueError('Supply opinion has a negative bound')
                    if lower.state == upper.state == 'known':
                        unit = lambda value: value.unit if hasattr(value, 'unit') else value.currency
                        if unit(lower.value) != unit(upper.value) or Decimal(lower.value.value) > Decimal(upper.value.value):
                            raise ValueError('Supply opinion bounds must share units/currency and be ordered')
                for refs in (line.product_refs, line.interface_issue_refs, line.evidence_refs, line.logistics.route_refs,
                             line.logistics.condition_refs, line.logistics.unresolved_refs):
                    if len({(r.kind, r.id) for r in refs}) != len(refs): raise ValueError('Supply opinion repeats a physical source')
                if not line.logistics.condition_refs: raise ValueError('Supply opinion omits logistics/delivery conditions')
            expected = {r.key() for r in action_input.option_refs} if action_input.option_refs else {action_input.brief_ref.key()}
            if len(set(bases)) != len(bases) or set(bases) != expected: raise ValueError('Supply advice must cover each requested basis once')
            for refs in (payload.withheld_requirement_refs, payload.unresolved_refs):
                if len({(r.kind, r.id) for r in refs}) != len(refs): raise ValueError('Supplier advice repeats an original gap/disclosure requirement')
        if choice == 'propose_study':
            if not payload.condition_refs: raise ValueError('Supplier study proposal needs explicit original conditions')
            if payload.effort_estimate.state == 'known' and Decimal(payload.effort_estimate.value.value) <= 0:
                raise ValueError('Known supplier study effort must be positive')
            if payload.fee_estimate.state == 'known' and Decimal(payload.fee_estimate.value.value) < 0:
                raise ValueError('Known supplier study fee cannot be negative')
    if action_id == 'CONTRACTOR-A13':
        if choice == 'provide_advice':
            if action_input.advisory_authority_ref is None or not payload.results:
                raise ValueError('Contractor advice needs original explicit bounded-work authority and results')
            bases = []
            for result in payload.results:
                ref = result.basis.brief_ref if result.basis.kind == 'brief' else result.basis.option_ref
                if result.basis.kind == 'brief' and ref.key() != action_input.brief_ref.key():
                    raise ValueError('Contractor advice changes original brief version')
                if result.basis.kind == 'option' and ref.key() not in {r.key() for r in action_input.option_refs}:
                    raise ValueError('Contractor advice changes original option version')
                bases.append(ref.key())
                if not result.assumptions or not result.validity_condition_refs:
                    raise ValueError('Contractor advice must preserve estimate assumptions and validity')
                for refs in (result.work_method_refs, result.assumptions, result.validity_condition_refs):
                    if len({(r.kind, r.id) for r in refs}) != len(refs): raise ValueError('Contractor advice repeats an original method or condition')
                lower, upper = result.duration.lower, result.duration.upper
                for bound in (lower, upper):
                    if bound.state == 'known' and Decimal(bound.value.value) < 0: raise ValueError('Advisory duration cannot be negative')
                if lower.state == upper.state == 'known' and (lower.value.unit != upper.value.unit or Decimal(lower.value.value) > Decimal(upper.value.value)):
                    raise ValueError('Advisory duration bounds must be ordered in the same unit')
            expected = {r.key() for r in action_input.option_refs} if action_input.option_refs else {action_input.brief_ref.key()}
            if len(set(bases)) != len(bases) or set(bases) != expected: raise ValueError('Contractor advice must cover each exact requested basis once')
        if choice == 'propose_paid_study':
            if not payload.condition_refs: raise ValueError('Paid study proposal needs explicit original conditions')
            if payload.effort.state == 'known' and Decimal(payload.effort.value.value) <= 0: raise ValueError('Known proposed effort must be positive')
            if payload.proposed_fee.state == 'known' and Decimal(payload.proposed_fee.value.value) < 0: raise ValueError('Known proposed fee cannot be negative')
    if action_id == 'CONTRACTOR-A04':
        if choice == 'accept':
            if payload.offer_ref.key() != action_input.offer_ref.key() or payload.terms_ref.key() != action_input.terms_ref.key():
                raise ValueError('Contractor acceptance changes the original final offer/terms versions')
            if not payload.proposed_allocations or any(Decimal(row.quantity.value) <= 0 for row in payload.proposed_allocations):
                raise ValueError('Contractor acceptance needs positive original proposed resources')
            keys = [(row.resource_ref.key(), row.task_scope_ref.kind, row.task_scope_ref.ref.key(),
                     tuple(sorted(ref.key() for ref in row.task_scope_ref.coverage_refs)), row.window_ref.key())
                    for row in payload.proposed_allocations]
            if len(set(keys)) != len(keys): raise ValueError('Contractor acceptance repeats an original task/resource/window')
        if choice == 'revise':
            if not payload.requirement_changes: raise ValueError('Contract revision needs original explicit change requests')
            if len({(ref.kind, ref.id) for ref in payload.requirement_changes}) != len(payload.requirement_changes):
                raise ValueError('Contract revision repeats a physical change request')
    if action_id == 'CONTRACTOR-A03':
        if payload.prior_bid_ref.key() != action_input.bid_ref.key():
            raise ValueError('Amendment must retain the exact original bid identity')
        if choice == 'explain':
            refs = [answer.question_ref for answer in payload.answers]
            if not refs or {ref.key() for ref in refs} != {ref.key() for ref in action_input.clarification_refs}:
                raise ValueError('Explanation must answer the original clarification set')
            if len({ref.key() for ref in refs}) != len(refs):
                raise ValueError('Explanation repeats an original clarification')
            if any(not answer.answer.strip() or answer.changed_requirement_refs for answer in payload.answers):
                raise ValueError('Explanation cannot hide a bid revision')
        if choice == 'revise':
            bid = payload.replacement_bid
            if bid.package_ref.key() != action_input.package_ref.key() or Decimal(bid.price.value) <= 0:
                raise ValueError('Replacement must price the current original package')
            if not bid.cost_basis_refs or not bid.proposed_resources:
                raise ValueError('Replacement must retain complete cost and proposed resources')
            for refs in (bid.cost_basis_refs, bid.exclusion_refs, payload.changed_requirement_refs):
                if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                    raise ValueError('Revision repeats an original cost/requirement identity')
    if action_id == 'CONTRACTOR-A02' and choice == 'submit_bid':
        if payload.bid.package_ref != action_input.package_ref or set(payload.bid.cost_basis_refs) != set(action_input.cost_refs):
            raise ValueError('Contractor bid changes original package or declared cost versions')
        if Decimal(payload.bid.price.value) <= 0 or not payload.planned_tasks:
            raise ValueError('Contractor bid needs positive commercial price and original planned work')
        if len({row.local_key for row in payload.planned_tasks}) != len(payload.planned_tasks):
            raise ValueError('Contractor bid repeats a planned task local identity')
        for refs in (payload.bid.cost_basis_refs, payload.bid.exclusion_refs):
            if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                raise ValueError('Contractor bid repeats an original cost or exclusion')
        for row in payload.planned_tasks:
            if row.work_method_ref not in action_input.allowed_method_refs or not row.target_quantities or not row.allocations:
                raise ValueError('Contractor bid task lacks declared applicable method, target quantity or resources')
            if any(Decimal(q.value) <= 0 for q in row.target_quantities):
                raise ValueError('Contractor bid proposed target quantities must be positive')
        task_allocations = [a for row in payload.planned_tasks for a in row.allocations]
        if task_allocations != payload.bid.proposed_resources:
            raise ValueError('Contractor bid resources must preserve its exact original planned task allocations')
    if action_id == "OWN-A01":
        if choice in {"create_case", "propose"}:
            _nonempty(payload, ["source_refs"])
        if choice == "revise_case" and payload.case_ref not in action_input.existing_case_refs:
            raise ValueError("Revised case must belong to the input case set")
        if choice == "follow":
            target = payload.target
            supplied = action_input.opportunity_refs if target.kind == "opportunity" else action_input.existing_case_refs
            selected = target.opportunity_ref if target.kind == "opportunity" else target.case_ref
            if selected not in supplied:
                raise ValueError("Follow target must belong to the supplied opportunity or case set")
    if action_id == "OWN-A16" and choice in {"propose", "revise"}:
        _nonempty(payload, ["briefs"] + (["prior_brief_refs"] if choice == "revise" else []))
        for brief in payload.briefs:
            if len(set(brief.region_ids)) != len(brief.region_ids):
                raise ValueError("Proposal brief region repeated")
            for refs in (brief.alternatives, brief.rights_refs, brief.unresolved_refs):
                if len({ref.key() for ref in refs}) != len(refs):
                    raise ValueError("Proposal brief reference repeated")
        if choice == "revise":
            if len(payload.prior_brief_refs) != len(payload.briefs) or len({ref.key() for ref in payload.prior_brief_refs}) != len(payload.prior_brief_refs):
                raise ValueError("Each revised brief needs a distinct exact prior brief")
    if action_id == "OWN-A03" and choice in {"revise", "study_more"}:
        if not payload.target_option_refs and not payload.issue_refs:
            raise ValueError("Whole-comparison revision requires specific issues")
        for refs in (payload.target_option_refs, payload.issue_refs):
            if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                raise ValueError("Investment followup reference repeated across versions")
    if action_id == "OWN-A03" and choice in {"authorize_preparation", "invest"}:
        if not payload.scope.scope_ref.coverage_refs or not payload.scope.basis_refs:
            raise ValueError("Investment/preparation requires a bounded scope and evidence")
        if len({row.requirement_ref.key() for row in payload.conditions}) != len(payload.conditions):
            raise ValueError("Investment condition repeated")
        if any(row.verification == "met" and not row.evidence_refs for row in payload.conditions):
            raise ValueError("Met investment condition requires verification evidence")
    if action_id == "OWN-A02" and choice != "stop":
        if action_input.brief_ref is None and not action_input.issue_refs:
            raise ValueError("Study without a brief requires registered questions")
        if Decimal(payload.expenditure_cap.value) <= 0:
            raise ValueError("Limited study requires a positive expenditure cap")
        if payload.expenditure_cap.currency != action_input.spending_limit.currency or Decimal(payload.expenditure_cap.value) > Decimal(action_input.spending_limit.value):
            raise ValueError("Limited study cap exceeds the supplied spending limit")
        if not payload.task_scope.scope_ref.coverage_refs or not payload.task_scope.basis_refs:
            raise ValueError("Study requires nonempty bounded work and evidence")
        if choice == "commission" and payload.offer_ref not in action_input.service_candidates:
            raise ValueError("Commission must select an actually received service offer")
        if choice == "internal_study":
            _nonempty(payload, ["allocations"])
            for row in payload.allocations:
                if Decimal(row.quantity.value) <= 0 or row.window_ref != payload.window_ref:
                    raise ValueError("Internal study allocations require positive quantity in the selected window")
                if row.task_target.kind != "proposed" or row.task_target.scope_ref != payload.task_scope.scope_ref:
                    raise ValueError("Internal study allocates only its bounded newly proposed task")
    if action_id == "OWN-A04":
        if choice in {"invite", "clarify"}:
            _nonempty(payload, ["recipient_ids"] + (["issue_refs"] if choice == "clarify" else []))
            if len(set(payload.recipient_ids)) != len(payload.recipient_ids):
                raise ValueError("Service procurement recipient repeated")
            if len({(ref.kind,ref.id) for ref in payload.issue_refs}) != len(payload.issue_refs):
                raise ValueError("Service procurement issue repeated across versions")
        if choice == "accept" and payload.offer_ref not in action_input.candidates:
            raise ValueError("Service acceptance must select an actually received exact offer")
        if choice == "internal":
            _nonempty(payload, ["allocations"])
            if any(Decimal(row.quantity.value) <= 0 for row in payload.allocations):
                raise ValueError("Internal service allocations must be positive")
    if action_id == 'OWN-A05':
        if choice == 'own_funds':
            _nonempty(payload, ['source_refs'])
            if len({(ref.kind, ref.id) for ref in payload.source_refs}) != len(payload.source_refs):
                raise ValueError('Financing source repeated across versions')
            if not set(payload.source_refs) <= {row.source_ref for row in action_input.funding_lines}:
                raise ValueError('Own funds must select a declared funding source')
        if choice in {'accept_offer', 'negotiate'} and payload.offer_ref not in action_input.offers:
            raise ValueError('Financing choice must select an actually received exact offer')
        if choice == 'apply':
            draft = payload.application
            if draft.borrower_id != action_input.borrower_id or draft.scope_ref != action_input.scope_ref or Decimal(draft.requested.value) <= 0:
                raise ValueError('Financing application changes borrower/scope or has nonpositive principal')
        if choice == 'negotiate':
            _nonempty(payload, ['questions'])
            if len({row.local_key for row in payload.questions}) != len(payload.questions):
                raise ValueError('Financing question local key repeated')
        if choice == 'resize':
            if not payload.change_scope.scope_ref.coverage_refs or not payload.change_scope.basis_refs:
                raise ValueError('Funding resize requires bounded scope and evidence')
            for row in payload.revised_lines:
                for value in (row.available, row.planned_use):
                    if isinstance(value, Known) and Decimal(value.value.value) < 0:
                        raise ValueError('Funding resize cannot contain a negative amount')
    if action_id == "OWN-A06" and choice in {"pay", "repay"}:
        _nonempty(payload, ["lines"])
        if any(Decimal(line.amount.value) <= 0 for line in payload.lines):
            raise ValueError("Payment lines must have positive amounts")
    if action_id == "OWN-A09":
        if (choice == "publish_package") != (action_input.package_context.kind == "preparation"):
            raise ValueError("Publication needs preparation; all other branches need published context")
        if choice == "evaluate":
            disjoint(payload.ranked_bid_refs, payload.rejected_bid_refs, "Selected and rejected bids overlap")
            for refs in (payload.ranked_bid_refs, payload.rejected_bid_refs):
                if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                    raise ValueError('Tender evaluation repeats a physical bid across versions')
            if not {ref.key() for ref in payload.ranked_bid_refs + payload.rejected_bid_refs} <= {ref.key() for ref in action_input.bid_refs}:
                raise ValueError('Tender evaluation invents an undeclared original bid')
        if choice == 'publish_package':
            original = action_input.package_context
            if (payload.package.scope_ref != original.scope_ref
                    or payload.package.procedure_ref != original.procedure_ref
                    or set(payload.package.technical_submission_refs) != set(original.technical_submission_refs)
                    or set(payload.package.requirement_refs) != set(original.requirement_refs)
                    or original.quantity_basis.state != 'known'
                    or payload.package.quantity_basis_ref != original.quantity_basis.value
                    or payload.package.evaluation_profile_ref != action_input.evaluation_profile_ref):
                raise ValueError('First tender publication must preserve original scope, authorized inputs and actual quantity basis')
        if choice in {'invite', 'publish_package'} and len(set(payload.bidder_ids)) != len(payload.bidder_ids):
            raise ValueError('Tender invitation repeats a real organization')
        if choice == 'invite' and not payload.bidder_ids:
            raise ValueError('Tender invitation requires actual authorized recipients')
        if choice in {'revise_package', 'retender'}:
            if (payload.package_draft.prior_package_ref != action_input.package_context.package_ref
                    or not payload.replaced_round_refs
                    or not set(payload.replaced_round_refs) <= set(action_input.round_refs)):
                raise ValueError('Tender revision must preserve original package and declared affected rounds')
        if choice == 'cancel_round' and payload.round_ref not in action_input.round_refs:
            raise ValueError('Tender cancellation invents an undeclared original round')
        if choice == 'negotiate' and (payload.bid_ref not in action_input.bid_refs or not payload.questions):
            raise ValueError('Tender negotiation needs an original received bid and explicit questions')
        if choice == 'clarify':
            if not payload.target.request_refs or not payload.responses:
                raise ValueError('Tender clarification needs original requests and responses')
            if payload.target.kind == 'package' and payload.target.package_ref != action_input.package_context.package_ref:
                raise ValueError('Pre-bid clarification must preserve the original published package')
            if payload.target.kind == 'bid' and payload.target.bid_ref not in action_input.bid_refs:
                raise ValueError('Bid clarification borrows an undeclared received bid')
    if action_id == 'OWN-A10':
        if choice == 'accept':
            if payload.offer_ref != action_input.selected_offer_ref or payload.terms_ref != action_input.final_terms_ref:
                raise ValueError('Owner acceptance must preserve selected original offer and final terms')
            if len({ref.key() for ref in payload.condition_refs}) != len(payload.condition_refs):
                raise ValueError('Owner award acceptance repeats a formation condition')
        if choice == 'revise' and (not payload.requested_change_refs
                or len({ref.key() for ref in payload.requested_change_refs}) != len(payload.requested_change_refs)):
            raise ValueError('Owner award revision requires distinct original requested changes')
    if action_id == "BANK-A02":
        if payload.application_ref != action_input.application_ref:
            raise ValueError("Intake must preserve the submitted finance application version")
        if choice == "accept_for_review" and payload.product_ref not in action_input.product_candidates:
            raise ValueError("Accepted product must belong to supplied candidates")
    if action_id == "BANK-A03":
        if len({(row.dimension_ref.kind, row.dimension_ref.id) for row in payload.findings}) != len(payload.findings):
            raise ValueError('Credit finding dimension repeated')
        if any(row.method_ref != action_input.risk_method_ref for row in payload.findings):
            raise ValueError('Credit finding must preserve the supplied public risk method version')
        if len({(row.requirement_ref.kind, row.requirement_ref.id) for row in payload.conditions}) != len(payload.conditions):
            raise ValueError('Credit condition requirement repeated')
        if choice in {"recommend", "conditional"}:
            if not isinstance(payload.assessed_amount, Known):
                raise ValueError("Recommendation requires a known evidence-based amount range")
            interval = payload.assessed_amount.value
            if not isinstance(interval.lower, Known) or not isinstance(interval.upper, Known):
                raise ValueError('Credit recommendation requires known monetary endpoints')
            if Decimal(interval.lower.value.value) <= 0:
                raise ValueError('Credit recommendation requires a positive monetary interval')
        if choice == 'recommend' and (any(row.conclusion != 'acceptable' for row in payload.findings)
                or any(row.outcome != 'satisfied' for row in payload.conditions)):
            raise ValueError('Unconditional credit recommendation cannot conceal unresolved findings or conditions')
    if action_id == "BANK-A04" and choice in {"offer", "conditional_offer"}:
        if Decimal(payload.terms.principal_limit.value) <= 0:
            raise ValueError("Offered principal must be positive")
        if (payload.terms.product_ref != action_input.product_ref
                or payload.terms.pricing_ref not in action_input.pricing_candidates):
            raise ValueError('Quote must retain the input product and a supplied pricing candidate')
        for refs in (payload.terms.fee_rule_refs, payload.terms.condition_refs):
            if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                raise ValueError('Quote term source identity repeated')
        if choice == 'conditional_offer' and not payload.terms.condition_refs:
            raise ValueError('Conditional quote must retain explicit requirement references')
    if action_id == 'BANK-A01':
        if len({(ref.kind, ref.id) for ref in payload.basis_refs}) != len(payload.basis_refs):
            raise ValueError('Strategy observation identity repeated')
        _nonempty(payload, ['basis_refs'])
        if choice == 'investigate':
            _nonempty(payload, ['issue_refs'])
    if action_id == 'BANK-A13' and choice == 'indicative_opinion':
        if payload.range.method_ref != action_input.feasibility_method_ref:
            raise ValueError('Advisory opinion changes its original feasibility method')
        if payload.basis.kind == 'brief' and payload.basis.brief_ref != action_input.brief_ref:
            raise ValueError('Advisory opinion changes its original brief version')
        if payload.basis.kind == 'option' and payload.basis.option_ref not in action_input.option_refs:
            raise ValueError('Advisory opinion changes its supplied option version')
        _nonempty(payload.range, ['assumptions'])
    if action_id == 'BANK-A05':
        if choice == 'confirm':
            if payload.offer_ref != action_input.offer_ref or payload.acceptance_ref != action_input.borrower_acceptance_ref:
                raise ValueError('Formation confirmation must retain the exact input offer and acceptance')
            if len({(row.requirement_ref.kind, row.requirement_ref.id) for row in payload.conditions}) != len(payload.conditions):
                raise ValueError('Formation condition identity repeated')
        if choice == 'requote':
            _nonempty(payload, ['affected_requirement_refs'])
    if action_id == "BANK-A06" and choice == "approve_draw":
        _nonempty(payload, ["transfer_lines"])
        if Decimal(payload.approved_amount.value) <= 0:
            raise ValueError("Approved draw must be positive")
    if action_id == 'BANK-A09':
        if choice in {'calculate_due', 'correct_accrual'}:
            _nonempty(payload, ['basis_refs'])
            if payload.calculation_profile_ref.key() != action_input.calculation_profile_ref.key():
                raise ValueError('Debt calculation must preserve original input profile')
        if choice == 'allocate_receipt':
            _nonempty(payload, ['allocations'])
            identities = set()
            for allocation in payload.allocations:
                identity = (allocation.debt_component_ref.key(), allocation.receipt_ref.key())
                if (identity in identities or allocation.debt_component_ref.key() not in {ref.key() for ref in action_input.debt_components}
                        or allocation.receipt_ref.key() not in {ref.key() for ref in action_input.verified_receipts}
                        or Decimal(allocation.allocated.value) <= 0):
                    raise ValueError('Debt allocations require distinct original components/receipts and positive amounts')
                identities.add(identity)
        if choice == 'reconcile':
            _nonempty(payload, ['execution_refs'])
            refs = [ref.key() for ref in payload.execution_refs]
            if len(set(refs)) != len(refs) or set(refs) != {ref.key() for ref in action_input.execution_refs}:
                raise ValueError('Debt reconciliation must retain original input execution identities')
    if action_id == 'BANK-A08':
        if len({finding.dimension_ref.key() for finding in payload.findings}) != len(payload.findings):
            raise ValueError('Monitoring repeats an original risk dimension')
        if choice in {'issue_notice', 'restrict_scope', 'release_restriction'}:
            _nonempty(payload, ['basis_refs'])
            if payload.covenant_ref.key() not in {ref.key() for ref in action_input.covenant_refs}:
                raise ValueError('Monitoring measure must retain an original input covenant')
            if len({ref.key() for ref in payload.basis_refs}) != len(payload.basis_refs):
                raise ValueError('Monitoring measure repeats its evidence')
        if choice == 'request_evidence':
            _nonempty(payload, ['requirement_refs'])
            if len({ref.key() for ref in payload.requirement_refs}) != len(payload.requirement_refs):
                raise ValueError('Monitoring request repeats an original requirement')
    if action_id == "BANK-A07":
        expected = "initiate" if choice == "execute" else "existing"
        if action_input.operation_context.kind != expected:
            raise ValueError("Payment execution choice and input context mismatch")
        _nonempty(payload, ["lines"] if choice == "execute" else ["execution_refs"])
        operation = action_input.operation_context
        if choice == 'execute':
            if (payload.approval_ref.key() != operation.draw_approval_ref.key()
                    or payload.path_ref.key() != operation.path_ref.key()
                    or [line.model_dump(mode='python') for line in payload.lines]
                    != [line.model_dump(mode='python') for line in operation.lines]):
                raise ValueError('Funding execution must preserve original approval, path and transfers')
            if operation.prior_execution_refs:
                raise ValueError('Existing payment commands require reconciliation before new execution')
        else:
            refs = [ref.key() for ref in payload.execution_refs]
            if len(set(refs)) != len(refs) or set(refs) != {ref.key() for ref in operation.execution_refs}:
                raise ValueError('Reconciliation/cancellation must retain original execution identities')
    if action_id == "CONTRACTOR-A01":
        if payload.package_ref != action_input.package_ref:
            raise ValueError("Participation must preserve procurement package version")
        if choice == "clarify":
            _nonempty(payload, ["requirement_refs"])
    if action_id == "CONTRACTOR-A07":
        expected = {"execute": "ready", "rebalance": "ready", "report": "report", "reconcile": "existing"}[choice]
        if action_input.execution_context.kind != expected:
            raise ValueError("Construction choice and execution context mismatch")
        if choice == "reconcile":
            _nonempty(payload, ["execution_refs"])
        from src.actions.contracts.owner_study_objects import unique_refs
        operation = action_input.execution_context
        if choice == 'reconcile':
            unique_refs(payload.execution_refs)
            if {r.key() for r in payload.execution_refs} != {r.key() for r in operation.execution_refs}:
                raise ValueError('Construction reconciliation must preserve exact original selected executions')
        elif choice == 'report':
            row = payload.report
            if (row.task_ref != operation.task_ref
                    or {r.key() for r in row.observation_refs} != {r.key() for r in operation.observation_refs}
                    or {r.key() for r in row.execution_refs} != {r.key() for r in operation.execution_refs}):
                raise ValueError('Progress report invents or drops original task/observations/executions')
            for refs in (row.observation_refs, row.execution_refs, row.requested_requirement_refs):
                unique_refs(refs)
            if {i.requirement_ref.key() for i in row.issues} != {r.key() for r in row.requested_requirement_refs}:
                raise ValueError('Progress report issues must preserve the original requested requirements')
        else:
            if payload.task_ref != operation.task_ref or not payload.allocations:
                raise ValueError('Work input intention must preserve original task and positive resource allocations')
            unique_refs([r.resource_ref for r in payload.allocations]); unique_refs([r.allocation_ref for r in payload.materials])
            for allocation in payload.allocations:
                if (allocation.task_scope_ref != action_input.scope_ref or allocation.window_ref != operation.execution_window_ref
                        or Decimal(allocation.quantity.value) <= 0):
                    raise ValueError('Work resource intention changes original scope/window or nonzero input')
            if any(m.task_ref != operation.task_ref or Decimal(m.quantity.value) <= 0 for m in payload.materials):
                raise ValueError('Material intention must preserve original task and positive inputs')
    if action_id == "CONTRACTOR-A12" and choice in {"protect", "suspend", "resume", "handover", "exit"}:
        disjoint(payload.retain_resource_refs, payload.release_candidate_refs, "Cannot retain and release the same commitment")
    if action_id == "CONTRACTOR-A13" and choice == "provide_advice" and action_input.advisory_authority_ref is None:
        raise ValueError("Advisory output requires a bounded work authorization")
    if action_id == "SUPPLIER-A01":
        if choice in {"respond", "limited_scope", "clarify"} and payload.inquiry_ref not in action_input.inquiry_refs:
            raise ValueError("Response must name an actually received inquiry")
        if choice in {"respond", "limited_scope"}:
            _nonempty(payload, ["offered_scope_refs"])
        if choice == "clarify":
            _nonempty(payload, ["requirement_refs"])
            if len({ref.key() for ref in payload.requirement_refs}) != len(payload.requirement_refs):
                raise ValueError("Clarification requirement repeated")
        if choice == "track_market":
            if (any(ref not in action_input.market_refs for ref in payload.market_refs)
                    or len({ref.key() for ref in payload.market_refs}) != len(payload.market_refs)):
                raise ValueError("Market tracking must preserve distinct supplied observations")
        if choice == "decline" and not action_input.inquiry_refs:
            raise ValueError("Commercial refusal requires received inquiry inputs")
    if action_id == "SUPPLIER-A06" and choice != "request_maintenance":
        expected = {"execute": "production", "rebalance": "production", "reconcile_upstream": "purchase", "reconcile_execution": "reconciliation"}[choice]
        if action_input.execution_setup.kind != expected:
            raise ValueError("Supply choice and execution setup mismatch")
    if action_id == 'SUPPLIER-A06':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice in {'execute', 'rebalance'}:
            if payload.task_ref != action_input.task_ref or not payload.resources:
                raise ValueError('Production intention requires original task and actual nonzero resources')
            unique_refs([row.allocation_ref for row in payload.inputs])
            unique_refs([row.resource_ref for row in payload.resources])
            if any(Decimal(row.quantity.value) <= 0 for row in [*payload.inputs, *payload.resources]):
                raise ValueError('Actual production inputs must have positive original quantities')
        elif choice == 'reconcile_execution':
            _nonempty(payload, ('execution_refs',)); unique_refs(payload.execution_refs)
            if ({r.key() for r in payload.execution_refs} != {r.key() for r in action_input.execution_setup.execution_refs}
                    or not {r.key() for r in payload.execution_refs} <= {r.key() for r in action_input.prior_execution_refs}):
                raise ValueError('Production query must preserve exact original selected execution IDs')
        elif choice == 'reconcile_upstream':
            _nonempty(payload, ('delivery_refs',)); unique_refs(payload.delivery_refs)
            if {r.key() for r in payload.delivery_refs} != {r.key() for r in action_input.upstream_delivery_refs}:
                raise ValueError('External delivery query must preserve original physical delivery IDs')
        elif choice == 'request_maintenance':
            _nonempty(payload, ('issue_refs',)); unique_refs(payload.issue_refs)
    if action_id == "SUPPLIER-A02":
        if choice == "clarify":
            _nonempty(payload, ["requirement_refs"])
            if any(ref not in action_input.requirement_refs for ref in payload.requirement_refs):
                raise ValueError("Product clarification must preserve supplied requirement versions")
            if len({ref.key() for ref in payload.requirement_refs}) != len(payload.requirement_refs):
                raise ValueError("Product clarification requirement repeated")
        if choice in {"propose_original", "propose_substitute"}:
            _nonempty(payload, ["lines", "evidence_refs"])
            covered = []
            for line in payload.lines:
                if line.product_ref not in action_input.product_candidates:
                    raise ValueError("Proposed product must be a supplied candidate version")
                if (not line.requirement_refs or Decimal(line.quantity.value) <= 0
                        or any(ref not in action_input.requirement_refs for ref in line.requirement_refs)):
                    raise ValueError("Product line requires positive quantity and supplied requirements")
                if choice == "propose_original" and line.deviation_refs:
                    raise ValueError("Original proposal cannot conceal product deviations")
                covered.extend(ref.key() for ref in line.requirement_refs)
            if len(set(covered)) != len(covered) or set(covered) != {ref.key() for ref in action_input.requirement_refs}:
                raise ValueError("Proposal must cover each supplied requirement exactly once")
            if choice == "propose_substitute" and not any(line.deviation_refs for line in payload.lines):
                raise ValueError("Substitute proposal must disclose deviations")
            for refs in (payload.evidence_refs, payload.unresolved_refs):
                if len({ref.key() for ref in refs}) != len(refs):
                    raise ValueError("Product evidence or unresolved issue repeated")
    if action_id == "SUPPLIER-A07" and choice in {"isolate", "scrap"}:
        if Decimal(payload.quantity.value) <= 0:
            raise ValueError("Batch disposition quantity must be positive")
    if action_id == 'SUPPLIER-A07':
        from src.actions.contracts.owner_study_objects import unique_refs
        from src.organization.registry import scope_covers
        if choice in {'isolate','scrap'}:
            if payload.batch_ref != action_input.batch_ref or not payload.basis_refs:
                raise ValueError('Batch disposition must preserve original batch and actual basis')
            unique_refs(payload.basis_refs)
        elif choice in {'self_check','request_external_check'}:
            unique_refs(payload.evidence_refs)
            if {r.key() for r in payload.evidence_refs} != {r.key() for r in action_input.evidence_refs}:
                raise ValueError('Batch inspection must preserve original received evidence versions')
        elif choice == 'propose_deviation':
            _nonempty(payload,('deviation_refs',));unique_refs(payload.deviation_refs)
        elif choice == 'rework':
            if not payload.tasks or len({t.local_key for t in payload.tasks}) != len(payload.tasks):
                raise ValueError('Batch rework requires original nonempty unique task drafts')
            for task in payload.tasks:
                if (task.mode != 'rework' or not scope_covers(action_input.scope_ref,task.scope_ref)
                        or not scope_covers(task.scope_ref,task.target.destination_scope_ref)
                        or Decimal(task.target.quantity.value) <= 0):
                    raise ValueError('Batch rework draft changes original scope, mode or positive target')
                unique_refs(task.dependency_refs);unique_refs([r.resource_ref for r in task.resources])
                unique_refs([i.product_ref for i in task.planned_inputs])
    if action_id == "SUPPLIER-A03" and choice == "quote":
        _nonempty(payload.offer, ["lines", "cost_basis_refs"])
        for line in payload.offer.lines:
            if (Decimal(line.price.value) <= 0 or Decimal(line.product.quantity.value) <= 0
                    or not line.product.requirement_refs or not line.included_service_refs):
                raise ValueError("Binding quote lines require positive quantity/price and explicit scope/services")
        if len({line.price.currency for line in payload.offer.lines}) != 1:
            raise ValueError("Binding quote cannot silently mix currencies")
        if any(ref not in action_input.cost_basis_refs for ref in payload.offer.cost_basis_refs):
            raise ValueError("Binding quote cost references must come from the supplied exact versions")
        for refs in (payload.offer.cost_basis_refs, payload.offer.condition_refs):
            if len({ref.key() for ref in refs}) != len(refs):
                raise ValueError("Binding quote basis or conditions repeated")
        if any(Decimal(row.quantity.value) <= 0 for row in payload.proposed_allocations):
            raise ValueError("Proposed resource quantities must be positive")
    if action_id == "SUPPLIER-A04":
        if choice in {"accept", "accept_partial"}:
            if payload.offer_ref != action_input.offer_ref:
                raise ValueError("Order acceptance must preserve the supplied exact offer version")
            _nonempty(payload, ["accepted_lines"])
            for line in payload.accepted_lines:
                if (Decimal(line.product.quantity.value) <= 0 or Decimal(line.price.value) <= 0
                        or not line.product.requirement_refs or not line.included_service_refs):
                    raise ValueError("Accepted delivery needs positive quantity/price and explicit responsibilities")
                for refs in (line.product.requirement_refs, line.product.deviation_refs, line.included_service_refs):
                    if len({ref.key() for ref in refs}) != len(refs):
                        raise ValueError("Accepted delivery references repeated")
            if len({line.price.currency for line in payload.accepted_lines}) != 1:
                raise ValueError("Order acceptance cannot mix currencies")
            if any(Decimal(row.quantity.value) <= 0 for row in payload.proposed_allocations):
                raise ValueError("Proposed order allocations must be positive")
        if choice == "revise":
            _nonempty(payload, ["changed_requirement_refs"])
            if len({ref.key() for ref in payload.changed_requirement_refs}) != len(payload.changed_requirement_refs):
                raise ValueError("Order revision requirement repeated")
    if action_id == "SUPPLIER-A08" and choice == "reroute" and payload.current_position_ref not in action_input.position_refs:
        raise ValueError("Rerouting must preserve a visible actual transport position")
    if action_id == 'SUPPLIER-A08':
        from src.actions.contracts.owner_study_objects import unique_refs
        if choice in {'dispatch','split'}:
            if not payload.plans or choice == 'split' and len(payload.plans) < 2:
                raise ValueError('Dispatch requires concrete plans and split requires multiple partitions')
            for plan in payload.plans:
                if plan.route_ref not in action_input.route_candidates or Decimal(plan.quantity.value) <= 0 or not plan.transport_allocation_refs:
                    raise ValueError('Dispatch requires original route and positive physical stock/allocation')
                unique_refs(plan.transport_allocation_refs);unique_refs(plan.condition_evidence_refs)
        elif choice == 'reconcile':
            _nonempty(payload,('shipment_refs',));unique_refs(payload.shipment_refs)
            if not {r.key() for r in payload.shipment_refs} <= {r.key() for r in action_input.shipment_refs}:
                raise ValueError('Transport query must use original existing shipment IDs')
        elif choice == 'reroute':
            if payload.shipment_ref not in action_input.shipment_refs or payload.replacement_route_ref not in action_input.route_candidates:
                raise ValueError('Reroute requires original shipment and received replacement route')
        elif choice == 'reschedule':
            target = payload.target
            refs = target.line_refs if target.kind == 'order_lines' else target.shipment_refs
            if not refs:raise ValueError('Reschedule requires nonempty discriminated original target')
            unique_refs(refs)
            if target.kind == 'shipments' and not {r.key() for r in refs} <= {r.key() for r in action_input.shipment_refs}:
                raise ValueError('Shipment reschedule requires original existing transport tasks')
    if action_id == "SUPPLIER-A13" and choice in {"indicative_advice", "limited_disclosure"} and action_input.advisory_scope_ref is None:
        raise ValueError("Supply advice requires a bounded work authorization")
