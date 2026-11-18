"""Authenticate original QS learning execution without rewriting predictions or error history."""
from copy import deepcopy

from src.actions.contracts.common import StrictRecord, ref_type
from src.actions.contracts.qs_learning_objects import (
    QSLearningExecutionView, QSHistoricalCostPlanView, QSFrozenForecastView,
    QSForecastInformationView, QSReceivedOutcomeView, QSOutcomeAccessView,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.architect_learning_execution_query import (
    ArchitectLearningExecutionQueryRecord, EXECUTION_CODE, check_learning_execution,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


class QSLearningExecutionQueryRecord(ArchitectLearningExecutionQueryRecord):
    execution_ref: ref_type('QSLearningExecution')
    execution: QSLearningExecutionView


def preserve_qs_query_forecasts(raw, current_raw, old, current, read, *, exact_inputs=True, preserve_comparability=True):
    """Preserve immutable information at prediction time and private received outcomes."""
    if (preserve_comparability and raw['comparability_result_ref'] != current_raw['comparability_result_ref']
            or exact_inputs and any(raw[field] != current_raw[field] for field in ('forecast_refs', 'outcome_refs'))):
        raise TaskConflict('QS execution query replaces original forecast/outcome/comparability inputs')
    if not exact_inputs:
        for field in ('forecast_refs', 'outcome_refs'):
            before = {tuple(sorted(ref.items())) for ref in raw[field]}
            after = {tuple(sorted(ref.items())) for ref in current_raw[field]}
            if not before <= after:
                raise TaskConflict('QS learning recovery drops an original supplied forecast or received outcome')
    for field in ('forecast_refs', 'outcome_refs'):
        before = {ref.key() for ref in getattr(old['state'], field)}
        after = {ref.key() for ref in getattr(current['state'], field)}
        if (len(before) != len(getattr(old['state'], field)) or len(after) != len(getattr(current['state'], field))
                or not before <= after):
            raise TaskConflict('QS execution query repeats or drops original private forecast/outcome history')
    for version in (old, current):
        if len(set(version['state'].applied_error_pair_keys)) != len(version['state'].applied_error_pair_keys):
            raise TaskConflict('QS execution query repeats an already applied cost-error pair')
    if not set(old['state'].applied_error_pair_keys) <= set(current['state'].applied_error_pair_keys):
        raise TaskConflict('QS execution query drops original cost-error application history')
    for inputs, version in ((raw, old), (current_raw, current)):
        organization_id = version['state'].organization_id
        forecasts = [ref_type('CostPlan').model_validate(ref) for ref in inputs['forecast_refs']]
        outcomes = [ref_type('Outcome').model_validate(ref) for ref in inputs['outcome_refs']]
        if len({ref.key() for ref in forecasts}) != len(forecasts) or len({ref.key() for ref in outcomes}) != len(outcomes):
            raise TaskConflict('QS execution query repeats original supplied forecasts or outcomes')
        for ref in set(forecasts) | set(version['state'].forecast_refs):
            forecast = read(ref, QSHistoricalCostPlanView)
            frozen = read(forecast.immutable_source_ref, QSFrozenForecastView)
            if (forecast.organization_id != organization_id or frozen.organization_id != organization_id
                    or forecast.immutable_source_sha256 != content_digest(frozen) or frozen.forecast_ref != forecast.ref
                    or any(getattr(frozen, field) != getattr(forecast, field) for field in
                        ('organization_id', 'forecast_key', 'information_refs', 'comparison_basis', 'predicted_total', 'frozen_at'))
                    or frozen.available_at.clock_ref != forecast.frozen_at.clock_ref
                    or frozen.available_at.offset > forecast.frozen_at.offset
                    or len({ref.key() for ref in forecast.information_refs}) != len(forecast.information_refs)):
                raise TaskConflict('QS execution query rewrites immutable original forecast content')
            for information_ref in forecast.information_refs:
                information = read(information_ref, QSForecastInformationView)
                original = read(information.original_source_ref, StrictRecord)
                if (information.organization_id != organization_id or information.forecast_ref != forecast.ref
                        or information.original_source_sha256 != content_digest(original)
                        or information.received_at.clock_ref != forecast.frozen_at.clock_ref
                        or information.available_at.clock_ref != forecast.frozen_at.clock_ref
                        or not information.available_at.offset <= information.received_at.offset <= forecast.frozen_at.offset
                        or hasattr(original, 'available_at') and (original.available_at.clock_ref != information.received_at.clock_ref
                            or original.available_at.offset > information.received_at.offset)):
                    raise TaskConflict('QS execution query injects posterior information into original prediction')
        for ref in set(outcomes) | set(version['state'].outcome_refs):
            outcome = read(ref, QSReceivedOutcomeView)
            access = read(outcome.access_basis_ref, QSOutcomeAccessView)
            if (outcome.recipient_organization_id != organization_id
                    or outcome.author_organization_id != outcome.provider_organization_id
                    or access.outcome_ref != outcome.ref or access.provider_organization_id != outcome.provider_organization_id
                    or access.author_organization_id != outcome.provider_organization_id
                    or access.recipient_organization_id != organization_id):
                raise TaskConflict('QS execution query substitutes original outcome provider, private recipient or access basis')


def check_qs_learning_execution(check, selected, validate_relation, *, terminal=False):
    return check_learning_execution(check, selected, validate_relation, terminal=terminal, qs=True)


def qs_original_learning_execution_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS learning execution recovery requires guarded sources and native query authentication')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_qs_learning_execution(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('QS-A12', EXECUTION_CODE, '2', frozenset({'dependency_change'}), evaluate)
