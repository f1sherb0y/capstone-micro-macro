"""Retain QS-A06 rankings linked to their original persisted normalization."""
import json

from integration.qs_bid_calculation_publication import QSBidNormalizationPublicationStore
from integration.qs_cost_calculation_publication import QSCostCalculationPublishedViewProvider
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.qs_bid_objects import QSBidEvaluationProfileView
from src.actions.roles.qs_bid import prepare_bid_ranking
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_bid import RANK_METHOD, BidRankInput, BidRankReport, NormalizeInput


class QSBidRankingPublicationStore(QSBidNormalizationPublicationStore):
    """Persist ranking proof without rerunning ranking or normalization methods.

    Normalization must be saved in the same journal with its original immutable
    target and exact input/source versions. The host still supplies independent
    current source validation under its actual source/authorization writer guard.
    """
    SCHEMA = 'qs-bid-ranking-record.v1'
    PUBLICATION_SCHEMA = 'qs-bid-ranking-publication.v1'
    METHOD_REF = RANK_METHOD
    RECORDS_TABLE = 'qs_bid_ranking_records'
    PUBLICATIONS_TABLE = 'qs_bid_ranking_publications'
    RESULT_KIND = 'ranking'
    INPUT_MODEL = BidRankInput
    REPORT_MODEL = BidRankReport
    PREPARE_INPUT = staticmethod(prepare_bid_ranking)
    REQUIRE_EMPTY_RESULTS = False

    def __init__(self, *, normalizations, store, registry, methods, organizations, validate_source):
        if (type(normalizations) is not QSBidNormalizationPublicationStore
                or normalizations.store is not store or normalizations.registry is not registry
                or normalizations.methods is not methods or normalizations.organizations is not organizations):
            raise ValueError('Ranking persistence requires the original same-journal normalization store')
        self.normalizations = normalizations
        super().__init__(store=store, registry=registry, methods=methods,
            organizations=organizations, validate_source=validate_source)

    def _matches_output(self, projection, report):
        return projection.ranked_groups == report.ranked_groups and not projection.prices

    def _validate_normalization(self, record):
        """Check already saved dependency rows; safe inside a journal transaction."""
        if (self.normalizations.store is not self.store or self.normalizations.registry is not self.registry
                or self.normalizations.methods is not self.methods
                or self.normalizations.organizations is not self.organizations):
            raise TaskConflict('Ranking lost its original normalization store binding')
        sources = {Reference.model_validate(row['ref']).key(): row for row in record['prepared']['source_reading']}
        profile_ref = Reference.model_validate(record['action_input']['evaluation_profile_ref'])
        profile = QSBidEvaluationProfileView.model_validate(sources[profile_ref.key()]['projection'])
        ref = profile.normalization_result_ref
        if ref is None:
            return
        ref_key = task_digest([self.store.run_id, self.ACTION_ID, ref.model_dump(mode='json')])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.normalizations.RECORDS_TABLE} WHERE ref_key=?',
                (ref_key,)).fetchone()
        if raw is None:
            raise TaskConflict('Ranking requires its original persisted normalization execution')
        normalization = json.loads(raw[0])
        original, projection = self.normalizations._validate(normalization)
        current = ActionContext.model_validate(record['context'])
        if (normalization['organization_id'] != record['organization_id']
                or projection.ref != ref or sources.get(ref.key(), {}).get('projection') != projection.model_dump(mode='json')
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'execution_mode'))
                or original.business_time.clock_ref != current.business_time.clock_ref
                or original.business_time.offset > current.business_time.offset
                or any(normalization['action_input'][name] != record['action_input'][name] for name in
                    ('scope', 'round_ref', 'procurement_document_ref', 'bid_refs', 'clarification_refs', 'evaluation_profile_ref'))):
            raise TaskConflict('Ranking substitutes its original normalization result or source invocation')
        arithmetic = NormalizeInput.model_validate(normalization['prepared']['method_execution']['input'])
        originals = {Reference.model_validate(row['ref']).key(): row for row in normalization['prepared']['source_reading']}
        for dependency in {ref.key(): ref for ref in [*arithmetic.source_refs, *walk_references(arithmetic)]}.values():
            if sources.get(dependency.key()) != originals.get(dependency.key()) or dependency.key() not in originals:
                raise TaskConflict('Ranking changes original normalization price, eligibility or adjustment sources')

    def _validate(self, record):
        context, projection = super()._validate(record)
        self._validate_normalization(record)
        return context, projection

    def _save_targets(self, record, projection, *, is_new):
        self._validate_normalization(record)

    def _validate_saved_targets(self, record, projection):
        self._validate_normalization(record)

    def _publication_content(self, projection):
        """Carry the immutable normalization dependency to the ranking read point."""
        ref_key = task_digest([self.store.run_id, self.ACTION_ID, projection.ref.model_dump(mode='json')])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone()
        if raw is None:
            raise TaskConflict('Ranking publication requires its already saved original record')
        record = json.loads(raw[0])
        if (record['record_sha256'] != task_digest({k:v for k,v in record.items() if k != 'record_sha256'})
                or record['prepared']['projection'] != projection.model_dump(mode='json')):
            raise TaskConflict('Ranking publication changes its saved original projection')
        self._validate_normalization(record)
        sources = {Reference.model_validate(row['ref']).key(): row for row in record['prepared']['source_reading']}
        profile_ref = Reference.model_validate(record['action_input']['evaluation_profile_ref'])
        profile = QSBidEvaluationProfileView.model_validate(sources[profile_ref.key()]['projection'])
        dependencies = []
        if profile.normalization_result_ref is not None:
            original = sources[profile.normalization_result_ref.key()]
            dependencies.append({'ref': original['ref'], 'value': original['projection']})
        return {**super()._publication_content(projection), 'dependencies': dependencies}

    def _published_objects(self, publication):
        return [publication['object'], *publication['dependencies']]


class QSBidRankingPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSBidRankingPublicationStore):
            raise ValueError('Ranking provider requires its original QS-A06 ranking store')
        super().__init__(provider=provider, publications=publications)
