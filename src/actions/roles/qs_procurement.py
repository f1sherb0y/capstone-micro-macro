"""QS-A05 compiles original quantities and requests separately authorized publication."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementScopeView, QSProcurementTaskView, QSProcurementRoundView,
    QSProcurementTemplateView, QSProcurementDesignView, QSMeasurementRuleView,
    QSPricingRuleView, QSProcurementQuantityView, QSProcurementGapView,
    QSProcurementResponseView, QSProcurementExclusionView, QSProcurementPackageView,
    QSProcurementRevisionView, QSProcurementDocumentView, QSPublicationBasisView,
    QSProcurementPublicationAuthorityView, procurement_document_digest,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_procurement(context, action_input, reading):
    scope, now = action_input.scope, context.business_time
    revision_note = ''

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('qs-procurement-clock-conversion')

    def current(window, at=now):
        clock(window.start); clock(at)
        return window.contains(at)

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('qs-procurement-evidence-schema')
            if row.effective_window is not None and not current(row.effective_window):
                _needs('current_procurement_evidence', [ref])

    def read(ref, schema, active=True):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported('qs-procurement-projection:' + ref.kind)
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'scope') and row.scope != scope: raise ValueError('Procurement input changes authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_procurement_input', [ref])
            if active and not current(row.effective_window): _needs('current_procurement_input', [ref])
        return row

    def authority(ref, actor, function, action, roles, at=now, organization=None):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        evidence(grant.basis_refs + assignment.basis_refs)
        if (grant.actor_id != actor or grant.function_ref != function or assignment.role not in roles
                or (organization is not None and grant.organization_id != organization)):
            raise ValueError('Procurement source author or legal organization differs from original authority')
        if not current(grant.validity, at) or action not in grant.action_ids or not any(scope_covers(s, scope) for s in grant.scopes):
            _needs('original_procurement_authority', [ref])

    def author(row, roles, organization=None):
        assignment = read(row.author_function_ref, RoleAssignment)
        actions = {'Architect': {'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A13'},
            'Engineer': {'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A13'}, 'QS': {'QS-A04', 'QS-A05'}}
        if row.author_action_id not in actions.get(assignment.role, set()):
            _unsupported('qs-procurement-original-author-function')
        authority(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_action_id, roles, row.available_at, organization)

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope,
            'note': 'Original procurement cost-document decision only; saved versions and source limitations remain; no tender approval, construction permission, debt or cash effect' + revision_note, **fields}}

    try:
        procurement = read(action_input.procurement_scope_ref, QSProcurementScopeView)
        task = read(procurement.task_ref, QSProcurementTaskView)
        round_ = read(procurement.round_ref, QSProcurementRoundView)
        template = read(procurement.template_ref, QSProcurementTemplateView)
        if (task.procurement_scope_ref != procurement.ref or task.round_ref != round_.ref
                or task.organization_id != reading.organization_id or task.function_ref != context.function_ref
                or round_.procurement_scope_ref != procurement.ref or round_.template_ref != template.ref
                or round_.buyer_id != procurement.buyer_id or round_.buyer_organization_id != procurement.buyer_organization_id):
            raise ValueError('Procurement task changes original scope, round, buyer, template or QS organization')
        authority(task.authority_ref, context.actor_id, task.function_ref, 'QS-A05', {'QS'}, organization=reading.organization_id)
        if task.status != 'authorized' or round_.status not in {'preparation', 'open'}:
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'qs_procurement_task_or_round_not_ready', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref, round_.ref], 'earliest_time': None,
                'condition_code': 'qs.procurement.authorized_active_round'}}
        if 'procurement' not in template.allowed_uses: _unsupported('qs-procurement-template-use')
        unique_refs(action_input.design_refs)
        questions, seen_questions = [], set()
        recipients = {procurement.buyer_id}
        designs = [read(ref, QSProcurementDesignView) for ref in action_input.design_refs]
        for row in designs:
            author(row, {'Architect', 'Engineer'})
            recipients.add(row.author_actor_id)

        def question(issue, line_key=None, direct_ref=None):
            refs = [direct_ref] if direct_ref is not None else procurement.question_refs
            matches = []
            for ref in refs:
                row = read(ref, QSProcurementGapView)
                if row.issue != issue or (line_key is not None and row.line_key != line_key): continue
                requirement = read(row.response_requirement_ref, QSProcurementResponseView)
                if (row.procurement_scope_ref != procurement.ref or row.round_ref != round_.ref
                        or requirement.procurement_scope_ref != procurement.ref or requirement.round_ref != round_.ref
                        or not set(row.recipient_ids) <= set(requirement.recipient_ids)
                        or not set(row.recipient_ids) <= recipients or 'procurement' not in row.blocking_uses):
                    raise ValueError('Procurement question changes original round, scope or authorized recipients')
                matches.append(row)
                if row.ref.key() not in seen_questions:
                    seen_questions.add(row.ref.key())
                    questions.append({'scope': scope, 'target_refs': [row.ref], 'question': row.question,
                        'recipient_ids': row.recipient_ids, 'evidence_refs': row.evidence_refs,
                        'blocking_uses': row.blocking_uses, 'response_requirement_ref': requirement.ref})
            if not matches: _needs('registered_procurement_' + issue + '_question')

        def gaps():
            return completed('identify_gaps', questions=questions)

        if set(action_input.design_refs) != set(procurement.design_refs) or any('procurement' not in r.allowed_uses for r in designs):
            question('design'); return gaps()
        if (action_input.measurement_rule_ref != procurement.measurement_rule_ref
                or action_input.measurement_rule_ref not in template.measurement_rule_refs):
            question('measurement'); return gaps()
        measurement = read(action_input.measurement_rule_ref, QSMeasurementRuleView)
        if 'procurement' not in measurement.allowed_uses: question('measurement'); return gaps()
        if action_input.prior_document_ref != procurement.prior_document_ref:
            raise ValueError('Procurement revision changes original predecessor document identity')
        if action_input.quantity_schedule_ref is None or action_input.quantity_schedule_ref != procurement.quantity_schedule_ref:
            question('quantity'); return gaps()
        quantity = read(action_input.quantity_schedule_ref, QSProcurementQuantityView)
        author(quantity, {'QS'}, reading.organization_id)
        if (quantity.procurement_scope_ref != procurement.ref or quantity.round_ref != round_.ref
                or set(quantity.design_refs) != set(action_input.design_refs) or quantity.measurement_rule_ref != measurement.ref):
            question('quantity'); return gaps()
        pricing = read(procurement.pricing_rule_ref, QSPricingRuleView)
        if (pricing.ref not in template.pricing_rule_refs or pricing.round_ref != round_.ref
                or set(pricing.design_refs) != set(action_input.design_refs) or pricing.quantity_schedule_ref != quantity.ref
                or pricing.measurement_rule_ref != measurement.ref or 'procurement' not in pricing.allowed_uses
                or set(pricing.excluded_scope_refs) != set(procurement.exclusions)):
            question('pricing'); return gaps()
        exclusions = [read(ref, QSProcurementExclusionView) for ref in procurement.exclusions]
        if set(pricing.included_coverage_keys) & {k for row in exclusions for k in row.coverage_keys}:
            question('pricing'); return gaps()
        design_by_ref = {r.ref: r for r in designs}
        covered = set()
        for line in quantity.lines:
            evidence(line.basis_refs)
            if line.design_ref not in design_by_ref or not scope_covers(scope, line.covered_scope):
                raise ValueError('Quantity line borrows another design or unauthorized physical scope')
            if not set(line.coverage_keys) <= set(design_by_ref[line.design_ref].coverage_keys):
                raise ValueError('Quantity line exceeds original design coverage')
            if covered & set(line.coverage_keys): question('quantity', line.line_key); return gaps()
            covered.update(line.coverage_keys)
            if not set(line.coverage_keys) <= set(pricing.included_coverage_keys): question('pricing'); return gaps()
            if line.quantity.state == 'known':
                evidence([line.quantity.value.basis_ref])
                if line.quantity.value.unit not in measurement.supported_units: question('measurement'); return gaps()
            else:
                question('quantity', line.line_key, line.provisional_question_ref)
                if (line.quantity.state != 'unknown' or template.procurement_mode != 'provisional_quantity'
                        or not measurement.provisional_quantities_supported or not pricing.provisional_quantities_supported):
                    return gaps()
        if covered != {k for row in designs for k in row.coverage_keys}:
            question('quantity'); return gaps()
        if procurement.prior_document_ref is not None:
            prior = read(procurement.prior_document_ref, QSProcurementDocumentView, False)
            author(prior, {'QS'}, reading.organization_id)
            if prior.ref == procurement.saved_document_ref or prior.draft.procurement_scope_ref.id != procurement.ref.id:
                raise ValueError('Procurement predecessor changes original document chain')
            changed_design = set(prior.draft.design_refs) != set(action_input.design_refs)
            changed_quantity = prior.draft.quantity_schedule_ref != quantity.ref
            if (changed_design or changed_quantity) and prior.draft.pricing_rule_ref == pricing.ref:
                question('pricing'); return gaps()
            changed = (changed_design or changed_quantity or prior.draft.measurement_rule_ref != measurement.ref
                or prior.draft.pricing_rule_ref != pricing.ref or prior.round_ref != round_.ref)
            if changed:
                if procurement.revision_impact_ref is None: question('revision'); return gaps()
                impact = read(procurement.revision_impact_ref, QSProcurementRevisionView)
                if (impact.procurement_scope_ref != procurement.ref or impact.round_ref != round_.ref
                        or impact.prior_document_ref != prior.ref or set(impact.design_refs) != set(action_input.design_refs)
                        or impact.quantity_schedule_ref != quantity.ref or impact.pricing_rule_ref != pricing.ref):
                    raise ValueError('Revision impact changes original documents or affected quantity/price versions')
                previous_quantity = read(prior.draft.quantity_schedule_ref, QSProcurementQuantityView, False)
                previous_lines = {r.line_key: r for r in previous_quantity.lines}
                previous_keys = set(previous_lines)
                current_lines = {r.line_key: r for r in quantity.lines}
                expected_links = {(old, row.line_key) for row in quantity.lines for old in row.predecessor_line_keys}
                if any(old not in previous_keys for old, key in expected_links):
                    raise ValueError('Quantity revision invents an original predecessor')
                for key, line in current_lines.items():
                    if key in previous_lines and not line.predecessor_line_keys:
                        old = previous_lines[key]
                        if line.quantity != old.quantity or line.design_ref != old.design_ref or line.coverage_keys != old.coverage_keys:
                            question('revision'); return gaps()
                expected_removed = previous_keys - set(current_lines) - {old for old, key in expected_links}
                tracked, removed = set(), set()
                summaries = []
                for change in impact.changes:
                    package = read(change.package_ref, QSProcurementPackageView, False)
                    if package.procurement_scope_ref.id != procurement.ref.id or package.round_ref != prior.round_ref:
                        raise ValueError('Revision impact borrows another package or original procurement round')
                    if change.previous_line_key not in previous_keys:
                        raise ValueError('Revision invents an original predecessor quantity line')
                    old_value = previous_lines[change.previous_line_key].quantity
                    old_amount = old_value.value.value + ' ' + old_value.value.unit if old_value.state == 'known' else old_value.state
                    if not change.current_line_keys:
                        if change.previous_line_key not in expected_removed or change.previous_line_key in removed:
                            raise ValueError('Revision repeats or invents a removed quantity line')
                        removed.add(change.previous_line_key)
                        summaries.append(f'{package.ref.id}@{package.ref.version}:{change.previous_line_key}={old_amount}->removed')
                    for key in change.current_line_keys:
                        link = (change.previous_line_key, key)
                        if link in tracked or key not in current_lines or change.previous_line_key not in current_lines[key].predecessor_line_keys:
                            raise ValueError('Revision duplicates or loses original split/merged quantity identity')
                        tracked.add(link)
                        value = current_lines[key].quantity
                        amount = value.value.value + ' ' + value.value.unit if value.state == 'known' else value.state
                        summaries.append(f'{package.ref.id}@{package.ref.version}:{change.previous_line_key}={old_amount}->{key}={amount}')
                if tracked != expected_links or removed != expected_removed:
                    question('revision'); return gaps()
                revision_note = '; affected package/quantity: ' + ', '.join(summaries)
        draft = {'procurement_scope_ref': procurement.ref, 'design_refs': action_input.design_refs,
            'quantity_schedule_ref': quantity.ref, 'measurement_rule_ref': measurement.ref, 'pricing_rule_ref': pricing.ref,
            'exclusions': procurement.exclusions, 'open_questions': questions, 'prior_document_ref': procurement.prior_document_ref}
        if task.operation == 'compile': return completed('prepare', draft=draft)
        if procurement.saved_document_ref is None: _needs('saved_procurement_document_for_publication')
        document = read(procurement.saved_document_ref, QSProcurementDocumentView)
        author(document, {'QS'}, reading.organization_id)
        if (document.round_ref != round_.ref or document.draft.model_dump(mode='json') !=
                type(document.draft).model_validate(draft).model_dump(mode='json')):
            question('revision'); return gaps()
        if document.status == 'withdrawn': question('publication'); return gaps()

        def request_publication():
            return completed('request_publication', document_ref=document.ref, recipient_id=procurement.buyer_id)

        if action_input.publication_authority_ref is None: return request_publication()
        grant = read(action_input.publication_authority_ref, QSProcurementPublicationAuthorityView, False)
        if (grant.procurement_scope_ref != procurement.ref or grant.round_ref != round_.ref or grant.document_ref != document.ref
                or grant.delegate_actor_id != context.actor_id or grant.delegate_organization_id != reading.organization_id
                or grant.delegate_function_ref != context.function_ref or grant.buyer_actor_id != procurement.buyer_id
                or grant.buyer_organization_id != procurement.buyer_organization_id):
            raise ValueError('Publication grant changes original buyer, delegate, document or round')
        clock(grant.granted_at)
        if grant.granted_at.offset > grant.available_at.offset: _needs('received_original_publication_grant')
        authority(grant.buyer_authority_ref, procurement.buyer_id, grant.buyer_function_ref, 'OWN-A09', {'Owner'},
            grant.granted_at, procurement.buyer_organization_id)
        if not current(grant.effective_window) or grant.permission.state != 'known' or not grant.permission.value:
            return request_publication()
        basis = read(grant.publication_basis_ref, QSPublicationBasisView)
        if (basis.procurement_scope_ref != procurement.ref or basis.round_ref != round_.ref
                or basis.document_ref != document.ref or basis.document_digest != procurement_document_digest(document.draft)):
            raise ValueError('Publication purpose check changes original saved document or contents')
        clock(basis.checked_at)
        if basis.checked_at.offset > basis.available_at.offset or basis.checked_at.offset < document.available_at.offset:
            _needs('original_saved_document_publication_check')
        authority(basis.checker_authority_ref, basis.checker_actor_id, basis.checker_function_ref, 'QS-A05', {'QS'},
            basis.checked_at, reading.organization_id)
        if basis.permitted.state != 'known' or not basis.permitted.value: question('publication'); return gaps()
        return completed('publish_authorized', document_ref=document.ref, publication_basis_ref=basis.ref)
    except ObservationGap as exc:
        reading.recheck()
        return exc.result
