"""Receive actual native appointments through the original three A03 workers.

These are private compatibility decisions. Native engagements are never turned
into detailed service relationships, resource reservations or fee receipts.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from integration.architect_appointment_actions import ArchitectAppointmentActionAssembler
from integration.architect_appointment_results import ArchitectAppointmentResultWorker
from integration.engineer_appointment_actions import EngineerAppointmentActionAssembler
from integration.engineer_appointment_results import EngineerAppointmentResultWorker
from integration.qs_appointment_actions import QSAppointmentActionAssembler
from integration.qs_appointment_results import QSAppointmentResultWorker
from integration.bank_financing_private import checked_result
from integration.professional_appointment_native_sources import appointment_sources, received_team
from src.actions.contracts.common import ActionContext, StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


COMPONENTS = {
    'Architect': (ArchitectAppointmentActionAssembler, ArchitectAppointmentResultWorker),
    'Engineer': (EngineerAppointmentActionAssembler, EngineerAppointmentResultWorker),
    'QS': (QSAppointmentActionAssembler, QSAppointmentResultWorker),
}


class ProfessionalAppointmentPlan(StrictRecord):
    organization_id: TextId
    role: Literal['Architect', 'Engineer', 'QS']
    project_id: TextId
    tick: int = Field(ge=0)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    acceptance_evidence_ref: ref_type('Evidence')


class ProfessionalAppointmentSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest


class ProfessionalAppointmentApplication:
    VERSION = 'gba-v1-professional-appointment.v4'
    PREFIX = 'professional_appointment_received:'

    def __init__(self, *, professional, settings):
        self.professional = professional
        self.settings = ProfessionalAppointmentSettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        doc = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc) != {'schema_version', 'run_id', 'plans'}
                or doc['schema_version'] != 'professional-appointment-input.v1'
                or doc['run_id'] != professional.assembly.client.run_id):
            raise TaskConflict('Appointment inputs change their pinned schema or original run')
        self.plans = [ProfessionalAppointmentPlan.model_validate(p) for p in doc['plans']]
        keys = [(p.organization_id, p.project_id, p.tick) for p in self.plans]
        if not keys or len(set(keys)) != len(keys):
            raise TaskConflict('Appointment input repeats its original recipient and native time')
        for p in self.plans:
            c = p.context
            if (c.run_id != doc['run_id'] or c.actor_id != professional.organizations.get(p.organization_id).actor_id
                    or c.contract_ref.id != p.role.upper() + '-A03' or c.scope.kind != 'project'
                    or c.scope.ref.id != p.project_id or c.business_time.offset != p.tick
                    or c.execution_mode == 'offline_fixture'
                    or len({task_digest(r['ref']) for r in p.objects}) != len(p.objects)
                    or p.native_evidence_ref == p.acceptance_evidence_ref):
                raise TaskConflict('Appointment plan changes its original actor, scope, action or source identities')
        self._settings_sha = task_digest(self.settings.model_dump(mode='json'))
        self._plans_sha = task_digest([p.model_dump(mode='json') for p in self.plans])
        self._bound = {}
        self.assemblers, self.workers = {}, {}
        for role, (assembler, worker) in COMPONENTS.items():
            self.assemblers[role] = assembler(registry=professional.registry, organizations=professional.organizations,
                provider=self, macro_version='gba-public-2026-08-21', source_mode='formal',
                policy_version=professional.settings.policy_version,
                model_version=professional.assembly.client.versions['model'])
            self.workers[role] = worker(store=professional.assembly.client.tasks, snapshots=professional.snapshots,
                registry=professional.registry, client_version=self.VERSION + ':' + role,
                model_version=professional.assembly.client.versions['model'],
                validate_invocation=self.validate_invocation, validate_wait=professional.validate_wait)

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Appointment input differs from its pinned independent file')

    def check_components(self):
        self._check_file()
        p = self.professional
        if (task_digest(self.settings.model_dump(mode='json')) != self._settings_sha
                or task_digest([v.model_dump(mode='json') for v in self.plans]) != self._plans_sha
                or any(w.store is not p.assembly.client.tasks or w.registry is not p.registry for w in self.workers.values())
                or any(a.organizations is not p.organizations for a in self.assemblers.values())):
            raise TaskConflict('Appointment handler changed its original shared runtime or declared sources')

    def _key(self, event_id, organization_id):
        return self.PREFIX + task_digest({'event_id': event_id, 'organization_id': organization_id})

    def _record(self, event_id, organization_id):
        store = self.professional.assembly.client.tasks
        with store._lock:
            raw = store._db.execute('SELECT value FROM metadata WHERE key=?',
                (self._key(event_id, organization_id),)).fetchone()
        if raw is None:
            return None
        row = json.loads(raw[0])
        if (row['record_sha256'] != task_digest({k: v for k, v in row.items() if k != 'record_sha256'})
                or row['event_id'] != event_id or row['organization_id'] != organization_id
                or row['source_file_sha256'] != self.settings.file_sha256):
            raise TaskConflict('Appointment receipt changed its original event, recipient or durable record')
        return row

    def _save(self, value):
        value = deepcopy(value)
        value['record_sha256'] = task_digest({k: v for k, v in value.items() if k != 'record_sha256'})
        store = self.professional.assembly.client.tasks
        with store._transaction():
            store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                (self._key(value['event_id'], value['organization_id']), canonical(value)))
        return value

    def _current(self, plan, entry):
        self.professional._check()
        event = received_team(self, plan=plan, entry=entry)
        if plan.tick != self.professional.assembly.engine.current_tick:
            raise TaskConflict('Appointment receipt must be handled at its actual native event time')
        grants = self.professional.organizations.grants(plan.context, plan.role.upper() + '-A03', plan.role)
        if not grants or any(g.organization_id != plan.organization_id for g in grants):
            raise TaskConflict('Appointment receipt lacks its original current function authorization')
        return event

    def project(self, *, context, organization_id, grants):
        bound = self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or bound[0].organization_id != organization_id:
            raise TaskConflict('Appointment reading has no actual received native event')
        plan, entry = bound
        self._current(plan, entry)
        objects, observed = appointment_sources(self, plan=plan, entry=entry)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': self.VERSION + ':' + task_digest(observed), 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'),
            'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        bound = self._bound.get(prepared.context_sha256)
        if bound is None:
            raise TaskConflict('Appointment worker lost its original native reception')
        plan, entry = bound
        self._current(plan, entry)
        if (prepared.context != plan.context or row['identity']['organization_id'] != plan.organization_id
                or prepared.runner.registry is not self.professional.registry):
            raise TaskConflict('Appointment worker substituted its original function, actor or processor')
        prepared.reading.recheck()
        return True

    def dispatch(self, *, run_id, organization_id):
        """Use the client's existing post-observation dispatcher; never an engine patch."""
        p = self.professional
        with p.read_guard():
            p._check()
            client = p.assembly.client
            if run_id != client.run_id:
                raise TaskConflict('Appointment observation dispatcher changes its original run')
            role = client.organization_roles.get(organization_id)
            if role not in COMPONENTS:
                return
            for entry in client.inbox.for_organization(run_id=run_id, organization_id=organization_id):
                payload = entry['payload']
                if payload['event_type'] != 'consultant_team_appointed' or payload['tick'] != p.assembly.engine.current_tick:
                    continue
                plans = [v for v in self.plans if (v.organization_id, v.project_id, v.tick)
                    == (organization_id, payload['project_id'], payload['tick'])]
                if len(plans) != 1 or plans[0].role != role:
                    raise TaskConflict('Actual selected professional has no unique declared appointment receipt plan')
                plan = plans[0]
                self._current(plan, entry)
                old = self._record(entry['event_id'], organization_id)
                if old is not None:
                    if old['state'] != 'formed':
                        raise TaskConflict('Unresolved original appointment receipt requires diagnosis, not blind replay')
                    self._formed(old, plan, entry)
                    continue
                objects, observed = appointment_sources(self, plan=plan, entry=entry)
                self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, deepcopy(entry))
                record = self._save({'state': 'preparing', 'event_id': entry['event_id'],
                    'organization_id': organization_id, 'role': role, 'project_id': plan.project_id, 'tick': plan.tick,
                    'source_file_sha256': self.settings.file_sha256,
                    'source_sha256': task_digest(objects), 'observed': observed})
                prepared = self.assemblers[role].build(plan.context, **deepcopy(plan.action_input))
                worker = self.workers[role]
                identity = worker.register(prepared, request_id='received-appointment:' + self._key(entry['event_id'], organization_id))
                record.update(state='processing', identity=identity.as_dict())
                record = self._save(record)
                result = worker.execute(identity, prepared)['result']
                if (result['kind'] != 'completed'
                        or result['payload']['choice'] not in p.registry.get(role.upper() + '-A03').contract.choices):
                    raise TaskConflict('Unresolved appointment compatibility retains its original pending state')
                record.update(state='formed', identity=identity.as_dict(), result_sha256=task_digest(result),
                    choice=result['payload']['choice'])
                self._save(record)

    def _formed(self, record, plan, entry):
        # Reconstruct the exact reception, including both saved independent
        # decisions, rather than accepting a task hash or inbox row on its own.
        objects, observed = appointment_sources(self, plan=plan, entry=entry)
        saved = checked_result(self.workers[plan.role], TaskIdentity(**record['identity']))
        snapshot = self.professional.snapshots.get(TaskIdentity(**record['identity']))
        source_map = {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
        if (record['observed'] != observed or record['source_sha256'] != task_digest(objects)
                or record['result_sha256'] != saved['result_sha256']
                or saved['result']['payload']['choice'] != record['choice']
                or snapshot['context'] != plan.context.model_dump(mode='json')
                or snapshot['action_input'] != plan.action_input
                or source_map != {task_digest(r['ref']): r['value'] for r in objects}):
            raise TaskConflict('Appointment history substitutes its original received source or completed result')
        return saved

    def prior_confirmations(self, *, organization_id, tick, appointments, include_unresolved=False):
        """Read own actual A03 results; never resolve or cancel an appointment here."""
        if type(include_unresolved) is not bool:
            raise ValueError('Unresolved appointment history requires an explicit boolean choice')
        self.check_components()
        p = self.professional
        if tick != p.assembly.engine.current_tick:
            raise TaskConflict('Appointment confirmation consumption changes the current native clock')
        entries = {e['event_id']: e for e in p.assembly.client.inbox.for_organization(
            run_id=p.assembly.client.run_id, organization_id=organization_id)}
        origins = []
        for original in appointments:
            entry = entries[original['event_id']]
            plans = [v for v in self.plans if (v.organization_id, v.project_id, v.tick)
                == (organization_id, entry['payload']['project_id'], entry['payload']['tick'])]
            if len(plans) != 1 or plans[0].tick >= tick:
                raise TaskConflict('Later intake lost its own original earlier appointment plan')
            plan = plans[0]
            record = self._record(entry['event_id'], organization_id)
            if record is None or record['state'] != 'formed':
                raise TaskConflict('Later intake requires diagnosis of its unhandled actual prior appointment')
            saved=self._formed(record, plan, entry)
            if record['choice'] != 'confirm' and not include_unresolved:
                raise TaskConflict('Prior appointment amendment or incompatibility requires explicit resolution before new intake')
            origin={'event_id': entry['event_id'], 'project_id': plan.project_id, 'tick': plan.tick,
                'role': plan.role, 'organization_id': organization_id, 'choice': record['choice'],
                'micro_task_key': TaskIdentity(**record['identity']).key, 'result_sha256': record['result_sha256']}
            if record['choice']!='confirm':
                origin.update(unresolved=True,private_result=deepcopy(saved['result']['payload']),
                    source_reading_sha256=saved['source_reading_sha256'])
            origins.append(origin)
        return origins

    def evidence(self):
        self.check_components()
        store = self.professional.assembly.client.tasks
        with store._lock:
            records = [json.loads(raw) for raw, in store._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ? ORDER BY key', (self.PREFIX + '%',))]
        return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256, 'receipts': records,
            'limits': 'Private original A03 compatibility only; no service relationship, reservation, task plan, fee or native mutation.'}
