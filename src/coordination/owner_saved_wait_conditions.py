"""Common immutable invocation checks for actual persisted Owner planning waits."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.references import ActionReadView
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class OwnerSavedWaitConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None
    original_record: dict | None = None


def read_owner_saved_wait(check, selected, validate_relation, *, action_id, code, kinds, reading_type,
        trigger='dependency_change'):
    source = check.source['identity']
    if (source['action_id'] != action_id or source['role'] != 'Owner' or source['purpose'] != 'action'
            or check.condition.condition_code != code or check.condition.trigger != trigger
            or check.signal.trigger != trigger
            or tuple(ref.kind for ref in check.condition.object_refs) != kinds
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, reading_type) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Owner recovery requires its actual original typed private planning wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != action_id or context.execution_mode != 'llm'
            or not same_closeout_scope(context.scope, original.scope)
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Owner recovery changes original input, scope, time or current authority')
    reading.check_method_context(context, action_id)
    contract, saved = selected.contract, deepcopy(selected.original_record)
    if (not isinstance(contract, ActionContract) or contract.action_id != action_id or contract.role != 'Owner'
            or not isinstance(saved, dict) or saved.get('identity') != source
            or saved.get('result', {}).get('kind') != 'deferred'
            or saved['result'].get('resume_condition') != check.condition.model_dump(mode='json')
            or saved.get('result_sha256') != task_digest(saved['result'])
            or saved.get('record_sha256') != task_digest({key: value for key, value in saved.items() if key != 'record_sha256'})
            or not isinstance(saved.get('source_reading'), list)
            or saved.get('source_reading_sha256') != task_digest(saved['source_reading'])
            or saved.get('audit', {}).get('method_registry_digest') != source['versions']['method']):
        raise TaskConflict('Owner recovery lacks its actual saved wait, immutable sources and original method audit')
    for row in saved['source_reading']:
        ref = Reference.model_validate(row['ref'])
        if reading.resolve(ref).model_dump(mode='json') != row['projection']:
            raise TaskConflict('Owner recovery rewrites a saved immutable historical projection')
    return contract.validate_input(raw), contract.validate_input(current_raw), saved
