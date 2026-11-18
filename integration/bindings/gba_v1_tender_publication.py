"""Publish source-produced contractor objects at a new immutable authorized read point."""
from copy import deepcopy
import json

from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.contractor_objects import (
    CommitmentSnapshotView, ContractorCapabilityView, InvitationView,
    ProcurementPackageView, contractor_screening_schemas,
)
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidCapacityView, ContractorBidCommitmentView, ContractorBidResourceView, ContractorBidCostView,
)
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.organization.registry import OrganizationRegistry


class GbaTenderPublicationStore:
    """Technical projection storage, with no native ledger/state writes.

    validate_source(prepared, context) must recheck the actual source snapshot
    and independent terms before publication. A changed producer read token
    requires a new invocation; generated objects never enter the old snapshot.
    """
    SCHEMA = 'gba-v1-tender-publication.v1'

    def __init__(self, *, store, organizations, validate_source):
        if (not isinstance(store, TaskStore) or not isinstance(organizations, OrganizationRegistry)
                or organizations.run_id != store.run_id or not callable(validate_source)):
            raise ValueError('Actual run-local task store, organization registry and source revalidation required')
        self.store, self.organizations, self.validate_source = store, organizations, validate_source
        self.schemas = contractor_screening_schemas()
        from integration.bindings.gba_v1_bid_capacity import gba_bid_capacity_source_schemas
        self.bid_schemas = gba_bid_capacity_source_schemas()
        with store._transaction():
            store._db.execute('CREATE TABLE IF NOT EXISTS gba_tender_published_objects (ref_key TEXT PRIMARY KEY, record TEXT NOT NULL)')
            store._db.execute('CREATE TABLE IF NOT EXISTS gba_tender_publications (publication_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _key(self, context, organization_id):
        return task_digest([context.run_id, organization_id, context.read_token])

    def _object_key(self, context, ref):
        if context.contract_ref.id == 'CONTRACTOR-A01':
            # Retain the exact historical key; no existing object is migrated.
            return task_digest([context.run_id, ref])
        return task_digest([context.run_id, 'CONTRACTOR-A02.projection', ref])

    def publish_bid_capacity(self, prepared, *, source_context, reading, next_context):
        """Publish the complete A02 capacity/pool/commitment set in one transaction."""
        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        if (not isinstance(reading,ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A02'
                or source_context.contract_ref.id != 'CONTRACTOR-A02'
                or context.read_token == source_context.read_token
                or context.run_id != self.store.run_id
                or any(getattr(context,name) != getattr(source_context,name) for name in
                       ('run_id','actor_id','function_ref','contract_ref','scope','business_time','execution_mode'))
                or not isinstance(prepared,dict) or prepared.get('kind') != 'prepared'
                or prepared.get('context_sha256') != task_digest(source_context.model_dump(mode='json'))):
            raise TaskConflict('Bid capacity publication requires original same-time A02 and a new read token')
        reading.check_method_context(source_context,'CONTRACTOR-A02')
        grants = self.organizations.grants(context,'CONTRACTOR-A02','Contractor')
        organization_id = grants[0].organization_id
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (reading.organization_id != organization_id or organization_id not in self.store.organization_ids
                or prepared.get('source_mode') != mode):
            raise TaskConflict('Bid capacity publication changes original enterprise or source mode')
        capacity = prepared.get('capacity_projection')
        resources, commitments = prepared.get('resource_projections'), prepared.get('commitment_projections')
        if (not isinstance(capacity,ContractorBidCapacityView) or not isinstance(resources,list)
                or not isinstance(commitments,list) or any(not isinstance(row,ContractorBidResourceView) for row in resources)
                or any(not isinstance(row,ContractorBidCommitmentView) for row in commitments)
                or capacity.organization_id != organization_id or capacity.scope != context.scope
                or capacity.as_of != context.business_time
                or task_digest(capacity.model_dump(mode='json')) != prepared.get('capacity_sha256')):
            raise TaskConflict('Bid capacity publication changes its original strict projections')
        objects = [capacity,*resources,*commitments]
        if task_digest([obj.model_dump(mode='json') for obj in objects]) != prepared.get('objects_sha256'):
            raise TaskConflict('Bid capacity resource/commitment projection set changed')
        pools = {row.ref.key():row for row in resources}
        allocations = {row.ref.key():row for row in commitments}
        if (len(pools) != len(resources) or len(allocations) != len(commitments)
                or set(pools) != {row.resource_ref.key() for row in capacity.resources}
                or set(allocations) != {row.commitment_ref.key() for row in capacity.commitments}):
            raise TaskConflict('Published original resources/commitments omit or duplicate calendar rows')
        for row in capacity.resources:
            original = pools[row.resource_ref.key()]
            if (original.organization_id != organization_id or original.scope != context.scope
                    or original.resource_kind != row.resource_kind or original.region_id != row.region_id
                    or original.total != row.total or original.effective_window != row.effective_window):
                raise TaskConflict('Bid capacity changes an original resource version')
        for row in capacity.commitments:
            original = allocations[row.commitment_ref.key()]
            if (original.organization_id != organization_id or original.scope != context.scope
                    or original.resource_ref != row.resource_ref or original.quantity != row.quantity
                    or original.window != row.window):
                raise TaskConflict('Bid capacity changes an original occupied commitment version')
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        if any(obj.ref.key() not in permitted for obj in objects):
            raise TaskConflict('Published bid capacity objects are outside the actual next read authority')
        provenance = {name:prepared.get(name) for name in
                      ('source_record_sha256','capacity_input_sha256','enterprise_facts_sha256')}
        if any(not isinstance(value,str) or len(value) != 64
               or any(c not in '0123456789abcdef' for c in value) for value in provenance.values()):
            raise TaskConflict('Bid capacity publication lacks original source/calendar/enterprise evidence')
        if self.validate_source(deepcopy(prepared),source_context.model_copy(deep=True)) is not None:
            raise TaskConflict('Actual source/calendar and independent qualification facts require fresh validation')
        reading.recheck()
        records = [{'ref':obj.ref.model_dump(mode='json'),
            'value':self.bid_schemas.validate_projection(obj.ref,obj).model_dump(mode='json')} for obj in objects]
        record = {'schema_version':self.SCHEMA,'run_id':context.run_id,'organization_id':organization_id,
            'source_context_sha256':task_digest(source_context.model_dump(mode='json')),
            'context':context.model_dump(mode='json'),'source_mode':mode,'objects':records,
            'projection_namespace':'CONTRACTOR-A02','resource_provenance':provenance}
        record['record_sha256'] = task_digest(record)
        return self._save(context,organization_id,record,grants)

    def publish_bid_costs(self, prepared, *, source_context, reading, next_context):
        """Publish a bounded cost set and retain authorized original A02 publications."""
        from integration.contractor_bid_costs import ContractorBidCostAdoptionView
        from src.actions.contracts.qs_cost_objects import QSCostPriceView
        from src.actions.contracts.contractor_bid_objects import ContractorBidQuantityView
        from src.actions.contracts.owner_study_objects import unique_refs

        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A02'
                or source_context.contract_ref.id != 'CONTRACTOR-A02' or context.run_id != self.store.run_id
                or context.read_token == source_context.read_token
                or any(getattr(context, name) != getattr(source_context, name) for name in
                       ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or not isinstance(prepared, list) or not prepared):
            raise TaskConflict('Cost publication requires a nonempty original A02 set and a new same-time token')
        reading.check_method_context(source_context, 'CONTRACTOR-A02')
        grants = self.organizations.grants(context, 'CONTRACTOR-A02', 'Contractor')
        organization_id = grants[0].organization_id
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if reading.organization_id != organization_id or organization_id not in self.store.organization_ids:
            raise TaskConflict('Cost publication changes its original Contractor')
        records = []
        provenance, targets = [], []
        lines = set()
        for result in prepared:
            if (not isinstance(result, dict) or result.get('kind') != 'prepared'
                    or result.get('context_sha256') != task_digest(source_context.model_dump(mode='json'))
                    or result.get('source_mode') != mode):
                raise TaskConflict('Cost publication changes its original producer context or source mode')
            cost = result.get('cost_projection')
            if (not isinstance(cost, ContractorBidCostView) or cost.organization_id != organization_id
                    or cost.scope != context.scope or cost.available_at != context.business_time
                    or not cost.effective_window.contains(context.business_time)
                    or task_digest(cost.model_dump(mode='json')) != result.get('cost_sha256')):
                raise TaskConflict('Cost publication changes its original strict projection')
            basis = reading.resolve(Reference.model_validate(result['adoption_ref']))
            price = reading.resolve(Reference.model_validate(result['price_ref']))
            quantity = reading.resolve(cost.quantity_basis_ref)
            if (not isinstance(basis, ContractorBidCostAdoptionView) or not isinstance(price, QSCostPriceView)
                    or not isinstance(quantity, ContractorBidQuantityView)
                    or task_digest(basis.model_dump(mode='json')) != result.get('adoption_sha256')
                    or task_digest(price.model_dump(mode='json')) != result.get('price_sha256')
                    or task_digest(quantity.model_dump(mode='json')) != result.get('quantity_sha256')
                    or basis.run_id != context.run_id or basis.organization_id != organization_id
                    or basis.scope != context.scope or basis.price_sha256 != result.get('price_sha256')
                    or basis.quantity_sha256 != result.get('quantity_sha256')
                    or basis.price_ref != price.ref or basis.cost_ref != cost.ref
                    or basis.package_ref != cost.package_ref or basis.quantity_basis_ref != quantity.ref
                    or basis.quantity_line_key != cost.quantity_line_key or cost.unit_rate != price.unit_rate
                    or cost.quantity_unit != price.quantity_unit or cost.region_id != price.region_id
                    or cost.coverage_keys != price.coverage_keys or cost.method_ref != basis.method_ref
                    or cost.status != quantity.status
                    or any(getattr(cost, name) != getattr(basis, name) for name in
                           ('author_actor_id', 'author_function_ref', 'author_authority_ref'))):
                raise TaskConflict('Published cost substitutes its original adopted price, quantity or author')
            key = (cost.quantity_basis_ref.key(), cost.quantity_line_key)
            if key in lines:
                raise TaskConflict('Cost publication repeats a priced quantity line')
            lines.add(key)
            targets.append(cost.ref)
            records.append({'ref': cost.ref.model_dump(mode='json'),
                'value': self.bid_schemas.validate_projection(cost.ref, cost).model_dump(mode='json')})
            provenance.append({
                'adoption_ref': basis.ref.model_dump(mode='json'), 'price_ref': price.ref.model_dump(mode='json'),
                **{name: result[name] for name in
                   ('adoption_sha256', 'price_sha256', 'quantity_sha256', 'cost_sha256')}})
        unique_refs(targets)
        return self._publish_bid_additions(records, source_context=source_context, reading=reading,
            next_context=context, source_mode=mode, provenance={'cost_provenance': provenance},
            validation={'kind': 'prepared', 'cost_projections': deepcopy(prepared)})

    def publish_bid_quantities(self, prepared, *, source_context, reading, source_reading, next_context):
        """Publish exact original QS schedule lines using the existing A02 transaction."""
        from integration.contractor_bid_quantities import ContractorQuantityMappingView
        from src.actions.contracts.contractor_bid_objects import ContractorBidQuantityView
        from src.actions.contracts.qs_procurement_objects import (
            QSProcurementDesignView, QSProcurementDocumentView, QSProcurementQuantityView,
        )
        from src.actions.contracts.owner_study_objects import unique_refs

        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        if (not isinstance(prepared, list) or not prepared or not isinstance(source_reading, ActionReadView)
                or not isinstance(reading, ActionReadView) or source_reading.organization_id != reading.organization_id):
            raise TaskConflict('Quantity publication requires a nonempty original set and both authorized readings')
        reading.check_method_context(source_context, 'CONTRACTOR-A02')
        source_reading.check_method_context(source_context, 'CONTRACTOR-A02')
        mode = 'fixture' if source_context.execution_mode == 'offline_fixture' else 'formal'
        records, provenance, targets = [], [], []
        for result in prepared:
            if (not isinstance(result, dict) or result.get('kind') != 'prepared' or result.get('source_mode') != mode
                    or result.get('context_sha256') != task_digest(source_context.model_dump(mode='json'))):
                raise TaskConflict('Quantity publication changes its original producer context or mode')
            quantity = result.get('quantity_projection')
            if (not isinstance(quantity, ContractorBidQuantityView) or quantity.scope != source_context.scope
                    or quantity.available_at != source_context.business_time
                    or not quantity.effective_window.contains(source_context.business_time)
                    or task_digest(quantity.model_dump(mode='json')) != result.get('quantity_sha256')):
                raise TaskConflict('Quantity publication changes its original strict projection')
            mapping = reading.resolve(Reference.model_validate(result['mapping_ref']))
            if not isinstance(mapping, ContractorQuantityMappingView):
                raise TaskConflict('Quantity publication lacks its original concrete source mapping')
            document = source_reading.resolve(mapping.document_ref)
            schedule = source_reading.resolve(mapping.schedule_ref)
            if (not isinstance(document, QSProcurementDocumentView) or document.status != 'published'
                    or not isinstance(schedule, QSProcurementQuantityView)
                    or mapping.run_id != source_context.run_id or mapping.organization_id != reading.organization_id
                    or mapping.scope != quantity.scope or mapping.package_ref != quantity.package_ref
                    or mapping.quantity_ref != quantity.ref or mapping.measurement_rule_ref != quantity.measurement_rule_ref
                    or task_digest(mapping.model_dump(mode='json')) != result.get('mapping_sha256')
                    or task_digest(document.model_dump(mode='json')) != mapping.document_sha256
                    or task_digest(schedule.model_dump(mode='json')) != mapping.schedule_sha256
                    or result.get('document_sha256') != mapping.document_sha256
                    or result.get('schedule_sha256') != mapping.schedule_sha256
                    or document.draft.quantity_schedule_ref != schedule.ref or quantity.status != 'ok'
                    or quantity.deliverable_refs != [link.released_ref for link in mapping.design_links]
                    or [line.model_dump(mode='json') for line in quantity.lines] != [
                        {'local_key': line.line_key, 'coverage_keys': list(line.coverage_keys),
                         'quantity': line.quantity.model_dump(mode='json')} for line in schedule.lines]):
                raise TaskConflict('Published quantity substitutes original document, schedule, line values or relation')
            source_questions = [row.model_dump(mode='json') for row in document.draft.open_questions]
            designs = []
            design_limitations = {}
            unique_refs([link.design_ref for link in mapping.design_links])
            if {link.design_ref for link in mapping.design_links} != set(schedule.design_refs):
                raise TaskConflict('Published quantity omits or replaces an original source design')
            for link in mapping.design_links:
                design = source_reading.resolve(link.design_ref)
                if (not isinstance(design, QSProcurementDesignView) or design.ref != link.design_ref
                        or task_digest(design.model_dump(mode='json')) != link.design_sha256):
                    raise TaskConflict('Published quantity changes the original design version or content')
                # Keep full references in provenance: a display ID alone must
                # not collapse two independently supplied design versions.
                designs.append({'ref': design.ref.model_dump(mode='json'),
                    'projection_sha256': link.design_sha256, 'limitations': list(design.limitations)})
                prior = design_limitations.get(design.ref.id)
                if prior is not None and prior != list(design.limitations):
                    raise TaskConflict('Quantity producer limitations collapse different versions of one design ID')
                design_limitations[design.ref.id] = list(design.limitations)
            if (result.get('source_open_questions') != source_questions
                    or result.get('source_design_limitations') != design_limitations):
                raise TaskConflict('Published quantity drops or changes original unresolved questions or design limitations')
            targets.append(quantity.ref)
            records.append({'ref': quantity.ref.model_dump(mode='json'),
                'value': self.bid_schemas.validate_projection(quantity.ref, quantity).model_dump(mode='json')})
            provenance.append({'mapping_ref': mapping.ref.model_dump(mode='json'),
                'document_ref': document.ref.model_dump(mode='json'), 'schedule_ref': schedule.ref.model_dump(mode='json'),
                'source_open_questions': source_questions, 'source_designs': designs,
                **{name: result[name] for name in
                   ('mapping_sha256', 'document_sha256', 'schedule_sha256', 'quantity_sha256')}})
        unique_refs(targets)
        source_reading.recheck()
        return self._publish_bid_additions(records, source_context=source_context, reading=reading,
            next_context=next_context, source_mode=mode, provenance={'quantity_provenance': provenance},
            validation={'kind': 'prepared', 'quantity_projections': deepcopy(prepared)},
            extra_recheck=source_reading.recheck)

    def publish_bid_programme(self, prepared, *, source_context, reading, next_context):
        """Publish the original authored whole-line programme with the existing A02 bundle."""
        from integration.contractor_bid_programme import ContractorBidProgrammeBasisView
        from src.actions.contracts.contractor_bid_objects import ContractorBidProgrammeView, ContractorBidQuantityView

        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or not isinstance(prepared, dict)
                or prepared.get('kind') != 'prepared'
                or prepared.get('context_sha256') != task_digest(source_context.model_dump(mode='json'))):
            raise TaskConflict('Programme publication requires its original A02 producer context')
        reading.check_method_context(source_context, 'CONTRACTOR-A02')
        programme = prepared.get('programme_projection')
        basis = reading.resolve(Reference.model_validate(prepared['basis_ref']))
        if (not isinstance(programme, ContractorBidProgrammeView) or not isinstance(basis, ContractorBidProgrammeBasisView)
                or programme.scope != source_context.scope or programme.available_at != source_context.business_time
                or not programme.effective_window.contains(source_context.business_time)
                or task_digest(programme.model_dump(mode='json')) != prepared.get('programme_sha256')
                or task_digest(basis.model_dump(mode='json')) != prepared.get('basis_sha256')
                or basis.run_id != source_context.run_id or basis.organization_id != reading.organization_id
                or basis.scope != programme.scope or programme.organization_id != basis.organization_id
                or programme.ref != basis.programme_ref or programme.package_ref != basis.package_ref
                or programme.quantity_refs != basis.quantity_refs or len(programme.tasks) != len(basis.tasks)
                or any(getattr(programme, name) != getattr(basis, name) for name in
                       ('author_actor_id', 'author_function_ref', 'author_authority_ref'))):
            raise TaskConflict('Programme publication substitutes its original projection, source basis or author')
        for source in basis.source_digests:
            row = reading.resolve(source.ref)
            if task_digest(row.model_dump(mode='json')) != source.sha256:
                raise TaskConflict('Programme source version changed before publication')
        assigned = set()
        for task, instruction in zip(programme.tasks, basis.tasks):
            if task.model_dump(mode='json', exclude={'target_quantities'}) != instruction.model_dump(mode='json'):
                raise TaskConflict('Programme publication changes original task instructions or allocations')
            targets = []
            for target in instruction.quantity_sources:
                quantity = reading.resolve(target.quantity_basis_ref)
                if not isinstance(quantity, ContractorBidQuantityView):
                    raise TaskConflict('Programme target lacks the original concrete quantity projection')
                lines = [line for line in quantity.lines if line.local_key == target.quantity_line_key]
                key = (target.quantity_basis_ref.key(), target.quantity_line_key)
                if len(lines) != 1 or lines[0].quantity.state != 'known' or key in assigned:
                    raise TaskConflict('Programme publication repeats or invents original whole-line targets')
                assigned.add(key)
                targets.append(lines[0].quantity.value.model_dump(mode='json'))
            if [row.model_dump(mode='json') for row in task.target_quantities] != targets:
                raise TaskConflict('Programme publication changes original planned quantity values or units')
        records = [{'ref': programme.ref.model_dump(mode='json'),
            'value': self.bid_schemas.validate_projection(programme.ref, programme).model_dump(mode='json')}]
        provenance = {'programme_provenance': {'basis_ref': basis.ref.model_dump(mode='json'),
            'basis_sha256': prepared['basis_sha256'], 'programme_sha256': prepared['programme_sha256'],
            'source_digests': [row.model_dump(mode='json') for row in basis.source_digests]}}
        return self._publish_bid_additions(records, source_context=source_context, reading=reading,
            next_context=next_context, source_mode=prepared.get('source_mode'), provenance=provenance,
            validation={'kind': 'prepared', 'programme_projection': deepcopy(prepared)})

    def publish_bid_tender_mapping(self, *, request, assembly, worker, identity,
            source_context, reading, next_context, mapping_ref, revalidate):
        """Publish an independently sourced mapping for one exact original saved bid.

        Caller holds the actual host guard. Reuse original proposal validation
        without calling client.propose, selecting a new decision or recording a
        proposal task. Indicators and authorizations must already be supplied.
        """
        from integration.bindings.gba_v1 import GbaV1Assembly
        from integration.bindings.gba_v1_tender_proposal import (
            GbaTenderProposalAdapter, GbaTenderProposalMappingView,
        )
        from integration.contractor_bid_results import ContractorBidResultWorker
        from src.coordination.tasks import TaskIdentity
        from src.actions.contracts.common import walk_references
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1

        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        if (not isinstance(assembly, GbaV1Assembly) or assembly.client.tasks is not self.store
                or not isinstance(worker, ContractorBidResultWorker) or worker.ACTION_ID != 'CONTRACTOR-A02'
                or worker.store is not self.store or worker.snapshots.store is not self.store
                or not isinstance(reading, ActionReadView) or reading._resolver.source_mode != 'formal'
                or source_context.execution_mode == 'offline_fixture' or context.execution_mode == 'offline_fixture'
                or not callable(revalidate)):
            raise TaskConflict('Tender mapping publication requires actual same-run formal assembly/worker/reading and validator')
        assembly._validate_components()
        reading.check_method_context(source_context, 'CONTRACTOR-A02')
        request = AgentProposalRequestV1.model_validate(request).model_copy(deep=True)
        identity = TaskIdentity(**identity.as_dict())
        if (identity.versions['client'] != assembly.client.versions['client']
                or identity.versions['model'] != assembly.client.versions['model']
                or identity.organization_id != request.agent.agent_id
                or worker.client_version != assembly.client.versions['client']
                or worker.model_version != assembly.client.versions['model']):
            raise TaskConflict('Tender mapping publication changes original bid versions or request recipient')
        mapping_ref = Reference.model_validate(mapping_ref)
        original_record = worker.get_record(identity)
        native_versions = deepcopy(assembly.client.versions)
        saved = worker.read_completed(identity, current_context=source_context,
            reading=reading, mapping_ref=mapping_ref)
        adapter = GbaTenderProposalAdapter(run_id=self.store.run_id,
            simulation_id=assembly.client.simulation_id, registry=worker.registry,
            read_output=lambda original_request: saved, revalidate=revalidate)
        checked = adapter(request)
        mapping = reading.resolve(mapping_ref)
        if not isinstance(mapping, GbaTenderProposalMappingView):
            raise TaskConflict('Tender mapping publication lacks its independently supplied original projection')
        target_grants = self.organizations.grants(context, 'CONTRACTOR-A02', 'Contractor')
        permitted = {ref.key() for grant in target_grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        required = [mapping.ref, *walk_references(mapping)]
        if any(ref.key() not in permitted for ref in required):
            raise TaskConflict('Tender mapping or its original dependencies exceed next-token read authority')
        value = self.bid_schemas.validate_projection(mapping.ref, mapping).model_dump(mode='json')
        records = [{'ref': mapping.ref.model_dump(mode='json'), 'value': value}]
        provenance = {'tender_mapping': {'mapping_ref': mapping.ref.model_dump(mode='json'),
            'mapping_sha256': task_digest(value), 'bid_identity': identity.as_dict(),
            'request_sha256': task_digest(request.model_dump(mode='json')),
            'result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'audit_sha256': task_digest(saved.audit),
            'checked_transport_sha256': task_digest(checked.model_dump(mode='json'))}}

        def recheck_original():
            assembly._validate_components()
            if (assembly.client.versions != native_versions or worker.get_record(identity) != original_record
                    or self.store.get(identity)['output'] != saved.result.model_dump(mode='json')):
                raise TaskConflict('Tender original result or execution versions changed during publication validation')

        return self._publish_bid_additions(records, source_context=source_context, reading=reading,
            next_context=context, source_mode='formal', provenance=provenance,
            extra_recheck=recheck_original,
            validation={'kind': 'prepared', 'tender_mapping': deepcopy(provenance['tender_mapping']),
                'mapping': deepcopy(value), 'request': request.model_dump(mode='json'),
                'context': saved.context.model_dump(mode='json'),
                'action_input': saved.action_input.model_dump(mode='json'),
                'result': saved.result.model_dump(mode='json'), 'audit': deepcopy(saved.audit)})

    def retain_bid_sources(self, *, source_context, reading, next_context):
        """Carry the exact published A02 sources to a fresh authorized token.

        This introduces no object or business result. The original immutable
        publication is retained under the same actor, scope and business time.
        """
        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        reading.check_method_context(source_context, 'CONTRACTOR-A02')
        grants = self.organizations.grants(source_context, 'CONTRACTOR-A02', 'Contractor')
        parent = self.read(source_context, organization_id=reading.organization_id, grants=grants)
        if parent is None or not parent['objects']:
            raise TaskConflict('Retained A02 sources require the original nonempty publication')
        provenance = {'retained_sources': {'publication_sha256': parent['record_sha256']}}
        return self._publish_bid_additions([], source_context=source_context, reading=reading,
            next_context=next_context, source_mode=parent['source_mode'], provenance=provenance,
            validation={'kind': 'prepared', **provenance})

    def _publish_bid_additions(self, records, *, source_context, reading, next_context,
            source_mode, provenance, validation, extra_recheck=None):
        """Retain the original authorized bundle and atomically add immutable A02 objects."""
        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        if (context.run_id != self.store.run_id or context.contract_ref.id != 'CONTRACTOR-A02'
                or source_context.contract_ref.id != 'CONTRACTOR-A02'
                or context.read_token == source_context.read_token
                or any(getattr(context, name) != getattr(source_context, name) for name in
                       ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('A02 additions require original identity, business time and a new authorized token')
        reading.check_method_context(source_context, 'CONTRACTOR-A02')
        grants = self.organizations.grants(context, 'CONTRACTOR-A02', 'Contractor')
        organization_id = grants[0].organization_id
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (reading.organization_id != organization_id or organization_id not in self.store.organization_ids
                or source_mode != mode):
            raise TaskConflict('A02 additions change the original Contractor or source mode')
        source_grants = self.organizations.grants(source_context, 'CONTRACTOR-A02', 'Contractor')
        parent = self.read(source_context, organization_id=organization_id, grants=source_grants)
        retained = [] if parent is None else deepcopy(parent['objects'])
        for item in retained:
            ref = Reference.model_validate(item['ref'])
            if reading.resolve(ref).model_dump(mode='json') != item['value']:
                raise TaskConflict('Retained publication differs from the current authorized source')
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        merged = {}
        for item in [*retained, *records]:
            ref = Reference.model_validate(item['ref'])
            if ref.key() not in permitted:
                raise TaskConflict('New or retained A02 objects exceed next read authority')
            if ref.key() in merged and merged[ref.key()] != item:
                raise TaskConflict('A02 additions cannot replace an original immutable object version')
            merged[ref.key()] = item
        unique_refs([Reference.model_validate(item['ref']) for item in merged.values()])
        validation = {**deepcopy(validation), 'retained_publication': deepcopy(parent)}
        if self.validate_source(validation, source_context.model_copy(deep=True)) is not None:
            raise TaskConflict('Actual new and retained sources require fresh host validation')
        reading.recheck()
        if extra_recheck is not None:
            extra_recheck()
        record = {'schema_version': self.SCHEMA, 'run_id': context.run_id, 'organization_id': organization_id,
            'source_context_sha256': task_digest(source_context.model_dump(mode='json')),
            'context': context.model_dump(mode='json'), 'source_mode': mode, 'objects': list(merged.values()),
            'projection_namespace': 'CONTRACTOR-A02', **deepcopy(provenance),
            'parent_publication_sha256': None if parent is None else parent['record_sha256']}
        record['record_sha256'] = task_digest(record)
        return self._save(context, organization_id, record, grants)

    def publish(self, prepared, *, source_context, reading, next_context, resource_projections=None):
        source_context = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A01'
                or source_context.contract_ref.id != 'CONTRACTOR-A01'
                or context.read_token == source_context.read_token
                or any(getattr(context, name) != getattr(source_context, name) for name in
                       ('run_id','actor_id','function_ref','contract_ref','scope','business_time','execution_mode'))
                or context.run_id != self.store.run_id or not isinstance(prepared, dict)
                or prepared.get('kind') != 'prepared'):
            raise TaskConflict('Tender publication requires original same-time A01 identity and a new read token')
        reading.check_method_context(source_context, 'CONTRACTOR-A01')
        grants = self.organizations.grants(context, 'CONTRACTOR-A01', 'Contractor')
        organization_id = grants[0].organization_id
        if organization_id != reading.organization_id or organization_id not in self.store.organization_ids:
            raise TaskConflict('Tender publication changes its original enterprise recipient')
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if prepared.get('source_mode') != mode:
            raise TaskConflict('Tender publication source mode differs from its actual invocation')
        package = prepared.get('projection')
        invitation = prepared.get('invitation_projection')
        if (not isinstance(package, ProcurementPackageView)
                or task_digest(package.model_dump(mode='json')) != prepared.get('projection_sha256')
                or package.scope != context.scope):
            raise TaskConflict('Produced package projection changed its original schema, digest or scope')
        objects = [package]
        if invitation is not None:
            if (not isinstance(invitation, InvitationView) or invitation.package_ref != package.ref
                    or invitation.issuer_ref != package.employer_ref or invitation.recipient_actor_id != context.actor_id
                    or task_digest(invitation.model_dump(mode='json')) != prepared.get('invitation_sha256')):
                raise TaskConflict('Produced native invitation projection changes original package, recipient or digest')
            objects.append(invitation)
        resource_provenance = None
        if resource_projections is not None:
            if (not isinstance(resource_projections, dict) or resource_projections.get('kind') != 'prepared'
                    or resource_projections.get('source_mode') != mode
                    or resource_projections.get('context_sha256') != task_digest(source_context.model_dump(mode='json'))):
                raise TaskConflict('Screening resource publication changes original source context or mode')
            capability = resource_projections.get('capability_projection')
            commitments = resource_projections.get('commitments_projection')
            if (not isinstance(capability, ContractorCapabilityView) or not isinstance(commitments, CommitmentSnapshotView)
                    or capability.organization_ref != commitments.organization_ref
                    or capability.organization_ref.id != organization_id or commitments.as_of != context.business_time
                    or task_digest(capability.model_dump(mode='json')) != resource_projections.get('capability_sha256')
                    or task_digest(commitments.model_dump(mode='json')) != resource_projections.get('commitments_sha256')):
                raise TaskConflict('Produced capability/commitments change original enterprise, time or content')
            resource_provenance = {name:resource_projections.get(name) for name in
                ('source_record_sha256','capacity_input_sha256','enterprise_facts_sha256')}
            for digest in resource_provenance.values():
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise TaskConflict('Produced resource projections lack original source/calendar/competence provenance')
            objects.extend((capability, commitments))
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        if any(obj.ref.key() not in permitted for obj in objects):
            raise TaskConflict('Produced tender objects are outside the actual next invocation authority')
        for name in ('source_record_sha256', 'terms_sha256'):
            digest = prepared.get(name)
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise TaskConflict('Tender publication lacks original source/terms provenance')
        validation_input = deepcopy(prepared)
        if resource_projections is not None:
            validation_input['resource_projections'] = deepcopy(resource_projections)
        # For a complete bundle the host must validate BOTH original source
        # records and independent terms/facts at the same current read point.
        if self.validate_source(validation_input, source_context.model_copy(deep=True)) is not None:
            raise TaskConflict('Actual current source and original terms must be revalidated before publication')
        reading.recheck()
        records = []
        for obj in objects:
            value = self.schemas.validate_projection(obj.ref, obj)
            item = {'ref':obj.ref.model_dump(mode='json'), 'value':value.model_dump(mode='json')}
            records.append(item)
        record = {'schema_version':self.SCHEMA, 'run_id':context.run_id, 'organization_id':organization_id,
            'source_context_sha256':task_digest(source_context.model_dump(mode='json')),
            'context':context.model_dump(mode='json'), 'source_mode':mode, 'objects':records,
            'source_record_sha256':prepared['source_record_sha256'], 'terms_sha256':prepared['terms_sha256']}
        if resource_provenance is not None:
            record['resource_provenance'] = resource_provenance
        record['record_sha256'] = task_digest(record)
        return self._save(context,organization_id,record,grants)

    def _save(self, context, organization_id, record, grants):
        """Use the original publication transaction for both explicit action views."""
        key = self._key(context, organization_id)
        records = record['objects']
        with self.store._transaction():
            if self.organizations.grants(context, context.contract_ref.id, 'Contractor') != grants:
                raise TaskConflict('Tender publication authority changed during preparation')
            prior = self.store._db.execute('SELECT record FROM gba_tender_publications WHERE publication_key=?',(key,)).fetchone()
            if prior is not None:
                if json.loads(prior[0]) != record:
                    raise TaskConflict('Published tender read point cannot be changed')
                return deepcopy(record)
            for item in records:
                ref_key = self._object_key(context,item['ref'])
                saved = self.store._db.execute('SELECT record FROM gba_tender_published_objects WHERE ref_key=?',(ref_key,)).fetchone()
                if saved is not None and json.loads(saved[0]) != item:
                    raise TaskConflict('Original tender object version cannot be overwritten')
                if saved is None:
                    self.store._db.execute('INSERT INTO gba_tender_published_objects VALUES (?,?)',(ref_key,canonical(item)))
            self.store._db.execute('INSERT INTO gba_tender_publications VALUES (?,?)',(key,canonical(record)))
        return deepcopy(record)

    def read(self, context, *, organization_id, grants):
        context = ActionContext.model_validate(context)
        action_id = context.contract_ref.id
        if action_id not in {'CONTRACTOR-A01','CONTRACTOR-A02'}:
            return None
        schemas = self.schemas if action_id == 'CONTRACTOR-A01' else self.bid_schemas
        current = self.organizations.grants(context, action_id, 'Contractor')
        if current != grants or current[0].organization_id != organization_id:
            raise TaskConflict('Tender publication read changes the actual current authorization')
        with self.store._lock:
            saved = self.store._db.execute('SELECT record FROM gba_tender_publications WHERE publication_key=?',
                (self._key(context, organization_id),)).fetchone()
            if saved is None:
                return None
            record = json.loads(saved[0])
            if (record.get('schema_version') != self.SCHEMA or record.get('run_id') != self.store.run_id
                    or record.get('organization_id') != organization_id
                    or record.get('context') != context.model_dump(mode='json')
                    or task_digest({k:v for k,v in record.items() if k != 'record_sha256'}) != record.get('record_sha256')):
                raise TaskConflict('Stored tender publication changes its original identity or digest')
            if action_id == 'CONTRACTOR-A02' and record.get('projection_namespace') != action_id:
                raise TaskConflict('Bid publication loses its explicit action-specific projection identity')
            permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
            permitted &= {ref.key() for ref in context.visible_refs}
            for item in record['objects']:
                ref = Reference.model_validate(item['ref'])
                if ref.key() not in permitted:
                    raise TaskConflict('Published tender object is no longer authorized')
                schemas.validate_projection(ref, item['value'])
                stored = self.store._db.execute('SELECT record FROM gba_tender_published_objects WHERE ref_key=?',
                    (self._object_key(context,item['ref']),)).fetchone()
                if stored is None or json.loads(stored[0]) != item:
                    raise TaskConflict('Published tender object version differs from the original publication')
            return deepcopy(record)


class GbaTenderPublishedViewProvider:
    """Merge published objects into the real provider's authorized new read point."""
    def __init__(self, *, provider, publications):
        if not callable(getattr(provider, 'project', None)) or not isinstance(publications, GbaTenderPublicationStore):
            raise ValueError('Actual host view provider and original tender publication store required')
        self.provider, self.publications = provider, publications

    def project(self, *, context, organization_id, grants):
        raw = deepcopy(self.provider.project(context=context.model_copy(deep=True),
            organization_id=organization_id, grants=deepcopy(grants)))
        publication = self.publications.read(context, organization_id=organization_id, grants=grants)
        if publication is None:
            return raw
        if (not isinstance(raw, dict) or raw.get('run_id') != context.run_id
                or raw.get('read_token') != context.read_token or raw.get('organization_id') != organization_id
                or raw.get('business_time') != context.business_time.model_dump()
                or not isinstance(raw.get('objects'), list)):
            raise TaskConflict('Host provider changes the published tender read point')
        objects = {Reference.model_validate(item['ref']).key():item for item in raw['objects']}
        if len(objects) != len(raw['objects']):
            raise TaskConflict('Host provider repeats an original object version')
        for item in publication['objects']:
            key = Reference.model_validate(item['ref']).key()
            if key in objects and objects[key] != item:
                raise TaskConflict('Host source conflicts with an immutable produced tender object')
            objects[key] = item
        raw['objects'] = list(objects.values())
        raw['state_version'] = task_digest({'host_state_version':raw['state_version'],
            'tender_publication_sha256':publication['record_sha256']})
        return raw
