"""Read original GOV-A08 permit sources for guarded same-task recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoverySettings, GovernmentInspectionRecoveryBindings,
    _build_assembled_government_dispatcher,
)
from integration.government_permit_actions import GovernmentPermitActionAssembler, validate_government_permit_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.government_objects import GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_permit_objects import (
    GovPermitView, GovPermitDecisionView, GovPermitEffectView, GovPermitActionView,
    GovPermitRuleView, GovPermitAuthorityView, GovPermitConditionView, GovPermitFactView,
    GovPermitDependencyView, GovPermitDependencyVerificationView, GovPermitResultView, GovPermitQuestionView,
)
from src.actions.contracts.government_decision_objects import GovDecisionNotificationView
from src.coordination.government_permit_conditions import GovernmentPermitConditionReading, _CODE, _CODES, _BASES
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class GovernmentPermitCurrentSelection:
    request: RoleContractInvocation


class GovernmentPermitRecoverySettings(GovernmentInspectionRecoverySettings):
    """Original permit verification source and policy versions."""


@dataclass(frozen=True)
class GovernmentPermitRecoveryBindings(GovernmentInspectionRecoveryBindings):
    """Actual source guard, selector and independent native recovery validators."""


_HISTORY_SCHEMAS = {
    'Authorization': Authorization, 'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord,
    'Permit': GovPermitView, 'Decision': GovPermitDecisionView, 'EffectRule': GovPermitEffectView,
    'DecisionNotification': GovDecisionNotificationView, 'ActionDefinition': GovPermitActionView,
    'Rule': GovPermitRuleView, 'Authority': GovPermitAuthorityView,
    'PermitCondition': GovPermitConditionView, 'ConditionFact': GovPermitFactView,
    'PermitDependency': GovPermitDependencyView, 'DependencyVerification': GovPermitDependencyVerificationView,
    'MethodResult': GovPermitResultView, 'EvidenceTarget': GovPermitQuestionView,
    'RegulatoryRecipient': GovRecipientView, 'ResponseRequirement': GovResponseRequirementView,
}


class GovernmentPermitReader(GovernmentInspectionReader):
    """Read original/current permit histories without verifying fulfillment or issuing a permit."""
    ACTION_ID = 'GOV-A08'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentPermitActionAssembler
    READER_SCHEMA = 'government-permit-reader.v1'

    def __call__(self, check):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != ('Permit',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government review reader replaces original permit-effect wait or agency')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if tuple(waited) != (original_input.permit_ref,):
            raise TaskConflict('Government review reader changes exact original waited input references')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentPermitCurrentSelection):
            raise TaskConflict('Government review reader requires typed independently authorized current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field, _, _ in _BASES)
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government review reader replaces original scope/permit/action or authorized source visibility')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading, baseline = prepared.reading, deepcopy(prepared.reading.evidence())
        sources, typed_sources, missing = {}, {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government review assembly changes original source snapshot or agency')

            def read(ref, schema):
                row = reading.resolve(ref)
                actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', None))
                if not isinstance(row, schema) or actual_ref != ref:
                    raise TaskConflict('Government review history lacks exact typed original/current source')
                typed_sources[ref.key()] = row
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            pending = []
            for action_input in (original_input, prepared.action_input):
                for field, _, schema in _BASES:
                    row = read(getattr(action_input, field), schema)
                    pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                for ref in walk_references(action_input):
                    if ref.kind in _HISTORY_SCHEMAS:
                        row = read(ref, _HISTORY_SCHEMAS[ref.kind])
                        pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                rule = typed_sources[action_input.verification_rule_ref.key()]
                if rule.verification is None:
                    raise TaskConflict('Government permit recovery loses original verification rule purpose')
                invocation = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                grant = read(rule.verification.authority_ref, Authorization)
                read(invocation.function_ref, RoleAssignment)
                if grant.organization_id != source['organization_id'] or grant.function_ref != invocation.function_ref:
                    raise TaskConflict('Government permit history borrows another agency/function verifier authority')
            visited = set()
            while pending:
                ref = pending.pop()
                if ref.key() in visited:
                    continue
                visited.add(ref.key())
                if ref.key() not in reading._resolver._objects:
                    # Waits precede later substantive review sources. Preserve
                    # every omission for native validation, without inventing it.
                    missing[ref.key()] = ref.model_dump(mode='json')
                    continue
                row = read(ref, _HISTORY_SCHEMAS[ref.kind])
                if hasattr(row, 'author_authority_ref'):
                    grant = read(row.author_authority_ref, Authorization)
                    read(row.author_function_ref, RoleAssignment)
                    if (grant.actor_id != row.author_actor_id or grant.organization_id != row.author_organization_id
                            or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids):
                        raise TaskConflict('Government review history substitutes actual source author/action authority')
                related = ([row.function_ref, *row.basis_refs] if isinstance(row, Authorization)
                    else row.basis_refs if isinstance(row, RoleAssignment) else walk_references(row))
                pending.extend(ref for ref in related if ref.kind in _HISTORY_SCHEMAS)
            for action_input in (original_input, prepared.action_input):
                selected_context = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                validate_government_permit_sources(action_input, context=selected_context,
                    organization_id=source['organization_id'], sources=typed_sources)
            return GovernmentPermitConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'),
                action_input=prepared.action_input.model_dump(mode='json'),
                permit_sources=deepcopy(list(sources.values())), unavailable_targets=deepcopy(list(missing.values())),
                original_context=ActionContext.model_validate(snapshot['context']).model_copy(deep=True))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government review reader changes original snapshot or current assembled source/input/context')


def build_assembled_government_permit_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.task_continuation import build_government_permit_continuation_dispatcher
    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentPermitReader, dispatcher_factory=build_government_permit_continuation_dispatcher)
