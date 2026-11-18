"""Summarize explicit saved paired observations without constructing clients."""
from hashlib import sha256
from pathlib import Path

from integration.action_catalog import write_new
from integration.paired_experiment_callbacks import check_saved_paired_callbacks
from integration.paired_experiment_hosts import PairedModelHosts
from integration.paired_experiment_isolation import PairedStateSnapshot
from integration.paired_experiment_results import summarize_paired_results
from integration.paired_experiment_sources import _run_neutral
from integration.paired_experiments import PairedExperimentConfiguration, prepare_paired_experiment
from integration.scenario_v2 import parse_input_json
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def _checked_record(record, schema):
    schemas = (schema,) if isinstance(schema, str) else schema
    if (not isinstance(record, dict) or record.get('schema_version') not in schemas
            or record.get('record_sha256') != task_digest({
                key: value for key, value in record.items() if key != 'record_sha256'})):
        raise TaskConflict('Saved paired artifact changes its original schema or record digest')


def _read_artifact(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root):
        raise TaskConflict('Saved paired artifact escapes its original experiment namespace')
    raw = path.read_bytes()
    _, record = parse_input_json(raw)
    return path, record, {'path': path.as_posix(), 'file_sha256': sha256(raw).hexdigest()}


def _load_assembly(config, root, plan, assembly_archive):
    archive_path, archive, archive_source = _read_artifact(assembly_archive, root)
    _checked_record(archive, 'paired-assembly-archive.v1')
    if (archive_path != root / 'assemblies' / (archive['record_sha256'] + '.json')
            or task_digest(archive.get('configuration')) != task_digest(config.model_dump(mode='json'))):
        raise TaskConflict('Saved paired assembly changes its original configuration or locator')
    evidence, source, isolation = (archive[name] for name in ('evidence', 'source_check', 'isolation_check'))
    for record, schema in ((evidence, ('paired-model-hosts.v1', 'paired-model-hosts.v2')),
            (source, 'paired-experiment-source-check.v1'),
            (isolation, ('paired-experiment-isolation-check.v1', 'paired-experiment-isolation-check.v2'))):
        _checked_record(record, schema)
    if ((evidence['schema_version'] == 'paired-model-hosts.v2')
                != (isolation['schema_version'] == 'paired-experiment-isolation-check.v2')
            or evidence.get('configuration_sha256') != task_digest(config.model_dump(mode='json'))
            or evidence.get('source_check_sha256') != source['record_sha256']
            or evidence.get('isolation_check_sha256') != isolation['record_sha256']
            or isolation.get('source_check_sha256') != source['record_sha256']
            or any(record.get('plan_sha256') != plan['plan_sha256'] for record in (source, isolation))
            or set(evidence.get('hosts', {})) != {arm.strategy for arm in config.arms}):
        raise TaskConflict('Saved paired assembly lost its original plan or preflight associations')
    if 'application_callbacks' in archive or 'application_callbacks_sha256' in evidence:
        callbacks = archive.get('application_callbacks')
        check_saved_paired_callbacks(callbacks,
            required=('assembly_guard', 'validate_sources', 'validate_isolation', 'validate_components',
                'prepare_action', 'read_guard', 'validate_execute', 'validate_record', 'close'))
        if (callbacks['record_sha256'] != evidence.get('application_callbacks_sha256')
                or task_digest(callbacks) != task_digest(evidence.get('application_callbacks'))):
            raise TaskConflict('Saved paired assembly lost its original application callback association')
    if isolation['schema_version'] == 'paired-experiment-isolation-check.v2':
        strategies = {arm.strategy for arm in config.arms}
        snapshots, descriptors = isolation.get('snapshots'), isolation.get('descriptors')
        if (not isinstance(snapshots, dict) or set(snapshots) != strategies
                or not isinstance(descriptors, dict) or set(descriptors) != strategies
                or not isinstance(isolation.get('actual_gate'), dict)
                or not isinstance(isolation['actual_gate'].get('implementation'), dict)):
            raise TaskConflict('Saved paired state v2 lost its original snapshot or implementation declarations')
        kinds = {'session', 'cache', 'cognition'}
        for arm in config.arms:
            if (not isinstance(snapshots[arm.strategy], dict) or set(snapshots[arm.strategy]) != kinds
                    or not isinstance(descriptors[arm.strategy], dict) or set(descriptors[arm.strategy]) != kinds):
                raise TaskConflict('Saved paired state v2 omits an original state category')
            for kind in kinds:
                snapshot = PairedStateSnapshot.model_validate(snapshots[arm.strategy][kind])
                descriptor = descriptors[arm.strategy][kind]
                if (snapshot.run_id != arm.run_id or not isinstance(descriptor, dict)
                        or descriptor.get('schema_version') != 'paired-state-binding.v2'
                        or not isinstance(descriptor.get('implementation'), dict)):
                    raise TaskConflict('Saved paired state v2 changes its original run or adapter declaration')
    for arm in config.arms:
        metadata = evidence['hosts'][arm.strategy]
        if (metadata.get('run_id') != arm.run_id or metadata.get('model_version') != config.model_version
                or task_digest(metadata.get('configuration')) != task_digest(arm.model_host.model_dump(mode='json'))
                or metadata.get('configuration_sha256') != task_digest({
                    key: value for key, value in metadata.items() if key != 'configuration_sha256'})):
            raise TaskConflict('Saved paired model host changes its original run or configuration')
    # Empty hosts and absent state_binding keep either archive version read-only.
    return PairedModelHosts(config, {}, source, isolation, evidence), archive_source


