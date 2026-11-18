"""Actual A13 execution feedback preserving independently observed residual duties."""
from copy import deepcopy

from integration.module_host import module_factory_descriptor
from integration.owner_continuation_results import OwnerContinuationResultWorker
from integration.owner_submission_feedback import OwnerSubmissionFeedback
from integration.owner_submission_host import OwnerSubmissionHost
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_continuation_objects import (
    OwnerContinuationCommitmentView, OwnerContinuationContractView, OwnerContinuationDutyView,
    OwnerContinuationExecutionView, OwnerContinuationProfileView, OwnerContinuationStateView,
)
from src.coordination.tasks import TaskConflict, task_digest


class OwnerContinuationSubmissionFeedback(OwnerSubmissionFeedback):
    """Use the original inbox with an independent A13 record namespace.

    validate_native_relation authenticates the original request/authority,
    actual execution outcome, current complete ledger and each retained,
    released or transferred duty/resource relation. Its arguments are the
    existing Owner feedback validator arguments. Neither a succeeded event
    nor an accepted transport receipt implies that all debt or duties ended.
    Unknown/pending executions remain unconfirmed. No successor is created.
    """
    VERSION = 'owner-continuation-submission-feedback.v2'
    METADATA_PREFIX = 'owner_continuation_submission_feedback:'
    EVENT_PREFIX = 'owner-continuation-feedback:'

    def __init__(self, *, host, inbox, version, validate_native_relation, validate_read):
        if (not isinstance(host, OwnerSubmissionHost) or not callable(validate_native_relation)
                or not isinstance(host.workers.get('OWN-A13'), OwnerContinuationResultWorker)):
            raise ValueError('Continuation feedback requires original A13 worker and independent native validation')
        self.validate_native_relation = validate_native_relation
        self._original_native_relation = validate_native_relation
        self._original_components = (host, inbox, validate_read)
        super().__init__(host=host, inbox=inbox, version=version,
            validate_relation=self._validate_continuation_relation, validate_read=validate_read)

    def _configuration(self):
        return {**super()._configuration(), 'continuation_native_relation': module_factory_descriptor(
            self.validate_native_relation, 'validate_native_relation'),
            'continuation_validation': module_factory_descriptor(type(self)._validate_continuation_relation, self.VERSION),
            'metadata_prefix': self.METADATA_PREFIX, 'event_prefix': self.EVENT_PREFIX}

    def _check(self):
        if (self.validate_native_relation is not self._original_native_relation
                or any(current is not original for current, original in zip(
                    (self.host, self.inbox, self.validate_read), self._original_components))
                or getattr(self.validate_relation, '__self__', None) is not self
                or getattr(self.validate_relation, '__func__', None) is not type(self)._validate_continuation_relation):
            raise TaskConflict('Continuation feedback replaced its original native validation boundary')
        super()._check()

    def _validate_continuation_relation(self, *, identity, receipt, snapshot, observation, sources, evidence, context, reading):
        if (identity.action_id != 'OWN-A13' or observation.target_action_id != 'OWN-A13'
                or observation.native_evidence_ref in observation.source_refs):
            raise TaskConflict('Continuation feedback requires original A13 submission and current A13 sources')
        record = self.host.workers['OWN-A13'].get_record(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or record['record_sha256'] != receipt['record_sha256']
                or receipt['identity'] != identity.as_dict() or receipt['receipt']['disposition'] != 'accepted'):
            raise TaskConflict('Continuation feedback lacks original completed result and accepted registration request')
        original_context = ActionContext.model_validate(snapshot['context'])
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in record['source_reading']}
        profile_ref = Reference.model_validate(snapshot['action_input']['continuation_profile_ref'])
        profile = OwnerContinuationProfileView.model_validate(originals[profile_ref.key()])
        original_state = OwnerContinuationStateView.model_validate(originals[profile.state_ref.key()])
        projections = {Reference.model_validate(row['ref']).key(): row['projection'] for row in sources}
        executions = [OwnerContinuationExecutionView.model_validate(row['projection']) for row in sources
            if row['ref']['kind'] == 'ContinuationExecution'
            and row['projection'].get('profile_ref') == profile.ref.model_dump(mode='json')
            and row['projection'].get('operation_id') == identity.request_id]
        if len(projections) != len(sources) or len(executions) != 1:
            raise TaskConflict('Continuation feedback needs one original profile/operation-bound execution')
        execution = executions[0]
        if (execution.profile_sha256 != task_digest(profile.model_dump(mode='json'))
                or profile.choice != record['result']['payload']['choice']
                or execution.business_key != profile.business_key or execution.run_id != identity.run_id
                or execution.organization_id != identity.organization_id or execution.scope != original_context.scope
                or execution.state_ref.key() not in projections
                or observation.native_evidence_ref not in execution.evidence_refs
                or execution.available_at.clock_ref != context.business_time.clock_ref
                or not original_context.business_time.offset <= execution.available_at.offset <= observation.available_at.offset
                or not execution.effective_window.contains(observation.observed_at)
                or execution.status == 'succeeded' and execution.core_event_id != observation.native_event_id
                or execution.status != 'succeeded' and execution.core_event_id is not None):
            raise TaskConflict('Continuation execution changes original profile, business identity, event or observed outcome')
        state = OwnerContinuationStateView.model_validate(projections[execution.state_ref.key()])
        if (state.organization_id != identity.organization_id or state.scope != context.scope
                or (state.ref.kind, state.ref.id) != (original_state.ref.kind, original_state.ref.id)
                or state.producer != 'core' or state.coverage != 'complete' or state.as_of != observation.observed_at
                or state.available_at.clock_ref != context.business_time.clock_ref
                or state.available_at.offset > context.business_time.offset
                or not state.effective_window.contains(context.business_time) or execution.ref not in state.execution_refs
                or not set(execution.resource_refs) <= set(state.resource_refs)):
            raise TaskConflict('Continuation feedback omits the actual complete current state or selected execution/resources')
        required = [state.scope_rule_ref, *state.risk_refs, *state.contract_refs, *state.resource_refs,
            *state.obligation_refs, *state.retained_duty_refs, *state.right_refs, *state.document_refs,
            *state.funding_refs, *state.permit_refs, *state.execution_refs]
        retained = [*original_state.contract_refs, *original_state.resource_refs,
            *original_state.obligation_refs, *original_state.retained_duty_refs]
        for ref in original_state.contract_refs:
            contract = OwnerContinuationContractView.model_validate(originals[ref.key()])
            retained.extend([*contract.retained_obligation_refs, *contract.continuing_duty_refs])
        for ref in state.contract_refs:
            if ref.key() not in projections:
                raise TaskConflict('Continuation feedback omits a current original contract')
            contract = OwnerContinuationContractView.model_validate(projections[ref.key()])
            if contract.as_of != observation.observed_at:
                raise TaskConflict('Continuation feedback reuses a stale current contract')
            required.extend([contract.rule_ref, *contract.retained_obligation_refs, *contract.continuing_duty_refs])
        for ref in state.resource_refs:
            if ref.key() not in projections:
                raise TaskConflict('Continuation feedback omits a current resource commitment')
            resource = OwnerContinuationCommitmentView.model_validate(projections[ref.key()])
            if resource.owner_id != identity.organization_id or resource.as_of != observation.observed_at:
                raise TaskConflict('Continuation feedback substitutes another owner resource or stale release state')
            required.extend([resource.release_rule_ref, *resource.execution_refs])
        for ref in state.retained_duty_refs:
            if ref.key() not in projections:
                raise TaskConflict('Continuation feedback omits a retained duty')
            duty = OwnerContinuationDutyView.model_validate(projections[ref.key()])
            if duty.organization_id != identity.organization_id:
                raise TaskConflict('Continuation feedback substitutes another owner continuing duty')
            required.extend([*duty.obligation_refs, *duty.task_refs])
        if any(ref.key() not in projections for ref in required):
            raise TaskConflict('Continuation feedback omits current rules, risks, rights, finance, permits or residual responsibilities')
        physical_sources = {(Reference.model_validate(row['ref']).kind, Reference.model_validate(row['ref']).id) for row in sources}
        if any((ref.kind, ref.id) not in physical_sources for ref in retained):
            raise TaskConflict('Continuation feedback silently drops an original contract, commitment, debt or continuing duty')
        # Independent validation must authenticate every release/transfer and
        # physical commitment/version mapping; absence from state is not release.
        native = {'schema_version': 'owner-continuation-native-feedback.v1', 'native_event_id': observation.native_event_id,
            'source_identity': identity.as_dict(), 'source_record_sha256': record['record_sha256'],
            'source_result_sha256': record['result_sha256'], 'source_reading_sha256': record['source_reading_sha256'],
            'original_receipt_sha256': receipt['receipt_sha256'], 'original_result': deepcopy(record['result']),
            'original_profile': profile.model_dump(mode='json'), 'observed_at': observation.observed_at.model_dump(mode='json'),
            'available_at': observation.available_at.model_dump(mode='json'), 'sources': deepcopy(sources), 'coverage': 'complete'}
        if observation.native_source_sha256 != task_digest(native):
            raise TaskConflict('Continuation native evidence does not bind complete original execution and residual-duty sources')
        reading.recheck()
        return self.validate_native_relation(identity=identity, receipt=deepcopy(receipt), snapshot=deepcopy(snapshot),
            observation=observation.model_copy(deep=True), sources=deepcopy(sources), evidence=deepcopy(evidence),
            context=context.model_copy(deep=True), reading=reading) is True
