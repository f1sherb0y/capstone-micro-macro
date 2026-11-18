"""Concrete native snapshot checks for exposing and consuming a saved A02 bid."""
from contextlib import nullcontext
import json

from integration.contractor_tender_task_selection import ContractorTenderTaskSelector
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


class ContractorTenderCurrentValidator:
    """Callbacks used under the installed tender host's actual writer guard.

    The proposal adapter owns professional indicator, authorship and branch
    checks. These callbacks independently retain the original selected task and
    actual own native invitation/resources. An exposure record proves only this
    check occurred; it is neither a completed proposal nor a native bid receipt.
    The final callback requires the client's separately saved completed proposal.
    """
    VERSION = 'contractor-tender-current-validator.v1'

    def __init__(self, *, selector, validator_id, version):
        if (not isinstance(selector, ContractorTenderTaskSelector)
                or not all(isinstance(value, str) and value.strip() for value in (validator_id, version))):
            raise ValueError('Tender current validator requires its original selector and explicit identity/version')
        self.selector, self.store = selector, selector.store
        self.validator_id, self.version = validator_id, version
        self._components = (selector, selector.store)
        self._declared = self._configuration()
        self._key = 'contractor_tender_current_validator:' + validator_id
        with self.store._transaction():
            prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if prior is None:
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._key, canonical(self._declared)))
            elif json.loads(prior[0]) != self._declared:
                raise TaskConflict('Original tender current validator configuration changed')

    def _configuration(self):
        return {'schema_version': self.VERSION, 'validator_id': self.validator_id, 'version': self.version,
            'run_id': self.store.run_id, 'selector_sha256': task_digest(self.selector._declared),
            'code': module_factory_descriptor(type(self).revalidate, self.VERSION)}

    def _check(self, *, bound=True):
        if (self.selector is not self._components[0] or self.store is not self._components[1]
                or self.selector.store is not self.store or self._configuration() != self._declared):
            raise TaskConflict('Tender current validator changed its original selector or configuration')
        self.selector._check(bound=bound)
        with self.store._lock:
            row = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key,)).fetchone()
            if row is None or json.loads(row[0]) != self._declared:
                raise TaskConflict('Tender current validator configuration evidence changed')

    def _exposure_key(self, request):
        return self._key + ':exposure:' + task_digest([request.agent.agent_id, request.request_id])

    def _current(self, request, *, source_refs=()):
        self._check()
        request = self.selector._request(request)
        selected = self.selector.select_current(request)
        pipeline = self.selector.host.pipeline
        assembly = pipeline.assembly
        project = request.inputs.get('project')
        tick = request.metadata.get('tick')
        if (not isinstance(project, dict) or not isinstance(project.get('project_id'), str)
                or type(tick) is not int or tick < 0 or tick != assembly.engine.current_tick):
            raise TaskConflict('Tender current validation requires the actual same-tick native project request')
        resource = assembly.read_enterprise_resources(organization_id=request.agent.agent_id, read_guard=nullcontext)
        tender = assembly.read_invited_tender_project(organization_id=request.agent.agent_id,
            project_id=project['project_id'], read_guard=nullcontext)
        if (tender.get('kind') == 'needs_information' or tender.get('observed_tick') != tick
                or resource['observed_tick'] != tick):
            raise TaskConflict('Tender current validation lacks its actual current own invitation and resources')
        reading = pipeline.assembler.build_result_reading(selected.current_context)
        saved = pipeline.worker.read_completed(selected.identity, current_context=selected.current_context,
            reading=reading, mapping_ref=selected.mapping_ref)
        mapping = reading.resolve(selected.mapping_ref)
        for ref in source_refs:
            reading.resolve(Reference.model_validate(ref))
        reading.recheck()
        body = {'schema_version': self.VERSION, 'configuration_sha256': task_digest(self._declared),
            'host_sha256': self.selector.host.configuration_sha256,
            'request': request.model_dump(mode='json'), 'request_sha256': task_digest(request.model_dump(mode='json')),
            'identity': selected.identity.as_dict(),
            'original_context_sha256': task_digest(saved.context.model_dump(mode='json')),
            'current_context_sha256': task_digest(saved.current_context.model_dump(mode='json')),
            'input_sha256': task_digest(saved.action_input.model_dump(mode='json')),
            'result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'audit_sha256': task_digest(saved.audit), 'mapping_sha256': task_digest(mapping.model_dump(mode='json')),
            'source_reading': reading.evidence(),
            'reading_sha256': task_digest(reading.evidence()),
            'native_resource_sha256': resource['record_sha256'], 'native_tender_sha256': tender['record_sha256'],
            'project_id': project['project_id'], 'tick': tick}
        body['record_sha256'] = task_digest(body)
        return request, selected, saved, body

    def revalidate(self, *, request, original_context, current_context, action_input, result, reading):
        """Check exposure after the original adapter's professional/authority checks."""
        reading.recheck()
        request, selected, saved, body = self._current(request,
            source_refs=[row['ref'] for row in reading.evidence()])
        if (original_context != saved.context or current_context != saved.current_context
                or action_input.model_dump(mode='json') != saved.action_input.model_dump(mode='json')
                or result.model_dump(mode='json') != saved.result.model_dump(mode='json')
                or reading.organization_id != selected.identity.organization_id):
            raise TaskConflict('Tender exposure changed the original selected bid or current authority')
        reading.check_method_context(current_context, 'CONTRACTOR-A02')
        reading.recheck()
        if task_digest(reading.evidence()) != body['reading_sha256']:
            raise TaskConflict('Tender exposure changed its original authorized source projections')
        self._check()
        with self.store._transaction():
            key = self._exposure_key(request)
            prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if prior is None:
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(body)))
            elif json.loads(prior[0]) != body:
                raise TaskConflict('Tender exposure cannot replace its original native request, task or snapshot')

    def validate_current(self, *, request, proposal, task_identity):
        """Reconcile completed saved proposal and original exposure before final choice."""
        from gba_construction_sim.backend.agents.contracts import AGENT_MODULE_CONTRACT_VERSION, AgentDecisionRequestV1
        from integration.observations import observation_digest

        self._check()
        request = AgentDecisionRequestV1.model_validate(request).model_copy(deep=True)
        identity = TaskIdentity(**task_identity.as_dict())
        client = self.selector.host.pipeline.assembly.client
        if (request.contract_version != AGENT_MODULE_CONTRACT_VERSION
                or request.agent.role != 'Contractor' or request.decision_type != 'tender_decision'
                or request.metadata.get('simulation_id') not in {None, client.simulation_id}
                or identity.run_id != self.store.run_id or identity.organization_id != request.agent.agent_id
                or identity.role != 'Contractor' or identity.action_id != 'consider_tender'
                or identity.purpose != 'propose' or identity.versions != client.versions
                or identity.request_id != proposal.request_id or request.project_id != request.project.get('project_id')
                or proposal.action_type not in request.constraints.allowed_actions):
            raise TaskConflict('Final tender validation changes its original native request, proposal or task')
        key = self._key + ':exposure:' + task_digest([identity.organization_id, identity.request_id])
        with self.store._lock:
            row = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        if row is None:
            raise TaskConflict('Final tender decision lacks its original exposure validation evidence')
        exposure = json.loads(row[0])
        if exposure.get('record_sha256') != task_digest({k: v for k, v in exposure.items() if k != 'record_sha256'}):
            raise TaskConflict('Original tender exposure evidence changed')
        native, _, saved, current = self._current(exposure['request'],
            source_refs=[row['ref'] for row in exposure['source_reading']])
        if (current != exposure or request.tick != exposure['tick'] or request.project_id != exposure['project_id']
                or native.request_id != identity.request_id
                or identity.input_sha256 != observation_digest({'run_id': client.run_id,
                    'versions': client.versions, 'request': exposure['request']})
                or identity.context_sha256 != observation_digest({'simulation_id': client.simulation_id,
                    'request': exposure['request']})):
            raise TaskConflict('Final tender current sources differ from the original checked exposure')
        task = self.store.get(identity)
        if task['state'] != 'output_formed' or task['output'] != proposal.model_dump(mode='json'):
            raise TaskConflict('Final tender requires its separately persisted completed native proposal')
        expected = {'micro_action_id': 'CONTRACTOR-A02', 'micro_input_sha256': exposure['input_sha256'],
            'micro_result_sha256': exposure['result_sha256'], 'original_audit_sha256': exposure['audit_sha256'],
            'indicator_mapping_sha256': exposure['mapping_sha256'], 'proposal_request_sha256': exposure['request_sha256'],
            'project_id': exposure['project_id'], 'proposal_tick': exposure['tick']}
        if (any(proposal.factors.get(name) != value for name, value in expected.items())
                or proposal.action_type != saved.result.payload.choice
                or proposal.accepted != (saved.result.payload.choice == 'submit_bid')):
            raise TaskConflict('Final tender proposal changed the original A02 choice or provenance')
        self._check()
