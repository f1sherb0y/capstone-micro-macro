"""Resume the same procurement task only when its task and round are ready."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementScopeView, QSProcurementTaskView, QSProcurementRoundView, QSProcurementTemplateView,
    QSProcurementDesignView, QSMeasurementRuleView, QSPricingRuleView, QSProcurementQuantityView,
    QSProcurementDocumentView, QSProcurementRevisionView, QSProcurementPublicationAuthorityView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'qs.procurement.authorized_active_round'
_FIELDS = frozenset({'scope', 'procurement_scope_ref', 'design_refs', 'measurement_rule_ref',
    'quantity_schedule_ref', 'prior_document_ref', 'publication_authority_ref'})
_ACTIVE = frozenset({'preparation', 'open'})


@dataclass(frozen=True)
class QSProcurementConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def qs_original_procurement_task_round_profile(read_current, validate_relation):
    """Ready starts fresh judgment; it saves or publishes no procurement document."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS procurement recovery requires actual sources and native task/round/history validation')

    def indexed(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('QS procurement recovery duplicates a physical source')
        return rows

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A05' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 2 or [ref.kind for ref in old_refs] != ['Task', 'ProcurementRound']):
            raise TaskConflict('QS procurement recovery substitutes original joint task/round wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSProcurementConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS procurement recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(old_input) != _FIELDS or set(action_input) != _FIELDS or task_digest(old_input) != source['input_sha256']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A05'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or old_input['scope'] != action_input['scope']):
                raise TaskConflict('QS procurement recovery changes original snapshot, scope or current invocation')
            scope, now = TypeAdapter(ScopeRef).validate_python(action_input['scope']), context.business_time
            if context.scope != scope:
                raise TaskConflict('QS procurement recovery changes original procurement coverage')
            reading.check_method_context(context, 'QS-A05')
            proof_rows, proof_refs = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != scope:
                    raise TaskConflict('QS procurement recovery lacks an exact scoped original/current source')
                proof_rows.append(row)
                return row

            versions = []
            for raw in (old_input, action_input):
                procurement = read(ref_type('ProcurementScope').model_validate(raw['procurement_scope_ref']), QSProcurementScopeView)
                task = read(procurement.task_ref, QSProcurementTaskView)
                round_ = read(procurement.round_ref, QSProcurementRoundView)
                template = read(procurement.template_ref, QSProcurementTemplateView)
                if (task.procurement_scope_ref != procurement.ref or task.round_ref != round_.ref
                        or round_.procurement_scope_ref != procurement.ref or round_.template_ref != template.ref
                        or round_.buyer_id != procurement.buyer_id or round_.buyer_organization_id != procurement.buyer_organization_id
                        or task.organization_id != source['organization_id']):
                    raise TaskConflict('QS procurement recovery substitutes original task, round, template, buyer or QS organization')
                versions.append({'procurement': procurement, 'task': task, 'round': round_, 'template': template})
            old, current = versions
            original, procurement = old['procurement'], current['procurement']
            task, round_, template = current['task'], current['round'], current['template']
            if (old['task'].ref != old_refs[0] or old['round'].ref != old_refs[1]
                    or (old['task'].status == 'authorized' and old['round'].status in _ACTIVE)
                    or any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field in old)
                    or original.buyer_id != procurement.buyer_id or original.buyer_organization_id != procurement.buyer_organization_id
                    or old['task'].organization_id != task.organization_id or old['task'].function_ref != task.function_ref
                    or old['task'].operation != task.operation or task.function_ref != context.function_ref
                    or task.authority_ref not in context.authorization_refs or old['template'].procurement_mode != template.procurement_mode
                    or old['template'].allowed_uses != template.allowed_uses):
                raise TaskConflict('QS procurement recovery changes original joint wait, task purpose, buyer or procurement mode')
            if task.status != 'authorized' or round_.status not in _ACTIVE:
                return 'waiting'
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in current.values()):
                return 'unavailable'

            def authorize(ref, actor, function_ref, action, at, roles, organization=None):
                grant, function = reading.resolve(ref), reading.resolve(function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                        or function.function_ref != function_ref or function.role not in roles
                        or grant.actor_id != actor or grant.function_ref != function_ref or action not in grant.action_ids
                        or at.clock_ref != now.clock_ref or at.offset > now.offset or not grant.validity.contains(at)
                        or organization is not None and grant.organization_id != organization
                        or not any(scope_covers(s, scope) for s in grant.scopes)):
                    raise TaskConflict('QS procurement recovery lacks original author or current QS task authority')
                actions = {'QS': {'QS-A04', 'QS-A05'}, 'Architect': {'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A13'},
                    'Engineer': {'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A13'}}
                if action not in actions.get(function.role, set()):
                    raise TaskConflict('QS procurement recovery changes original author function/action')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])

            authorize(task.authority_ref, context.actor_id, task.function_ref, 'QS-A05', now, {'QS'}, source['organization_id'])
            designs = []
            for raw, bases in ((old_input, old), (action_input, current)):
                refs = indexed([ref_type('Deliverable').model_validate(value) for value in raw['design_refs']])
                if raw is action_input and {ref.key() for ref in refs.values()} != {ref.key() for ref in procurement.design_refs}:
                    raise TaskConflict('QS procurement successor omits its complete current declared design set')
                for key, ref in indexed(bases['procurement'].design_refs).items():
                    if key in refs and refs[key] != ref:
                        raise TaskConflict('QS procurement history selects two versions of one declared design')
                    refs[key] = ref
                designs.append({key: read(ref, QSProcurementDesignView) for key, ref in refs.items()})
            if not designs[0].keys() <= designs[1].keys():
                raise TaskConflict('QS procurement recovery drops original known design identities')
            histories = {'design_refs': {'original': [row.model_dump(mode='json') for row in designs[0].values()],
                'current': [row.model_dump(mode='json') for row in designs[1].values()]}}
            for field, kind, schema in (('measurement_rule_ref', 'MeasurementRule', QSMeasurementRuleView),
                    ('quantity_schedule_ref', 'QuantitySchedule', QSProcurementQuantityView),
                    ('prior_document_ref', 'ProcurementDocument', QSProcurementDocumentView)):
                pair = []
                for raw, bases in ((old_input, old), (action_input, current)):
                    selected_ref = None if raw[field] is None else ref_type(kind).model_validate(raw[field])
                    declared_ref = getattr(bases['procurement'], field)
                    if raw is action_input and selected_ref != declared_ref:
                        raise TaskConflict('QS procurement successor replaces a declared measurement, quantity or predecessor selection')
                    refs = {ref.key(): ref for ref in (selected_ref, declared_ref) if ref is not None}
                    pair.append([read(ref, schema) for ref in refs.values()])
                histories[field] = {'original': [row.model_dump(mode='json') for row in pair[0]],
                    'current': [row.model_dump(mode='json') for row in pair[1]]}
                before, after = getattr(original, field), getattr(procurement, field)
                if before is not None and (after is None or before.key()[:2] != after.key()[:2]):
                    raise TaskConflict('QS procurement recovery drops its original declared measurement/quantity/predecessor identity')
            for field, schema in (('pricing_rule_ref', QSPricingRuleView),
                    ('saved_document_ref', QSProcurementDocumentView), ('revision_impact_ref', QSProcurementRevisionView)):
                pair = []
                for bases in (old, current):
                    ref = getattr(bases['procurement'], field)
                    pair.append(None if ref is None else read(ref, schema))
                histories[field] = {'original': None if pair[0] is None else pair[0].model_dump(mode='json'),
                    'current': None if pair[1] is None else pair[1].model_dump(mode='json')}
            authorities = []
            for raw in (old_input, action_input):
                ref = raw['publication_authority_ref']
                authorities.append(None if ref is None else read(ref_type('Authority').model_validate(ref), QSProcurementPublicationAuthorityView))
            histories['publication_authority_ref'] = {'original': None if authorities[0] is None else authorities[0].model_dump(mode='json'),
                'current': None if authorities[1] is None else authorities[1].model_dump(mode='json')}
            # Read and retain old/new versions. Native validation must prove
            # any design/quantity revision and saved-document lineage using
            # the original revision and independent publication sources.
            for row in proof_rows:
                proof_refs.extend(row.evidence_refs)
                if isinstance(row, (QSProcurementDesignView, QSProcurementQuantityView, QSProcurementDocumentView)):
                    roles = {'Architect', 'Engineer'} if isinstance(row, QSProcurementDesignView) else {'QS'}
                    authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id,
                        row.available_at, roles, None if isinstance(row, QSProcurementDesignView) else source['organization_id'])
                if isinstance(row, QSProcurementQuantityView):
                    for line in row.lines:
                        proof_refs.extend(line.basis_refs)
                        if line.quantity.state == 'known':
                            proof_refs.append(line.quantity.value.basis_ref)
            observed = {}
            for ref in proof_refs:
                evidence = reading.resolve(ref)
                if not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
                    raise TaskConflict('QS procurement recovery requires actual observed native task/round/source evidence')
                observed[ref.key()] = evidence.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_sources={field: row.model_copy(deep=True) for field, row in old.items()},
                    current_sources={field: row.model_copy(deep=True) for field, row in current.items()},
                    procurement_history=deepcopy(histories), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS procurement recovery lacks native joint task/round readiness and complete revision/history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A05', _CODE, '1', frozenset({'dependency_change'}), evaluate)
