"""Original tender alternatives from explicitly authorized pricing profiles.

These callbacks enumerate private inputs. They neither change source facts nor
submit a bid. The existing model strategy executes the original processor and
candidate gates for every input; the tender host retains native submission.
"""
from contextlib import nullcontext
from typing import Literal

from integration.action_model_host import ActionModelHostConfiguration
from integration.action_option_snapshot_store import (
    ActionOptionSnapshotStore, build_snapshot_action_model_host,
)
from src.actions.contracts.common import StrictRecord, TextId, walk_references
from src.actions.contracts.contractor_bid_objects import ContractorBidProfileView
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView
from src.actions.model_strategy import ActionDecisionOption, model_client_request_policy
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


class TenderPricingOptions:
    VERSION = 'tender.authorized_pricing_profile_options.v1'
    ACTION_IDS = frozenset({'CONTRACTOR-A01', 'CONTRACTOR-A02'})

    def __init__(self, *, registry, read_guard=nullcontext):
        self.registry, self.read_guard = registry, read_guard

    def prepare_options(self, *, context, action_input, registration, reading):
        with self.read_guard():
            if (registration.action_id not in self.ACTION_IDS
                    or self.registry.get(registration.action_id) is not registration
                    or registration.role != 'Contractor' or not isinstance(reading, ActionReadView)):
                raise TaskConflict('Tender options require the original Contractor registration and reading')
            reading.check_method_context(context, registration.action_id)
            original_input = registration.contract.validate_input(action_input)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Tender options require the original typed candidate permissions')
            candidates.check_context(context, registration.contract.choices)
            options = [ActionDecisionOption('original-input', original_input)]
            if registration.action_id == 'CONTRACTOR-A02':
                original = reading.resolve(original_input.pricing_profile_ref)
                self._profile(original, context, reading)
                for candidate in candidates.candidates:
                    if candidate.ref.kind != 'ContractorPricingProfile' or candidate.ref == original.ref:
                        continue
                    profile = reading.resolve(candidate.ref)
                    self._profile(profile, context, reading)
                    same_basis = ('programme_ref', 'terms_ref', 'validity_ref', 'exclusion_refs', 'markup_basis_ref')
                    if (profile.ref != candidate.ref or profile.organization_id != original.organization_id
                            or profile.package_ref != original.package_ref or profile.scope != original.scope
                            or profile.authority_ref != original.authority_ref or profile.currency != original.currency
                            or any(getattr(profile, name) != getattr(original, name) for name in same_basis)
                            or profile.commercial_allowance.currency != original.commercial_allowance.currency
                            or profile.commercial_allowance.basis_ref != original.commercial_allowance.basis_ref
                            or profile.choice not in candidate.permitted_choices):
                        raise TaskConflict('Tender alternative substitutes original package, authority or choice permission')
                    values = original_input.model_dump(mode='python')
                    values['pricing_profile_ref'] = profile.ref
                    alternative = registration.contract.validate_input(values)
                    for ref in walk_references(alternative):
                        reading.resolve(ref)
                    options.append(ActionDecisionOption('pricing-profile:' + task_digest(
                        profile.ref.model_dump(mode='json')), alternative))
            reading.recheck()
            return options

    @staticmethod
    def _profile(profile, context, reading):
        now = context.business_time
        if (not isinstance(profile, ContractorBidProfileView)
                or profile.organization_id != reading.organization_id
                or profile.authority_ref not in context.authorization_refs
                or not scope_covers(profile.scope, context.scope)
                or profile.available_at.clock_ref != now.clock_ref or profile.available_at.offset > now.offset
                or profile.effective_window.start.clock_ref != now.clock_ref
                or profile.effective_window.end.clock_ref != now.clock_ref
                or not profile.effective_window.contains(now)):
            raise TaskConflict('Tender pricing profile lacks current own scope and original authority')

    def validate_options(self, *, options, **kwargs):
        expected = self.prepare_options(**kwargs)
        if (not isinstance(options, (tuple, list))
                or any(not isinstance(option, ActionDecisionOption) for option in options)):
            return False
        registration = kwargs['registration']
        describe = lambda rows: [(option.option_id, registration.contract.validate_input(
            option.action_input).model_dump(mode='json')) for option in rows]
        return describe(options) == describe(expected)

    def validate_current(self, *, snapshot, **kwargs):
        # Snapshot equality/source authority are checked by the existing store.
        # Independently re-enumerate the permitted business alternatives too.
        return self.validate_options(**kwargs)


class TenderModelHostSettings(StrictRecord):
    namespace: TextId
    strategy: Literal['single_agent', 'organization_discussion']
    host: ActionModelHostConfiguration


def build_model_host(*, assembly, registry, organizations, store, read_guard,
                     request, output_directory, settings):
    """Configured tender factory; client and journal remain assembly-owned.

    Supply the explicit model transport through the model native client factory.
    The original per-invocation snapshot store provides durable alternatives and
    the host provides its existing shared call budget. No model call occurs here.
    """
    config = TenderModelHostSettings.model_validate(settings).model_copy(deep=True)
    if (set(config.host.action_ids) != TenderPricingOptions.ACTION_IDS
            or len(config.host.action_ids) != len(TenderPricingOptions.ACTION_IDS)
            or store is not assembly.client.tasks or organizations.run_id != store.run_id
            or not callable(read_guard)):
        raise ValueError('Tender model host requires both original actions and the actual shared journal/authority')
    client = getattr(assembly.client, 'tender_model_client', None)
    policy = model_client_request_policy(client)
    version = 'tender-model:' + task_digest(policy)
    if assembly.client.versions['model'] != version:
        raise TaskConflict('Tender model transport differs from the original native client model version')
    # Explicit pre-assembly strategy selection uses the public registry API.
    # It retains original processors, Skills, contracts and candidate bindings.
    if any(store.for_organization(run_id=store.run_id, organization_id=organization)
           for organization in assembly.client.organization_roles):
        from integration.native_checkpoint import checkpoint_binding_installation_allowed
        if not checkpoint_binding_installation_allowed(assembly.client):
            raise TaskConflict('Configure model strategies before tasks, or inside verified checkpoint reinstallation')
    for action_id in sorted(TenderPricingOptions.ACTION_IDS):
        original = registry.get(action_id)
        registry.register_processor(action_id, original.processor_id, original.processor, strategy=config.strategy)
    producer = TenderPricingOptions(registry=registry, read_guard=read_guard)
    snapshots = ActionOptionSnapshotStore(store=store, registry=registry, namespace=config.namespace,
        action_ids=config.host.action_ids, max_options=config.host.max_options,
        validate_current=producer.validate_current,
        option_producers={action_id: producer.prepare_options for action_id in config.host.action_ids})
    return build_snapshot_action_model_host(snapshots=snapshots, client=client,
        model_version=version, configuration=config.host)
