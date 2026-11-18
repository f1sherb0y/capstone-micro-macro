"""Prepare BANK-A12 from explicitly received private outcomes and immutable judgments."""
from dataclasses import dataclass

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_learning_objects import (
    BankJudgmentView, BankLearningCaseView, BankLearningMethodView, BankLearningObservationView,
    BankLearningOrganizationView, BankLearningProfileView, BankLearningProjectView,
    BankLearningStateView, BankLearningExecutionView, BankVerifiedOutcomeView, bank_learning_schemas,
)
from src.actions.contracts.bank_strategy_objects import LendingStrategyView
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_study_objects import unique_refs


def validate_learning_selection(action_input, *, scope, organization_id, resolve):
    """Check original private ownership without evaluating or revising predictions."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Learning selection changes an original typed source reference')
        return row

    anchor = read(scope.ref, (BankLearningOrganizationView, BankLearningCaseView, BankLearningProjectView))
    state = read(anchor.learning_state_ref, BankLearningStateView)
    profile = read(state.profile_ref, BankLearningProfileView)
    if (state.organization_id != organization_id or profile.organization_id != organization_id
            or state.scope != scope or profile.scope != scope or profile.state_ref.key() != state.ref.key()):
        raise ValueError('Learning selection changes original private bank, scope, state or profile')
    for refs, schema, owner_field in (
            (action_input.observation_refs, BankLearningObservationView, 'recipient_organization_id'),
            (action_input.prior_judgment_refs, BankJudgmentView, 'lender_id'),
            (action_input.outcome_refs, BankVerifiedOutcomeView, 'lender_id'),
            (action_input.allowed_strategy_refs, LendingStrategyView, 'lender_id')):
        for ref in refs:
            row = read(ref, schema)
            if getattr(row, owner_field) != organization_id:
                raise ValueError('Learning source belongs to another private recipient or lender')
    if action_input.learning_method_ref is not None:
        read(action_input.learning_method_ref, BankLearningMethodView)
    # Null retains its original disabled-learning meaning. Maturity, original
    # information hashes, method support, unknown executions and future-only
    # strategy permissions remain the existing processor's responsibility.


def validate_learning_execution_history(action_input, *, scope, organization_id, sources):
    """Preserve supplied original private profile ownership and execution scope."""
    anchor = sources[scope.ref.key()]
    state = sources[anchor.learning_state_ref.key()]
    profile = sources[state.profile_ref.key()]
    for ref in state.execution_refs:
        execution = sources.get(ref.key())
        if execution is not None and (not isinstance(execution, BankLearningExecutionView)
                or execution.organization_id != organization_id):
            raise ValueError('Learning history substitutes the original private bank')
        if execution is not None and execution.business_key == profile.business_key:
            original = sources.get(execution.profile_ref.key())
            if original is not None and (not isinstance(original, BankLearningProfileView)
                    or original.organization_id != execution.organization_id or original.scope != execution.scope
                    or original.business_key != execution.business_key):
                raise ValueError('Learning execution substitutes its original private profile or scope')


@dataclass(frozen=True)
class PreparedBankLearning(PreparedBankIntake):
    """A local private learning invocation, without rewriting judgments or strategy."""


class BankLearningActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A12'
    SOURCE_SCHEMAS = staticmethod(bank_learning_schemas)

    def build(self, context, *, observation_refs, prior_judgment_refs, outcome_refs,
            learning_method_ref, allowed_strategy_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in
            (('observation_refs', observation_refs), ('prior_judgment_refs', prior_judgment_refs),
             ('outcome_refs', outcome_refs), ('allowed_strategy_refs', allowed_strategy_refs))}
        for refs in selected.values():
            unique_refs(refs)
        return self._prepare_supplied_snapshot(context, input_values={**selected,
            'learning_method_ref': None if learning_method_ref is None else Reference.model_validate(learning_method_ref)},
            prepared_type=PreparedBankLearning, validate_sources=lambda action_input, **boundary:
                validate_learning_selection(action_input, scope=context.scope, **boundary),
            validate_source_history=lambda action_input, **boundary:
                validate_learning_execution_history(action_input, scope=context.scope, **boundary))
