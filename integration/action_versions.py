"""Identify the actual components of a prepared action without executing it."""
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView
from src.actions.implementation import callable_implementation
from src.actions.runner import ActionRunner
from src.methods.registry import MethodRegistry
from src.coordination.tasks import TaskConflict, task_digest, _text


def prepared_action_execution_versions(prepared, *, client_version, model_version):
    # Loaded after worker module initialization: the worker itself uses this
    # function to identify a prepared invocation. Its execution protocol is
    # part of the version boundary, including the pre-preparation claim.
    from integration.contractor_bid_results import ContractorBidResultWorker
    from integration.contractor_bid_source_history import save_bid_source_history

    if not isinstance(prepared.context, ActionContext) or not isinstance(prepared.runner, ActionRunner):
        raise TaskConflict('Execution versions require a prepared typed context and actual runner')
    _text(client_version); _text(model_version)
    context = prepared.context
    registration = prepared.runner.registry.get(context.contract_ref.id)
    if registration.skill is None or not registration.implemented:
        raise TaskConflict('Execution versions require the bound Skill and processor')
    if prepared.runner.model_version is not None and prepared.runner.model_version != model_version:
        raise TaskConflict('Model version differs from the configured runner')
    if context.execution_mode == 'llm' and prepared.runner.model_version is None:
        raise TaskConflict('An LLM invocation needs explicit configured model version evidence')
    skill = registration.skill
    path = 'deterministic' if context.execution_mode in {'rule','routine','offline_fixture'} else registration.strategy
    strategy_version = {'execution_path':path,'configured_strategy':registration.strategy,
        'processor_id':registration.processor_id,'policy_version':prepared.runner.policy_version,
        'candidate_fields':[[choice, list(fields)] for choice, fields in registration.candidate_fields],
        'candidate_collection_fields':[[choice, list(fields)] for choice, fields in registration.candidate_collection_fields],
        'role_configuration':prepared.runner.registry.role_configurations[registration.role].model_dump(mode='json'),
        'bid_source_retention':prepared.runner.retain_reading_evidence
            if context.contract_ref.id == 'CONTRACTOR-A02' else None,
        'implementation':{
            'worker_registration':callable_implementation(ContractorBidResultWorker.register),
            'worker_execution':callable_implementation(ContractorBidResultWorker.execute),
            'bid_source_retention':callable_implementation(save_bid_source_history)
                if context.contract_ref.id == 'CONTRACTOR-A02' else None,
            'processor':callable_implementation(registration.processor),
            'runner':callable_implementation(prepared.runner.run_action),
            'preparation':callable_implementation(prepared.runner.prepare_decision),
            'reading':callable_implementation(ActionReadView.resolve),
            'candidate_permissions':callable_implementation(CandidateSet.check_selected),
            'candidate_policy':callable_implementation(registration.check_candidate_permissions),
            'reference_identity':callable_implementation(Reference.__eq__),
            'reference_hash':callable_implementation(Reference.__hash__),
            'registry':callable_implementation(prepared.runner.registry.get),
            'contract_input':callable_implementation(registration.contract.validate_input),
            'contract_decision':callable_implementation(registration.contract.validate_decision),
            'contract_rules':callable_implementation(registration.contract.decision_validator),
            'authorization':callable_implementation(prepared.runner.organizations.grants)
                if prepared.runner.organizations is not None else None,
            'method_boundary':callable_implementation(MethodRegistry.invoke),
            'version_boundary':callable_implementation(prepared_action_execution_versions)}}
    binding = prepared.runner.decision_strategies.get(path)
    if binding is not None:
        strategy_version['decision_binding'] = binding.evidence(status='configured')
        strategy_version['decision_implementation'] = callable_implementation(binding.execute)
        if binding.prepare_invocation is not None:
            strategy_version['preparation_implementation'] = callable_implementation(binding.prepare_invocation)
    return {
        'client':client_version,
        'skill':task_digest(skill.manifest.model_dump(mode='json')),
        'prompt':task_digest({'content':skill.content,'shared_content':skill.shared_content}),
        'contract':task_digest({'ref':context.contract_ref.model_dump(mode='json'),
            'source_sha256':registration.contract.source_sha256,
            'input_schema':registration.contract.input_model.model_json_schema(),
            'payload_schema':registration.contract.payload_adapter.json_schema()}),
        'method':prepared.runner.methods.content_digest,
        'model':model_version,
        'strategy':task_digest(strategy_version),
    }
