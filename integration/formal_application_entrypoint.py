"""Explicit saved-task submission, receipt, payment observation and feedback operations."""
import argparse
from copy import deepcopy
import importlib
import json
from pathlib import Path

from integration.module_host import module_factory_descriptor
from integration.owner_payment_settlement import OwnerPaymentSettlementReconciler
from integration.role_contract_host import RoleContractInvocation
from integration.run import load_agent_client_factory
from integration.scenario_v2 import read_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import ActionContext
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


_ROLES = {'supplier': 'Supplier', 'contractor': 'Contractor', 'owner': 'Owner',
    'bank': 'Bank', 'architect': 'Architect', 'engineer': 'Engineer',
    'qs': 'QS', 'government': 'Government'}
_OPERATIONS = frozenset({'submit', 'recover', 'read_receipt', 'query_payment_execution',
    'query_payment_settlement', 'record_feedback', 'read_feedback'})
_FEEDBACK_OPERATIONS = frozenset({'record_feedback', 'read_feedback'})
_PAYMENT_QUERIES = frozenset({'query_payment_execution', 'query_payment_settlement'})


def _save_payment_observation(directory, filename, value):
    path = directory / filename
    if value is not None:
        atomic_json(path, value)
    return {'status': 'unavailable' if value is None else 'observed',
        'path': None if value is None else path.as_posix(),
        'content_sha256': None if value is None else task_digest(value)}


def _feedback_selection(records, *, identity, context, observation=None):
    """Export only original records already checked by the actual read gate."""
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise TaskConflict('Actual feedback read must return original structured records')
    selected = []
    for row in records:
        original = TaskIdentity(**row['identity'])
        if (original.run_id != context.run_id or original.organization_id != identity.organization_id
                or original.role != identity.role
                or row['observation']['target_action_id'] != context.contract_ref.id
                or row.get('record_sha256') != task_digest({
                    key: value for key, value in row.items() if key != 'record_sha256'})):
            raise TaskConflict('Feedback selection changes its original recipient, target or saved digest')
        if observation is None or (original.as_dict() == identity.as_dict()
                and row['observation']['native_event_id'] == observation['native_event_id']):
            selected.append(deepcopy(row))
    hashes = [row['record_sha256'] for row in selected]
    if len(set(hashes)) != len(hashes) or observation is not None and len(selected) != 1:
        raise TaskConflict('Feedback selection lacks one unique original saved event or repeats a record')
    return {'run_id': context.run_id, 'organization_id': identity.organization_id,
        'target_action_id': context.contract_ref.id, 'feedback_sha256s': sorted(hashes)}, selected


def _feedback_operation(application, *, operation, identity, context, observation,
        reading_factory, reading_specification, reading_descriptor):
    """Build the application's actual reading and consume it under one guard.

    reading_factory(application, context) returns the independently supplied
    formal ActionReadView, using the application's actual source provider and
    concrete schemas. No projection or observed business event is invented here.
    """
    with application.base.read_guard(context.model_copy(deep=True)):
        application._check()
        original_task = application.base.store.get(identity)
        reading = reading_factory(application=application, context=context.model_copy(deep=True))
        application._check()
        registration = application.base.registry.get(context.contract_ref.id)
        if (not isinstance(reading, ActionReadView)
                or reading._organizations is not application.base.organizations
                or reading._resolver.run_id != identity.run_id or reading._resolver.source_mode != 'formal'
                or reading._role != registration.role or registration.role != identity.role
                or reading.organization_id != identity.organization_id
                or application.base.store.get(identity) != original_task
                or module_factory_descriptor(reading_factory, reading_specification) != reading_descriptor):
            raise TaskConflict('Feedback reading changed its original application, recipient, task or factory')
        reading.check_method_context(context, context.contract_ref.id)
        reading.recheck()
        # Call the original feedback component under this one source guard;
        # nesting the application's guard wrapper could deadlock actual hosts.
        feedback_export = {}
        if operation == 'record_feedback':
            returned = application.feedback.record(identity, context=context,
                reading=reading, observation=deepcopy(observation))
            # The inbox returns only an insertion acknowledgement. A saved SHA
            # must come from an actual authorized read, never from that boolean
            # or from reconstructing a presumed record. A read failure cannot
            # undo an already delivered event or trigger another write.
            try:
                records = application.feedback.read(context=context, reading=reading)
                selection, records = _feedback_selection(records, identity=identity,
                    context=context, observation=observation)
            except Exception as exc:
                feedback_export.update(saved_record_read_status='unavailable',
                    saved_record_read_error_type=type(exc).__name__, selection=None)
            else:
                feedback_export.update(saved_record_read_status='observed',
                    selection=selection, records=records)
        else:
            returned = application.feedback.read(context=context, reading=reading)
            selection, records = _feedback_selection(returned, identity=identity, context=context)
            feedback_export.update(saved_record_read_status='observed', selection=selection, records=records)
        reading.recheck()
        application._check()
        if application.base.store.get(identity) != original_task:
            raise TaskConflict('Feedback operation changed its original saved journal task')
        return returned, {'context': context.model_dump(mode='json'),
            'reading': reading.evidence(), 'reading_factory': reading_descriptor, **feedback_export}


