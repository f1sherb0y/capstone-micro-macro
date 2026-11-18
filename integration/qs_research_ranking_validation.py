"""Reread actual ranking sources and retained normalization proof without formulas."""
from copy import deepcopy
import json

from integration.module_host import module_factory_descriptor
from integration.qs_research_normalization_calculations import _ranking_preparation_payload
from integration.qs_research_normalization_publication import QSResearchNormalizationPublicationStore
from integration.qs_research_normalization_validation import QSResearchNormalizationSourceValidator
from src.actions.contracts.common import ActionContext, Reference, ref_type, walk_references
from src.actions.contracts.qs_research_objects import QSResearchMethodProjection, QSResearchProfileView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_research import prepare_qs_research_ranking_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.qs_research import (
    RESEARCH_NORMALIZE_METHOD, RESEARCH_RANK_METHOD, ResearchRankInput, ResearchRankReport,
    ResearchNormalizationInput, ResearchNormalizationReport,
)


class QSResearchRankingSourceValidator(QSResearchNormalizationSourceValidator):
    """Read beneath publication wrappers; actual criteria/risk verifier is required.

    Rebuild comparable original costs without normalization or ranking formulas.
    Retained normalization must belong to the original journal and exact source
    versions. Validate its recorded method proof and independent actual source
    gate, leaving pure mathematical report checks to the publication stores.
    """
    VERSION = 'qs-research-ranking-source-validator.v1'
    RESULT_KIND = 'ranking'
    METHOD_REF = RESEARCH_RANK_METHOD
    INPUT_MODEL = ResearchRankInput
    REPORT_MODEL = ResearchRankReport
    PREPARE_INPUT = staticmethod(prepare_qs_research_ranking_input)
    PREPARATION_PAYLOAD = staticmethod(_ranking_preparation_payload)

    def __init__(self, *, normalizations, validate_ranking_basis, **components):
        if (type(normalizations) is not QSResearchNormalizationPublicationStore
                or normalizations.registry is not components.get('registry')
                or normalizations.organizations is not components.get('organizations')
                or normalizations.store.run_id != normalizations.organizations.run_id
                or not callable(validate_ranking_basis)):
            raise ValueError('Research ranking validation requires original normalization journal and actual criteria/risk verifier')
        self.normalizations = normalizations
        self._normalization_components = (normalizations, normalizations.store, normalizations.registry,
            normalizations.organizations, normalizations.methods, normalizations.validate_source, normalizations.schemas)
        self.validate_ranking_basis = validate_ranking_basis
        super().__init__(validate_normalization_basis=validate_ranking_basis, **components)
        self._declared['normalization_provenance_runtime'] = module_factory_descriptor(
            type(self).validate_normalization_provenance, self.VERSION + '.normalization_provenance')
        self._declared['normalization_proof_runtime'] = module_factory_descriptor(
            normalizations._validate_method_execution, self.VERSION + '.normalization_proof')
        self._declared['normalization_actual_source'] = module_factory_descriptor(
            normalizations.validate_source, self.VERSION + '.normalization_actual_source')
        self._declared['normalization_binding'] = normalizations._binding()

    def _check(self):
        super()._check()
        current = (self.normalizations, self.normalizations.store, self.normalizations.registry,
            self.normalizations.organizations, self.normalizations.methods,
            self.normalizations.validate_source, self.normalizations.schemas)
        if (any(actual is not original for actual, original in zip(current, self._normalization_components))
                or self.validate_ranking_basis is not self._basis_verifier
                or self.normalizations.registry is not self.registry or self.normalizations.organizations is not self.organizations
                or self.normalizations.ACTION_ID != self.ACTION_ID or self.normalizations.ROLE != self.ROLE
                or self.normalizations.METHOD_REF != RESEARCH_NORMALIZE_METHOD
                or self.normalizations._binding() != self._declared['normalization_binding']
                or module_factory_descriptor(type(self).validate_normalization_provenance,
                    self.VERSION + '.normalization_provenance') != self._declared['normalization_provenance_runtime']
                or module_factory_descriptor(self.normalizations._validate_method_execution,
                    self.VERSION + '.normalization_proof') != self._declared['normalization_proof_runtime']
                or module_factory_descriptor(self.normalizations.validate_source,
                    self.VERSION + '.normalization_actual_source') != self._declared['normalization_actual_source']):
            raise TaskConflict('Research ranking changed original normalization journal, actual verifier or proof/source binding')

    def _matches_output(self, row, report):
        return row.ranked_groups == report.ranked_groups and not row.normalized_costs

    def _local_dependency_sources(self, context, action_input, preparation, originals, actual, *, profile, saved_projection):
        """Add only the original published normalization beneath source wrappers.

        Production requires publication at this authorized token. A retained
        ranking record may carry that same dependency to its later publication
        token; revalidate the persisted normalization and actual original sources
        without reading a ranking publication recursively or executing formulas.
        """
        ref = profile.normalization_result_ref
        if ref is None:
            return actual
        grants = self.organizations.grants(context, self.ACTION_ID, self.ROLE)
        permitted = {item.key() for grant in grants for item in grant.readable_refs}
        permitted &= {item.key() for item in context.visible_refs}
        if ref.key() not in permitted:
            raise TaskConflict('Local ranking dependency lacks current normalization read permission')
        boundary = task_digest([context.run_id, grants[0].organization_id, context.read_token])
        with self.normalizations.store._lock:
            raw = self.normalizations.store._db.execute(
                f'SELECT record FROM {self.normalizations.PUBLICATIONS_TABLE} WHERE boundary_key=?', (boundary,)).fetchone()
        publication = None
        if raw is not None:
            publication = json.loads(raw[0])
            if (not isinstance(publication, dict) or set(publication) != {'schema_version', 'context', 'organization_id',
                    'execution_sha256', 'object', 'record_sha256'}
                    or publication['schema_version'] != self.normalizations.PUBLICATION_SCHEMA
                    or publication['context'] != context.model_dump(mode='json')
                    or publication['organization_id'] != grants[0].organization_id
                    or publication['record_sha256'] != task_digest({k:v for k,v in publication.items() if k != 'record_sha256'})
                    or not isinstance(publication['object'], dict) or set(publication['object']) != {'ref', 'value'}
                    or publication['object']['ref'] != ref.model_dump(mode='json')):
                raise TaskConflict('Local ranking dependency replaces original normalization publication or read boundary')
            content = publication['object']['value']
        elif saved_projection is not None:
            rows = [row for row in originals if row['ref'] == ref.model_dump(mode='json')]
            if len(rows) != 1:
                raise TaskConflict('Saved ranking lacks its exact original carried normalization dependency')
            content = rows[0]['projection']
        else:
            raise TaskConflict('Ranking production requires original normalization published at its current read token')
        dependency = self.normalizations.schemas.validate_projection(ref, content)
        if dependency.model_dump(mode='json') != content or ref.key() in actual and actual[ref.key()] != dependency:
            raise TaskConflict('Local normalization publication conflicts with an actual native source version')
        augmented = {**actual, ref.key(): dependency}
        records = [{'ref': {'kind': key[0], 'id': key[1], 'version': key[2]},
            'projection': value.model_dump(mode='json')} for key, value in augmented.items()]
        retained = self._normalization_record(context, action_input, preparation, records)
        original_context = ActionContext.model_validate(retained['context'])
        if (publication is not None and publication['execution_sha256'] != retained['record_sha256']
                or original_context.read_token == context.read_token
                or original_context.business_time != context.business_time):
            raise TaskConflict('Local normalization dependency lacks original saved execution and same-time fresh publication token')
        with self.normalizations.store._lock:
            if self.normalizations.store._db.execute(
                    f'SELECT record FROM {self.normalizations.PUBLICATIONS_TABLE} WHERE boundary_key=?', (boundary,)).fetchone() != raw:
                raise TaskConflict('Local normalization publication changed during independent ranking source validation')
        return augmented

    def _normalization_record(self, context, action_input, preparation, original_sources):
        """Check original retained proof by hashing only; execute no store arithmetic."""
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(action_input)
        sources = {}
        for row in original_sources:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Research ranking provenance requires closed original source records')
            key = Reference.model_validate(row['ref']).key()
            if key in sources:
                raise TaskConflict('Research ranking provenance repeats an original reference version')
            sources[key] = row
        profile_ref = ref_type('ComparisonProfile').model_validate(preparation['profile_ref'])
        profile = QSResearchProfileView.model_validate(sources[profile_ref.key()]['projection'])
        ref = profile.normalization_result_ref
        if (profile.task_ref != action_input.task_ref or profile.comparison_basis_ref != action_input.comparison_basis_ref
                or preparation['normalization_result_ref'] != (ref.model_dump(mode='json') if ref else None)):
            raise TaskConflict('Research ranking changes original normalization dependency or source profile')
        if ref is None:
            return None
        ref_key = task_digest([context.run_id, self.ACTION_ID, ref.model_dump(mode='json')])
        with self.normalizations.store._lock:
            raw = self.normalizations.store._db.execute(
                f'SELECT record FROM {self.normalizations.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone()
        if raw is None:
            raise TaskConflict('Research ranking lacks its actual original persisted normalization execution')
        record = json.loads(raw[0])
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.normalizations.SCHEMA
                or record['binding'] != self.normalizations._binding()
                or record['record_sha256'] != task_digest({k:v for k,v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Research ranking dependency changes original normalization schema, binding or digest')
        saved = record['prepared']
        original_context = ActionContext.model_validate(record['context'])
        projection = QSResearchMethodProjection.model_validate(saved['projection'])
        if (projection.comparison is None or projection.ref != ref
                or saved['projection'] != sources.get(ref.key(), {}).get('projection')
                or record['organization_id'] != self.organizations.grants(context, self.ACTION_ID, self.ROLE)[0].organization_id
                or any(getattr(original_context, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'execution_mode'))
                or original_context.business_time.clock_ref != context.business_time.clock_ref
                or original_context.business_time.offset > context.business_time.offset
                or record['action_input'] != action_input.model_dump(mode='json')):
            raise TaskConflict('Research ranking substitutes original normalization output, identity or invocation')
        data = ResearchNormalizationInput.model_validate(saved['method_execution']['input'])
        result = MethodOk[ResearchNormalizationReport].model_validate(saved['method_execution']['result'])
        if (set(saved['method_execution']) != {'method_ref', 'registry_digest', 'input', 'result'}
                or result.method_ref != RESEARCH_NORMALIZE_METHOD
                or projection.comparison.normalized_costs != result.value.normalized_costs
                or projection.comparison.ranked_groups):
            raise TaskConflict('Research ranking normalization dependency changes original proof or report')
        originals = {}
        for row in saved['source_reading']:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Original normalization cache repeats a dependency source version')
            originals[key] = row
        for dependency in {ref.key():ref for ref in [*data.source_refs, *walk_references(data)]}.values():
            if dependency.key() not in originals or sources.get(dependency.key()) != originals[dependency.key()]:
                raise TaskConflict('Research ranking changes original normalization quantity/price/coverage or adjustment sources')
        self.normalizations._validate_method_execution(context=original_context, arithmetic=data,
            execution=saved['method_execution'], originals={key:row['projection'] for key,row in originals.items()}, result=result)
        if self.normalizations.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Research ranking normalization dependency lacks actual current source validation')
        with self.normalizations.store._lock:
            if self.normalizations.store._db.execute(
                    f'SELECT record FROM {self.normalizations.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone() != raw:
                raise TaskConflict('Original normalization execution changed during ranking source validation')
        self._check()
        return record

    def validate_normalization_provenance(self, *, context, action_input, preparation, original_sources, reading):
        """Producer dependency gate: retain exact cache and execute no formula or method."""
        if (not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations
                or reading.evidence() != original_sources):
            raise TaskConflict('Research ranking provenance changes original authorized source reading')
        reading.check_method_context(context, self.ACTION_ID)
        before = reading.method_evidence()
        self._normalization_record(context, action_input, preparation, original_sources)
        if reading.method_evidence() != before or reading.evidence() != original_sources:
            raise TaskConflict('Research ranking provenance gate changed cache or executed a method')
        reading.recheck()
        self._check()
        return True

    def validate_source(self, record, context):
        """Save/publication/read gate includes the original persisted dependency proof."""
        super().validate_source(record, context)
        saved = record['prepared']
        self._normalization_record(context, record['action_input'], saved['preparation'], saved['source_reading'])
        self._check()
        return True
