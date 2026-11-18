"""Plan or explicitly evaluate one synthetic V6 QS-A09 evidence request."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.qs_role_contract_fixture_sources import QSFixtureSourceSettings
from integration.qs_role_contract_host import QSRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.actions.contracts.qs_final_account_objects import (
    QSChangeClaimView, QSFinalContractView, QSFinalProfileView,
    QSFinalQuestionView, QSFinalResponseView, qs_final_account_schemas,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.qs_role_contract_host:build_role_host'
_SOURCES = 'integration.qs_role_contract_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V6'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V6 QS evidence requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = QSRoleContractSettings.model_validate(configuration.settings)
    source = QSFixtureSourceSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'QS-A09' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'request_evidence'
            or context.contract_ref.id != 'QS-A09' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'QS-A09'
            or settings.source_factory != _SOURCES or settings.source_version != 'configured-qs-fixture-sources.v1'
            or source.action_id != 'QS-A09' or source.allow_saved_recovery or settings.feedback_inputs is not None
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V6 QS evidence changes original offline action, factory, run or snapshot')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V6 QS evidence changes complete original visible projection identities')
    schemas = qs_final_account_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V6 offline evidence request cannot treat native observations as fixture evidence')

    def original(reference, schema):
        return schema.model_validate(originals[reference.key()])

    contract = original(Reference.model_validate(request.action_input['contract_ref']), QSFinalContractView)
    profile = original(contract.final_profile_ref, QSFinalProfileView)
    if (request.action_input['scope'] != context.scope.model_dump(mode='json')
            or profile.choice != 'request_evidence' or profile.contract_ref != contract.ref
            or contract.valuation_organization_id != projection['organization_id']
            or contract.valuation_actor_id != context.actor_id or contract.valuation_function_ref != context.function_ref
            or profile.author_organization_id != contract.valuation_organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope
            or contract.coverage != 'complete' or contract.as_of != context.business_time
            or request.action_input['reconciliation_result_ref'] is not None):
        raise ValueError('V6 QS evidence requires the original current contract and explicit question-only opinion')
    for supplied, declared in (('determined_change_refs', 'determined_change_refs'),
            ('certificate_refs', 'all_certificate_refs'), ('payment_receipt_refs', 'receipt_refs'),
            ('unresolved_claim_refs', 'unresolved_claim_refs')):
        values = [Reference.model_validate(value) for value in request.action_input[supplied]]
        if len(set(values)) != len(values) or set(values) != set(getattr(contract, declared)):
            raise ValueError('V6 QS evidence omits original final-account history: ' + supplied)
    expected_claims = [Reference.model_validate(value) for value in step['expected_unresolved_claim_refs']]
    if (not expected_claims or len(set(expected_claims)) != len(expected_claims)
            or set(expected_claims) != set(contract.unresolved_claim_refs)):
        raise ValueError('V6 QS evidence must preserve the complete declared unresolved claim set')
    for reference in expected_claims:
        claim = original(reference, QSChangeClaimView)
        if claim.contract_ref != contract.ref or claim.status != 'submitted':
            raise ValueError('V6 QS evidence substitutes or withdraws its original unresolved claim')
    if (not profile.question_refs or len(set(profile.question_refs)) != len(profile.question_refs)
            or profile.question_refs != [Reference.model_validate(value) for value in step['expected_question_refs']]):
        raise ValueError('V6 QS evidence requires its exact original evidence questions')
    questions = []
    recipients = set()
    responses = []
    for reference in profile.question_refs:
        question = original(reference, QSFinalQuestionView)
        response = original(question.response_requirement_ref, QSFinalResponseView)
        if (question.contract_ref != contract.ref or response.contract_ref != contract.ref
                or not question.recipient_ids or len(set(question.recipient_ids)) != len(question.recipient_ids)
                or not set(question.recipient_ids) <= set(contract.party_ids)
                or not set(question.recipient_ids) <= set(response.recipient_ids)):
            raise ValueError('V6 QS evidence substitutes original contract parties or response requirements')
        responses.append(response.ref.model_dump(mode='json'))
        recipients.update(question.recipient_ids)
        questions.append(dict(scope=context.scope.model_dump(mode='json'), target_refs=[reference.model_dump(mode='json')],
            question=question.question, recipient_ids=list(question.recipient_ids),
            evidence_refs=[value.model_dump(mode='json') for value in question.evidence_refs],
            blocking_uses=['cost_estimation'], response_requirement_ref=response.ref.model_dump(mode='json')))
    if (responses != step['expected_response_requirement_refs']
            or len(set(step['expected_recipient_ids'])) != len(step['expected_recipient_ids'])
            or recipients != set(step['expected_recipient_ids'])):
        raise ValueError('V6 QS evidence changes its declared response requirements or recipients')
    return (path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'),
            configuration.model_dump(mode='json'), questions)


def run_v6_qs_final_evidence_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 QS evidence execution selection must be an explicit boolean')
    path, digest, case, request, configuration, questions = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V6 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-qs-final-evidence-plan.v1', 'scenario_id': 'V6', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'QS-A09', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_questions': deepcopy(questions),
        'unresolved_claim_refs': deepcopy(step['expected_unresolved_claim_refs']),
        'limitations': ['Isolated synthetic evidence request; no final price, settlement, cash or claim-resolution effects.',
            'Other final-account branches, V6 connected inputs and formal behavior remain pending.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-qs-final-evidence-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V6 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'qs', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'QS', 'action_id': 'QS-A09', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'QS-A09'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'qs_final_account_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'request_evidence'
                or result['payload']['scope'] != request['context']['scope']
                or result['payload']['questions'] != questions
                or 'account' in result['payload'] or 'determination_basis_ref' in result['payload']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V6 QS evidence did not preserve exact questions and original result without determination or transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V6 original QS evidence input changed during evaluation')
        summary = {**plan, 'mode': 'executed_offline', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result': deepcopy(result), 'real_model_calls': 0}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v6_qs_final_evidence_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
