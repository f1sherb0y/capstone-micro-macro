"""Freeze explicit host-authored alternatives for the existing model host.

This is a local decision-input snapshot, never a macro projection, permission
or receipt. The caller retains its actual read guard and supplies an independent
gate for the relation between these alternatives and the original invocation.
No alternative, profile, source value or professional result is synthesized.
"""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from integration.action_model_host import ActionOptionSource
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView
from src.actions.model_strategy import ActionDecisionOption
from src.actions.registry import ActionRegistration
from src.coordination.tasks import TaskConflict, task_digest


Digest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class CapturedActionInputOption(StrictRecord):
    option_id: TextId
    action_input: dict


class CapturedActionOptionProjection(StrictRecord):
    ref: Reference
    projection: dict


class ActionOptionSnapshot(StrictRecord):
    schema_version: Literal['action-option-snapshot.v1'] = 'action-option-snapshot.v1'
    action_id: TextId
    role: TextId
    organization_id: TextId
    source_mode: Literal['formal', 'fixture']
    context: ActionContext
    action_input: dict
    options: Annotated[list[CapturedActionInputOption], Field(min_length=1)]
    source_reading: Annotated[list[CapturedActionOptionProjection], Field(min_length=1)]
    source_reading_sha256: Digest

    @model_validator(mode='after')
    def closed_original_snapshot(self):
        if (self.context.contract_ref.kind != 'ActionContract' or self.context.contract_ref.id != self.action_id
                or (self.context.execution_mode == 'offline_fixture') != (self.source_mode == 'fixture')):
            raise ValueError('Option snapshot changes original action or formal/fixture boundary')
        ids = [option.option_id for option in self.options]
        inputs = [task_digest(option.action_input) for option in self.options]
        refs = [row.ref.key() for row in self.source_reading]
        visible = {ref.key() for ref in self.context.visible_refs}
        if (len(set(ids)) != len(ids) or len(set(inputs)) != len(inputs)
                or len(set(refs)) != len(refs) or not set(refs) <= visible
                or self.context.candidate_set_ref.key() not in refs
                or self.source_reading_sha256 != task_digest(
                    [row.model_dump(mode='json') for row in self.source_reading])):
            raise ValueError('Option snapshot repeats alternatives, adds hidden sources or changes its source digest')
        # Reject non-JSON values/NaN even inside the contract-independent data.
        task_digest(self.model_dump(mode='json'))
        return self


def _validated_inputs(registration, action_input, options):
    if (not isinstance(registration, ActionRegistration) or not registration.implemented
            or registration.skill is None or not isinstance(options, (tuple, list)) or not options
            or any(not isinstance(option, ActionDecisionOption) for option in options)):
        raise ValueError('Option snapshots require an implemented action and explicit typed host alternatives')
    original = registration.contract.validate_input(action_input)
    alternatives = [CapturedActionInputOption(option_id=option.option_id,
        action_input=registration.contract.validate_input(option.action_input).model_dump(mode='json'))
        for option in options]
    return original, alternatives


