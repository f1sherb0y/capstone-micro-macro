"""Continue a proven unstarted micro action within its still-open native call."""
from src.coordination.tasks import TaskConflict, task_digest


def execute_original_stage(*, worker, identity, prepared, enabled, record, stage, save_record):
    """Keep the original invocation; never retry preparation or an unknown result.

    Hosts retain their engine guard and pin this function's implementation.
    The original worker rechecks sources/authority and atomically claims the
    registered snapshot before any preparation. This is a single continuation,
    not a retry loop, result recovery, or a new native business request.
    """
    if type(enabled) is not bool:
        raise ValueError('Unstarted action continuation requires an explicit boolean')
    try:
        return worker.execute(identity, prepared)
    except Exception as original_error:
        if not enabled:
            raise
        try:
            proof=worker.unstarted_evidence(identity)
        except TaskConflict:
            raise original_error
        attempt={'stage':stage,'identity':identity.as_dict(),
            'initial_error_type':type(original_error).__name__,
            'unstarted_claim_sha256':proof['claim_sha256'],'status':'continuing'}
        record.setdefault('unstarted_continuations',[]).append(attempt)
        save_record(record)
        outcome=worker.execute(identity,prepared)
        attempt.update(status='result_saved',result_sha256=task_digest(outcome['result']))
        save_record(record)
        return outcome
