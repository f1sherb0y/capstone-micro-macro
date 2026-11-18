"""Prepare offline tender reception configurations without opening journals or running actions."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.contractor_role_contract_host import ContractorRoleContractSettings
from integration.lifecycle_v2_offline import _CONFIGURED_CASES, _check_durable_result
from integration.owner_role_contract_host import OwnerRoleContractSettings
from integration.owner_tender_contractor_fixture_sources import (
    ContractorOwnerTenderFixtureSettings, DeclaredOwnerTenderRegistration, OwnerTenderHistorySettings,
)
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import EvidenceRecord
from src.coordination.tasks import TaskIdentity, task_digest


def _bind_history_metadata(history, settings, result):
    """Join original execution metadata to explicitly supplied current sources."""
    history = history.model_dump(mode='json') if hasattr(history, 'model_dump') else deepcopy(history)
    if not isinstance(history, dict) or not isinstance(result, dict) or not isinstance(result.get('execution_evidence'), dict):
        raise ValueError('History binding requires explicit current sources and original execution evidence')
    original = {'identity': result['execution_evidence'].get('identity'), **{key: getattr(settings, key)
        for key in ('macro_version', 'client_version', 'policy_version', 'model_version')}}
    for key, value in original.items():
        supplied = history.get(key)
        if isinstance(supplied, TaskIdentity):
            supplied = supplied.as_dict()
        if key in history and supplied != value:
            raise ValueError('History substitutes original execution identity or versions')
        history[key] = deepcopy(value)
    return history


def configure_received_tender(*, owner_request, owner_configuration, owner_result,
        owner_history, registration, contractor_request, contractor_configuration):
    """Bind supplied actual result lineage and independent receiver facts.

    The original journal is read by the configured source factory at execution.
    Preparing files proves neither that journal nor publication/reception exists.
    No package ID, mapping, observed Evidence or result is manufactured here.
    """
    owner_request = RoleContractInvocation.model_validate(owner_request).model_copy(deep=True)
    owner_configuration = RoleContractHostConfiguration.model_validate(owner_configuration).model_copy(deep=True)
    owner_settings = OwnerRoleContractSettings.model_validate(owner_configuration.settings)
    history = OwnerTenderHistorySettings.model_validate(
        _bind_history_metadata(owner_history, owner_settings, owner_result)).model_copy(deep=True)
    registration = DeclaredOwnerTenderRegistration.model_validate(registration).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(contractor_request).model_copy(deep=True)
    configuration = RoleContractHostConfiguration.model_validate(contractor_configuration).model_copy(deep=True)
    settings = ContractorRoleContractSettings.model_validate(configuration.settings)
    result = deepcopy(owner_result)
    original_request = owner_request.model_dump(mode='json')
    _check_durable_result(result, {'request': original_request}, action_id='OWN-A09',
        role='Owner', result_table='owner_tender_results')
    evidence = result['execution_evidence']
    result_payload = result['result']['payload']
    context = request.context
    source = settings.source_settings
    if (owner_settings.action_id != 'OWN-A09'
            or owner_request.context.execution_mode != 'offline_fixture'
            or owner_request.execution_path not in {None, 'deterministic'}
            or owner_settings.source_factory != 'integration.owner_role_contract_fixture_sources:build_sources'
            or owner_settings.source_version != 'configured-owner-fixture-sources.v1'
            or result_payload.get('choice') != 'publish_package'
            or result.get('request_sha256') != task_digest(original_request)
            or result.get('configuration') != {'host_id': owner_configuration.host_id,
                'version': owner_configuration.version,
                'sha256': task_digest(owner_configuration.model_dump(mode='json'))}
            or result.get('macro_execution') != 'not_performed'
            or history.identity.as_dict() != evidence['identity']
            or registration.source_identity.as_dict() != history.identity.as_dict()
            or registration.source_record_sha256 != evidence['record_sha256']
            or registration.source_result_sha256 != task_digest(result['result'])
            or registration.source_reading_sha256 != evidence['source_reading_sha256']
            or settings.action_id != 'CONTRACTOR-A02' or context.contract_ref.id != 'CONTRACTOR-A02'
            or settings.source_factory != 'integration.contractor_bid_fixture_sources:build_sources'
            or settings.source_version != 'configured-contractor-bid-fixture-sources.v1'
            or settings.received_tender_inputs is not None
            or request.execution_path not in {None, 'deterministic'}
            or context.execution_mode != 'offline_fixture' or history.request.context.execution_mode != 'offline_fixture'
            or history.request.execution_path not in {None, 'deterministic'}
            or owner_request.context.run_id != context.run_id or history.request.context.run_id != context.run_id
            or history.request.context.business_time != context.business_time
            or owner_request.context.business_time.clock_ref != context.business_time.clock_ref
            or owner_request.context.business_time.offset > context.business_time.offset
            or any(getattr(history.request.context, key) != getattr(owner_request.context, key)
                for key in ('actor_id', 'function_ref', 'contract_ref', 'scope'))
            or history.request.action_input != owner_request.action_input
            or history.source_settings.action_id != 'OWN-A09'
            or Path(history.source_settings.journal_path).resolve() != Path(owner_settings.source_settings['journal_path']).resolve()
            or Path(history.source_settings.journal_path).resolve() == Path(source['journal_path']).resolve()
            or any(getattr(history, key) != getattr(owner_settings, key)
                for key in ('macro_version', 'client_version', 'policy_version', 'model_version'))
            or registration.run_id != context.run_id or registration.current_state != 'received'
            or registration.sharing_authorized is not True
            or registration.recipient_organization_id != source['source_projection']['organization_id']
            or registration.recipient_actor_id != context.actor_id
            or registration.recipient_function_ref != context.function_ref
            or registration.recipient_authorization_refs != context.authorization_refs
            or registration.scope != context.scope
            or registration.package.ref.model_dump(mode='json') != request.action_input['package_ref']):
        raise ValueError('Received-tender configuration changes original publication lineage or current recipient')
    objects = source['source_projection']['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('Received-tender configuration needs one exact supplied native projection')
        return matches[0]
    package = registration.package
    native_evidence = EvidenceRecord.model_validate(original(registration.native_evidence_ref.model_dump(mode='json')))
    relation = {'schema_version': 'owner-tender-contractor-reception.v1',
        'source_identity': history.identity.as_dict(), 'source_record_sha256': evidence['record_sha256'],
        'source_result_sha256': registration.source_result_sha256,
        'source_reading_sha256': evidence['source_reading_sha256'],
        'package_ref': package.ref.model_dump(mode='json'), 'round_ref': package.round_ref.model_dump(mode='json'),
        'package_sha256': task_digest(package.model_dump(mode='json')),
        'recipient_organization_id': registration.recipient_organization_id}
    if (original(request.action_input['package_ref']) != package.model_dump(mode='json')
            or native_evidence.ref not in package.evidence_refs
            or native_evidence.source_kind != 'synthetic' or native_evidence.basis_kind != 'observed'
            or native_evidence.content_hash != task_digest(relation)):
        raise ValueError('Received-tender configuration lacks independently supplied observed native mapping evidence')
    combined_source = ContractorOwnerTenderFixtureSettings.model_validate({**deepcopy(source),
        'owner_history': history.model_dump(mode='json'), 'registration': registration.model_dump(mode='json')})
    configured = settings.model_dump(mode='json')
    configured.update(source_factory='integration.owner_tender_contractor_fixture_sources:build_sources',
        source_version='configured-contractor-owner-tender-fixture-sources.v1',
        source_settings=combined_source.model_dump(mode='json'),
        received_tender_inputs={'version': 'configured-owner-tender-reception.v1',
            'selections': {context.operation_id: {'source_task_sha256': history.identity.key,
                'native_evidence_ref': registration.native_evidence_ref.model_dump(mode='json')}}})
    configuration.settings = ContractorRoleContractSettings.model_validate(configured).model_dump(mode='json')
    return configuration


def _bind_bid_execution(row):
    """Import a supplied execution witness without manufacturing native intake."""
    from integration.contractor_bid_owner_fixture_sources import (
        ContractorBidHistorySettings, DeclaredContractorBidRegistration,
    )

    row = deepcopy(row)
    if not isinstance(row, dict) or 'execution' not in row:
        return row
    if set(row) != {'history', 'registration', 'execution'}:
        raise ValueError('Bid execution binding requires history, registration and execution')
    execution = row.pop('execution')
    if not isinstance(execution, dict) or set(execution) != {'request', 'configuration', 'result'}:
        raise ValueError('Bid execution requires its original request, configuration and result')
    original = RoleContractInvocation.model_validate(execution['request'])
    config = RoleContractHostConfiguration.model_validate(execution['configuration'])
    settings = ContractorRoleContractSettings.model_validate(config.settings)
    result = execution['result']
    _check_durable_result(result, {'request': original.model_dump(mode='json')},
        action_id='CONTRACTOR-A02', role='Contractor', result_table='contractor_bid_results',
        require_source_reading=False)
    evidence = result['execution_evidence']
    witness = evidence.get('bid_source_witness')
    witness_fields = {'schema_version', 'status', 'original_source_reading', 'source_reading_sha256',
        'source_snapshot', 'source_snapshot_sha256', 'source_record_sha256', 'source_audit_reading_sha256'}
    if (not isinstance(witness, dict) or set(witness) != witness_fields
            or witness['schema_version'] != 'contractor-bid-source-witness.v1'
            or witness['status'] != 'captured' or not witness['original_source_reading']):
        raise ValueError('Bid configuration needs the captured original execution source witness')
    history = _bind_history_metadata(row['history'], settings, result)
    if ('original_source_reading' in history
            and history['original_source_reading'] != witness['original_source_reading']):
        raise ValueError('Supplied bid history changes the execution source witness')
    history['original_source_reading'] = deepcopy(witness['original_source_reading'])
    history = ContractorBidHistorySettings.model_validate(history)
    registration = DeclaredContractorBidRegistration.model_validate(row['registration'])
    snapshot = witness['source_snapshot']
    if not isinstance(snapshot, dict) or set(snapshot) != {
            'schema_version', 'identity', 'action_input', 'context', 'snapshot_sha256'}:
        raise ValueError('Bid execution witness lacks its original invocation snapshot')
    accepted_factories = {
        'integration.contractor_bid_fixture_sources:build_sources': 'configured-contractor-bid-fixture-sources.v1',
        'integration.owner_tender_contractor_fixture_sources:build_sources': 'configured-contractor-owner-tender-fixture-sources.v1',
    }
    payload, audit = result['result']['payload'], evidence['saved_audit']
    if (settings.action_id != 'CONTRACTOR-A02'
            or accepted_factories.get(settings.source_factory) != settings.source_version
            or original.context.execution_mode != 'offline_fixture'
            or original.execution_path not in {None, 'deterministic'}
            or result.get('request_sha256') != task_digest(original.model_dump(mode='json'))
            or result.get('configuration') != {'host_id': config.host_id, 'version': config.version,
                'sha256': task_digest(config.model_dump(mode='json'))}
            or result.get('macro_execution') != 'not_performed' or payload.get('choice') != 'submit_bid'
            or history.identity.as_dict() != evidence['identity']
            or registration.source_identity.as_dict() != evidence['identity']
            or snapshot['schema_version'] != 'task-invocation.v1' or snapshot['identity'] != evidence['identity']
            or snapshot['context'] != original.context.model_dump(mode='json')
            or snapshot['action_input'] != original.action_input
            or snapshot['snapshot_sha256'] != task_digest({k: v for k, v in snapshot.items() if k != 'snapshot_sha256'})
            or witness['source_snapshot_sha256'] != task_digest(snapshot)
            or registration.source_snapshot_sha256 != witness['source_snapshot_sha256']
            or witness['source_record_sha256'] != evidence['record_sha256']
            or registration.source_record_sha256 != evidence['record_sha256']
            or registration.source_result_sha256 != task_digest(result['result'])
            or witness['source_reading_sha256'] != audit['reading']['sha256']
            or task_digest(witness['original_source_reading']) != audit['reading']['sha256']
            or witness['source_audit_reading_sha256'] != task_digest(audit['reading'])
            or registration.source_audit_reading_sha256 != witness['source_audit_reading_sha256']
            or registration.draft != payload['bid'] or registration.planned_tasks != payload['planned_tasks']
            or any(getattr(history, key) != getattr(settings, key)
                for key in ('macro_version', 'client_version', 'policy_version', 'model_version'))
            or Path(history.source_settings.journal_path).resolve() != Path(settings.source_settings['journal_path']).resolve()
            or settings.source_settings['source_projection']['organization_id'] != history.identity.organization_id
            or history.request.action_input != original.action_input
            or any(getattr(history.request.context, key) != getattr(original.context, key)
                for key in ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'execution_mode'))
            or history.request.context.business_time.clock_ref != original.context.business_time.clock_ref
            or history.request.context.business_time.offset < original.context.business_time.offset):
        raise ValueError('Bid intake substitutes original execution, source witness or independent registration')
    row['history'] = history.model_dump(mode='json')
    return row


def configure_received_bids(*, owner_request, owner_configuration, received_bids):
    """Select every declared A02 bid; original journals are checked at execution."""
    from integration.contractor_bid_owner_fixture_sources import OwnerContractorBidFixtureSettings
    from src.actions.contracts.owner_tender_objects import OwnerTenderBidView

    request = RoleContractInvocation.model_validate(owner_request).model_copy(deep=True)
    configuration = RoleContractHostConfiguration.model_validate(owner_configuration).model_copy(deep=True)
    settings = OwnerRoleContractSettings.model_validate(configuration.settings)
    context, action_input = request.context, request.action_input
    if (settings.action_id != 'OWN-A09' or context.contract_ref.id != 'OWN-A09'
            or context.execution_mode != 'offline_fixture' or request.execution_path not in {None, 'deterministic'}
            or settings.source_factory != 'integration.owner_role_contract_fixture_sources:build_sources'
            or settings.source_version != 'configured-owner-fixture-sources.v1'
            or settings.received_contractor_bid_inputs is not None
            or action_input.get('package_context', {}).get('kind') != 'published'):
        raise ValueError('Received bids require original offline Owner A09 published-package configuration')
    source = OwnerContractorBidFixtureSettings.model_validate({**deepcopy(settings.source_settings),
        'received_bids': [_bind_bid_execution(row) for row in received_bids]})
    objects = source.source_projection['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('Owner intake requires one exact supplied native bid or evidence projection')
        return matches[0]
    bids = [OwnerTenderBidView.model_validate(original(ref)) for ref in action_input['bid_refs']]
    expected = {bid.ref.key() for bid in bids if bid.author_action_id == 'CONTRACTOR-A02'}
    registrations = source.received_bids
    if (len({bid.ref.key() for bid in bids}) != len(bids)
            or len({row.registration.bid.ref.key() for row in registrations}) != len(registrations)
            or len({row.history.identity.key for row in registrations}) != len(registrations)
            or {row.registration.bid.ref.key() for row in registrations} != expected):
        raise ValueError('Owner intake selection must cover every A02 bid exactly once')
    selections = []
    for row in registrations:
        history, registration = row.history, row.registration
        bid = registration.bid
        evidence = EvidenceRecord.model_validate(original(registration.native_evidence_ref.model_dump(mode='json')))
        relation = {'schema_version': 'contractor-bid-owner-reception.v1',
            'source_identity': history.identity.as_dict(), 'source_record_sha256': registration.source_record_sha256,
            'source_result_sha256': registration.source_result_sha256,
            'source_snapshot_sha256': registration.source_snapshot_sha256,
            'source_audit_reading_sha256': registration.source_audit_reading_sha256,
            'bid_ref': bid.ref.model_dump(mode='json'), 'bid_sha256': task_digest(bid.model_dump(mode='json')),
            'recipient_organization_id': registration.recipient_organization_id}
        if (history.identity.as_dict() != registration.source_identity.as_dict()
                or history.identity.run_id != context.run_id or history.identity.action_id != 'CONTRACTOR-A02'
                or history.identity.role != 'Contractor' or history.identity.purpose != 'action'
                or history.request.context.run_id != context.run_id
                or history.request.context.business_time != context.business_time
                or history.request.context.execution_mode != 'offline_fixture'
                or history.request.execution_path not in {None, 'deterministic'}
                or history.request.context.contract_ref.id != 'CONTRACTOR-A02'
                or registration.run_id != context.run_id or registration.current_state != 'received'
                or registration.sharing_authorized is not True
                or registration.recipient_organization_id != source.source_projection['organization_id']
                or registration.recipient_actor_id != context.actor_id
                or registration.recipient_function_ref != context.function_ref
                or registration.recipient_authorization_refs != context.authorization_refs
                or registration.scope != context.scope
                or original(bid.ref.model_dump(mode='json')) != bid.model_dump(mode='json')
                or bid.package_ref.model_dump(mode='json') != action_input['package_context']['package_ref']
                or bid.round_ref.model_dump(mode='json') not in action_input['round_refs']
                or bid.bidder_ref.model_dump(mode='json') not in action_input['bidder_refs']
                or bid.bidder_organization_id != history.identity.organization_id
                or evidence.ref not in bid.evidence_refs or evidence.basis_kind != 'observed'
                or evidence.source_kind != 'synthetic' or evidence.content_hash != task_digest(relation)
                or Path(history.source_settings.journal_path).resolve() == Path(source.journal_path).resolve()):
            raise ValueError('Owner intake changes declared original task, native bid evidence or current recipient')
        selections.append({'source_task_sha256': history.identity.key,
            'bid_ref': bid.ref.model_dump(mode='json'),
            'native_evidence_ref': registration.native_evidence_ref.model_dump(mode='json')})
    configured = settings.model_dump(mode='json')
    configured.update(source_factory='integration.contractor_bid_owner_fixture_sources:build_sources',
        source_version='configured-owner-contractor-bid-fixture-sources.v1',
        source_settings=source.model_dump(mode='json'),
        received_contractor_bid_inputs={'version': 'configured-contractor-bid-reception.v1',
            'selections': {context.operation_id: {'bids': selections}}})
    configuration.settings = OwnerRoleContractSettings.model_validate(configured).model_dump(mode='json')
    return configuration


def configure_selected_evaluation(*, evaluation_request, evaluation_configuration, evaluation_result,
        owner_history, registration, award_request, award_configuration):
    """Bind an original evaluation to supplied independent offer/terms selection."""
    from integration.owner_tender_award_fixture_sources import (
        DeclaredOwnerTenderSelection, OwnerTenderAwardFixtureSettings,
    )

    original_request = RoleContractInvocation.model_validate(evaluation_request).model_copy(deep=True)
    original_config = RoleContractHostConfiguration.model_validate(evaluation_configuration).model_copy(deep=True)
    original_settings = OwnerRoleContractSettings.model_validate(original_config.settings)
    history = OwnerTenderHistorySettings.model_validate(
        _bind_history_metadata(owner_history, original_settings, evaluation_result)).model_copy(deep=True)
    selection = DeclaredOwnerTenderSelection.model_validate(registration).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(award_request).model_copy(deep=True)
    configuration = RoleContractHostConfiguration.model_validate(award_configuration).model_copy(deep=True)
    settings = OwnerRoleContractSettings.model_validate(configuration.settings)
    result = deepcopy(evaluation_result)
    _check_durable_result(result, {'request': original_request.model_dump(mode='json')}, action_id='OWN-A09',
        role='Owner', result_table='owner_tender_results')
    evidence, payload = result['execution_evidence'], result['result']['payload']
    bid, offer, terms, round_view = selection.selected_bid, selection.offer, selection.terms, selection.round
    context = request.context
    source_versions = {
        'integration.owner_role_contract_fixture_sources:build_sources': 'configured-owner-fixture-sources.v1',
        'integration.contractor_bid_owner_fixture_sources:build_sources': 'configured-owner-contractor-bid-fixture-sources.v1',
    }
    if (original_settings.action_id != 'OWN-A09'
            or original_settings.source_factory not in source_versions
            or original_settings.source_version != source_versions[original_settings.source_factory]
            or original_request.context.execution_mode != 'offline_fixture'
            or original_request.execution_path not in {None, 'deterministic'}
            or payload.get('choice') != 'evaluate' or original_request.action_input['package_context']['kind'] != 'published'
            or result.get('request_sha256') != task_digest(original_request.model_dump(mode='json'))
            or result.get('configuration') != {'host_id': original_config.host_id, 'version': original_config.version,
                'sha256': task_digest(original_config.model_dump(mode='json'))}
            or result.get('macro_execution') != 'not_performed'
            or history.identity.as_dict() != evidence['identity']
            or selection.source_identity.as_dict() != history.identity.as_dict()
            or selection.source_record_sha256 != evidence['record_sha256']
            or selection.source_result_sha256 != task_digest(result['result'])
            or selection.source_reading_sha256 != evidence['source_reading_sha256']
            or history.request.action_input != original_request.action_input
            or history.request.context.run_id != context.run_id or history.identity.run_id != context.run_id
            or history.request.context.business_time != context.business_time
            or history.request.context.execution_mode != 'offline_fixture'
            or history.request.execution_path not in {None, 'deterministic'}
            or any(getattr(history.request.context, key) != getattr(original_request.context, key)
                for key in ('actor_id', 'function_ref', 'contract_ref', 'scope'))
            or original_request.context.business_time.clock_ref != context.business_time.clock_ref
            or original_request.context.business_time.offset > context.business_time.offset
            or any(getattr(history, key) != getattr(original_settings, key)
                for key in ('macro_version', 'client_version', 'policy_version', 'model_version'))
            or Path(history.source_settings.journal_path).resolve() != Path(original_settings.source_settings['journal_path']).resolve()
            or settings.action_id != 'OWN-A10' or context.contract_ref.id != 'OWN-A10'
            or context.execution_mode != 'offline_fixture' or request.execution_path not in {None, 'deterministic'}
            or settings.source_factory != 'integration.owner_role_contract_fixture_sources:build_sources'
            or settings.source_version != 'configured-owner-fixture-sources.v1' or settings.tender_evaluation_inputs is not None
            or selection.run_id != context.run_id or selection.current_state != 'selected'
            or selection.selection_authorized is not True
            or selection.recipient_organization_id != history.identity.organization_id
            or selection.recipient_organization_id != settings.source_settings['source_projection']['organization_id']
            or selection.recipient_actor_id != context.actor_id or selection.recipient_function_ref != context.function_ref
            or selection.recipient_authorization_refs != context.authorization_refs or selection.scope != context.scope
            or original_request.context.scope != context.scope
            or bid.ref.model_dump(mode='json') not in original_request.action_input['bid_refs']
            or bid.ref.model_dump(mode='json') not in payload['ranked_bid_refs']
            or bid.ref.model_dump(mode='json') in payload['rejected_bid_refs']
            or bid.ref not in selection.shared_source_refs
            or bid.package_ref.model_dump(mode='json') != original_request.action_input['package_context']['package_ref']
            or bid.round_ref != round_view.ref or round_view.ref.model_dump(mode='json') not in original_request.action_input['round_refs']
            or offer.ref.model_dump(mode='json') != request.action_input['selected_offer_ref']
            or terms.ref.model_dump(mode='json') != request.action_input['final_terms_ref']
            or round_view.ref.model_dump(mode='json') != request.action_input['round_ref']):
        raise ValueError('Award configuration changes original evaluation, eligible selection or current recipient')
    objects = settings.source_settings['source_projection']['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('Award selection requires one supplied native offer, terms, round or evidence projection')
        return matches[0]
    native = EvidenceRecord.model_validate(original(selection.native_evidence_ref.model_dump(mode='json')))
    relation = {'schema_version': 'owner-tender-evaluation-award-selection.v1',
        'source_identity': history.identity.as_dict(), 'source_record_sha256': selection.source_record_sha256,
        'source_result_sha256': selection.source_result_sha256, 'source_reading_sha256': selection.source_reading_sha256,
        'selected_bid_ref': bid.ref.model_dump(mode='json'), 'selected_bid_sha256': task_digest(bid.model_dump(mode='json')),
        'offer_sha256': task_digest(offer.model_dump(mode='json')), 'terms_sha256': task_digest(terms.model_dump(mode='json')),
        'round_sha256': task_digest(round_view.model_dump(mode='json'))}
    if (any(original(value.ref.model_dump(mode='json')) != value.model_dump(mode='json')
            for value in (offer, terms, round_view))
            or native.ref not in offer.evidence_refs or native.basis_kind != 'observed'
            or native.source_kind != 'synthetic' or native.content_hash != task_digest(relation)):
        raise ValueError('Award configuration lacks supplied independent selected offer/terms and native evidence')
    source = OwnerTenderAwardFixtureSettings.model_validate({**deepcopy(settings.source_settings),
        'owner_history': history.model_dump(mode='json'), 'registration': selection.model_dump(mode='json')})
    configured = settings.model_dump(mode='json')
    configured.update(source_factory='integration.owner_tender_award_fixture_sources:build_sources',
        source_version='configured-owner-tender-award-fixture-sources.v1', source_settings=source.model_dump(mode='json'),
        tender_evaluation_inputs={'version': 'configured-owner-tender-selection.v1',
            'selections': {context.operation_id: {'source_task_sha256': history.identity.key,
                'selected_bid_ref': bid.ref.model_dump(mode='json'),
                'native_evidence_ref': selection.native_evidence_ref.model_dump(mode='json')}}})
    configuration.settings = OwnerRoleContractSettings.model_validate(configured).model_dump(mode='json')
    return configuration


def configure_received_award(*, owner_request, owner_configuration, owner_result,
        owner_history, registration, contractor_request, contractor_configuration):
    """Bind original Owner acceptance and supplied complete Contractor agreement."""
    from integration.owner_award_contractor_fixture_sources import (
        ContractorOwnerAwardFixtureSettings, DeclaredOwnerAwardReception, OwnerAwardHistorySettings,
    )
    from src.actions.contracts.contractor_formation_objects import contractor_agreement_digest

    original_request = RoleContractInvocation.model_validate(owner_request).model_copy(deep=True)
    original_config = RoleContractHostConfiguration.model_validate(owner_configuration).model_copy(deep=True)
    original_settings = OwnerRoleContractSettings.model_validate(original_config.settings)
    history = OwnerAwardHistorySettings.model_validate(
        _bind_history_metadata(owner_history, original_settings, owner_result)).model_copy(deep=True)
    reception = DeclaredOwnerAwardReception.model_validate(registration).model_copy(deep=True)
    request = RoleContractInvocation.model_validate(contractor_request).model_copy(deep=True)
    configuration = RoleContractHostConfiguration.model_validate(contractor_configuration).model_copy(deep=True)
    settings = ContractorRoleContractSettings.model_validate(configuration.settings)
    result = deepcopy(owner_result)
    _check_durable_result(result, {'request': original_request.model_dump(mode='json')}, action_id='OWN-A10',
        role='Owner', result_table='owner_award_results')
    evidence, payload = result['execution_evidence'], result['result']['payload']
    context = request.context
    source_versions = {
        'integration.owner_role_contract_fixture_sources:build_sources': 'configured-owner-fixture-sources.v1',
        'integration.owner_tender_award_fixture_sources:build_sources': 'configured-owner-tender-award-fixture-sources.v1',
    }
    if (original_settings.action_id != 'OWN-A10' or original_settings.source_factory not in source_versions
            or original_settings.source_version != source_versions[original_settings.source_factory]
            or original_request.context.execution_mode != 'offline_fixture'
            or original_request.execution_path not in {None, 'deterministic'} or payload.get('choice') != 'accept'
            or result.get('request_sha256') != task_digest(original_request.model_dump(mode='json'))
            or result.get('configuration') != {'host_id': original_config.host_id, 'version': original_config.version,
                'sha256': task_digest(original_config.model_dump(mode='json'))}
            or result.get('macro_execution') != 'not_performed'
            or history.identity.as_dict() != evidence['identity']
            or reception.source_identity.as_dict() != history.identity.as_dict()
            or reception.source_record_sha256 != evidence['record_sha256']
            or reception.source_result_sha256 != task_digest(result['result'])
            or reception.source_reading_sha256 != evidence['source_reading_sha256']
            or history.request.action_input != original_request.action_input
            or history.request.context.run_id != context.run_id or history.identity.run_id != context.run_id
            or history.request.context.business_time != context.business_time
            or history.request.context.execution_mode != 'offline_fixture'
            or history.request.execution_path not in {None, 'deterministic'}
            or any(getattr(history.request.context, key) != getattr(original_request.context, key)
                for key in ('actor_id', 'function_ref', 'contract_ref', 'scope'))
            or original_request.context.scope != context.scope
            or original_request.context.business_time.clock_ref != context.business_time.clock_ref
            or original_request.context.business_time.offset > context.business_time.offset
            or any(getattr(history, key) != getattr(original_settings, key)
                for key in ('macro_version', 'client_version', 'policy_version', 'model_version'))
            or Path(history.source_settings.journal_path).resolve() != Path(original_settings.source_settings['journal_path']).resolve()
            or Path(history.source_settings.journal_path).resolve() == Path(settings.source_settings['journal_path']).resolve()
            or settings.action_id != 'CONTRACTOR-A04' or context.contract_ref.id != 'CONTRACTOR-A04'
            or context.execution_mode != 'offline_fixture' or request.execution_path not in {None, 'deterministic'}
            or settings.source_factory != 'integration.contractor_formation_fixture_sources:build_sources'
            or settings.source_version != 'configured-contractor-formation-fixture-sources.v1'
            or settings.received_award_inputs is not None
            or reception.run_id != context.run_id or reception.current_state != 'received'
            or reception.sharing_authorized is not True
            or reception.recipient_organization_id == history.identity.organization_id
            or reception.recipient_organization_id != settings.source_settings['source_projection']['organization_id']
            or reception.recipient_actor_id != context.actor_id or reception.recipient_function_ref != context.function_ref
            or reception.recipient_authorization_refs != context.authorization_refs or reception.scope != context.scope
            or reception.owner_offer.ref.model_dump(mode='json') != payload['offer_ref']
            or reception.owner_terms.ref.model_dump(mode='json') != payload['terms_ref']
            or reception.owner_offer.ref.model_dump(mode='json') != original_request.action_input['selected_offer_ref']
            or reception.owner_terms.ref.model_dump(mode='json') != original_request.action_input['final_terms_ref']
            or reception.owner_offer.ref not in reception.shared_source_refs
            or reception.owner_terms.ref not in reception.shared_source_refs
            or reception.offer.ref.model_dump(mode='json') != request.action_input['offer_ref']
            or reception.terms.ref.model_dump(mode='json') != request.action_input['terms_ref']
            or reception.acceptance.ref.model_dump(mode='json') not in request.action_input['counterpart_acceptance_refs']
            or reception.acceptance.agreement_sha256 != contractor_agreement_digest(reception.terms)):
        raise ValueError('Formation configuration changes original award acceptance or independent agreement intake')
    objects = settings.source_settings['source_projection']['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('Award reception requires one supplied agreement, acceptance or evidence projection')
        return matches[0]
    native = EvidenceRecord.model_validate(original(reception.native_evidence_ref.model_dump(mode='json')))
    relation = {'schema_version': 'owner-award-contractor-reception.v1',
        'source_identity': history.identity.as_dict(), 'source_record_sha256': reception.source_record_sha256,
        'source_result_sha256': reception.source_result_sha256, 'source_reading_sha256': reception.source_reading_sha256,
        'owner_offer_sha256': task_digest(reception.owner_offer.model_dump(mode='json')),
        'owner_terms_sha256': task_digest(reception.owner_terms.model_dump(mode='json')),
        'contractor_offer_sha256': task_digest(reception.offer.model_dump(mode='json')),
        'contractor_terms_sha256': task_digest(reception.terms.model_dump(mode='json')),
        'acceptance_ref': reception.acceptance.ref.model_dump(mode='json'),
        'agreement_sha256': reception.acceptance.agreement_sha256}
    if (any(original(value.ref.model_dump(mode='json')) != value.model_dump(mode='json')
            for value in (reception.offer, reception.terms, reception.acceptance))
            or native.ref not in reception.acceptance.evidence_refs or native.basis_kind != 'observed'
            or native.source_kind != 'synthetic' or native.content_hash != task_digest(relation)):
        raise ValueError('Formation configuration lacks independent complete native agreement and observed reception evidence')
    source = ContractorOwnerAwardFixtureSettings.model_validate({**deepcopy(settings.source_settings),
        'owner_history': history.model_dump(mode='json'), 'registration': reception.model_dump(mode='json')})
    configured = settings.model_dump(mode='json')
    configured.update(source_factory='integration.owner_award_contractor_fixture_sources:build_sources',
        source_version='configured-contractor-owner-award-fixture-sources.v1', source_settings=source.model_dump(mode='json'),
        received_award_inputs={'version': 'configured-owner-award-reception.v1',
            'selections': {context.operation_id: {'source_task_sha256': history.identity.key,
                'acceptance_ref': reception.acceptance.ref.model_dump(mode='json'),
                'native_evidence_ref': reception.native_evidence_ref.model_dump(mode='json')}}})
    configuration.settings = ContractorRoleContractSettings.model_validate(configured).model_dump(mode='json')
    return configuration


def _read_pinned_json(binding, pins):
    """Read one explicitly supplied source; create no registration facts."""
    root = Path(__file__).resolve().parents[1]
    if not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}:
        raise ValueError('Each source file requires its path and raw file SHA')
    relative = Path(binding['path'])
    path = (root / relative).resolve()
    if (relative.is_absolute() or not any(path.is_relative_to(root / directory)
            for directory in ('integration/examples', 'output/integration'))):
        raise ValueError('Source files must stay in repository examples or integration output')
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != binding['file_sha256'] or path in pins and pins[path] != sha:
        raise ValueError('Source file differs from its declared original SHA')
    _, value = parse_input_json(raw)
    pins[path] = sha
    return value


def _read_execution_files(declared, pins):
    """Read pinned source artifacts, retaining their raw file hashes."""
    if not isinstance(declared, dict) or set(declared) != {'request', 'configuration', 'result'}:
        raise ValueError('Reception needs three explicitly pinned original execution files')
    return {label: _read_pinned_json(binding, pins) for label, binding in declared.items()}


def _bind_file_field(record, field, pins):
    file_field = field + '_file'
    if file_field in record:
        if field in record:
            raise ValueError('Reception cannot mix file-backed and inline ' + field)
        record[field] = _read_pinned_json(record.pop(file_field), pins)


def _read_bid_execution_files(received_bids):
    """Load explicitly pinned upstream artifacts for an unexecuted continuation."""
    rows, pins = deepcopy(received_bids), {}
    if not isinstance(rows, list):
        raise ValueError('Bid reception requires a list of declared sources')
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in ('registration', 'history'):
            _bind_file_field(row, field, pins)
        if 'execution_files' not in row:
            continue
        if set(row) != {'history', 'registration', 'execution_files'}:
            raise ValueError('File-backed bid intake cannot mix inline execution or extra bindings')
        row['execution'] = _read_execution_files(row.pop('execution_files'), pins)
    return rows, pins


def prepare_reception_files(*, input_path, output_directory, expected_choice=None):
    """Capture one explicit configuration bundle and save a new, unexecuted binding."""
    path = Path(input_path).resolve()
    raw = path.read_bytes()
    _, bundle = parse_input_json(raw)
    bid_intake = bundle.get('schema_version') == 'contractor-bid-reception-configuration.v1'
    if bid_intake:
        fields = {'owner_request', 'owner_configuration', 'received_bids'}
        configure, request_field = configure_received_bids, 'owner_request'
        factory = 'integration.owner_role_contract_host:build_role_host'
    elif bundle.get('schema_version') == 'owner-tender-award-configuration.v1':
        fields = {'evaluation_request', 'evaluation_configuration', 'evaluation_result', 'owner_history',
            'registration', 'award_request', 'award_configuration'}
        configure, request_field = configure_selected_evaluation, 'award_request'
        factory = 'integration.owner_role_contract_host:build_role_host'
    elif bundle.get('schema_version') in {'owner-tender-reception-configuration.v1', 'owner-award-reception-configuration.v1'}:
        fields = {'owner_request', 'owner_configuration', 'owner_result', 'owner_history',
            'registration', 'contractor_request', 'contractor_configuration'}
        configure = (configure_received_award if bundle['schema_version'] == 'owner-award-reception-configuration.v1'
            else configure_received_tender)
        request_field = 'contractor_request'
        factory = 'integration.contractor_role_contract_host:build_role_host'
    else:
        raise ValueError('Unknown offline reception configuration schema')
    upstream_files = {}
    if not bid_intake:
        for field in ('registration', 'owner_history'):
            _bind_file_field(bundle, field, upstream_files)
    source_prefix = {
        'owner-tender-reception-configuration.v1': 'owner',
        'owner-tender-award-configuration.v1': 'evaluation',
        'owner-award-reception-configuration.v1': 'owner',
    }.get(bundle['schema_version'])
    if source_prefix is not None and 'upstream_execution_files' in bundle:
        source_fields = {source_prefix + '_' + label for label in ('request', 'configuration', 'result')}
        if set(bundle) != (fields - source_fields) | {'schema_version', 'upstream_execution_files'}:
            raise ValueError('File-backed reception cannot mix inline execution or extra bindings')
        execution = _read_execution_files(bundle.pop('upstream_execution_files'), upstream_files)
        bundle.update({source_prefix + '_' + label: value for label, value in execution.items()})
    if set(bundle) != fields | {'schema_version'}:
        raise ValueError('Reception configuration input changes its declared bindings')
    if bid_intake:
        bundle['received_bids'], upstream_files = _read_bid_execution_files(bundle['received_bids'])
    configuration = configure(**{key: bundle[key] for key in fields})
    request = RoleContractInvocation.model_validate(bundle[request_field]).model_dump(mode='json')
    digest = hashlib.sha256(raw).hexdigest()
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Tender configuration input changed during preparation')
    for source, sha in upstream_files.items():
        if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
            raise ValueError('Original execution artifact changed during configuration preparation')
    directory = Path(output_directory)
    root = Path(__file__).resolve().parents[1]
    result_schema = bundle['schema_version'].replace('-configuration.v1', '-configuration-result.v1')
    case_id = next(key for key, route in _CONFIGURED_CASES.items() if route['preparation_schema'] == result_schema)
    if expected_choice is not None and (expected_choice not in _CONFIGURED_CASES[case_id]['choices']
            or not directory.resolve().is_relative_to(root / 'output/integration')):
        raise ValueError('V2 case generation requires a valid explicit branch and repository integration output directory')
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / 'invocation.json', request)
    atomic_json(directory / 'configuration.json', configuration.model_dump(mode='json'))
    summary = {'schema_version': result_schema,
        'status': 'configuration_prepared_history_read_pending', 'origin': 'synthetic',
        'input_path': str(path), 'input_file_sha256': digest,
        'invocation_sha256': task_digest(request),
        'configuration_sha256': task_digest(configuration.model_dump(mode='json')),
        'factory': factory,
        'limitations': ['No journal opened or action executed; original source journal/current authority and independent reception remain subject to the source factory and handoff.']}
    if upstream_files:
        summary['source_execution_files'] = [{'path': source.relative_to(root).as_posix(), 'file_sha256': sha}
            for source, sha in upstream_files.items()]
    atomic_json(directory / 'summary.json', summary)
    if expected_choice is not None:
        step = {'action_id': request['context']['contract_ref']['id'],
            'operation_id': request['context']['operation_id'], 'expected_kind': 'completed',
            'expected_choice': expected_choice, 'host_factory': factory}
        for label, name in (('invocation', 'invocation.json'), ('configuration', 'configuration.json'),
                ('preparation', 'summary.json')):
            artifact = directory / name
            step[label + '_path'] = artifact.resolve().relative_to(root).as_posix()
            step[label + '_file_sha256'] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        atomic_json(directory / 'v2-case.json', {'schema_version': 'lifecycle-input-case.v1',
            'scenario_id': 'V2', 'case_id': case_id, 'origin': 'synthetic',
            'run_id': request['context']['run_id'], 'steps': [step],
            'remaining_requirements': ['Remaining original same-run lifecycle decisions and complete V2/PLAN acceptance.']})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--expected-choice', help='Also save a V2 continuation case for this explicit branch')
    args = parser.parse_args()
    prepare_reception_files(input_path=args.input, output_directory=args.output, expected_choice=args.expected_choice)


if __name__ == '__main__':
    main()
