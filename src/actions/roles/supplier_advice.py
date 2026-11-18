"""SUPPLIER-A13 original indicative opinions with bounded work and disclosure."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow, walk_references
from src.actions.contracts.contractor_advice_objects import (
    ContractorAdviceBriefView, ContractorAdviceOptionView, ContractorAdviceAuthorityView,
    ContractorAdviceTaskView, ContractorAdviceExecutionView, ContractorAdviceFeeView, ContractorAdviceProposalView,
)
from src.actions.contracts.supplier_advice_objects import (
    SupplierAdviceRequestView, SupplierAdviceDisclosureView, SupplierAdviceCapabilityView,
    SupplierAdviceCommitmentView, SupplierAdviceProfessionalView, SupplierAdviceMethodView,
    SupplierAdviceReferenceView, SupplierAdviceIssueView, SupplierAdviceCaseView,
)
from src.actions.contracts.supplier_product_objects import ProductSpecificationView, ProductEvidenceView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.supplier_advice import SUPPLIER_ADVICE_METHOD
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def give_supply_advice(context, action_input, reading):
    now = context.business_time

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('supplier-advice-clock-alignment')

    def evidence(refs):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('supplier-advice-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not row.effective_window.contains(now): _needs('current_original_supply_advice_evidence', [ref])

    def read(ref, schema, covered=True):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'supplier-advice-projection:{ref.kind}')
        if covered and hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Supply advice input leaves original authorized scope')
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not row.effective_window.contains(now): _needs('current_original_supply_advice_input', [ref])
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_supply_advice_input', [ref])
        evidence(getattr(row, 'evidence_refs', [])); return row

    def authorize(ref, actor, function_ref, organization, action, roles):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or action not in grant.action_ids or function.role not in roles
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            raise ValueError('Supply advice lacks independent original actor/organization/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_supply_advice_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs])

    def external_authority(row, prefix, professional=False):
        role = read(getattr(row, prefix + '_function_ref'), RoleAssignment).role
        actions = {'Owner': {'OWN-A02', 'OWN-A04'}, 'Architect': {'ARCHITECT-A13'}, 'Engineer': {'ENGINEER-A13'},
                   'QS': {'QS-A13'}, 'Contractor': {'CONTRACTOR-A13'}}
        action = getattr(row, prefix + '_action_id')
        if action not in actions.get(role, set()) or (professional and role not in {'Architect', 'Engineer', 'QS'}):
            raise ValueError('Supply advice requester/issuer has no independently authorized action')
        authorize(getattr(row, prefix + '_authority_ref'), getattr(row, prefix + '_actor_id'),
                  getattr(row, prefix + '_function_ref'), getattr(row, prefix + '_organization_id'), action, {role})

    def reference(ref, basis_ref=None, disclose=True):
        row = read(ref, SupplierAdviceReferenceView)
        if not same(row.request_ref, request.ref) or (basis_ref is not None and basis_ref.key() not in keys(row.basis_refs)):
            raise ValueError('Supply advice condition/method/use changes original request or basis')
        if not _known(row.allowed, 'original_supply_advice_reference_permission') or 'preliminary_advice' not in row.allowed_uses:
            _needs('original_supply_advice_reference_permission', [ref])
        if disclose and not set(profile.allowed_recipient_ids) <= set(row.recipient_ids):
            raise ValueError('Supply advice reference cannot be disclosed to the chosen recipients')
        return row

    def state_basis(state, disclose=False):
        if state.state == 'known':
            if disclose and state.value.basis_ref.key() not in disclosable_evidence:
                raise ValueError('Supply advice exposes an unauthorized private evidence reference')
            evidence([state.value.basis_ref])
        elif state.state == 'unknown':
            if disclose and not keys(state.missing_refs) <= disclosable_evidence:
                raise ValueError('Supply advice exposes unauthorized missing-evidence references')
        else: reference(state.rule_ref if state.state == 'not_applicable' else state.capability_ref, disclose=disclose)

    def issue(ref, basis_ref=None):
        row = read(ref, SupplierAdviceIssueView)
        if not same(row.request_ref, request.ref) or (basis_ref is not None and not same(row.basis_ref, basis_ref)):
            raise ValueError('Supply advice issue changes original scoped version')
        if not keys(row.evidence_refs_to_disclose) <= disclosable_evidence:
            raise ValueError('Supply advice issue discloses unauthorized evidence')
        evidence(row.evidence_refs_to_disclose); return row

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    def technical(code):
        reading.recheck(); return {'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'}

    def dimensions(basis):
        if len({row.code for row in basis.dimensions}) != len(basis.dimensions): raise ValueError('Supply basis repeats an original dimension')
        for row in basis.dimensions: state_basis(row.value)
        if basis.desired_delivery_at.state == 'known': clock(basis.desired_delivery_at.value)
        return {row.code: row.value for row in basis.dimensions}

    def finite_work(grant):
        if (grant.organization_id != reading.organization_id or grant.delegate_actor_id != context.actor_id
                or grant.delegate_function_ref != context.function_ref or grant.scope != context.scope
                or not same(grant.request_ref, request.ref)):
            raise ValueError('Supplier advisory work changes the original bounded delegation')
        external_authority(grant, 'issuer')
        if not set(profile.allowed_recipient_ids) <= set(grant.allowed_recipient_ids):
            raise ValueError('Supplier work delegation does not allow the chosen recipients')
        original_inputs = keys([action_input.brief_ref, *action_input.option_refs, *action_input.professional_advice_refs])
        if not original_inputs <= keys(grant.allowed_input_refs): _needs('explicit_original_supply_advice_input_permission')
        task = read(grant.task_ref, ContractorAdviceTaskView)
        if (task.organization_id != reading.organization_id or task.scope != grant.scope
                or not same(task.authority_ref, grant.ref) or not same(task.request_ref, request.ref)
                or keys(task.input_refs) != original_inputs):
            raise ValueError('Supplier study task changes original grant/input versions')
        if task.status == 'failed': return technical('supplier_advisory_study_failed'), None
        if task.status != 'completed' or task.execution_coverage != 'complete': _needs('completed_original_supplier_study')
        cap = _known(grant.max_effort, 'finite_supplier_study_effort_limit')
        cost_cap = _known(grant.max_internal_cost, 'finite_supplier_study_cost_limit')
        evidence([cap.basis_ref, cost_cap.basis_ref]); effort_sum, cost_sum = Fraction(), Fraction()
        if decimal_fraction(cap.value) <= 0 or decimal_fraction(cost_cap.value) < 0: raise ValueError('Supplier study has invalid finite limits')
        keys(task.execution_refs)
        for ref in task.execution_refs:
            work = read(ref, ContractorAdviceExecutionView); clock(work.execution_window.start)
            if (work.organization_id != reading.organization_id or work.scope != task.scope
                    or not same(work.task_ref, task.ref) or not same(work.authority_ref, grant.ref)
                    or work.execution_window.start.offset < grant.effective_window.start.offset
                    or work.execution_window.end.offset > min(now.offset, grant.effective_window.end.offset)):
                raise ValueError('Supplier study record changes original task or business window')
            if work.status == 'failed': return technical('supplier_advisory_execution_failed'), None
            if work.status != 'completed': _needs('actual_completed_supplier_study_records', [ref])
            effort = _known(work.effort, 'actual_supplier_study_effort'); cost = _known(work.internal_cost, 'actual_supplier_study_cost')
            evidence([effort.basis_ref, cost.basis_ref])
            if effort.unit != cap.unit or cost.currency != cost_cap.currency: _unsupported('supplier-study-effort-cost-domain')
            if decimal_fraction(effort.value) <= 0 or decimal_fraction(cost.value) < 0: raise ValueError('Actual supplier study effort/cost is invalid')
            effort_sum += decimal_fraction(effort.value); cost_sum += decimal_fraction(cost.value)
        if effort_sum > decimal_fraction(cap.value) or cost_sum > decimal_fraction(cost_cap.value):
            _needs('separate_authorization_for_additional_supplier_study_work')
        if grant.mode == 'paid':
            if grant.fee_obligation_ref is None: _needs('original_supplier_study_fee_arrangement')
            fee = read(grant.fee_obligation_ref, ContractorAdviceFeeView)
            if (not same(fee.authority_ref, grant.ref) or fee.creditor_id != reading.organization_id
                    or fee.debtor_id != grant.issuer_organization_id): raise ValueError('Supplier fee changes original service/parties')
            amount = _known(fee.agreed_fee, 'original_agreed_supplier_study_fee'); evidence([amount.basis_ref])
            if fee.status != 'effective' or decimal_fraction(amount.value) <= 0: _needs('effective_original_paid_supplier_study')
        elif grant.fee_obligation_ref is not None: raise ValueError('Explicit free supplier exchange cannot silently create a client fee')
        return None, task

    try:
        request = read(action_input.advisory_request_ref, SupplierAdviceRequestView)
        profile = read(action_input.disclosure_profile_ref, SupplierAdviceDisclosureView)
        if (request.recipient_organization_id != reading.organization_id or profile.organization_id != reading.organization_id
                or not same(profile.request_ref, request.ref)):
            raise ValueError('Supplier advice choice belongs to another supplier/request')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, reading.organization_id, 'SUPPLIER-A13', {'Supplier'})
        external_authority(request, 'author')
        if profile.choice == 'decline': return completed('decline')
        allowed_sources = keys(profile.allowed_source_refs)
        disclosable_evidence = keys(profile.disclosable_evidence_refs)
        brief = read(action_input.brief_ref, ContractorAdviceBriefView)
        if not same(request.brief_ref, brief.ref) or keys(request.option_refs) != keys(action_input.option_refs):
            raise ValueError('Supply consultation changes original brief/option versions')
        bases = {brief.ref.key(): brief}; dimensions(brief)
        for ref in action_input.option_refs:
            row = read(ref, ContractorAdviceOptionView)
            if not same(row.brief_ref, brief.ref): raise ValueError('Supply option changes original brief version')
            dimensions(row); bases[ref.key()] = row
        if profile.choice == 'propose_study':
            if profile.proposal_ref is None: _needs('original_finite_supplier_study_proposal')
            proposal = read(profile.proposal_ref, ContractorAdviceProposalView)
            if (proposal.organization_id != reading.organization_id or proposal.scope != context.scope
                    or not same(proposal.request_ref, request.ref)): raise ValueError('Supplier study proposal changes original scope/request')
            evidence(proposal.estimate_basis_refs)
            for state, positive in ((proposal.effort, True), (proposal.proposed_fee, False)):
                state_basis(state)
                if state.state == 'known' and (decimal_fraction(state.value.value) < 0 or (positive and decimal_fraction(state.value.value) == 0)):
                    raise ValueError('Known proposed supplier effort/fee is invalid')
            keys(proposal.condition_refs)
            for ref in proposal.condition_refs: reference(ref)
            return completed('propose_study', scope_ref=proposal.scope, fee_estimate=proposal.proposed_fee,
                             effort_estimate=proposal.effort, condition_refs=proposal.condition_refs)
        if action_input.advisory_scope_ref is None: _needs('bounded_paid_or_explicit_free_supplier_work_authorization', [request.ref])
        if not profile.allowed_recipient_ids: _needs('original_authorized_supplier_advice_recipients')
        grant = read(action_input.advisory_scope_ref, ContractorAdviceAuthorityView)
        failure, task = finite_work(grant)
        if failure is not None: return failure
        capability = read(action_input.capability_ref, SupplierAdviceCapabilityView, covered=False); clock(capability.as_of)
        if capability.organization_id != reading.organization_id: raise ValueError('Supply capability belongs to another organization')
        if capability.as_of != now or capability.coverage != 'complete': _needs('complete_current_original_supplier_advice_capability')
        withheld = keys(profile.withheld_requirement_refs)
        if not withheld <= keys(request.requirement_refs): raise ValueError('Supplier withholds an unrelated requirement')
        if profile.choice == 'indicative_advice' and withheld: raise ValueError('Withholding must use the explicit limited-disclosure branch')
        if profile.choice == 'limited_disclosure' and not withheld: _needs('explicit_original_withheld_requirements')
        if withheld and capability.disclosure_commitment_coverage != 'complete': _needs('complete_original_existing_quote_disclosure_obligations')
        required_disclosures = set(); keys(capability.commitment_refs)
        for ref in capability.commitment_refs:
            commitment = read(ref, SupplierAdviceCommitmentView, covered=False)
            if commitment.organization_id != reading.organization_id: raise ValueError('Disclosure obligation belongs to another supplier')
            evidence([commitment.disposition_basis_ref])
            if commitment.status == 'effective': required_disclosures.update(keys(commitment.required_disclosure_refs))
        if withheld & required_disclosures: _needs('required_binding_quote_information_cannot_be_hidden_by_confidentiality')
        withheld_fields = {}
        for ref in profile.withheld_requirement_refs:
            row = reference(ref, disclose=False)
            if not row.withheld_field_codes: _needs('explicit_fields_for_limited_supplier_disclosure', [ref])
            for basis_ref in row.basis_refs:
                withheld_fields.setdefault(basis_ref.key(), set()).update(row.withheld_field_codes)
        for ref in profile.unresolved_refs: issue(ref)
        if not keys(action_input.professional_advice_refs) <= keys(request.allowed_professional_advice_refs):
            raise ValueError('Supplier reads undisclosed professional advice')
        professional = {}
        for ref in action_input.professional_advice_refs:
            row = read(ref, SupplierAdviceProfessionalView)
            if row.basis_ref.key() not in bases or 'preliminary_advice' not in row.allowed_uses:
                raise ValueError('Professional opinion changes original basis or permitted use')
            external_authority(row, 'author', professional=True)
            if row.status == 'failed': return technical('supplier_original_professional_advice_failed')
            professional[ref.key()] = row
        if not action_input.feasibility_method_refs: _unsupported('supplier-preliminary-feasibility-method')
        if not keys(action_input.feasibility_method_refs) <= keys(capability.method_refs): _unsupported('supplier-advice-capability-method-domain')
        production_window = read(request.production_window_ref, TimeWindow); clock(production_window.start)
        if production_window.end.offset <= now.offset: _needs('current_or_future_original_supply_advice_production_window')
        if not profile.case_refs: _needs('original_scoped_supplier_advisory_lines')
        keys(profile.case_refs); lines, covered = [], set()
        for ref in profile.case_refs:
            case = read(ref, SupplierAdviceCaseView)
            if (case.organization_id != reading.organization_id or case.scope != context.scope
                    or not same(case.request_ref, request.ref) or not same(case.task_ref, task.ref)
                    or case.basis_ref.key() not in bases or not same(case.production_window_ref, request.production_window_ref)):
                raise ValueError('Supply estimate changes original task/basis/production-window versions')
            if case.basis_ref.key() in covered: raise ValueError('Supply advice repeats the same original basis')
            covered.add(case.basis_ref.key()); basis = bases[case.basis_ref.key()]
            if case.status == 'failed': return technical('supplier_advisory_estimate_failed')
            if case.status != 'ok': _unsupported('supplier-advisory-estimate-domain')
            if 'preliminary_advice' not in basis.allowed_uses: _needs('original_preliminary_supply_basis_use')
            if (basis.region_id not in capability.region_ids or basis.object_type not in capability.object_types
                    or not set(basis.special_condition_codes) <= set(capability.special_condition_codes)):
                _unsupported('supplier-advisory-region-object-special-condition-domain')
            if dimensions(basis) != {row.code: row.value for row in case.input_dimensions} or len({row.code for row in case.input_dimensions}) != len(case.input_dimensions):
                _needs('same_original_supplier_scale_structure_and_transport_batch')
            if case.feasibility_method_ref.key() not in keys(action_input.feasibility_method_refs): raise ValueError('Supply advice substitutes an undeclared method')
            method = read(case.feasibility_method_ref, SupplierAdviceMethodView)
            if (basis.region_id not in method.region_ids or basis.object_type not in method.object_types
                    or not set(basis.special_condition_codes) <= set(method.special_condition_codes)):
                _unsupported('supplier-feasibility-method-applicability')
            if not same(method.local_method_ref, SUPPLIER_ADVICE_METHOD): _unsupported('supplier-feasibility-local-method-binding')
            for ref_ in (method.quantity_method_ref, method.price_method_ref, method.delivery_price_method_ref):
                if reference(ref_, case.basis_ref).purpose != 'method': raise ValueError('Supply estimate cites a non-method source')
            original_sources = {r.key() for r in walk_references(case.estimate)}
            if not original_sources <= allowed_sources & keys(grant.allowed_input_refs):
                raise ValueError('Supply estimate borrows unapproved private source material')
            if not {case.basis_ref.key(), request.production_window_ref.key(), method.ref.key()} <= keys(case.estimate.source_refs):
                raise ValueError('Supply estimate is detached from original basis/method/window')
            for ref_ in case.estimate.source_refs: reading.resolve(ref_)
            for state in (case.estimate.quantity_lower, case.estimate.quantity_upper, case.estimate.unit_price_lower,
                          case.estimate.unit_price_upper, case.estimate.fixed_price_lower, case.estimate.fixed_price_upper,
                          case.estimate.effective_throughput): state_basis(state)
            evidence([case.estimate.duration_tick.basis_ref, case.estimate.result_basis_ref])
            if not keys(case.product_refs) <= keys(capability.product_refs): raise ValueError('Supply advice proposes another supplier portfolio')
            issue_codes = set(); keys(case.interface_issue_refs)
            for ref_ in case.interface_issue_refs: issue_codes.add(issue(ref_, case.basis_ref).code)
            if not {'site_receiving', 'installation'} <= issue_codes:
                _needs('original_site_receiving_and_installation_responsibility_conditions')
            for ref_ in case.product_refs:
                product = read(ref_, ProductSpecificationView)
                if product.supplier_organization_id != reading.organization_id: raise ValueError('Supply product belongs to another supplier')
                if product.quantity_unit != case.estimate.throughput_quantity_unit: _unsupported('supplier-advice-product-quantity-unit-domain')
                if product.factory_id.state != 'known' or product.use_codes.state != 'known' or product.properties.state != 'known':
                    if 'product_unverified' not in issue_codes: _needs('explicit_original_product_factory_and_use_limits')
                for product_evidence_ref in product.product_evidence_refs:
                    original = read(product_evidence_ref, ProductEvidenceView)
                    if not same(original.product_ref, product.ref): raise ValueError('Supplier borrows another product evidence')
                    if product.factory_id.state == 'known' and original.factory_id != product.factory_id.value:
                        raise ValueError('Supplier evidence belongs to another factory')
                    if product.use_codes.state == 'known' and original.intended_use_code not in product.use_codes.value:
                        raise ValueError('Supplier evidence belongs to another intended use')
            if not keys(case.professional_advice_refs) <= set(professional): raise ValueError('Case applies unread professional advice')
            for ref_ in case.professional_advice_refs:
                row = professional[ref_.key()]
                if not same(row.basis_ref, case.basis_ref): raise ValueError('Case silently applies another professional version')
                if row.status != 'ok' and 'professional_interface' not in issue_codes: _needs('original_unverified_professional_interface_issue')
                if not keys(row.issue_refs) <= keys([*profile.unresolved_refs, *case.interface_issue_refs]):
                    _needs('all_original_professional_interface_gaps_retained')
            use = reference(case.permitted_use_ref, case.basis_ref)
            if use.purpose != 'use' or not use.condition_refs or not use.assumption_refs:
                _needs('original_supply_estimate_maturity_assumptions_and_validity_conditions')
            for ref_ in [*use.condition_refs, *use.assumption_refs]: reference(ref_, case.basis_ref)
            for ref_ in case.route_refs:
                if reference(ref_, case.basis_ref).purpose != 'route': raise ValueError('Supply advice uses an unrelated transport route')
            if not case.logistics_condition_refs: _needs('original_transport_site_and_delivery_conditions')
            keys(case.route_refs); keys(case.logistics_condition_refs); keys(case.logistics_unresolved_refs)
            for ref_ in case.logistics_condition_refs: reference(ref_, case.basis_ref)
            logistics_issues = [issue(ref_, case.basis_ref) for ref_ in case.logistics_unresolved_refs]
            hidden = withheld_fields.get(case.basis_ref.key(), set())
            if 'quantity' in hidden: hidden = hidden | {'indicative_price', 'manufacturing_duration'}
            for state in (case.logistics_duration, case.delivery_price_lower, case.delivery_price_upper):
                state_basis(state, disclose='logistics' not in hidden)
                if state.state == 'known' and decimal_fraction(state.value.value) < 0: raise ValueError('Logistics estimate cannot be negative')
            low, high = case.delivery_price_lower, case.delivery_price_upper
            if low.state == high.state == 'known' and (low.value.currency != high.value.currency or decimal_fraction(low.value.value) > decimal_fraction(high.value.value)):
                _unsupported('supplier-advice-delivery-cost-domain')
            if not case.route_refs and case.logistics_duration.state == 'known': _needs('original_route_basis_for_known_transport_duration')
            if any(state.state != 'known' for state in (case.logistics_duration, low, high)) and not logistics_issues:
                _needs('explicit_unknown_or_unsupported_logistics_issue')
            if not keys(case.evidence_refs_to_disclose) <= disclosable_evidence: raise ValueError('Supplier opinion leaks private evidence')
            evidence(case.evidence_refs_to_disclose)
            result = reading.calculate(SUPPLIER_ADVICE_METHOD, case.estimate)
            if result.kind != 'ok':
                if result.kind == 'invalid_input': _unsupported('supplier-declared-supply-range-method-domain')
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information': raw['requested_refs'] = []
                raise ObservationGap(raw)
            report = result.value
            gap = {'state': 'unknown', 'reason_code': 'withheld_by_supplier_choice', 'missing_refs': []}
            for field, states in (('quantity', (report.quantity_lower, report.quantity_upper)),
                                  ('indicative_price', (report.price_lower, report.price_upper)),
                                  ('manufacturing_duration', (report.manufacturing_duration,))):
                if field not in hidden:
                    for state in states: state_basis(state, disclose=True)
            lines.append({'basis': {'kind': 'brief', 'brief_ref': case.basis_ref} if case.basis_ref.kind == 'OwnerBrief'
                          else {'kind': 'option', 'option_ref': case.basis_ref}, 'product_refs': case.product_refs,
                'quantity': {'lower': gap if 'quantity' in hidden else report.quantity_lower,
                    'upper': gap if 'quantity' in hidden else report.quantity_upper, 'method_ref': method.quantity_method_ref},
                'indicative_price': {'lower': gap if 'indicative_price' in hidden else report.price_lower,
                    'upper': gap if 'indicative_price' in hidden else report.price_upper, 'method_ref': method.price_method_ref},
                'manufacturing_duration': gap if 'manufacturing_duration' in hidden else report.manufacturing_duration,
                'logistics': {'route_refs': [] if 'logistics' in hidden else case.route_refs,
                    'duration': gap if 'logistics' in hidden else case.logistics_duration,
                    'delivery_cost': {'lower': gap if 'logistics' in hidden else low,
                        'upper': gap if 'logistics' in hidden else high, 'method_ref': method.delivery_price_method_ref},
                    'condition_refs': case.logistics_condition_refs, 'unresolved_refs': case.logistics_unresolved_refs},
                'interface_issue_refs': case.interface_issue_refs, 'evidence_refs': case.evidence_refs_to_disclose,
                'permitted_use_ref': case.permitted_use_ref})
        expected = keys(action_input.option_refs) if action_input.option_refs else {brief.ref.key()}
        if covered != expected: _needs('complete_original_supplier_brief_or_option_advice')
        return completed(profile.choice, lines=lines, withheld_requirement_refs=profile.withheld_requirement_refs,
                         unresolved_refs=profile.unresolved_refs)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
