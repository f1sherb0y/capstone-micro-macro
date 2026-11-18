"""Validate QS-A06 ranking sources against original normalization executions."""
from copy import deepcopy
import json

from integration.module_host import module_factory_descriptor
from integration.qs_bid_calculation_publication import QSBidNormalizationPublicationStore
from integration.qs_bid_calculation_validation import QSBidNormalizationSourceValidator
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.qs_bid_objects import QSBidEvaluationProfileView
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_bid import prepare_bid_ranking
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_bid import RANK_METHOD


class QSBidRankingSourceValidator(QSBidNormalizationSourceValidator):
    """Re-read real sources and the original same-journal normalization proof.

    Use the original provider beneath all publication wrappers. A saved dependency
    is added only to this independent validation resolver after its actual source
    gate succeeds. No publication is written, no macro fact is invented, and no
    normalization or ranking executor runs. Caller holds the real writer guard.
    """
    VERSION = 'qs-bid-ranking-source-validator.v1'
    RESULT_KIND = 'ranking'
    METHOD_REF = RANK_METHOD
    PREPARE_INPUT = staticmethod(prepare_bid_ranking)

    def __init__(self, *, normalizations, registry, organizations, provider, macro_version, source_mode):
        if (type(normalizations) is not QSBidNormalizationPublicationStore
                or normalizations.registry is not registry or normalizations.organizations is not organizations
                or normalizations.store.run_id != organizations.run_id):
            raise ValueError('Ranking validation requires the actual original normalization store and registry')
        self.normalizations = normalizations
        self._normalization_components = (normalizations, normalizations.store, normalizations.registry,
            normalizations.organizations, normalizations.methods, normalizations.validate_source)
        super().__init__(registry=registry, organizations=organizations, provider=provider,
            macro_version=macro_version, source_mode=source_mode)
        self._declared['normalization_validation'] = module_factory_descriptor(
            normalizations._validate, self.VERSION + '.normalization_validation')
        self._declared['normalization_source'] = module_factory_descriptor(
            normalizations.validate_source, self.VERSION + '.normalization_source')

    def _check(self):
        super()._check()
        current = (self.normalizations, self.normalizations.store, self.normalizations.registry,
            self.normalizations.organizations, self.normalizations.methods, self.normalizations.validate_source)
        if (any(actual is not original for actual, original in zip(current, self._normalization_components))
                or self.normalizations.registry is not self.registry or self.normalizations.organizations is not self.organizations
                or module_factory_descriptor(self.normalizations._validate, self.VERSION + '.normalization_validation')
                    != self._declared['normalization_validation']
                or module_factory_descriptor(self.normalizations.validate_source, self.VERSION + '.normalization_source')
                    != self._declared['normalization_source']):
            raise TaskConflict('Ranking validation changed its original normalization store or source gate')

    def _prepare(self, context, action_input):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID
                or self._views.source_mode != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Ranking validation changes its original run, action or explicit source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('Ranking validation requires its original implemented contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        actual = self._views.assemble(context, self.ACTION_ID, 'QS')
        sources = {row.ref.key(): row.value for row in actual.objects}
        profile = sources.get(action_input.evaluation_profile_ref.key())
        if not isinstance(profile, QSBidEvaluationProfileView):
            raise TaskConflict('Ranking validation lacks its original concrete evaluation profile')
        if profile.normalization_result_ref is not None:
            ref = profile.normalization_result_ref
            ref_key = task_digest([context.run_id, self.ACTION_ID, ref.model_dump(mode='json')])
            with self.normalizations.store._lock:
                raw = self.normalizations.store._db.execute(
                    f'SELECT record FROM {self.normalizations.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone()
            if raw is None:
                raise TaskConflict('Ranking validation requires the original persisted normalization execution')
            record = json.loads(raw[0])
            _, normalized = self.normalizations._validate(record)
            if (record['organization_id'] != actual.organization_id or normalized.ref != ref
                    or any(record['action_input'][name] != action_input.model_dump(mode='json')[name] for name in
                        ('scope', 'round_ref', 'procurement_document_ref', 'bid_refs', 'clarification_refs', 'evaluation_profile_ref'))
                    or ref.key() in sources and sources[ref.key()] != normalized):
                raise TaskConflict('Ranking substitutes its saved normalization result or original input versions')
            if self.normalizations.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
                raise TaskConflict('Ranking normalization lost its independently validated actual original sources')
            sources[ref.key()] = normalized
        resolver = ReferenceResolver(context.run_id, source_mode=self._views.source_mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for key, value in sources.items():
            ref = Reference(kind=key[0], id=key[1], version=key[2])
            resolver.register_projection(ref, value)
            refs.append(ref)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        prepared = self.PREPARE_INPUT(context, action_input, reading)
        if prepared['kind'] != 'prepared' or reading.method_evidence():
            raise TaskConflict('Current original sources no longer support the saved ranking input')
        reading.recheck()
        self._check()
        return context, reading, prepared
