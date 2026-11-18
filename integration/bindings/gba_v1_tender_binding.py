"""Immutable original tender binding evidence for explicit client restoration."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from src.coordination.tasks import TaskConflict, canonical, task_digest


METADATA_KEY = 'gba_contractor_tender_binding.v1'


def tender_binding_record(client, proposal, decision, *, versions, host_configuration_sha256):
    """Host digest covers actual callbacks, selectors, policy and source config.

    It is a required explicit host declaration, not a claim that arbitrary
    callable configuration can be reconstructed through Python introspection.
    Concrete bridge source bytes and actual A02 contract/Skill are also bound.
    """
    from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalAdapter
    from integration.bindings.gba_v1_tender_decision import GbaTenderDecisionAdapter

    if (not isinstance(proposal, GbaTenderProposalAdapter) or not isinstance(decision, GbaTenderDecisionAdapter)
            or decision.client is not client or proposal.run_id != client.run_id
            or client.simulation_id is None or proposal.simulation_id != client.simulation_id
            or not isinstance(host_configuration_sha256, str)
            or re.fullmatch(r'[0-9a-f]{64}', host_configuration_sha256) is None):
        raise TaskConflict('Tender binding requires actual components, original simulation and host configuration digest')
    registration = proposal.registry.get('CONTRACTOR-A02')
    if not registration.implemented or registration.skill is None:
        raise TaskConflict('Tender binding requires the actual registered A02 processor and Skill')
    skill, contract = registration.skill, registration.contract
    root = Path(__file__).resolve().parents[1]
    sources = ('agent_client.py', 'bindings/gba_v1_tender_proposal.py', 'bindings/gba_v1_tender_decision.py',
               'bindings/gba_v1_tender_feedback.py', 'bindings/gba_v1_tender_binding.py')
    record = {'schema_version':METADATA_KEY, 'run_id':client.run_id, 'simulation_id':client.simulation_id,
        'organization_roles':deepcopy(client.organization_roles), 'versions':deepcopy(versions),
        'host_configuration_sha256':host_configuration_sha256,
        'proposal_component':{'id':'GbaTenderProposalAdapter', 'version':proposal.VERSION},
        'decision_component':{'id':'GbaTenderDecisionAdapter', 'version':decision.VERSION},
        'proposal_keys':sorted([list(key) for key in {*client.proposal_handlers, proposal.HANDLER_KEY}]),
        'a02':{'processor_id':registration.processor_id, 'strategy':registration.strategy,
            'skill_sha256':task_digest(skill.manifest.model_dump(mode='json')),
            'prompt_sha256':task_digest({'content':skill.content, 'shared_content':skill.shared_content}),
            'contract_sha256':task_digest({'source_sha256':contract.source_sha256,
                'input_schema':contract.input_model.model_json_schema(),
                'payload_schema':contract.payload_adapter.json_schema()})},
        'source_hashes':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}}
    record['record_sha256'] = task_digest(record)
    return record


def saved_tender_binding(store):
    with store._lock:
        saved = store._db.execute('SELECT value FROM metadata WHERE key=?', (METADATA_KEY,)).fetchone()
        if saved is None:
            return None
        record = json.loads(saved[0])
        if (not isinstance(record, dict) or record.get('schema_version') != METADATA_KEY
                or record.get('run_id') != store.run_id
                or task_digest({k:v for k,v in record.items() if k != 'record_sha256'}) != record.get('record_sha256')):
            raise TaskConflict('Original tender binding metadata changed or belongs to another run')
        return deepcopy(record)


def save_tender_binding(store, record):
    with store._transaction():
        original = saved_tender_binding(store)
        if original is not None and original != record:
            raise TaskConflict('Original tender binding cannot be replaced; use a new isolated run for changed configuration')
        if original is None:
            store._db.execute('INSERT INTO metadata VALUES (?,?)', (METADATA_KEY, canonical(record)))
