"""Reconcile the exact persisted tender proposal before exposing its final choice."""
from pydantic import Field, model_validator

from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalAdapter
from integration.observations import observation_digest
from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import TaskConflict, TaskIdentity


class TenderFinalValidationSettings(StrictRecord):
    # Exact original native requests, selected by their original request_id.
    # Their full contents must match both the persisted task digests and mapping.
    proposal_requests: dict[TextId, dict] = Field(default_factory=dict)
    use_request_trigger: bool = False

    @model_validator(mode='after')
    def explicit_source(self):
        if self.use_request_trigger and self.proposal_requests:
            raise ValueError('Final tender must use one explicit source of original proposal requests')
        if not self.use_request_trigger and not self.proposal_requests:
            raise ValueError('Final tender requires supplied proposal requests or the original request trigger')
        return self


def _original_request(configuration, identity, application):
    if not configuration.use_request_trigger:
        original = configuration.proposal_requests.get(identity.request_id)
        if original is None:
            raise TaskConflict('Final tender requires an explicitly supplied exact original proposal request')
        return original
    from integration.contractor_tender_request_trigger import read_request_record

    record = read_request_record(application=application, organization_id=identity.organization_id,
        request_id=identity.request_id)
    if record['state'] != 'selected' or 'native_request' not in record:
        raise TaskConflict('Final tender requires the original request and completed micro selection, without replay')
    return record['native_request']


def validate_final(*, request, proposal, task_identity, application, settings):
    """Configured professional.final callback for submit_bid and decline_bid.

    Reuses the original adapter's deterministic saved-output validation and the
    configured independent exposure gate. It never calls client.propose/decide,
    runs a strategy/processor, creates a task or writes another exposure record.
    Current native snapshot/exposure validation stays in the separate factory
    callback. A final choice is neither an award nor a native effect receipt.
    """
    from gba_construction_sim.backend.agents.contracts import (
        AGENT_MODULE_CONTRACT_VERSION, AgentDecisionRequestV1,
        AgentProposalRequestV1, AgentProposalResponseV1,
    )

    configuration = TenderFinalValidationSettings.model_validate(settings).model_copy(deep=True)
    request = AgentDecisionRequestV1.model_validate(request).model_copy(deep=True)
    proposal = AgentProposalResponseV1.model_validate(proposal).model_copy(deep=True)
    identity = TaskIdentity(**task_identity.as_dict())
    application._check()
    if application.host is None or application.selector is None:
        raise TaskConflict('Final tender validation requires the original installed host and selector')
    application.host._check(bound=True)
    client = application.assembly.client
    proposal_id = f'proposal-tick{request.tick}-{request.project_id}-{request.agent.agent_id}-consider_tender'
    if (request.contract_version != AGENT_MODULE_CONTRACT_VERSION
            or request.agent.role != 'Contractor' or request.decision_type != 'tender_decision'
            or request.metadata.get('simulation_id') not in {None, client.simulation_id}
            or request.tick != application.assembly.engine.current_tick
            or client.organization_roles.get(request.agent.agent_id) != 'Contractor'
            or identity.run_id != application.store.run_id or identity.organization_id != request.agent.agent_id
            or identity.role != 'Contractor' or identity.action_id != 'consider_tender' or identity.purpose != 'propose'
            or identity.versions != client.versions or identity.request_id != proposal_id
            or proposal.request_id != proposal_id or request.project_id != request.project.get('project_id')
            or proposal.action_type not in {'submit_bid', 'decline_bid'}
            or proposal.action_type not in request.constraints.allowed_actions
            or proposal.accepted != (proposal.action_type == 'submit_bid')):
        raise TaskConflict('Final tender changes its original task, bounded choice, project, recipient or tick')
    original = _original_request(configuration, identity, application)
    native = AgentProposalRequestV1.model_validate(original).model_copy(deep=True)
    native = application.selector._request(native)
    content = native.model_dump(mode='json')
    if (native.request_id != identity.request_id or native.agent.agent_id != identity.organization_id
            or type(native.metadata.get('tick')) is not int or native.metadata['tick'] != request.tick
            or native.inputs['project'].get('project_id') != request.project_id
            or identity.input_sha256 != observation_digest({'run_id': client.run_id,
                'versions': client.versions, 'request': content})
            or identity.context_sha256 != observation_digest({'simulation_id': client.simulation_id, 'request': content})):
        raise TaskConflict('Final tender substitutes the original persisted proposal request content')
    task = application.store.get(identity)
    if task['state'] != 'output_formed' or task['output'] != proposal.model_dump(mode='json'):
        raise TaskConflict('Final tender requires the separately saved completed native proposal')
    selection = application.selector.select_current(native)
    pipeline = application.host.pipeline
    reading = pipeline.assembler.build_result_reading(selection.current_context)
    saved = pipeline.worker.read_completed(selection.identity, current_context=selection.current_context,
        reading=reading, mapping_ref=selection.mapping_ref)
    record = pipeline.worker.get_record(selection.identity)
    # Build transport from the original saved decision only. The callback below
    # checks real independent indicators through the pinned application gate;
    # it is not a fixed-success replacement for professional/native validation.
    adapter = GbaTenderProposalAdapter(run_id=application.store.run_id,
        simulation_id=client.simulation_id, registry=application.registry,
        read_output=lambda original_request: saved, revalidate=application.exposure)
    checked = adapter(native)
    if checked.model_dump(mode='json') != proposal.model_dump(mode='json'):
        raise TaskConflict('Final proposal changes original price, indicators, reason, choice or provenance')
    risk_inputs = request.current_state.get('risk_inputs', {})
    assessment = risk_inputs.get('bid_assessment') if isinstance(risk_inputs, dict) else None
    if assessment is not None:
        if (not isinstance(assessment, dict) or assessment.get('decision_factors') != proposal.factors
                or any(assessment.get(name) != proposal.data.get(name) for name in
                    ('bid_probability', 'bid_price', 'expected_profit', 'risk_level', 'decline_reason'))):
            raise TaskConflict('Current core assessment differs from the exact original saved tender proposal')
    reading.recheck()
    if (application.store.get(identity) != task or client.versions != identity.versions
            or pipeline.worker.get_record(selection.identity) != record
            or application.selector.select_current(native) != selection):
        raise TaskConflict('Original native proposal, selected micro result or versions changed during final validation')
    application.host._check(bound=True)
    application._check()
