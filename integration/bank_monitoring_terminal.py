"""Archive persisted actual original monitoring observations under the Bank guard."""
from integration.architect_learning_terminal import _reconcile_learning_wait
from src.actions.contracts.common import ResumeCondition
from src.coordination.bank_monitoring_terminal import EXISTING_CODE, check_existing_monitoring_measure
from src.coordination.bank_monitoring_conditions import NOTICE_CODE
from src.coordination.tasks import TaskConflict, TaskIdentity


def reconcile_existing_monitoring_measure(*, identity, signal, bridge, validate_relation):
    return _reconcile_bank_terminal_wait(identity=identity, signal=signal, bridge=bridge,
        validate_relation=validate_relation, checker=check_existing_monitoring_measure,
        proof=lambda resolution: (resolution['notices'], resolution['existing_measure_refs']),
        action_id='BANK-A08', accepts_condition=lambda code: code in {NOTICE_CODE, EXISTING_CODE})


def _reconcile_bank_terminal_wait(*, identity, signal, bridge, validate_relation,
        checker, proof, action_id, accepts_condition):
    bridge._check()
    if validate_relation is not bridge.native_validator:
        raise TaskConflict('Existing monitoring measure archive replaced original native validator')
    reader = bridge.terminal_reader
    source = reader.snapshots.store.get(identity)
    if len(source['conditions']) != 1:
        raise TaskConflict('Existing monitoring measure archive requires one original explicit notice wait')
    code = ResumeCondition.model_validate(source['conditions'][0]).condition_code
    if not accepts_condition(code):
        raise TaskConflict('Existing monitoring measure archive is outside original notice wait routes')

    def authenticate(**kwargs):
        bridge._check()
        original = TaskIdentity(**kwargs['source_identity'])
        snapshot = reader.snapshots.get(original)
        if (snapshot['context'] != kwargs['original_context'].model_dump(mode='json')
                or snapshot['action_input'] != kwargs['original_action_input']):
            raise TaskConflict('Existing measure authentication replaces original persisted snapshot')
        try:
            return validate_relation(**kwargs)
        finally:
            bridge._check()
            if reader.snapshots.get(original) != snapshot:
                raise TaskConflict('Existing measure authentication rewrote original persisted invocation')

    result = _reconcile_learning_wait(identity=identity, signal=signal, reader=reader,
        dispatcher=bridge.dispatcher, validate_relation=authenticate, condition_code=code,
        checker=checker, reader_options={'execution_terminal': True}, proof=proof,
        action_id=action_id, role='Bank')
    bridge._check()
    return result
