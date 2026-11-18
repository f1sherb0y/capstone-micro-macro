"""Shared original-task preflight and guarded formal-application V7 reopening."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from integration.lifecycle_v7_wait_recovery import WaitRecoverySources
from integration.module_host import module_factory_descriptor
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def build_formal_wait_recovery_sources(*, identity, journal_path, config, role, action_ids,
        application_type, dependencies_type, load_factory, metadata_namespace):
    """Reopen existing sources; no original task, action or model call is created.

    The configured dependency factory supplies actual current providers and an
    existing model host. It owns partial resources until it returns dependencies.
    V7 still independently checks the selected wait, successor and current facts.
    """
    selected = TaskIdentity(**identity.as_dict())
    application_settings, request = config.application, config.request
    path = Path(journal_path).resolve()
    if (selected.role != role or selected.purpose != 'action'
            or selected.action_id not in action_ids
            or application_settings.action_id != selected.action_id
            or request.context.contract_ref.id != selected.action_id or request.context.run_id != selected.run_id
            or request.context.execution_mode != 'llm' or application_settings.execution_recovery is None
            or request.context.operation_id != selected.request_id
            or task_digest(request.context.model_dump(mode='json')) != selected.context_sha256
            or task_digest(request.action_input) != selected.input_sha256
            or application_settings.feedback is None or application_settings.submission is None
            or application_settings.client_version != selected.versions['client']
            or application_settings.model_version != selected.versions['model'] or not path.is_file()):
        raise TaskConflict('Formal V7 sources require the original action, versions and existing journal')
    factory = load_factory(application_settings.dependency_factory)
    descriptor = module_factory_descriptor(factory, application_settings.dependency_factory)
    key = metadata_namespace + task_digest([
        application_settings.dependency_factory, selected.action_id])
    # Read-only preflight prevents an undeclared/new application from reaching
    # its dependency factory or inserting configuration into the original DB.
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('BEGIN')
        task = connection.execute('SELECT record FROM tasks WHERE key=?', (selected.key,)).fetchone()
        declared = connection.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if task is None or declared is None:
            raise TaskConflict('Formal V7 requires existing original task and application evidence')
        original, evidence = json.loads(task[0]), json.loads(declared[0])
        if (original['identity'] != selected.as_dict() or task_digest(original) != config.source_task_sha256
                or original['state'] != 'waiting_input'
                or any(original[name] is not None for name in ('output', 'submission', 'receipt'))
                or task_digest(evidence) != config.application_configuration_sha256
                or evidence['settings_sha256'] != task_digest(application_settings.model_dump(mode='json'))
                or evidence['dependency_factory'] != descriptor):
            raise TaskConflict('Formal V7 original task or declared application changed before reopening')
    finally:
        connection.close()
    dependencies = factory(request=request.model_copy(deep=True), output_directory=Path(config.output_directory),
        offline=False, settings=deepcopy(application_settings.dependency_settings))
    if not isinstance(dependencies, dependencies_type):
        raise ValueError('Formal V7 dependency factory must return original formal application dependencies')
    application = None
    try:
        base, recovery = dependencies.sources, dependencies.execution_recovery
        if (base.store.path is None or Path(base.store.path).resolve() != path
                or base.store.run_id != selected.run_id or selected.organization_id not in base.store.organization_ids
                or recovery is None or module_factory_descriptor(factory,
                    application_settings.dependency_factory) != descriptor):
            raise TaskConflict('Formal V7 dependencies substituted original journal or recovery declarations')
        with recovery.read_guard(run_id=selected.run_id, organization_id=selected.organization_id):
            if task_digest(base.store.get(selected)) != config.source_task_sha256:
                raise TaskConflict('Formal V7 original task changed during source reopening')
            application = application_type(request=request, settings=application_settings,
                dependencies=dependencies, factory_descriptor=descriptor)
            if task_digest(application._declared) != config.application_configuration_sha256:
                raise TaskConflict('Formal V7 reopened application changed original declaration')
            sources = application.wait_recovery_sources(identity=selected, journal_path=path)
            if task_digest(base.store.get(selected)) != config.source_task_sha256:
                raise TaskConflict('Formal V7 source assembly changed original selected task')

        def check():
            if module_factory_descriptor(factory, application_settings.dependency_factory) != descriptor:
                raise TaskConflict('Formal V7 actual dependency factory changed')
            application._check()

        @contextmanager
        def guard(current_identity, signal):
            check()
            with sources.read_guard(current_identity, signal):
                check()
                try:
                    yield
                finally:
                    check()

        def prepare(source, signal):
            check()
            result = sources.prepare(deepcopy(source), signal.model_copy(deep=True))
            check()
            return result

        def revalidate(source, preparation, signal):
            check()
            result = sources.revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
            check()
            return result

        check()
        return WaitRecoverySources(journal=sources.journal, prepare=prepare, revalidate=revalidate,
            read_guard=guard, close=application.close)
    except Exception:
        if application is not None:
            application.close()
        else:
            dependencies.sources.close()
        raise
