"""Rebuild exact authorized source projections before technical tender publication."""
from contextlib import nullcontext

from pydantic import BaseModel

from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
from integration.bindings.gba_v1_tender_package import GbaTenderPackageTermsView
from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalAdapter
from integration.contractor_bid_costs import prepare_contractor_bid_cost
from integration.contractor_bid_programme import prepare_contractor_bid_programme
from integration.contractor_bid_quantities import prepare_contractor_bid_quantity
from integration.contractor_tender_native_publication import validate_native_publication
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class TenderNativePublicationSources(StrictRecord):
    project_id: TextId | None = None
    terms_ref: ref_type('GbaTenderPackageTerms') | None = None
    screening_facts_ref: ref_type('GbaScreeningEnterpriseFacts') | None = None
    bid_facts_ref: ref_type('GbaBidEnterpriseFacts') | None = None


class TenderPublicationValidationSettings(StrictRecord):
    native_sources: dict[TextId, TenderNativePublicationSources]


def _plain(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _same(original, current, description):
    if _plain(original) != _plain(current):
        raise TaskConflict('Publication changes its original ' + description)


def _retained(prepared, context, reading, pipeline, grants):
    parent = pipeline.publications.read(context, organization_id=reading.organization_id, grants=grants)
    _same(prepared['retained_publication'], parent, 'journal parent publication')
    if parent is not None:
        for item in parent['objects']:
            _same(item['value'], reading.resolve(Reference.model_validate(item['ref'])),
                'retained authorized source projection')


def _mapping(prepared, context, reading, application):
    pipeline = application.host.pipeline
    provenance = prepared['tender_mapping']
    if not isinstance(provenance, dict):
        raise TaskConflict('Publication requires the original tender mapping provenance')
    identity = TaskIdentity(**provenance['bid_identity'])
    if (identity.run_id != context.run_id or identity.organization_id != reading.organization_id
            or identity.role != 'Contractor' or identity.action_id != 'CONTRACTOR-A02'
            or identity.purpose != 'action'
            or identity.versions['client'] != pipeline.worker.client_version
            or identity.versions['model'] != pipeline.worker.model_version):
        raise TaskConflict('Publication changes its original saved bid identity or versions')
    mapping_ref = Reference.model_validate(provenance['mapping_ref'])
    original_record = pipeline.worker.get_record(identity)
    saved = pipeline.worker.read_completed(identity, current_context=context,
        reading=reading, mapping_ref=mapping_ref)
    pipeline.assembler.check_execution_versions(identity, context=saved.context)
    for name in ('context', 'action_input', 'result', 'audit'):
        _same(prepared[name], getattr(saved, name), 'saved bid ' + name)
    mapping = reading.resolve(mapping_ref)
    _same(prepared['mapping'], mapping, 'independently supplied tender indicators')
    # This adapter validates saved output only. It does not call client.propose,
    # run a processor, submit a bid or create another native request.
    revalidate = application.host.callbacks.revalidate
    if application.host.callbacks.validate_mapping is not None:
        def revalidate(**kwargs):
            return application.host.callbacks.validate_mapping(identity=identity,
                mapping_ref=mapping_ref, **kwargs)
    adapter = GbaTenderProposalAdapter(run_id=application.store.run_id,
        simulation_id=application.assembly.client.simulation_id, registry=pipeline.worker.registry,
        read_output=lambda request: saved, revalidate=revalidate)
    checked = adapter(prepared['request'])
    expected = {'mapping_ref': mapping_ref.model_dump(mode='json'),
        'mapping_sha256': task_digest(_plain(mapping)), 'bid_identity': identity.as_dict(),
        'request_sha256': task_digest(prepared['request']), 'result_sha256': task_digest(_plain(saved.result)),
        'audit_sha256': task_digest(saved.audit), 'checked_transport_sha256': task_digest(_plain(checked))}
    _same(provenance, expected, 'request/result/audit/transport provenance')
    _same(pipeline.worker.get_record(identity), original_record, 'persistent bid result record')


def validate_publication(prepared, context, *, application, settings):
    """Configured professional.publication callback; caller holds the writer guard.

    Native refs are selected explicitly by operation_id. Documentary producers
    rerun only their read/prepare paths and retain separate professional gates.
    Success authorizes technical projection storage, never a native receipt,
    independent qualification, actual quantity, booking or payment effect.
    """
    config = TenderPublicationValidationSettings.model_validate(settings).model_copy(deep=True)
    context = ActionContext.model_validate(context).model_copy(deep=True)
    application._check()
    if (application.host is None or context.run_id != application.store.run_id
            or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id not in {'CONTRACTOR-A01', 'CONTRACTOR-A02'}
            or not isinstance(prepared, dict) or prepared.get('kind') != 'prepared'):
        raise TaskConflict('Publication requires the installed original application and Contractor context')
    application.host._check(bound=True)
    pipeline = application.host.pipeline
    grants = application.organizations.grants(context, context.contract_ref.id, 'Contractor')
    authority_sha256 = task_digest(_plain(grants))
    sources = config.native_sources.get(context.operation_id)
    if context.contract_ref.id == 'CONTRACTOR-A01':
        if sources is None or sources.project_id is None or sources.terms_ref is None:
            raise TaskConflict('A01 publication requires explicit original project and terms refs')
        schemas = gba_contractor_screening_source_schemas()
        schemas.register_kind('GbaTenderPackageTerms', GbaTenderPackageTermsView, str)
        views = AuthorizedMacroViewAssembler(application.organizations, pipeline.assembler.provider,
            schemas, macro_version=pipeline.assembler.macro_version, source_mode=pipeline.assembler.source_mode)
        reading = ActionReadView(context, views.build_resolver(context, 'CONTRACTOR-A01', 'Contractor'),
            application.organizations, 'CONTRACTOR-A01', 'Contractor')
        rebuilt = application.assembly.prepare_tender_package(context=context, reading=reading,
            project_id=sources.project_id, read_guard=nullcontext, terms_ref=sources.terms_ref)
        if 'resource_projections' in prepared:
            if sources.screening_facts_ref is None:
                raise TaskConflict('A01 bundle requires its explicitly configured enterprise facts')
            rebuilt['resource_projections'] = application.assembly.prepare_screening_resources(
                context=context, reading=reading, read_guard=nullcontext, facts_ref=sources.screening_facts_ref)
        _same(prepared, rebuilt, 'complete native package/resource producer output')
        validate_native_publication(assembly=application.assembly, organizations=application.organizations,
            prepared=prepared, context=context, project_id=sources.project_id)
    else:
        additions = {'cost_projections', 'quantity_projections', 'programme_projection', 'tender_mapping', 'retained_sources'}
        branches = additions.intersection(prepared)
        if not branches:
            if sources is None or sources.bid_facts_ref is None or 'capacity_projection' not in prepared:
                raise TaskConflict('A02 capacity requires explicit original enterprise facts and producer output')
            reading = pipeline.assembler.build_capacity_reading(context)
            rebuilt = application.assembly.prepare_bid_capacity(context=context, reading=reading,
                read_guard=nullcontext, facts_ref=sources.bid_facts_ref)
            _same(prepared, rebuilt, 'complete native capacity producer output')
            validate_native_publication(assembly=application.assembly, organizations=application.organizations,
                prepared=prepared, context=context)
        else:
            if len(branches) != 1:
                raise TaskConflict('Publication mixes independently prepared addition routes')
            branch = next(iter(branches))
            expected_keys = {'kind', 'retained_publication', branch}
            if branch == 'tender_mapping':
                expected_keys.update({'mapping', 'request', 'context', 'action_input', 'result', 'audit'})
            if set(prepared) != expected_keys:
                raise TaskConflict('Publication addition has missing or unexpected original fields')
            reading = (pipeline.assembler.build_result_reading(context) if branch == 'tender_mapping'
                else pipeline.assembler.build_capacity_reading(context))
            _retained(prepared, context, reading, pipeline, grants)
            if branch == 'retained_sources':
                parent = prepared['retained_publication']
                if (parent is None or not parent['objects'] or prepared[branch] != {
                        'publication_sha256': parent['record_sha256']}):
                    raise TaskConflict('Retained A02 sources differ from the exact original publication')
            elif branch == 'tender_mapping':
                _mapping(prepared, context, reading, application)
            elif branch == 'programme_projection':
                original = prepared[branch]
                rebuilt = prepare_contractor_bid_programme(context=context, reading=reading,
                    basis_ref=original['basis_ref'], validate_current=application.programme)
                _same(original, rebuilt, 'complete programme producer output')
            else:
                originals = prepared[branch]
                if not isinstance(originals, list) or not originals:
                    raise TaskConflict('Publication requires a nonempty exact prepared addition set')
                source_reading = (pipeline.assembler.build_quantity_source_reading(context,
                    source_provider=pipeline.source_provider) if branch == 'quantity_projections' else None)
                for original in originals:
                    if branch == 'cost_projections':
                        rebuilt = prepare_contractor_bid_cost(context=context, reading=reading,
                            adoption_ref=original['adoption_ref'], validate_current=application.cost)
                    else:
                        rebuilt = prepare_contractor_bid_quantity(context=context, reading=reading,
                            source_reading=source_reading, mapping_ref=original['mapping_ref'],
                            validate_current=application.quantity)
                    _same(original, rebuilt, 'complete original ' + branch + ' producer output')
                if source_reading is not None:
                    source_reading.recheck()
            _retained(prepared, context, reading, pipeline, grants)
    reading.recheck()
    current_grants = application.organizations.grants(context, context.contract_ref.id, 'Contractor')
    if task_digest(_plain(current_grants)) != authority_sha256:
        raise TaskConflict('Original publication authority changed during source validation')
    application.host._check(bound=True)
    application._check()
