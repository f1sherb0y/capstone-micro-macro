"""Plan or explicitly evaluate one synthetic V4 Supplier planning request."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_planning_fixture_sources import SupplierPlanningFixtureSettings
from integration.supplier_order_planning_fixture_sources import (
    SupplierOrderPlanningFixtureSettings, check_order_connection_selection, check_order_connection_provenance,
)
from integration.supplier_order_handoff import supplier_order_handoff_schemas
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Known, Reference, TimeWindow
from src.actions.contracts.supplier_planning_objects import (
    SupplierWorkAuthorityView, SupplierPlanningProfileView, SupplierSupplyPlanView,
    SupplierPlanningCommitmentView,
    SupplierProcurementAuthorityView,
)
from src.actions.contracts.supplier_order_objects import FormationOfferView, FormationTermsView
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_planning_fixture_sources:build_sources'
_LINKED_SOURCES = 'integration.supplier_order_planning_fixture_sources:build_sources'
_PLAN_CHOICES = {'plan_manufacture', 'plan_purchase', 'split_plan', 'revise_plan'}
_REQUEST_CHOICES = {'request_quote', 'accept_upstream_offer', 'seek_delivery_change'}


def _expected_payload(step):
    if step['expected_choice'] in _PLAN_CHOICES:
        payload = {'tasks': deepcopy(step['expected_tasks'])}
        if step['expected_choice'] == 'revise_plan':
            payload['prior_plan_ref'] = deepcopy(step['expected_prior_plan_ref'])
        return payload
    return deepcopy(step['expected_payload'])


def _check_request_selection(*, step, profile, work, originals, inputs, context):
    """Preserve exact requested recipients/products/terms; original processor checks effects."""
    if (profile.plan_ref is not None or profile.prior_plan_ref is not None
            or step.get('expected_plan_ref') is not None or step.get('expected_tasks')):
        raise ValueError('V4 non-plan request cannot silently select a supply plan')
    if profile.choice == 'request_quote':
        if (not profile.supplier_ids or len(set(profile.supplier_ids)) != len(profile.supplier_ids)
                or work.organization_id in profile.supplier_ids or not profile.required_lines):
            raise ValueError('V4 quote request requires explicit independent recipients and products')
        expected = {'supplier_ids': profile.supplier_ids,
            'required_lines': [row.model_dump(mode='json') for row in profile.required_lines]}
    elif profile.choice == 'seek_delivery_change':
        if (work.order_ref is None or not profile.affected_line_refs or profile.proposed_window_ref is None
                or len({ref.key() for ref in profile.affected_line_refs}) != len(profile.affected_line_refs)
                or not {ref.key() for ref in profile.affected_line_refs} <= {ref.key() for ref in work.order_line_refs}):
            raise ValueError('V4 delivery change requires exact original order lines and proposed window')
        window = TimeWindow.model_validate(originals[profile.proposed_window_ref.key()])
        if window.start.clock_ref != context.business_time.clock_ref or window.start.offset < context.business_time.offset:
            raise ValueError('V4 proposed delivery window changes original clock or precedes request')
        expected = {'affected_line_refs': [ref.model_dump(mode='json') for ref in profile.affected_line_refs],
            'proposed_window_ref': profile.proposed_window_ref.model_dump(mode='json')}
    else:
        if (profile.offer_ref is None or profile.procurement_authority_ref is None
                or profile.offer_ref.key() not in {Reference.model_validate(ref).key() for ref in inputs['upstream_offer_refs']}):
            raise ValueError('V4 acceptance must select an explicitly received original offer and procurement authority')
        offer = FormationOfferView.model_validate(originals[profile.offer_ref.key()])
        terms = FormationTermsView.model_validate(originals[offer.terms_ref.key()])
        authority = SupplierProcurementAuthorityView.model_validate(originals[profile.procurement_authority_ref.key()])
        offer_lines = {row.local_key: row for row in offer.lines}
        if (offer.buyer_id != work.organization_id or offer.supplier_organization_id == work.organization_id
                or terms.offer_ref != offer.ref or terms.buyer_id != offer.buyer_id or terms.payer_id != offer.payer_id
                or terms.supplier_organization_id != offer.supplier_organization_id
                or authority.work_authority_ref != work.ref or authority.organization_id != work.organization_id
                or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                or not isinstance(authority.permitted, Known) or authority.permitted.value is not True
                or offer.payer_id not in authority.allowed_payer_ids
                or not profile.offer_line_keys or len(set(profile.offer_line_keys)) != len(profile.offer_line_keys)
                or not set(profile.offer_line_keys) <= set(offer_lines)
                or len(offer_lines) != len(offer.lines)
                or profile.required_lines != [offer_lines[key].delivery.product for key in profile.offer_line_keys]):
            raise ValueError('V4 acceptance changes original offer lines, parties, terms or independent procurement authority')
        expected = {'offer_ref': offer.ref.model_dump(mode='json'), 'terms_ref': terms.ref.model_dump(mode='json'),
            'required_lines': [row.model_dump(mode='json') for row in profile.required_lines]}
    if step.get('expected_payload') != expected:
        raise ValueError('V4 non-plan request changes its exact declared branch payload')


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V4 planning requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    linked = settings.source_factory == _LINKED_SOURCES
    source = (SupplierOrderPlanningFixtureSettings if linked else SupplierPlanningFixtureSettings).model_validate(settings.source_settings)
    if linked:
        check_order_connection_selection(request=request, settings=settings, source=source)
    elif settings.order_inputs is not None:
        raise ValueError('Standalone planning cannot silently declare an order connection')
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A05' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') not in _PLAN_CHOICES | _REQUEST_CHOICES
            or context.contract_ref.id != 'SUPPLIER-A05' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A05'
            or not linked and (settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-planning-fixture-sources.v1')
            or source.action_id != 'SUPPLIER-A05' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V4 planning changes original offline action, factory, run or snapshot')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V4 planning aliases independent organization source identities')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V4 planning changes complete original visible source identities')
    schemas = supplier_order_handoff_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V4 offline planning evidence must declare its synthetic origin')
    inputs = request.action_input
    work = SupplierWorkAuthorityView.model_validate(originals[Reference.model_validate(inputs['work_authority_ref']).key()])
    profile = SupplierPlanningProfileView.model_validate(originals[work.profile_ref.key()])
    if (work.ref.model_dump(mode='json') != step['expected_work_authority_ref']
            or work.organization_id != projection['organization_id'] or work.scope != context.scope
            or profile.work_authority_ref != work.ref or profile.organization_id != work.organization_id
            or profile.scope != context.scope or profile.actor_id != context.actor_id
            or profile.function_ref != context.function_ref or profile.authority_ref not in context.authorization_refs
            or profile.choice != step['expected_choice']):
        raise ValueError('V4 planning replaces its original work or authorized profile')
    if profile.choice in _REQUEST_CHOICES:
        _check_request_selection(step=step, profile=profile, work=work, originals=originals, inputs=inputs, context=context)
    else:
        plan = SupplierSupplyPlanView.model_validate(originals[profile.plan_ref.key()])
        tasks = [task.model_dump(mode='json') for task in plan.tasks]
        if (plan.ref.model_dump(mode='json') != step['expected_plan_ref'] or plan.work_authority_ref != work.ref
                or plan.status != 'proposed' or plan.scope != context.scope or not tasks or tasks != step['expected_tasks']):
            raise ValueError('V4 planning replaces its original full proposed plan')
        modes = {task.mode for task in plan.tasks}
        task_keys = {task.local_key for task in plan.tasks}
        if (not modes <= set(work.permitted_modes) or len(task_keys) != len(plan.tasks)
                or set(plan.task_requirement_refs) != task_keys
                or profile.choice == 'plan_purchase' and modes != {'purchase'}
                or profile.choice == 'plan_manufacture' and not modes <= {'manufacture', 'rework'}
                or profile.choice == 'split_plan' and len(plan.tasks) < 2):
            raise ValueError('V4 planning changes permitted modes or complete explicit task partitions')
        if profile.choice == 'revise_plan':
            if (profile.prior_plan_ref is None or plan.replaces_plan_ref != profile.prior_plan_ref
                    or profile.prior_plan_ref.model_dump(mode='json') != step.get('expected_prior_plan_ref')
                    or [ref.model_dump(mode='json') for ref in plan.replacement_commitment_refs] != step.get('expected_replacement_commitment_refs')
                    or len({ref.key() for ref in plan.replacement_commitment_refs}) != len(plan.replacement_commitment_refs)):
                raise ValueError('V4 revision requires its exact original prior plan and explicit replacement commitments')
            prior = SupplierSupplyPlanView.model_validate(originals[profile.prior_plan_ref.key()])
            if (prior.ref == plan.ref or prior.work_authority_ref != work.ref or prior.scope != context.scope
                    or prior.status not in {'proposed', 'effective'}):
                raise ValueError('V4 revision replaces a different mandate, scope or plan')
            for ref in plan.replacement_commitment_refs:
                commitment = SupplierPlanningCommitmentView.model_validate(originals[ref.key()])
                if commitment.plan_ref != prior.ref or commitment.organization_id != work.organization_id:
                    raise ValueError('V4 revision replaces another plan or organization commitment')
        elif profile.prior_plan_ref is not None or plan.replaces_plan_ref is not None or plan.replacement_commitment_refs:
            raise ValueError('V4 new plan cannot silently replace original plans or commitments')
    for name in ('requirement_refs', 'design_refs', 'method_refs'):
        values = [Reference.model_validate(value) for value in inputs[name]]
        if len({ref.key() for ref in values}) != len(values) or [ref.key() for ref in values] != [ref.key() for ref in getattr(work, name)]:
            raise ValueError('V4 planning changes complete selected work requirements, designs or methods')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v4_supplier_planning_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 planning execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V4 execution requires its declared new output directory and exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-supplier-planning-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A05', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_work_authority_ref': deepcopy(step['expected_work_authority_ref']),
        'expected_choice': step['expected_choice'],
        'expected_plan_ref': deepcopy(step.get('expected_plan_ref')), 'expected_tasks': deepcopy(step.get('expected_tasks')),
        'expected_payload': _expected_payload(step),
        'source_order_selection': deepcopy(configuration['settings'].get('order_inputs')),
        'expected_prior_plan_ref': deepcopy(step.get('expected_prior_plan_ref')),
        'expected_replacement_commitment_refs': deepcopy(step.get('expected_replacement_commitment_refs', [])),
        'limitations': ['Synthetic effective order, work authority, stock and capacity are explicitly supplied assumptions.',
            'Planning output creates no formal tasks, release, production, stock or connected V4 execution evidence.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-supplier-planning-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V4 planning input changed or journal exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'supplier', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Supplier', 'action_id': 'SUPPLIER-A05', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A05'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_planning_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != step['expected_choice']
                or any(result['payload'].get(key) != value for key, value in _expected_payload(step).items())
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V4 planning did not preserve exact proposed tasks and original result without native execution')
        if configuration['settings'].get('order_inputs') is not None:
            source = SupplierOrderPlanningFixtureSettings.model_validate(configuration['settings']['source_settings'])
            check_order_connection_provenance(request=RoleContractInvocation.model_validate(request),
                source=source, evidence=evidence)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V4 original planning input changed during evaluation')
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
    print(run_v4_supplier_planning_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