def _collect_groups(configuration, *, output_root, assembly_archives, observations):
    config = PairedExperimentConfiguration.model_validate(configuration)
    config = PairedExperimentConfiguration.model_validate(config.model_dump(mode='python'))
    plan = prepare_paired_experiment(config, output_root=output_root)
    root = Path(output_root).resolve() / config.experiment_id
    if root.resolve() != root:
        raise TaskConflict('Saved paired experiment namespace changed through a symlink')
    archive_paths = [Path(path).resolve() for path in assembly_archives]
    paths = [Path(path).resolve() for path in observations]
    if (not archive_paths or len(set(archive_paths)) != len(archive_paths)
            or not paths or len(set(paths)) != len(paths)):
        raise TaskConflict('Paired summary requires explicit distinct archive and observation artifacts')
    groups = {}
    for path in sorted(archive_paths):
        assembly, archive_source = _load_assembly(config, root, plan, path)
        digest = assembly.evidence['record_sha256']
        if digest in groups:
            raise TaskConflict('Multiple saved archives refer to the same original paired assembly')
        groups[digest] = dict(assembly=assembly, archive_source=archive_source,
            records=[], artifact_sources=[])
    for path in sorted(paths):
        path, record, artifact_source = _read_artifact(path, root)
        _checked_record(record, ('paired-action-observation.v1', 'paired-action-observation.v2'))
        group = groups.get(record.get('assembly_sha256'))
        if group is None:
            raise TaskConflict('Saved observation lacks its explicitly selected original assembly archive')
        evidence = group['assembly'].evidence
        identity = TaskIdentity(**record['identity'])
        arm = next((arm for arm in config.arms if arm.strategy == record.get('strategy')), None)
        basis = next((basis for basis in config.action_basis if basis.action_id == identity.action_id), None)
        if (arm is None or basis is None or identity.run_id != arm.run_id or identity.purpose != 'action'
                or record.get('assembly_sha256') != evidence['record_sha256']
                or path != root / arm.strategy / 'observations' / identity.key / (record['record_sha256'] + '.json')):
            raise TaskConflict('Saved observation changes its original assembly, arm, task or locator')
        snapshot = record['snapshot']
        if (snapshot.get('schema_version') != InvocationSnapshotStore.SCHEMA
                or task_digest(snapshot.get('identity')) != task_digest(identity.as_dict())
                or snapshot.get('snapshot_sha256') != task_digest({
                    key: value for key, value in snapshot.items() if key != 'snapshot_sha256'})
                or task_digest(snapshot['context']) != identity.context_sha256
                or snapshot['context']['run_id'] != identity.run_id
                or task_digest(snapshot['action_input']) != identity.input_sha256
                or task_digest(_run_neutral(snapshot['action_input'], identity.run_id)) != basis.input_sha256):
            raise TaskConflict('Saved paired observation changes its original context or frozen input')
        audit, result = record.get('audit'), record.get('result')
        if record.get('original_result_record_sha256') is not None:
            if (not isinstance(audit, dict) or not isinstance(result, dict)
                    or audit.get('run_id') != identity.run_id or audit.get('action_id') != identity.action_id
                    or audit.get('operation_id') != snapshot['context']['operation_id']
                    or audit.get('input_sha256') != identity.input_sha256
                    or audit.get('result_sha256') != task_digest(result)
                    or audit.get('model_version') != config.model_version
                    or audit.get('execution_path') != arm.strategy or audit.get('strategy') != arm.strategy):
                raise TaskConflict('Saved paired result lost its original task, model or strategy audit')
        elif audit is not None or result is not None:
            raise TaskConflict('Saved paired observation invents an unavailable original result')
        group['records'].append(record)
        group['artifact_sources'].append(artifact_source)
    reports = []
    for digest, group in sorted(groups.items()):
        if not group['records']:
            raise TaskConflict('Selected paired archive has no supplied original observations')
        report = summarize_paired_results(group['assembly'], group['records'])
        report.update(artifact_mode='saved_observations_only', assembly_archive=group['archive_source'],
            observation_artifacts=group['artifact_sources'], plan_sha256=plan['plan_sha256'])
        report['report_sha256'] = task_digest({key: value for key, value in report.items() if key != 'report_sha256'})
        reports.append(report)
    return config, root, plan, reports