def run_formal_application_operation(*, role, operation, request, settings, identity, output_directory,
        feedback_context=None, observation=None, reading_factory=None, reading_specification=None):
    """Operate on an original journal identity; never prepare/register/run an action.

    The dependency factory supplies the original persistent sources, configured
    model host and actual endpoint callbacks. Its resource ownership follows the
    existing role source factories. The caller explicitly selects one operation;
    unknown submissions use original host recovery rules, without CLI retries.
    """
    if role not in _ROLES or operation not in _OPERATIONS:
        raise TaskConflict('Formal operation requires an explicit supported role and operation')
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    if not isinstance(identity, TaskIdentity):
        raise TaskConflict('Formal operation requires its original saved task identity')
    identity = TaskIdentity(**identity.as_dict())
    if operation in _PAYMENT_QUERIES and (
            role != 'owner' or identity.role != 'Owner' or identity.action_id != 'OWN-A06'):
        raise TaskConflict('Native payment query requires the original Owner OWN-A06 task')
    if (identity.purpose != 'action' or request.context.execution_mode != 'llm'
            or identity.run_id != request.context.run_id
            or identity.action_id != request.context.contract_ref.id
            or identity.context_sha256 != task_digest(request.context.model_dump(mode='json'))
            or identity.input_sha256 != task_digest(request.action_input)):
        raise TaskConflict('Formal operation changes the original invocation or saved task identity')
    reading_descriptor = None
    if operation in _FEEDBACK_OPERATIONS:
        feedback_context = ActionContext.model_validate(feedback_context).model_copy(deep=True)
        if (feedback_context.run_id != identity.run_id or feedback_context.execution_mode == 'offline_fixture'
                or not callable(reading_factory) or not isinstance(reading_specification, str)
                or not reading_specification.strip()
                or operation == 'record_feedback' and observation is None
                or operation == 'read_feedback' and observation is not None):
            raise TaskConflict('Feedback operation requires actual current context, reading factory and explicit observation mode')
        reading_descriptor = module_factory_descriptor(reading_factory, reading_specification)
        if reading_descriptor['source_sha256'] is None:
            raise TaskConflict('Feedback reading factory requires locatable original implementation code')
    elif any(value is not None for value in (feedback_context, observation, reading_factory, reading_specification)):
        raise TaskConflict('Feedback arguments require an explicitly selected feedback operation')
    module = importlib.import_module('integration.' + role + '_formal_application')
    prefix = _ROLES[role] + 'FormalApplication'
    config = getattr(module, prefix + 'Settings').model_validate(settings).model_copy(deep=True)
    if (config.action_id != identity.action_id or config.submission is None
            or identity.action_id not in {route.action_id for route in config.submission.routes}):
        raise TaskConflict('Formal operation requires its explicitly configured original action route')
    if operation in _FEEDBACK_OPERATIONS and config.feedback is None:
        raise TaskConflict('Feedback operation requires the original configured feedback inbox and actual validators')
    if operation in _PAYMENT_QUERIES:
        route = next(route for route in config.submission.routes if route.action_id == identity.action_id)
        if (not route.native_payment_execution or not route.supported_choices
                or not set(route.supported_choices) <= {'pay', 'repay'}):
            raise TaskConflict('Native payment query requires its explicitly enabled pay/repay observation route')
        if operation == 'query_payment_settlement' and not route.native_payment_settlement:
            raise TaskConflict('Native settlement query requires its explicitly enabled independent settlement route')
    factory = module._load_factory(config.dependency_factory)
    descriptor = module_factory_descriptor(factory, config.dependency_factory)
    directory = Path(output_directory)
    # Claim a fresh evidence directory before constructing application resources.
    # A failed or interrupted operation keeps this intent; never resume it here.
    directory.mkdir(parents=True, exist_ok=False)
    intent = {'schema_version': 'formal-application-operation-intent.v1', 'status': 'started',
        'role': role, 'operation': operation, 'identity': identity.as_dict(),
        'request_sha256': task_digest(request.model_dump(mode='json')),
        'settings_sha256': task_digest(config.model_dump(mode='json')), 'factory': descriptor}
    if operation in _FEEDBACK_OPERATIONS:
        intent.update(feedback_context_sha256=task_digest(feedback_context.model_dump(mode='json')),
            observation_sha256=task_digest(observation) if observation is not None else None,
            reading_factory=reading_descriptor)
    intent['record_sha256'] = task_digest(intent)
    atomic_json(directory / 'intent.json', intent)
    application = dependencies = None
    owns_dependencies = False
    try:
        # PLAN requires original input snapshots in every operation artifact.
        # Save them before constructing resources, so failed/unknown work can
        # be diagnosed from this directory without reconstructing the inputs.
        snapshots = {'invocation.json': request.model_dump(mode='json'),
            'settings.json': config.model_dump(mode='json'), 'identity.json': identity.as_dict()}
        if operation in _FEEDBACK_OPERATIONS:
            snapshots['feedback-context.json'] = feedback_context.model_dump(mode='json')
            if observation is not None:
                snapshots['observation.json'] = deepcopy(observation)
        for name, payload in snapshots.items():
            atomic_json(directory / name, payload)
        input_snapshots = {name: {'path': (directory / name).as_posix(),
            'content_sha256': task_digest(payload)} for name, payload in snapshots.items()}
        dependencies = factory(request=request.model_copy(deep=True), output_directory=directory,
            offline=False, settings=deepcopy(config.dependency_settings))
        if not isinstance(dependencies, getattr(module, prefix + 'Dependencies')):
            raise TaskConflict('Actual dependency factory returned a different formal application type')
        owns_dependencies = True
        if module_factory_descriptor(factory, config.dependency_factory) != descriptor:
            raise TaskConflict('Actual formal dependency factory changed during assembly')
        application = getattr(module, prefix)(request=request, settings=config,
            dependencies=dependencies, factory_descriptor=descriptor)
        application._check()
        if (application.base.store.run_id != identity.run_id
                or identity.organization_id not in application.base.store.organization_ids):
            raise TaskConflict('Formal operation changed the original journal or task recipient')
        before = application.base.store.get(identity)
        if before is None:
            raise TaskConflict('Formal operation requires an existing original journal task')
        sources_before = application.evidence()
        feedback_evidence = None
        if operation in _FEEDBACK_OPERATIONS:
            if application.feedback is None:
                raise TaskConflict('Original formal application has no actual feedback component')
            returned, feedback_evidence = _feedback_operation(application, operation=operation,
                identity=identity, context=feedback_context, observation=observation,
                reading_factory=reading_factory, reading_specification=reading_specification,
                reading_descriptor=reading_descriptor)
        else:
            returned = getattr(application, operation)(identity)
        application._check()
        after = application.base.store.get(identity)
        if after is None:
            raise TaskConflict('Formal operation lost its original journal task')
        if operation in _PAYMENT_QUERIES and after != before:
            raise TaskConflict('Read-only native payment observation changed its original journal task')
        evidence = {'schema_version': 'formal-application-operation-result.v1', 'status': 'operation_returned',
            'intent_sha256': intent['record_sha256'], 'role': role, 'operation': operation,
            'input_snapshots': input_snapshots,
            'identity': identity.as_dict(), 'task_before': before, 'task_after': after,
            'returned': returned, 'application_before': sources_before,
            'application_after': application.evidence(), 'model_execution': 'not_requested',
            'limitations': 'Explicit original-host operation only. No decision execution, new task registration or CLI retry. Configured capabilities and accepted receipts do not establish native business effects.'}
        if feedback_evidence is not None:
            evidence['feedback_evidence'] = feedback_evidence
        if operation in _PAYMENT_QUERIES:
            issued = returned
            if operation == 'query_payment_settlement':
                issued = returned.get('issued_reception') if isinstance(returned, dict) else None
                if returned is not None and (
                        not isinstance(returned, dict) or not isinstance(issued, dict)
                        or returned.get('schema_version') != OwnerPaymentSettlementReconciler.VERSION
                        or returned.get('source_identity') != identity.as_dict()
                        or returned.get('source_result_sha256') != before['output_sha256']
                        or issued.get('schema_version') != 'owner-payment-issued-reception.v1'
                        or any(issued.get(key) != returned.get(key) for key in (
                            'source_identity', 'source_record_sha256', 'source_result_sha256', 'source_reading_sha256'))
                        or returned.get('issued_reception_sha256') != task_digest(issued)):
                    raise TaskConflict('Native settlement export replaces its original task or linked payment observation')
            evidence['payment_execution_observation'] = _save_payment_observation(
                directory, 'issued-reception.json', issued)
            if operation == 'query_payment_settlement':
                evidence['payment_settlement_observation'] = _save_payment_observation(
                    directory, 'native-settlement.json', returned)
        evidence['record_sha256'] = task_digest(evidence)
        atomic_json(directory / 'result.json', evidence)
        atomic_json(directory / 'attempt.json', {'status': 'result_saved',
            'intent_sha256': intent['record_sha256'], 'result_sha256': evidence['record_sha256']})
        return evidence
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {'status': 'failed',
            'intent_sha256': intent['record_sha256'], 'error_type': type(exc).__name__,
            'replay': 'requires_original_journal_diagnosis'})
        raise
    finally:
        if application is not None:
            application.close()
        elif owns_dependencies:
            dependencies.sources.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=sorted(_ROLES), required=True)
    parser.add_argument('--operation', choices=sorted(_OPERATIONS), required=True)
    parser.add_argument('--invocation', type=Path, required=True, help='Original role-contract invocation JSON')
    parser.add_argument('--settings', type=Path, required=True, help='Original formal application settings and persistent journal configuration')
    parser.add_argument('--identity', type=Path, required=True, help='Exact original TaskIdentity JSON, including all seven versions')
    parser.add_argument('--output', type=Path, required=True, help='New operation evidence directory')
    parser.add_argument('--feedback-context', type=Path, help='Current authorized target ActionContext JSON')
    parser.add_argument('--feedback-reading-factory', help='Actual formal reading factory as module:callable')
    parser.add_argument('--observation', type=Path, help='Actual role feedback observation JSON; only with record_feedback')
    args = parser.parse_args(argv)
    if args.operation in _PAYMENT_QUERIES and args.role != 'owner':
        parser.error('Payment queries require --role owner and original OWN-A06 inputs')
    if args.operation in _FEEDBACK_OPERATIONS:
        if not args.feedback_context or not args.feedback_reading_factory:
            parser.error('Feedback operations require --feedback-context and --feedback-reading-factory')
        if (args.operation == 'record_feedback') != (args.observation is not None):
            parser.error('--observation is required only for record_feedback')
    elif any((args.feedback_context, args.feedback_reading_factory, args.observation)):
        parser.error('Feedback arguments require record_feedback or read_feedback')
    _, request = read_input_json(args.invocation)
    _, settings = read_input_json(args.settings)
    _, identity = read_input_json(args.identity)
    feedback_args = {}
    if args.operation in _FEEDBACK_OPERATIONS:
        _, context = read_input_json(args.feedback_context)
        feedback_args.update(feedback_context=context,
            reading_factory=load_agent_client_factory(args.feedback_reading_factory),
            reading_specification=args.feedback_reading_factory)
        if args.observation is not None:
            _, observation = read_input_json(args.observation)
            feedback_args['observation'] = observation
    result = run_formal_application_operation(role=args.role, operation=args.operation,
        request=request, settings=settings, identity=TaskIdentity(**identity), output_directory=args.output,
        **feedback_args)
    summary = {'status': result['status'], 'operation': args.operation,
        'action_id': result['identity']['action_id'], 'task_state': result['task_after']['state'],
        'result_path': (args.output / 'result.json').as_posix()}
    if 'feedback_evidence' in result:
        summary.update(saved_record_read_status=result['feedback_evidence']['saved_record_read_status'],
            feedback_selection=result['feedback_evidence']['selection'])
    if 'payment_execution_observation' in result:
        summary['payment_execution_observation'] = result['payment_execution_observation']
    if 'payment_settlement_observation' in result:
        summary['payment_settlement_observation'] = result['payment_settlement_observation']
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
