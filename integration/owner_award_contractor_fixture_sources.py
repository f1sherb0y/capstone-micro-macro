"""Offline Contractor formation intake from an existing original Owner award journal."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.contractor_formation_fixture_sources import (
    ContractorFormationFixtureSettings, build_sources as build_formation_sources,
)
from integration.owner_award_actions import OwnerAwardActionAssembler
from integration.owner_award_results import OwnerAwardResultWorker
from integration.owner_role_contract_fixture_sources import build_sources as build_owner_sources
from integration.owner_tender_contractor_fixture_sources import OwnerTenderHistorySettings, _OwnerTenderHistoryBinding
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimeWindow, ref_type
from src.actions.contracts.contractor_formation_objects import (
    ContractorFormationAcceptanceView, ContractorFormationOfferView, ContractorFormationTermsView,
    contractor_agreement_digest,
)
from src.actions.contracts.owner_award_objects import OwnerAwardOfferView, OwnerAwardTermsView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class OwnerAwardHistorySettings(OwnerTenderHistorySettings):
    """Original A10 task and current independent Owner read configuration."""


class DeclaredOwnerAwardReception(StrictRecord):
    schema_version: Literal['owner-award-reception.v1']
    reception_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    owner_offer: OwnerAwardOfferView
    owner_terms: OwnerAwardTermsView
    offer: ContractorFormationOfferView
    terms: ContractorFormationTermsView
    acceptance: ContractorFormationAcceptanceView
    native_evidence_ref: ref_type('Evidence')
    recipient_organization_id: TextId
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    scope: ScopeRef
    effective_window: TimeWindow
    sharing_authorized: bool
    shared_source_refs: Annotated[list[Reference], Field(min_length=2)]
    current_state: Literal['received', 'withdrawn', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class ContractorOwnerAwardFixtureSettings(ContractorFormationFixtureSettings):
    owner_history: OwnerAwardHistorySettings
    registration: DeclaredOwnerAwardReception


class _AwardReception(_OwnerTenderHistoryBinding):
    VERSION = 'configured-contractor-owner-award-fixture-sources.v1'
    ACTION_ID = 'OWN-A10'
    ASSEMBLER = OwnerAwardActionAssembler
    WORKER = OwnerAwardResultWorker
    EXPECTED_CHOICE = 'accept'

    def validate_reception(self, saved, offer, terms, acceptance, evidence, context):
        self._check(context)
        declaration = self.settings.registration
        original = self.read_owner_tender(context=context,
            source_task_sha256=self.settings.owner_history.identity.key)
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in original.source_reading}
        if (saved != original or declaration.source_identity.as_dict() != saved.identity.as_dict()
                or declaration.run_id != context.run_id or declaration.current_state != 'received'
                or declaration.sharing_authorized is not True
                or declaration.recipient_organization_id != self.settings.source_projection['organization_id']
                or declaration.recipient_actor_id != context.actor_id
                or declaration.recipient_function_ref != context.function_ref
                or declaration.recipient_authorization_refs != context.authorization_refs
                or declaration.scope != context.scope or offer.scope != declaration.scope or terms.scope != declaration.scope
                or declaration.offer != offer or declaration.terms != terms or declaration.acceptance != acceptance
                or declaration.owner_offer.ref != saved.result.payload.offer_ref
                or declaration.owner_terms.ref != saved.result.payload.terms_ref
                or declaration.owner_offer.ref not in declaration.shared_source_refs
                or declaration.owner_terms.ref not in declaration.shared_source_refs
                or originals.get(declaration.owner_offer.ref.key()) != declaration.owner_offer.model_dump(mode='json')
                or originals.get(declaration.owner_terms.ref.key()) != declaration.owner_terms.model_dump(mode='json')
                or acceptance.agreement_sha256 != contractor_agreement_digest(terms)
                or declaration.native_evidence_ref != evidence.ref or evidence.ref not in acceptance.evidence_refs
                or evidence.basis_kind != 'observed' or evidence.source_kind != 'synthetic'
                or not declaration.effective_window.contains(context.business_time)):
            raise TaskConflict('Independent award reception changes original Owner decision or complete native agreement mapping')
        # Full native terms equality includes programme, deliverables, payments,
        # exclusions and amendments. Common Owner terms are also checked by the
        # original handoff; A04 retains its independent acceptance/capacity gates.
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.recipient.evidence()), 'schema_version': self.VERSION,
            'owner_award': {'source_task_sha256': self.settings.owner_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'reception_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Independent synthetic reception; no signature, contract formation, resource effect or formal receipt.']}}


def build_sources(*, request, output_directory, offline, settings):
    """Bind supplied agreement and original accepted award; create no acceptance."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = ContractorOwnerAwardFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, declaration = settings.owner_history, settings.registration
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or request.context.contract_ref.id != 'CONTRACTOR-A04' or settings.action_id != 'CONTRACTOR-A04'
            or history.request.context.contract_ref.id != 'OWN-A10' or history.source_settings.action_id != 'OWN-A10'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.request.execution_path not in {None, 'deterministic'}
            or history.identity.role != 'Owner' or history.identity.action_id != 'OWN-A10' or history.identity.purpose != 'action'
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or history.identity.organization_id == settings.source_projection['organization_id']
            or declaration.run_id != request.context.run_id or declaration.current_state != 'received'
            or declaration.sharing_authorized is not True or declaration.source_identity.as_dict() != history.identity.as_dict()
            or declaration.recipient_organization_id != settings.source_projection['organization_id']
            or declaration.offer.ref.model_dump(mode='json') != request.action_input['offer_ref']
            or declaration.terms.ref.model_dump(mode='json') != request.action_input['terms_ref']
            or declaration.acceptance.ref.model_dump(mode='json') not in request.action_input['counterpart_acceptance_refs']
            or Path(history.source_settings.journal_path).resolve() == Path(settings.journal_path).resolve()
            or not Path(history.source_settings.journal_path).is_file()):
        raise ValueError('Award reception requires existing independent Owner A10 acceptance and explicit same-run A04 intake')
    formation = owner = None
    try:
        formation = build_formation_sources(request=request, output_directory=output_directory, offline=offline,
            settings=settings.model_dump(mode='json', exclude={'owner_history', 'registration'}))
        owner = build_owner_sources(request=history.request, output_directory=output_directory,
            offline=offline, settings=history.source_settings)
        binding = _AwardReception(request, settings, formation, owner)
        return replace(formation, version=binding.VERSION, read_owner_award=binding.read_owner_tender,
            validate_received_award=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if owner is not None:
                owner.close()
        finally:
            if formation is not None:
                formation.close()
        raise
