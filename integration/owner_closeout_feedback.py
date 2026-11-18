"""Actual closeout registration feedback with complete residual-duty source coverage."""
from copy import deepcopy

from integration.module_host import module_factory_descriptor
from integration.owner_closeout_results import OwnerCloseoutResultWorker
from integration.owner_submission_feedback import OwnerSubmissionFeedback
from integration.owner_submission_host import OwnerSubmissionHost
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_closeout_objects import (
    OwnerCloseoutContractView, OwnerCloseoutDecisionView, OwnerCloseoutProfileView, OwnerCloseoutStateView,
)
from src.coordination.tasks import TaskConflict, task_digest


class OwnerCloseoutSubmissionFeedback(OwnerSubmissionFeedback):
    """Retain the original inbox/dedup/read protocol for actual Owner A12 events.

    validate_native_relation receives the same complete arguments as the existing
    Owner feedback validator. It independently authenticates native registration,
    actual scoped acceptance/settlement/retention and any lawful residual-duty
    discharge or version mapping. Transport acceptance never proves those facts.
    Construction/recording creates no acceptance, successor, cash or cleared debt.
    Current A12 feedback can feed the existing OwnerFeedbackInputAssembler.
    """
    VERSION = 'owner-closeout-submission-feedback.v2'

    def __init__(self, *, host, inbox, version, validate_native_relation, validate_read):
        if (not isinstance(host, OwnerSubmissionHost) or not callable(validate_native_relation)
                or not isinstance(host.workers.get('OWN-A12'), OwnerCloseoutResultWorker)):
            raise ValueError('Closeout feedback requires original Owner A12 worker and independent native relation validation')
        self.validate_native_relation = validate_native_relation
        self._original_native_relation = validate_native_relation
        self._original_components = (host, inbox, validate_read)
        super().__init__(host=host, inbox=inbox, version=version,
            validate_relation=self._validate_closeout_relation, validate_read=validate_read)

    def _configuration(self):
        return {**super()._configuration(), 'closeout_native_relation': module_factory_descriptor(
            self.validate_native_relation, 'validate_native_relation'),
            'closeout_validation': module_factory_descriptor(type(self)._validate_closeout_relation, self.VERSION)}

    def _check(self):
        if (self.validate_native_relation is not self._original_native_relation
                or any(current is not original for current, original in zip(
                    (self.host, self.inbox, self.validate_read), self._original_components))
                or getattr(self.validate_relation, '__self__', None) is not self
                or getattr(self.validate_relation, '__func__', None) is not type(self)._validate_closeout_relation):
            raise TaskConflict('Closeout feedback replaced original native validation boundary')
        super()._check()

    def _validate_closeout_relation(self, *, identity, receipt, snapshot, observation, sources, evidence, context, reading):
        if (identity.action_id != 'OWN-A12' or observation.target_action_id != 'OWN-A12'
                or observation.native_evidence_ref in observation.source_refs):
            raise TaskConflict('Closeout feedback requires original A12 submission and a current A12 source reading')
        record = self.host.workers['OWN-A12'].get_record(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or record['record_sha256'] != receipt['record_sha256']
                or receipt['identity'] != identity.as_dict()
                or receipt['receipt']['disposition'] != 'accepted'):
            raise TaskConflict('Actual closeout feedback lacks original completed action and accepted native registration request')
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in record['source_reading']}
        original_context = ActionContext.model_validate(snapshot['context'])
        anchor = originals[original_context.scope.ref.key()]
        original_state = OwnerCloseoutStateView.model_validate(originals[Reference.model_validate(anchor['closeout_state_ref']).key()])
        profile = OwnerCloseoutProfileView.model_validate(originals[original_state.decision_profile_ref.key()])
        projections = {Reference.model_validate(row['ref']).key(): row['projection'] for row in sources}
        decisions = [OwnerCloseoutDecisionView.model_validate(row['projection']) for row in sources
            if row['ref']['kind'] == 'OwnerCloseoutDecision'
            and row['projection'].get('profile_ref') == profile.ref.model_dump(mode='json')]
        if len(decisions) != 1:
            raise TaskConflict('Closeout native feedback must identify one original profile-bound decision registration')
        decision = decisions[0]
        if (decision.profile_sha256 != task_digest(profile.model_dump(mode='json'))
                or decision.choice != record['result']['payload']['choice'] or decision.choice != profile.choice
                or decision.business_key != profile.business_key or decision.contract_ref != profile.contract_ref
                or decision.author_organization_id != identity.organization_id
                or decision.author_actor_id != original_context.actor_id or decision.author_function_ref != original_context.function_ref
                or decision.author_authority_ref not in original_context.authorization_refs
                or decision.author_action_id != 'OWN-A12' or decision.status not in {'accepted', 'rejected'}
                or not decision.effective_window.contains(decision.authored_at)
                or decision.authored_at.clock_ref != original_context.business_time.clock_ref
                or not original_context.business_time.offset <= decision.authored_at.offset <= observation.observed_at.offset
                or decision.available_at.clock_ref != context.business_time.clock_ref
                or not decision.authored_at.offset <= decision.available_at.offset <= observation.available_at.offset):
            raise TaskConflict('Native closeout registration changes original profile, branch, business identity, author or final outcome')
        if decision.state_ref.key() not in projections or decision.contract_ref.key() not in projections:
            raise TaskConflict('Closeout feedback omits actual current state or original selected contract')
        state = OwnerCloseoutStateView.model_validate(projections[decision.state_ref.key()])
        contract = OwnerCloseoutContractView.model_validate(projections[decision.contract_ref.key()])
        if (state.organization_id != identity.organization_id or contract.owner_id != identity.organization_id
                or (state.ref.kind, state.ref.id) != (original_state.ref.kind, original_state.ref.id)
                or state.coverage != 'complete' or contract.coverage != 'complete'
                or state.as_of != observation.observed_at or contract.as_of != observation.observed_at
                or state.available_at.clock_ref != context.business_time.clock_ref
                or contract.available_at.clock_ref != context.business_time.clock_ref
                or state.available_at.offset > context.business_time.offset
                or contract.available_at.offset > context.business_time.offset
                or not state.effective_window.contains(context.business_time)
                or not contract.effective_window.contains(context.business_time)
                or decision.ref not in state.decision_history_refs or contract.ref not in state.contract_refs
                or decision.scope != original_context.scope or state.scope != context.scope
                or observation.native_evidence_ref not in decision.evidence_refs):
            raise TaskConflict('Actual closeout feedback changes original state/owner or lacks complete current native history')
        required = [*state.contract_refs, *state.handover_refs, *state.verification_refs, *state.permit_refs,
            *state.defect_refs, *state.settlement_refs, *state.obligation_refs, *state.responsibility_refs,
            *state.decision_history_refs, *contract.handover_refs, *contract.settlement_refs,
            *contract.component_refs, *contract.issue_refs, *contract.defect_refs, *contract.responsibility_refs]
        if any(ref.key() not in projections for ref in required):
            raise TaskConflict('Closeout feedback omits a current check, permit, defect, settlement, liability or continuing responsibility')
        physical_sources = {(Reference.model_validate(row['ref']).kind, Reference.model_validate(row['ref']).id) for row in sources}
        # Original liabilities need explicit current disposition sources even if
        # the application's new state no longer lists them. Actual release and
        # new-version relationships are separately authenticated below.
        original_contract = OwnerCloseoutContractView.model_validate(originals[profile.contract_ref.key()])
        retained = [*original_state.obligation_refs, *original_state.responsibility_refs,
            *original_state.defect_refs, *original_contract.component_refs, *original_contract.issue_refs,
            *original_contract.defect_refs, *original_contract.responsibility_refs]
        if any((ref.kind, ref.id) not in physical_sources for ref in retained):
            raise TaskConflict('Closeout feedback silently drops an original unpaid obligation, defect or residual responsibility')
        native = {'schema_version': 'owner-closeout-native-feedback.v1', 'native_event_id': observation.native_event_id,
            'source_identity': identity.as_dict(), 'source_record_sha256': record['record_sha256'],
            'source_result_sha256': record['result_sha256'], 'source_reading_sha256': record['source_reading_sha256'],
            'original_receipt_sha256': receipt['receipt_sha256'],
            'original_result': deepcopy(record['result']), 'original_profile': profile.model_dump(mode='json'),
            'observed_at': observation.observed_at.model_dump(mode='json'),
            'available_at': observation.available_at.model_dump(mode='json'), 'sources': deepcopy(sources), 'coverage': 'complete'}
        if observation.native_source_sha256 != task_digest(native):
            raise TaskConflict('Closeout native evidence does not bind the complete original decision and residual-duty source observation')
        reading.recheck()
        return self.validate_native_relation(identity=identity, receipt=deepcopy(receipt), snapshot=deepcopy(snapshot),
            observation=observation.model_copy(deep=True), sources=deepcopy(sources), evidence=deepcopy(evidence),
            context=context.model_copy(deep=True), reading=reading) is True
