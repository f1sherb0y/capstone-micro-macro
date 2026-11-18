"""Run with: python -m integration.run --input ... --output ... --offline"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from integration.bootstrap import enable_gba_imports


def load_agent_client_factory(specification):
    """Resolve one explicitly selected host factory; never construct a default model."""
    import importlib

    if not isinstance(specification, str) or specification.count(':') != 1:
        raise ValueError('Agent client factory must use module:callable syntax')
    module_name, name = specification.split(':')
    if not module_name or not name.isidentifier():
        raise ValueError('Agent client factory requires a module and a callable name')
    factory = getattr(importlib.import_module(module_name), name, None)
    if not callable(factory):
        raise ValueError('Selected agent client factory is not callable')
    return factory


def build_engine(dataset, client, directory, ticks=120, seed=42, profile="smoke", native_provider=None, seed_rosters=None, workflow=None, restore_initial=False, binding=None):
    enable_gba_imports()
    from gba_construction_sim.backend.models.procurement import ProcurementExecution
    from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
    from integration.gba_adapter import CodedemoProcurementExecutor
    request = dataset.macro_request(ticks, seed)
    request.workflow_configuration = workflow or {}
    request.procurement_execution = ProcurementExecution(mode="codedemo_micro", adapter_profile_id="codedemo-local")
    executor = CodedemoProcurementExecutor(dataset, client, directory, profile, seed_rosters=seed_rosters, restore_initial=restore_initial)
    if binding is not None:
        native_provider = binding
    return SimulationEngine.from_request(request, decision_provider=native_provider, procurement_executor=executor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Deterministic fixture, no API calls")
    mode.add_argument("--llm", action="store_true", help="Real micro model configured by existing environment")
    parser.add_argument('--input-format', choices=['shared_dataset', 'gba_request', 'role_contract_invocation'], default='shared_dataset')
    parser.add_argument("--ticks", type=int, help="Override input ticks; SharedDataset defaults to 120")
    parser.add_argument("--seed", type=int, help="Override input random seed; SharedDataset defaults to 42")
    parser.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    parser.add_argument('--macro-mode', choices=['legacy_procurement', 'gba_v1_module', 'role_contract'], default='legacy_procurement')
    parser.add_argument('--role-contract-factory', help='Local action host factory as module:callable')
    parser.add_argument('--role-contract-config', type=Path, help='Explicit versioned local action host configuration JSON')
    parser.add_argument('--agent-client-factory', help='GBA module host factory as module:callable')
    parser.add_argument('--agent-client-config', type=Path, help='Explicit versioned GBA module host configuration JSON')
    parser.add_argument('--module-assembly-hook', help='Explicit engine-dependent host configuration as module:callable')
    parser.add_argument('--module-assembly-config', type=Path, help='Explicit versioned configuration for the engine-dependent hook')
    parser.add_argument('--checkpoint-out', type=Path, help='New immutable completed-tick checkpoint file')
    parser.add_argument('--resume-checkpoint', type=Path, help='Restore this checkpoint in its original output directory')
    parser.add_argument('--stop-after-tick', type=int, help='Stop at this completed native tick and save --checkpoint-out')
    parser.add_argument('--allow-native-project-generation', action='store_true',
        help='Explicitly use original native project generation with fully supplied enterprise identities')
    parser.add_argument('--allow-native-initial-projects-with-generation', action='store_true',
        help='Explicitly combine supplied initial cases with original generation; initial IDs cannot use PGEN')
    args = parser.parse_args(argv)
    if args.checkpoint_out or args.resume_checkpoint or args.stop_after_tick is not None:
        if args.macro_mode != 'gba_v1_module' or not args.module_assembly_hook:
            parser.error('Checkpoint options require gba_v1_module and its explicit assembly hook')
        if args.stop_after_tick is not None and (args.stop_after_tick < 1 or not args.checkpoint_out):
            parser.error('--stop-after-tick requires a positive tick and --checkpoint-out')
        if args.checkpoint_out is not None and args.checkpoint_out.exists():
            parser.error('--checkpoint-out must be a new file; existing checkpoints are immutable')
    if args.allow_native_project_generation and (args.macro_mode != 'gba_v1_module' or args.input_format != 'gba_request'):
        parser.error('--allow-native-project-generation requires gba_v1_module and gba_request input')
    if args.allow_native_initial_projects_with_generation and not args.allow_native_project_generation:
        parser.error('--allow-native-initial-projects-with-generation requires --allow-native-project-generation')
    if args.macro_mode == 'role_contract':
        if args.input_format != 'role_contract_invocation' or not args.role_contract_factory:
            parser.error('role_contract requires --input-format role_contract_invocation and --role-contract-factory')
        if (args.agent_client_factory or args.agent_client_config or args.module_assembly_hook or args.module_assembly_config
                or args.ticks is not None or args.seed is not None):
            parser.error('role_contract does not accept GBA host configuration, ticks or seed overrides')
        from integration.role_contract_host import (load_role_contract_invocation,
            load_role_contract_host_configuration, run_role_contract)

        result = run_role_contract(request=load_role_contract_invocation(args.input),
            factory=load_agent_client_factory(args.role_contract_factory), specification=args.role_contract_factory,
            output_directory=args.output, offline=args.offline,
            configuration=load_role_contract_host_configuration(args.role_contract_config) if args.role_contract_config else None)
        print(json.dumps({'output': str(args.output), 'action_id': result['action_id'],
            'result_kind': result['result']['kind']}, ensure_ascii=False))
        return
    if args.role_contract_factory or args.role_contract_config or args.input_format == 'role_contract_invocation':
        parser.error('role contract factory/input apply only to --macro-mode role_contract')
    if args.input_format == 'gba_request' and args.macro_mode != 'gba_v1_module':
        parser.error('gba_request input requires --macro-mode gba_v1_module')
    if args.macro_mode == 'gba_v1_module' and not args.agent_client_factory:
        parser.error('gba_v1_module requires an explicit --agent-client-factory')
    if args.macro_mode == 'legacy_procurement' and (args.agent_client_factory or args.agent_client_config
            or args.module_assembly_hook or args.module_assembly_config):
        parser.error('GBA client and module assembly options apply only to gba_v1_module')
    if args.module_assembly_config and not args.module_assembly_hook:
        parser.error('--module-assembly-config requires --module-assembly-hook')
    enable_gba_imports()
    from integration.sessions import atomic_json
    if args.input_format == 'gba_request':
        from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
        from integration.scenario_v2 import read_input_json

        _, payload = read_input_json(args.input)
        request = SimulationCreateRequest.model_validate(payload)
        overrides = {}
        if args.ticks is not None:
            overrides['ticks'] = args.ticks
        if args.seed is not None:
            overrides['random_seed'] = args.seed
        request = SimulationCreateRequest.model_validate({**request.model_dump(), **overrides})
    else:
        from integration.shared_data import SharedDataset

        dataset = SharedDataset.load(args.input)
        args.ticks = 120 if args.ticks is None else args.ticks
        args.seed = 42 if args.seed is None else args.seed
    assembly = None
    host_extension = None
    checkpoint_evidence = None
    result_path = args.output / 'result.json'
    if args.macro_mode == 'gba_v1_module':
        from integration.bindings.gba_v1 import build_module_engine
        from integration.module_host import (build_module_host_client, load_module_host_configuration,
            configure_module_host_extension, validate_module_host_client)

        if args.input_format == 'shared_dataset':
            request = dataset.macro_request(args.ticks, args.seed)
        factory = load_agent_client_factory(args.agent_client_factory)
        configuration = load_module_host_configuration(args.agent_client_config) if args.agent_client_config else None
        extension_configuration = load_module_host_configuration(args.module_assembly_config) if args.module_assembly_config else None
        client, host_evidence = build_module_host_client(factory=factory, specification=args.agent_client_factory,
            request=request, output_directory=args.output, offline=args.offline, configuration=configuration)
        try:
            assembly = build_module_engine(request, client,
                allow_native_project_generation=args.allow_native_project_generation,
                allow_native_initial_projects_with_generation=args.allow_native_initial_projects_with_generation,
                checkpoint=args.resume_checkpoint, checkpointable=args.checkpoint_out is not None)
            if args.module_assembly_hook:
                host_extension = configure_module_host_extension(assembly=assembly,
                    hook=load_agent_client_factory(args.module_assembly_hook), specification=args.module_assembly_hook,
                    request=request, output_directory=args.output, offline=args.offline,
                    host_evidence=host_evidence, configuration=configuration,
                    extension_configuration=extension_configuration)
            if args.resume_checkpoint is not None:
                origin = client._native_checkpoint_origin
                result_path = args.output / ('result-resume-' + origin['checkpoint_sha256'][:16] + '.json')
        except Exception:
            client.close()
            raise
        engine = assembly.engine
    else:
        from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider
        from integration.macro_binding import MacroBinding

        if args.offline:
            from integration.fixture_client import IntegrationFixtureClient
            client = IntegrationFixtureClient()
        else:
            from src.llm_client import OpenAICompatibleClient
            from integration.model_client import CachedModelClient
            client = CachedModelClient(OpenAICompatibleClient.from_env(), args.output / "model_cache")
        binding = MacroBinding(RuleBasedDecisionProvider())
        engine = build_engine(dataset, client, args.output, args.ticks, args.seed, args.profile, binding=binding)
    try:
        try:
            if assembly is not None:
                assembly._validate_components()
                if host_extension is None:
                    validate_module_host_client(client, host_evidence)
            if host_extension is not None:
                host_extension.run_engine(ticks=args.stop_after_tick)
                if args.checkpoint_out is not None:
                    checkpoint_evidence = host_extension.save_checkpoint(request=request, path=args.checkpoint_out)
            else:
                engine.run()
        finally:
            if assembly is not None:
                if host_extension is None:
                    validate_module_host_client(client, host_evidence)
                result = {'macro_mode': args.macro_mode, 'input_format': args.input_format,
                    'requested_model_mode': 'offline' if args.offline else 'llm',
                    'native_initialization': {
                        'allow_project_generation': args.allow_native_project_generation,
                        'allow_initial_projects_with_generation': args.allow_native_initial_projects_with_generation,
                        'initial_project_ids': [p.project_id for p in request.initial_projects]},
                    'agent_client_factory': args.agent_client_factory,
                    'module_host': host_evidence,
                    'module_host_extension': host_extension.evidence() if host_extension is not None else None,
                    **({'native_checkpoint': checkpoint_evidence} if checkpoint_evidence is not None else {}),
                    **({'resumed_from': client._native_checkpoint_origin} if args.resume_checkpoint is not None else {}),
                    'macro_assembly': assembly.evidence(), 'simulation': engine.response().model_dump(mode='json')}
            else:
                result = {"macro_mode": args.macro_mode, "offline_fixture": args.offline,
                    "non_procurement_provider": "GBA RuleBasedDecisionProvider",
                    "macro_binding": binding.evidence(), "simulation": engine.response().dict(),
                    "procurement": engine.procurement_executor.status()}
            atomic_json(result_path, result)
    finally:
        if assembly is not None:
            try:
                if host_extension is not None:
                    host_extension.close()
            finally:
                client.close()
    print(json.dumps({"output": str(args.output), "result": str(result_path), "tick": engine.current_tick,
                      "projects": {p.project_id: p.current_stage.value for p in engine.projects.values()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
