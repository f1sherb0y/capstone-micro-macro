"""Prepare paired plans, or explicitly execute one action in both checked arms."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass, fields
import json
from pathlib import Path
from typing import Callable

from integration.action_catalog import write_new
from integration.module_host import module_factory_descriptor
from integration.paired_experiment_callbacks import PairedCallbackSet
from integration.paired_experiment_archive import (
    summarize_paired_observation_files, summarize_paired_observation_groups,
)
from integration.paired_experiment_hosts import assemble_paired_model_hosts
from integration.paired_experiment_results import summarize_paired_results
from integration.paired_experiment_run import run_paired_action
from integration.paired_experiments import PairedExperimentConfiguration, prepare_paired_experiment
from integration.run import load_agent_client_factory
from integration.scenario_v2 import read_input_json
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PairedExperimentApplication:
    """Actual application resources and gates; close owns their cleanup.

    prepare_action(strategy, action_id, model_host) assembles the original worker
    and prepared invocation using the supplied exact host, without executing it.
    assembly_guard(configuration) guards both arms' actual source/state snapshots.
    read_guard must protect the current invocation and actual state routing;
    state describe_current adapters use their original storage locks for any
    state snapshot outside that source guard. They only read existing state.
    Optional read_feedback(strategy, identity, host) reads original actual
    records only; validate_record verifies their authority and provenance.
    Optional read_cost(strategy, identity, host) returns one invocation allocation
    or None. Its paired validate_cost gate verifies the actual original source.
    Optional submit_action uses the application's original durable submission
    host. validate_submission checks actual routing and receipt provenance.
    """
    arms: dict
    states: dict
    clients: dict
    option_sources: dict
    assembly_guard: Callable
    validate_sources: Callable
    validate_isolation: Callable
    validate_components: Callable
    prepare_action: Callable
    read_guard: Callable
    validate_execute: Callable
    validate_record: Callable
    close: Callable
    read_feedback: Callable | None = None
    read_cost: Callable | None = None
    validate_cost: Callable | None = None
    submit_action: Callable | None = None
    validate_submission: Callable | None = None

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in {'arms', 'states', 'clients', 'option_sources'}:
                if not isinstance(value, dict):
                    raise ValueError('Paired application requires explicit component maps')
            elif item.name in {'read_feedback', 'read_cost', 'validate_cost',
                    'submit_action', 'validate_submission'} and value is None:
                continue
            elif not callable(value):
                raise ValueError('Paired application requires every original gate, guard and cleanup callback')
        if (self.read_cost is None) != (self.validate_cost is None):
            raise ValueError('Paired costs require both an explicit reader and actual source validator')
        if (self.submit_action is None) != (self.validate_submission is None):
            raise ValueError('Paired submission requires both the original host adapter and actual validator')


def _save_same_or_new(path, payload):
    if path.exists():
        _, prior = read_input_json(path)
        if task_digest(prior) != task_digest(payload):
            raise TaskConflict('Existing paired artifact differs; choose an explicit new experiment configuration')
    else:
        write_new(path, payload)


def prepare_paired_plan_file(configuration, *, output_root: Path):
    """Save only a configuration plan; do not import or invoke an application factory."""
    config = PairedExperimentConfiguration.model_validate(configuration)
    plan = prepare_paired_experiment(config, output_root=output_root)
    root = Path(output_root).resolve() / config.experiment_id
    path = root / 'plan.json'
    if not path.resolve().is_relative_to(root):
        raise TaskConflict('Paired plan path escapes its declared experiment namespace')
    _save_same_or_new(path, plan)
    return {'path': path.as_posix(), 'plan': plan}


def execute_paired_action(configuration, *, output_root: Path, factory, specification, action_id, request_id,
        submit_pair=False):
    """Explicit live entry: run one selected action once in each original strategy.

    Calling this function authorizes its supplied application's model calls.
    Macro submission additionally requires submit_pair=True and actual adapters.
    A durable pair intent prevents automatic
    re-entry after factory/assembly/action interruption; existing outcomes are
    read without constructing clients. Unknown work requires actual diagnosis.
    """
    config = PairedExperimentConfiguration.model_validate(configuration)
    config = PairedExperimentConfiguration.model_validate(config.model_dump(mode='python'))
    if (type(submit_pair) is not bool or not callable(factory)
            or action_id not in {basis.action_id for basis in config.action_basis}
            or not isinstance(request_id, str) or not request_id.strip()):
        raise TaskConflict('Paired execution requires a supplied application factory, declared action and explicit request ID')
    descriptor = module_factory_descriptor(factory, specification)
    descriptor['implementation'] = callable_implementation(factory)
    if descriptor['source_sha256'] is None:
        raise TaskConflict('Paired execution factory requires locatable original implementation code')
    prepared_plan = prepare_paired_plan_file(config, output_root=output_root)
    root = Path(output_root).resolve() / config.experiment_id
    pair_root = root / 'pairs' / task_digest([action_id, request_id])
    if not pair_root.resolve().is_relative_to(root):
        raise TaskConflict('Paired invocation path escapes its declared experiment namespace')
    intent_path, outcome_path = pair_root / 'intent.json', pair_root / 'outcome.json'
    intent = {'schema_version': 'paired-entry-intent.v2', 'status': 'explicit_execution_requested',
        'plan_sha256': prepared_plan['plan']['plan_sha256'], 'action_id': action_id, 'request_id': request_id,
        'factory': descriptor}
    if submit_pair:
        intent['macro_submission_requested'] = True
    intent['record_sha256'] = task_digest(intent)
    if intent_path.exists():
        _, prior = read_input_json(intent_path)
        if task_digest(prior) != task_digest(intent):
            raise TaskConflict('Original paired entry intent changed; no factory or action replay')
        if not outcome_path.exists():
            raise TaskConflict('Paired entry has an unresolved original intent; diagnose existing runs before re-entry')
        _, outcome = read_input_json(outcome_path)
        if (outcome.get('intent_sha256') != intent['record_sha256']
                or outcome.get('record_sha256') != task_digest({key: value for key, value in outcome.items() if key != 'record_sha256'})):
            raise TaskConflict('Saved paired outcome changes its original intent or digest')
        return outcome
    write_new(intent_path, intent)
    with ExitStack() as cleanup:
        app = factory(configuration=config.model_copy(deep=True), output_root=Path(output_root).resolve())
        if not isinstance(app, PairedExperimentApplication):
            raise TaskConflict('Paired factory must return its explicit PairedExperimentApplication')
        cleanup.callback(app.close)
        component_maps = {name: getattr(app, name) for name in ('arms', 'states', 'clients', 'option_sources')}
        callback_names = tuple(item.name for item in fields(app) if item.name not in component_maps)
        callbacks = PairedCallbackSet(**{name: getattr(app, name) for name in callback_names})

        def check_application():
            callbacks.check(**{name: getattr(app, name) for name in callback_names})
            if any(getattr(app, name) is not original for name, original in component_maps.items()):
                raise TaskConflict('Paired application substituted an original component map')

        if submit_pair and (app.submit_action is None or app.validate_submission is None):
            raise TaskConflict('Explicit paired submission requires actual durable host adapters and validators')
        current_descriptor = module_factory_descriptor(factory, specification)
        current_descriptor['implementation'] = callable_implementation(factory)
        if task_digest(current_descriptor) != task_digest(descriptor):
            raise TaskConflict('Paired factory implementation changed during component construction')
        try:
            check_application()
            with callbacks.guard('assembly_guard', config.model_copy(deep=True)):
                check_application()
                assembly = assemble_paired_model_hosts(config, output_root=output_root,
                    arms=app.arms, states=app.states, clients=app.clients, option_sources=app.option_sources,
                    validate_sources=app.validate_sources, validate_isolation=app.validate_isolation,
                    validate_components=app.validate_components, application_callbacks=callbacks.evidence())
                check_application()
        finally:
            check_application()
        archive = {'schema_version': 'paired-assembly-archive.v1',
            'configuration': config.model_dump(mode='json'), 'evidence': deepcopy(assembly.evidence),
            'source_check': deepcopy(assembly.source_check), 'isolation_check': deepcopy(assembly.isolation_check),
            'factory': descriptor, 'application_callbacks': callbacks.evidence()}
        archive['record_sha256'] = task_digest(archive)
        archive_path = root / 'assemblies' / (archive['record_sha256'] + '.json')
        if not archive_path.resolve().is_relative_to(root):
            raise TaskConflict('Paired assembly archive escapes its original namespace')
        _save_same_or_new(archive_path, archive)
        drivers, observations = [], []
        for arm in config.arms:
            try:
                check_application()
                worker, prepared = callbacks.invoke('prepare_action', strategy=arm.strategy, action_id=action_id,
                    model_host=assembly.hosts[arm.strategy])
            finally:
                check_application()
            completed = run_paired_action(assembly, output_root=output_root, strategy=arm.strategy,
                worker=worker, prepared=prepared, request_id=request_id, read_guard=app.read_guard,
                validate_execute=app.validate_execute, validate_record=app.validate_record,
                read_feedback=app.read_feedback, read_cost=app.read_cost, validate_cost=app.validate_cost,
                submit_action=app.submit_action if submit_pair else None,
                validate_submission=app.validate_submission if submit_pair else None)
            check_application()
            drivers.append(completed['driver'])
            observations.append(completed['observation'])
        summary = summarize_paired_results(assembly, observations)
        summary_path = root / 'reports' / (summary['report_sha256'] + '.json')
        if not summary_path.resolve().is_relative_to(root):
            raise TaskConflict('Paired summary path escapes its original namespace')
        _save_same_or_new(summary_path, summary)
        outcome = {'schema_version': 'paired-entry-outcome.v1', 'status': 'attempts_recorded',
            'intent_sha256': intent['record_sha256'], 'assembly_archive': archive_path.as_posix(),
            'drivers': drivers, 'summary_path': summary_path.as_posix(), 'summary_sha256': summary['report_sha256'],
            'limitations': 'Original decisions and observations; macro submission only when explicitly requested. Receipts do not prove business effects. Missing results/costs stay unknown.'}
        outcome['record_sha256'] = task_digest(outcome)
        check_application()
        write_new(outcome_path, outcome)
        return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--execute-pair', action='store_true', help='Explicitly permit model execution for one action in both arms')
    parser.add_argument('--summarize-observations', action='store_true', help='Summarize explicit saved observations without clients or execution')
    parser.add_argument('--assembly-archive', type=Path, action='append', help='Original assembly archive; repeat to keep assemblies in separate groups')
    parser.add_argument('--observation', type=Path, action='append', help='Original observation artifact; repeat for all selected actions/arms')
    parser.add_argument('--submit-pair', action='store_true', help='Also explicitly submit formed outputs through original actual hosts')
    parser.add_argument('--factory', help='Explicit application module:callable; used only with --execute-pair')
    parser.add_argument('--action-id')
    parser.add_argument('--request-id')
    args = parser.parse_args()
    if args.summarize_observations:
        if args.execute_pair or args.submit_pair or any((args.factory, args.action_id, args.request_id)):
            parser.error('--summarize-observations cannot be combined with execution or factory arguments')
        if not args.assembly_archive or not args.observation:
            parser.error('--summarize-observations requires --assembly-archive and --observation')
    elif args.assembly_archive or args.observation:
        parser.error('Archive/observation arguments require --summarize-observations')
    if args.submit_pair and not args.execute_pair:
        parser.error('--submit-pair requires --execute-pair')
    if args.execute_pair and not all((args.factory, args.action_id, args.request_id)):
        parser.error('--execute-pair requires --factory, --action-id and --request-id')
    if not args.execute_pair and any((args.factory, args.action_id, args.request_id)):
        parser.error('Factory/action/request arguments require the explicit --execute-pair flag')
    text, _ = read_input_json(args.configuration)
    config = PairedExperimentConfiguration.model_validate_json(text)
    if args.summarize_observations:
        if len(args.assembly_archive) == 1:
            result = summarize_paired_observation_files(config, output_root=args.output_root,
                assembly_archive=args.assembly_archive[0], observations=args.observation)
        else:
            result = summarize_paired_observation_groups(config, output_root=args.output_root,
                assembly_archives=args.assembly_archive, observations=args.observation)
        print(json.dumps({'status': result['report']['status'], 'summary_path': result['path']}, ensure_ascii=False))
    elif args.execute_pair:
        result = execute_paired_action(config, output_root=args.output_root,
            factory=load_agent_client_factory(args.factory), specification=args.factory,
            action_id=args.action_id, request_id=args.request_id, submit_pair=args.submit_pair)
        print(json.dumps({'status': result['status'], 'summary_path': result['summary_path']}, ensure_ascii=False))
    else:
        result = prepare_paired_plan_file(config, output_root=args.output_root)
        print(json.dumps({'status': result['plan']['status'], 'plan_path': result['path']}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not serialize arbitrary factory/provider exception messages.
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
