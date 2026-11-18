"""Produce exact run-local successor snapshots without executing A12 actions."""
from integration.commercial_actions import PreparedCommercialAction
from integration.action_versions import prepared_action_execution_versions
from src.coordination.continuations import ContinuationPreparation, ResumeSignal
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest, _text


def commercial_execution_versions(prepared, *, client_version, model_version):
    """Bind task execution versions to the actual assembled runner and Skill."""
    if not isinstance(prepared,PreparedCommercialAction):
        raise TaskConflict('Execution versions require the actual prepared commercial invocation')
    return prepared_action_execution_versions(prepared,
        client_version=client_version,model_version=model_version)


def prepare_commercial_successor(source, signal, prepared, *, request_id,
        client_version, model_version):
    """Host supplies a freshly assembled invocation and actual client/model IDs.

    The journal remains responsible for the atomic successor insertion. Facts
    are the exact authorized read evidence, never event payload claims. Neither
    request creation nor a successful preparation submits a business action.
    """
    if not isinstance(prepared,PreparedCommercialAction) or not isinstance(signal,ResumeSignal):
        raise TaskConflict('Successor preparation requires a typed assembled invocation and signal')
    previous = TaskIdentity(**source['identity'])
    context = prepared.context
    action_id = context.contract_ref.id
    registration = prepared.runner.registry.get(action_id)
    if (action_id not in {'CONTRACTOR-A12','SUPPLIER-A12'} or context.contract_ref.kind != 'ActionContract'
            or previous.action_id != action_id or previous.role != registration.role
            or previous.run_id != context.run_id or previous.organization_id != prepared.reading.organization_id
            or signal.run_id != previous.run_id or signal.organization_id != previous.organization_id
            or context.business_time != signal.business_time):
        raise TaskConflict('Successor changes original run, firm, role, action or current signal time')
    if request_id == previous.request_id:
        raise TaskConflict('A continuation needs a new request ID, never a replay of the old request')
    if source.get('state') != 'waiting_input':
        raise TaskConflict('Only an original waiting task may have a continuation prepared')
    if registration.skill is None or not registration.implemented:
        raise TaskConflict('Successor requires the current bound Skill and processor')
    next_input = prepared.action_input.model_dump(mode='json')
    next_context = context.model_dump(mode='json')
    if (task_digest(next_input) != prepared.input_sha256 or task_digest(next_context) != prepared.context_sha256):
        raise TaskConflict('Prepared input or context changed after authorized assembly')
    registration.contract.validate_input(next_input)
    prepared.reading.check_method_context(context,action_id)
    prepared.reading.recheck()
    organizations = prepared.runner.organizations
    if organizations is None or organizations.run_id != previous.run_id:
        raise TaskConflict('Successor requires its actual run-local organization registry')
    grants = organizations.grants(context,action_id,registration.role)
    if any(grant.organization_id != previous.organization_id for grant in grants):
        raise TaskConflict('Successor authorization belongs to another organization')
    versions = commercial_execution_versions(prepared,client_version=client_version,model_version=model_version)
    successor = TaskIdentity(**(previous.as_dict() | {'request_id':request_id,
        'input_sha256':prepared.input_sha256,'context_sha256':prepared.context_sha256,'versions':versions}))
    if all(getattr(successor,name) == getattr(previous,name)
           for name in ('input_sha256','context_sha256','versions')):
        raise TaskConflict('A new request ID alone does not make a fresh continuation')
    facts_sha256 = task_digest(prepared.reading.evidence())
    authorization_sha256 = task_digest([grant.model_dump(mode='json') for grant in grants])
    prepared.reading.recheck()
    if organizations.grants(context,action_id,registration.role) != grants:
        raise TaskConflict('Successor authority changed while its snapshots were produced')
    return ContinuationPreparation(successor,facts_sha256,authorization_sha256,next_input,next_context)


def revalidate_commercial_successor(source, preparation, signal, freshly_prepared, *,
        client_version, model_version):
    """Reassemble through the actual host before calling this comparison.

    Reusing the original prepared object does not prove that host facts remain
    current. The caller must obtain freshly_prepared from a fresh host read.
    """
    if not isinstance(preparation,ContinuationPreparation):
        raise TaskConflict('Revalidation requires the exact proposed successor preparation')
    expected = prepare_commercial_successor(source,signal,freshly_prepared,
        request_id=preparation.successor.request_id,client_version=client_version,model_version=model_version)
    return expected == preparation