def _save_report(root, report):
    report['report_sha256'] = task_digest({key: value for key, value in report.items() if key != 'report_sha256'})
    report_path = root / 'reports' / (report['report_sha256'] + '.json')
    if report_path.resolve() != report_path:
        raise TaskConflict('Saved paired report path escapes its original namespace')
    if report_path.exists():
        _, prior, _ = _read_artifact(report_path, root)
        if task_digest(prior) != task_digest(report):
            raise TaskConflict('Existing paired report differs from its original immutable artifact')
    else:
        write_new(report_path, report)
    return {'path': report_path.as_posix(), 'report': report}


def summarize_paired_observation_files(configuration, *, output_root, assembly_archive, observations):
    """Read one original assembly's named artifacts without constructing clients.

    Historical source/isolation checks grant no current read/submit authority
    or proof of macro effects. Every input artifact is read only once.
    """
    _, root, _, reports = _collect_groups(configuration, output_root=output_root,
        assembly_archives=[assembly_archive], observations=observations)
    return _save_report(root, reports[0])


def summarize_paired_observation_groups(configuration, *, output_root, assembly_archives, observations):
    """Keep independent original assemblies separate in one experiment index.

    Both strategies must have results in the same original assembly to count
    as a pair. Cross-assembly observations never form an inferred pair. Costs,
    attempts and feedback remain in each original report without global sums.
    """
    config, root, plan, reports = _collect_groups(configuration, output_root=output_root,
        assembly_archives=assembly_archives, observations=observations)
    action_groups = {basis.action_id: [] for basis in config.action_basis}
    for report in reports:
        for action_id, associations in action_groups.items():
            strategies = [strategy for strategy, arm in report['arms'].items()
                if action_id not in arm['missing_action_ids']]
            if strategies:
                associations.append({'assembly_sha256': report['assembly_sha256'],
                    'report_sha256': report['report_sha256'], 'observed_strategies': strategies,
                    'paired_result_observed': action_id in report['paired_action_ids']})
    # Finish validating all groups before saving any new report artifacts.
    groups = []
    for report in reports:
        saved = _save_report(root, report)
        groups.append({'assembly_sha256': report['assembly_sha256'],
            'report_path': saved['path'], 'report_sha256': report['report_sha256'],
            'assembly_archive': report['assembly_archive'],
            'observation_artifacts': report['observation_artifacts']})
    paired = [action for action, entries in action_groups.items()
        if any(entry['paired_result_observed'] for entry in entries)]
    report = {'schema_version': 'paired-experiment-archive-results.v1', 'status': 'observations_only',
        'artifact_mode': 'saved_observations_grouped_by_assembly',
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'plan_sha256': plan['plan_sha256'], 'assembly_count': len(groups), 'groups': groups,
        'action_groups': action_groups, 'paired_action_ids': paired,
        'unpaired_action_ids': [action for action in action_groups if action not in paired],
        'missing_action_ids': [action for action, entries in action_groups.items() if not entries],
        'actions_with_multiple_assemblies': [action for action, entries in action_groups.items() if len(entries) > 1],
        'cost_aggregation': 'per_assembly_only',
        'limitations': 'Historical observations grouped by their original assembly only. Repeated tasks may appear in different assemblies; no global cost or attempt sum, cross-assembly pairing, current authority, business effect or mechanism advantage is inferred.'}
    return _save_report(root, report)
