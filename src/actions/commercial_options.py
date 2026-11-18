"""Produce A12 alternatives only from existing authorized same-state profiles."""
from src.actions.contracts.common import walk_references
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_types
from src.actions.contracts.supplier_continuation_objects import supplier_continuation_types
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.model_strategy import ActionDecisionOption, SingleAgentActionStrategy
from src.coordination.tasks import task_digest


class CommercialProfileOptionProvider:
    """The original profile is retained; alternatives need explicit candidates.

    A candidate cannot change state, authority basis, scope, organization or
    actor. Resource/WIP/inventory/shipment/debt/observation input references are
    left intact. Independent transition rights and complete current business
    conditions are still checked by the registered processor for each option.
    """
    VERSION = 'commercial.same_state_profile_options.v1'
    ACTION_IDS = frozenset({'CONTRACTOR-A12','SUPPLIER-A12'})

    def prepare_options(self, *, context, action_input, registration, reading):
        if (registration.action_id not in self.ACTION_IDS or context.contract_ref.id != registration.action_id
                or not isinstance(reading,ActionReadView)):
            raise ValueError('Commercial options require their actual A12 action and authorized reading')
        reading.check_method_context(context,registration.action_id)
        types = supplier_continuation_types() if registration.action_id=='SUPPLIER-A12' else commercial_continuation_types()
        original = reading.resolve(action_input.continuation_profile_ref)
        state = reading.resolve(original.state_ref) if isinstance(original,types['ContinuationProfile']) else None
        if (not isinstance(original,types['ContinuationProfile']) or not isinstance(state,types['ContinuationState'])
                or original.ref != action_input.continuation_profile_ref or state.run_id != context.run_id
                or state.organization_id != reading.organization_id or state.scope != context.scope
                or state.as_of != context.business_time or state.coverage != 'complete'):
            raise ValueError('Commercial options require the exact complete current original state/profile')
        candidates = reading.resolve(context.candidate_set_ref)
        if not isinstance(candidates,CandidateSet):
            raise ValueError('Commercial alternatives require a typed authorized candidate set')
        candidates.check_context(context,registration.contract.choices)
        permissions = {row.ref.key():set(row.permitted_choices) for row in candidates.candidates
                       if row.ref.kind=='ContinuationProfile'}
        refs = [original.ref,*[row.ref for row in candidates.candidates
                              if row.ref.kind=='ContinuationProfile' and row.ref != original.ref]]
        unique_refs(refs)
        options = []
        for ref in refs:
            profile = reading.resolve(ref)
            if not isinstance(profile,types['ContinuationProfile']) or profile.ref != ref:
                raise ValueError('Commercial candidate lacks its concrete original profile schema')
            if (profile.state_ref != original.state_ref or profile.basis_ref != original.basis_ref
                    or profile.organization_id != reading.organization_id or profile.scope != context.scope
                    or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                    or profile.authority_ref not in context.authorization_refs):
                raise ValueError('Commercial alternative changes original state, rights basis, scope or actor authority')
            if ref != original.ref and profile.choice not in permissions[ref.key()]:
                raise ValueError('Commercial profile choice is outside its explicitly permitted candidate choices')
            now = context.business_time
            if (profile.available_at.clock_ref != now.clock_ref or profile.available_at.offset > now.offset
                    or profile.effective_window.start.clock_ref != now.clock_ref
                    or profile.effective_window.end.clock_ref != now.clock_ref
                    or not profile.effective_window.contains(now)):
                raise ValueError('Commercial alternative profile is not current and actually available')
            raw = action_input.model_dump(mode='python')
            raw['continuation_profile_ref']=ref
            alternative = registration.contract.validate_input(raw)
            for source in walk_references(alternative): reading.resolve(source)
            options.append(ActionDecisionOption('profile:'+task_digest(ref.model_dump(mode='json')),alternative))
        reading.recheck()
        return options

    def validate_options(self, *, context, action_input, options, registration, reading):
        """Compare the full proposed input set to a new authorized enumeration."""
        expected = self.prepare_options(context=context,action_input=action_input,
            registration=registration,reading=reading)
        if any(not isinstance(option,ActionDecisionOption) for option in options): return False
        actual = {option.option_id:registration.contract.validate_input(option.action_input).model_dump(mode='json')
                  for option in options}
        required = {option.option_id:option.action_input.model_dump(mode='json') for option in expected}
        return len(actual)==len(options) and actual==required


def build_commercial_profile_strategy(*, registry, client, run_id, model_version,
        max_calls, action_ids=CommercialProfileOptionProvider.ACTION_IDS, max_options=3,
        max_prompt_chars=60000, max_response_chars=4096, call_budget=None):
    """Bind the explicit configured strategy to this concrete option producer.

    Mixed strategy configurations require separate components with explicit
    budgets; components may share a persistent budget. Creating this component makes
    no client call. Supply its binding to CommercialActionAssembler or Runner.
    """
    from src.actions.organization_strategy import OrganizationDiscussionActionStrategy

    action_ids = frozenset(action_ids)
    if not action_ids or not action_ids <= CommercialProfileOptionProvider.ACTION_IDS:
        raise ValueError('This producer supports only Contractor/Supplier A12')
    strategies = {registry.get(action_id).strategy for action_id in action_ids}
    if len(strategies)!=1: raise ValueError('One component requires one explicitly configured strategy')
    if not strategies <= {'single_agent','organization_discussion'}:
        raise ValueError('Commercial model options require an explicitly configured model strategy')
    producer = CommercialProfileOptionProvider()
    kwargs = {'run_id':run_id,'client':client,'model_version':model_version,'action_ids':action_ids,
        'prepare_options':producer.prepare_options,'validate_options':producer.validate_options,
        'options_version':producer.VERSION,'max_calls':max_calls,'max_options':max_options,
        'max_prompt_chars':max_prompt_chars,'max_response_chars':max_response_chars,'call_budget':call_budget}
    if strategies=={'organization_discussion'}:
        return OrganizationDiscussionActionStrategy(registry=registry,**kwargs)
    return SingleAgentActionStrategy(**kwargs)