def capture_action_option_snapshot(*, context, action_input, options, registration, reading):
    """Capture supplied inputs and actual authorized sources, without judging them.

    Source provenance is retained verbatim. Independent business relation
    approval is required again when the resulting source is used. This helper
    neither enumerates possible decisions nor executes their processors.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    original, alternatives = _validated_inputs(registration, action_input, options)
    if not isinstance(reading, ActionReadView):
        raise ValueError('Option capture requires an actual original authorized reading')
    reading.check_method_context(context, registration.action_id)
    before = reading.method_evidence()
    try:
        candidates = reading.resolve(context.candidate_set_ref)
        if not isinstance(candidates, CandidateSet):
            raise TaskConflict('Option capture requires the original typed candidate permissions')
        candidates.check_context(context, registration.contract.choices)
        for values in (original, *[registration.contract.validate_input(option.action_input) for option in alternatives]):
            for ref in walk_references(values):
                reading.resolve(ref)
        for candidate in candidates.candidates:
            reading.resolve(candidate.ref)
        sources = reading.evidence()
        return ActionOptionSnapshot(action_id=registration.action_id, role=registration.role,
            organization_id=reading.organization_id, source_mode=reading._resolver.source_mode,
            context=context, action_input=original.model_dump(mode='json'), options=alternatives,
            source_reading=[CapturedActionOptionProjection.model_validate(row) for row in sources],
            source_reading_sha256=task_digest(sources))
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise TaskConflict('Option capture cannot execute professional methods')


def build_snapshot_option_source(*, snapshot, registration, validate_current):
    """Bind one exact captured invocation to both existing model strategies.

    validate_current(snapshot, context, action_input, options, registration,
    reading) must authenticate original/current business identities, permitted
    alternative fields and the complete current authority/source relation.
    The original model strategy still runs every full processor, validates its
    output against both inputs and applies the original CandidateSet gates.
    A new invocation needs an explicitly captured source; there is no fallback.
    """
    snapshot = ActionOptionSnapshot.model_validate(snapshot).model_copy(deep=True)
    if (not isinstance(registration, ActionRegistration) or registration.action_id != snapshot.action_id
            or registration.role != snapshot.role or not callable(validate_current)):
        raise ValueError('Snapshot options require their original registered action and independent current gate')
    # A JSON capture prevents nested mutation through the caller's frozen
    # Pydantic model (its list/dict members are otherwise still mutable).
    captured_json = snapshot.model_dump_json()
    snapshot_sha256 = task_digest(snapshot.model_dump(mode='json'))
    gate = module_factory_descriptor(validate_current, 'action_options.validate_current')
    contract = registration.contract

    def prepare_options(*, context, action_input, registration, reading):
        frozen = ActionOptionSnapshot.model_validate_json(captured_json)
        if (registration is not original_registration or registration.contract is not contract
                or not isinstance(reading, ActionReadView)
                or context != frozen.context or reading.organization_id != frozen.organization_id
                or reading._resolver.source_mode != frozen.source_mode
                or registration.contract.validate_input(action_input).model_dump(mode='json') != frozen.action_input
                or module_factory_descriptor(validate_current, 'action_options.validate_current') != gate):
            raise TaskConflict('Snapshot options substituted the original invocation, source mode or current gate')
        reading.check_method_context(context, registration.action_id)
        before = reading.method_evidence()
        try:
            original, alternatives = _validated_inputs(registration, action_input,
                [ActionDecisionOption(row.option_id, row.action_input) for row in frozen.options])
            expected = {row.ref.key(): row.projection for row in frozen.source_reading}
            for row in frozen.source_reading:
                if reading.resolve(row.ref).model_dump(mode='json') != row.projection:
                    raise TaskConflict('Snapshot options changed an original authorized source projection')
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Snapshot options require their original typed candidates')
            candidates.check_context(context, registration.contract.choices)
            required = {context.candidate_set_ref.key(), *[row.ref.key() for row in candidates.candidates]}
            options = []
            for row in alternatives:
                values = registration.contract.validate_input(row.action_input)
                required.update(ref.key() for ref in walk_references(values))
                options.append(ActionDecisionOption(row.option_id, values))
            required.update(ref.key() for ref in walk_references(original))
            if not required <= set(expected):
                raise TaskConflict('Snapshot options omit actual input or candidate sources from their captured evidence')
            if validate_current(snapshot=frozen.model_copy(deep=True), context=context.model_copy(deep=True),
                    action_input=original.model_copy(deep=True), options=deepcopy(options),
                    registration=registration, reading=reading) is not True:
                raise TaskConflict('Snapshot options lack independent current business/authority authentication')
            for row in reading.evidence():
                ref = Reference.model_validate(row['ref'])
                if expected.get(ref.key()) != row['projection']:
                    raise TaskConflict('Option source validation consumed an uncaptured or changed source')
            if (registration is not original_registration or registration.contract is not contract
                    or module_factory_descriptor(validate_current, 'action_options.validate_current') != gate):
                raise TaskConflict('Snapshot options changed their original action or gate while validating')
            return options
        finally:
            reading.recheck()
            if reading.method_evidence() != before:
                raise TaskConflict('Option source validation cannot execute professional methods')

    def validate_options(*, context, action_input, options, registration, reading):
        expected = prepare_options(context=context, action_input=action_input,
            registration=registration, reading=reading)
        if (not isinstance(options, (tuple, list))
                or any(not isinstance(option, ActionDecisionOption) for option in options)):
            return False
        def dump(values):
            return [(row.option_id, registration.contract.validate_input(row.action_input).model_dump(mode='json'))
                for row in values]
        return dump(options) == dump(expected)

    original_registration = registration
    version = task_digest(dict(schema_version='snapshot-action-option-source.v1', snapshot_sha256=snapshot_sha256,
        validate_current=gate, producer=module_factory_descriptor(build_snapshot_option_source, 'snapshot_options')))
    return ActionOptionSource(version=version, prepare_options=prepare_options, validate_options=validate_options)
