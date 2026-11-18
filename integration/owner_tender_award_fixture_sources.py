"""Explicit offline award selection backed by an existing Owner evaluation journal."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings, build_sources as build_owner_sources
from integration.owner_tender_contractor_fixture_sources import OwnerTenderHistorySettings, _OwnerTenderHistoryBinding
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimeWindow, ref_type
from src.actions.contracts.owner_award_objects import OwnerAwardOfferView, OwnerAwardRoundView, OwnerAwardTermsView
from src.actions.contracts.owner_tender_objects import OwnerTenderBidView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredOwnerTenderSelection(StrictRecord):
    """Independent selected offer/terms; rank membership does not grant acceptance."""
    schema_version: Literal['owner-tender-award-selection.v1']
    selection_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_reading_sha256: Digest
    selected_bid: OwnerTenderBidView
    offer: OwnerAwardOfferView
    terms: OwnerAwardTermsView
    round: OwnerAwardRoundView
    native_evidence_ref: ref_type('Evidence')
    recipient_organization_id: TextId
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    scope: ScopeRef
    effective_window: TimeWindow
    selection_authorized: bool
    shared_source_refs: Annotated[list[Reference], Field(min_length=1)]
    equal_score_treatment: Literal['no_strict_preference']
    mapping_kind: Literal['original_bid', 'independent_negotiation']
    selection_reason: TextId
    current_state: Literal['selected', 'withdrawn', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class OwnerTenderAwardFixtureSettings(OwnerFixtureSourceSettings):
    owner_history: OwnerTenderHistorySettings
    registration: DeclaredOwnerTenderSelection


class _EvaluationSelection(_OwnerTenderHistoryBinding):
    VERSION = 'configured-owner-tender-award-fixture-sources.v1'
    EXPECTED_CHOICE = 'evaluate'
    AUTHORIZATION_FLAG = 'selection_authorized'

    def validate_selection(self, saved, bid, offer, terms, round_view, evidence, context):
        self._check(context)
        declaration = self.settings.registration
        original = self.read_owner_tender(context=context,
            source_task_sha256=self.settings.owner_history.identity.key)
        source_rows = {Reference.model_validate(row['ref']).key(): row['projection'] for row in original.source_reading}
        if (saved != original or declaration.source_identity.as_dict() != saved.identity.as_dict()
                or declaration.run_id != context.run_id or declaration.current_state != 'selected'
                or declaration.selection_authorized is not True
                or declaration.recipient_organization_id != self.settings.source_projection['organization_id']
                or saved.identity.organization_id != declaration.recipient_organization_id
                or declaration.recipient_actor_id != context.actor_id
                or declaration.recipient_function_ref != context.function_ref
                or declaration.recipient_authorization_refs != context.authorization_refs
                or declaration.scope != context.scope or offer.scope != declaration.scope or terms.scope != declaration.scope
                or bid != declaration.selected_bid or offer != declaration.offer or terms != declaration.terms
                or round_view != declaration.round or source_rows.get(bid.ref.key()) != bid.model_dump(mode='json')
                or bid.ref not in saved.result.payload.ranked_bid_refs or bid.ref in saved.result.payload.rejected_bid_refs
                or bid.ref not in declaration.shared_source_refs
                or declaration.native_evidence_ref != evidence.ref or evidence.ref not in offer.evidence_refs
                or evidence.basis_kind != 'observed' or evidence.source_kind != 'synthetic'
                or declaration.equal_score_treatment != 'no_strict_preference'
                or not declaration.effective_window.contains(context.business_time)):
            raise TaskConflict('Independent award selection changes original bid, native offer/terms, tie treatment or authority')
        if declaration.mapping_kind == 'original_bid' and (bid.total_price.state != 'known'
                or terms.total_price.value != bid.total_price.value.value
                or terms.total_price.currency != bid.total_price.value.currency):
            raise TaskConflict('Unnegotiated award selection changes the original offered price')
        # Independent negotiated terms are checked against the supplied current
        # native view above. Consent, conditions and budget remain A10 gates.
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.recipient.evidence()), 'schema_version': self.VERSION,
            'tender_selection': {'source_task_sha256': self.settings.owner_history.identity.key,
                'source_record_sha256': self.settings.registration.source_record_sha256,
                'selection_sha256': task_digest(self.settings.registration.model_dump(mode='json')),
                'configuration_sha256': self._settings_sha256,
                'limitations': ['Independent synthetic selection; no acceptance, contract formation or formal receipt.']}}


def build_sources(*, request, output_directory, offline, settings):
    """Read original evaluation under Owner authority; generate no offer or decision."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = OwnerTenderAwardFixtureSettings.model_validate(settings).model_copy(deep=True)
    history, declaration = settings.owner_history, settings.registration
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or request.context.contract_ref.id != 'OWN-A10' or settings.action_id != 'OWN-A10'
            or history.request.context.contract_ref.id != 'OWN-A09' or history.source_settings.action_id != 'OWN-A09'
            or history.request.context.execution_mode != 'offline_fixture'
            or history.request.execution_path not in {None, 'deterministic'}
            or history.identity.role != 'Owner' or history.identity.action_id != 'OWN-A09' or history.identity.purpose != 'action'
            or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
            or history.request.context.business_time != request.context.business_time
            or history.identity.organization_id != settings.source_projection['organization_id']
            or declaration.run_id != request.context.run_id or declaration.current_state != 'selected'
            or declaration.selection_authorized is not True
            or declaration.source_identity.as_dict() != history.identity.as_dict()
            or declaration.recipient_organization_id != history.identity.organization_id
            or declaration.offer.ref.model_dump(mode='json') != request.action_input['selected_offer_ref']
            or declaration.terms.ref.model_dump(mode='json') != request.action_input['final_terms_ref']
            or declaration.round.ref.model_dump(mode='json') != request.action_input['round_ref']
            or not Path(history.source_settings.journal_path).is_file()):
        raise ValueError('Award fixture requires existing original same-owner evaluation and independent current selection')
    award = evaluation = None
    try:
        award = build_owner_sources(request=request, output_directory=output_directory, offline=offline,
            settings=settings.model_dump(mode='json', exclude={'owner_history', 'registration'}))
        evaluation = build_owner_sources(request=history.request, output_directory=output_directory,
            offline=offline, settings=history.source_settings)
        binding = _EvaluationSelection(request, settings, award, evaluation)
        return replace(award, version=binding.VERSION, read_tender_evaluation=binding.read_owner_tender,
            validate_tender_award_selection=binding.validate_selection, evidence=binding.evidence, close=binding.close)
    except Exception:
        try:
            if evaluation is not None:
                evaluation.close()
        finally:
            if award is not None:
                award.close()
        raise
