"""Persist QS A13 ranking proof and carry its exact saved normalization dependency."""
import json

from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from integration.qs_research_normalization_calculations import _ranking_preparation_payload
from integration.qs_research_normalization_publication import QSResearchNormalizationPublicationStore
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.qs_research_objects import QSResearchProfileView
from src.actions.roles.qs_research import prepare_qs_research_ranking_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_research import (
    RESEARCH_RANK_METHOD, ResearchRankInput, ResearchRankReport, ResearchNormalizationInput, rank_plans,
)


class QSResearchRankingPublicationStore(QSResearchNormalizationPublicationStore):
    """Immutable ranking journal linked to the original same-journal normalization.

    Retain exact input/source/method proof and tied groups; never replay methods.
    Actual current source checks remain mandatory on save, publication and read.
    Publishing carries the original normalization to the ranking's fresh token,
    with no new cost plan, research authorization or investment effect.
    """
    SCHEMA = 'qs-research-ranking-record.v1'
    PUBLICATION_SCHEMA = 'qs-research-ranking-publication.v1'
    METHOD_REF = RESEARCH_RANK_METHOD
    RECORDS_TABLE = 'qs_research_ranking_records'
    PUBLICATIONS_TABLE = 'qs_research_ranking_publications'
    RESULT_KIND = 'ranking'
    INPUT_MODEL = ResearchRankInput
    REPORT_MODEL = ResearchRankReport
    PREPARE_INPUT = staticmethod(prepare_qs_research_ranking_input)
    PREPARATION_PAYLOAD = staticmethod(_ranking_preparation_payload)
    PURE_REPORT = staticmethod(rank_plans)

    def __init__(self, *, normalizations, **components):
        if (type(normalizations) is not QSResearchNormalizationPublicationStore
                or normalizations.store is not components.get('store')
                or normalizations.registry is not components.get('registry')
                or normalizations.methods is not components.get('methods')
                or normalizations.organizations is not components.get('organizations')):
            raise ValueError('Research ranking persistence requires its original same-journal normalization store')
        self.normalizations = normalizations
        self._normalization_components = (normalizations, normalizations.store, normalizations.registry,
            normalizations.methods, normalizations.organizations, normalizations.validate_source)
        super().__init__(**components)

    def _matches_output(self, comparison, report):
        return comparison.ranked_groups == report.ranked_groups and not comparison.normalized_costs

    def _validate_normalization(self, record):
        """Check retained dependency rows without actual source callbacks in transactions."""
        current = (self.normalizations, self.normalizations.store, self.normalizations.registry,
            self.normalizations.methods, self.normalizations.organizations, self.normalizations.validate_source)
        if (any(actual is not original for actual, original in zip(current, self._normalization_components))
                or self.normalizations.store is not self.store or self.normalizations.registry is not self.registry
                or self.normalizations.methods is not self.methods or self.normalizations.organizations is not self.organizations):
            raise TaskConflict('Research ranking lost its original normalization store binding')
        sources = {}
        for row in record['prepared']['source_reading']:
            key = Reference.model_validate(row['ref']).key()
            if key in sources:
                raise TaskConflict('Research ranking dependency source cache repeats an original reference')
            sources[key] = row
        profile_ref = Reference.model_validate(record['prepared']['preparation']['profile_ref'])
        profile = QSResearchProfileView.model_validate(sources[profile_ref.key()]['projection'])
        ref = profile.normalization_result_ref
        if record['prepared']['preparation']['normalization_result_ref'] != (ref.model_dump(mode='json') if ref else None):
            raise TaskConflict('Research ranking substitutes its declared normalization dependency')
        if ref is None:
            return None
        ref_key = task_digest([self.store.run_id, self.ACTION_ID, ref.model_dump(mode='json')])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.normalizations.RECORDS_TABLE} WHERE ref_key=?',
                (ref_key,)).fetchone()
        if raw is None:
            raise TaskConflict('Research ranking requires its original persisted normalization execution')
        normalization = json.loads(raw[0])
        original, projection = self.normalizations._validate(normalization)
        context = ActionContext.model_validate(record['context'])
        if (normalization['organization_id'] != record['organization_id'] or projection.ref != ref
                or sources.get(ref.key(), {}).get('projection') != projection.model_dump(mode='json')
                or any(getattr(original, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'execution_mode'))
                or original.business_time.clock_ref != context.business_time.clock_ref
                or original.business_time.offset > context.business_time.offset
                or normalization['action_input'] != record['action_input']):
            raise TaskConflict('Research ranking substitutes original normalization output or source invocation')
        data = ResearchNormalizationInput.model_validate(normalization['prepared']['method_execution']['input'])
        originals = {Reference.model_validate(row['ref']).key(): row for row in normalization['prepared']['source_reading']}
        for dependency in {ref.key(): ref for ref in [*data.source_refs, *walk_references(data)]}.values():
            if dependency.key() not in originals or sources.get(dependency.key()) != originals[dependency.key()]:
                raise TaskConflict('Research ranking changes original normalization cost, scope, authority or adjustment sources')
        return normalization

    def _validate(self, record):
        context, projection = super()._validate(record)
        self._validate_normalization(record)
        return context, projection

    def _save_targets(self, record, projection, *, is_new):
        self._validate_normalization(record)

    def _validate_saved_targets(self, record, projection):
        self._validate_normalization(record)

    def _publication_content(self, projection):
        ref_key = task_digest([self.store.run_id, self.ACTION_ID, projection.ref.model_dump(mode='json')])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone()
        if raw is None:
            raise TaskConflict('Research ranking publication requires its original saved record')
        record = json.loads(raw[0])
        if (record['record_sha256'] != task_digest({k:v for k,v in record.items() if k != 'record_sha256'})
                or record['prepared']['projection'] != projection.model_dump(mode='json')):
            raise TaskConflict('Research ranking publication changes its original retained projection')
        normalization = self._validate_normalization(record)
        dependencies = ([] if normalization is None else [{'ref': normalization['prepared']['projection']['ref'],
            'value': normalization['prepared']['projection']}])
        return {**super()._publication_content(projection), 'dependencies': dependencies}

    def _published_objects(self, publication):
        return [publication['object'], *publication['dependencies']]


class QSResearchRankingPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSResearchRankingPublicationStore):
            raise ValueError('Research ranking provider requires its original QS A13 ranking store')
        super().__init__(provider=provider, publications=publications)
