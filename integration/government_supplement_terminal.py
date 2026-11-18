"""Archive original A06 new-case waits only after actual independently lawful intake."""
from copy import deepcopy

from integration.task_continuation import observation_signal_matches
from src.actions.contracts.common import EvidenceRecord, ResumeCondition, ref_type, walk_references
from src.actions.contracts.government_supplement_objects import GovSupplementProfileView, GovSupplementRevisionView
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.government_supplement_conditions import _BASES, _LISTS
from src.coordination.government_supplement_transfer import GovernmentSupplementTransferRecord, NEW_CASE_CODE
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def reconcile_government_supplement_transfer(*, identity, signal, reader, dispatcher, validate_relation):
    store = reader.snapshots.store
    signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
    if (identity.action_id != 'GOV-A06' or identity.role != 'Government' or identity.purpose != 'action'
            or signal.run_id != identity.run_id or signal.organization_id != identity.organization_id):
        raise TaskConflict('Supplement transfer changes original action/run/recipient')
    events = [row for row in dispatcher.inbox.for_organization(run_id=identity.run_id,
        organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
    if len(events) != 1:
        raise TaskConflict('Supplement transfer requires original persisted recipient feedback')
    projected = dispatcher.project_signal(deepcopy(events[0]))
    if not observation_signal_matches(events[0], projected, expected=signal):
        raise TaskConflict('Supplement transfer replaces persisted feedback projection')
    source = store.get(identity)
    if (source['state'] not in {'waiting_input', 'wait_resolved'} or len(source['conditions']) != 1
            or store.continuation(identity) is not None):
        raise TaskConflict('Supplement transfer requires original pending wait with no same-case successor')
    condition = ResumeCondition.model_validate(source['conditions'][0])
    if (condition.condition_code != NEW_CASE_CODE or condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in condition.object_refs) != ('RegulatoryCase', 'RevisionBasis', 'Submission')
            or not dispatcher.journal._matches(condition, signal)):
        raise TaskConflict('Supplement transfer changes original revision-route wait or matching signal')
    selected = reader(ConditionCheck(deepcopy(source), condition, signal))
    reading, context = selected.reading, selected.context
    try:
        original_context = selected.original_context
        if (task_digest(selected.original_action_input) != identity.input_sha256 or original_context is None
                or task_digest(original_context.model_dump(mode='json')) != identity.context_sha256
                or selected.transfer is None):
            raise TaskConflict('Supplement transfer lacks original invocation or actual intake evidence')
        transfer = GovernmentSupplementTransferRecord.model_validate(deepcopy(selected.transfer))
        proof_rows, proof_refs, versions = [], [], []

        def identities(refs):
            keys = {ref.key()[:2] for ref in refs}
            if len(keys) != len(refs):
                raise TaskConflict('Supplement transfer duplicates a physical source')
            return keys

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref or not scope_covers(context.scope, row.scope):
                raise TaskConflict('Supplement transfer lacks exact original/current scoped sources')
            proof_rows.append(row)
            return row

        for raw, at in ((selected.original_action_input, original_context.business_time),
                (selected.action_input, context.business_time)):
            bases = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
            case, original, current, clock = (bases[field] for field, _, _ in _BASES)
            profile = read(case.supplement_profile_ref, GovSupplementProfileView)
            if profile.revision_basis_ref is None:
                raise TaskConflict('Supplement transfer loses original revision procedure basis')
            revision = read(profile.revision_basis_ref, GovSupplementRevisionView)
            if (case.organization_id != identity.organization_id or profile.organization_id != identity.organization_id
                    or profile.case_ref != case.ref or case.current_submission_ref != current.ref
                    or profile.original_submission_ref != original.ref or profile.current_submission_ref != current.ref
                    or original.ref not in case.linked_submission_refs or current.ref not in case.linked_submission_refs
                    or original.ref == current.ref or revision.route != 'new_case'
                    or revision.case_ref != case.ref or revision.procedure_ref != case.procedure_ref
                    or revision.original_submission_ref != original.ref or revision.original_content_sha256 != original.content_sha256
                    or revision.current_submission_ref != current.ref or revision.current_content_sha256 != current.content_sha256
                    or revision.author_organization_id != identity.organization_id or revision.author_action_id != 'GOV-A06'
                    or revision.authored_at.clock_ref != at.clock_ref or revision.available_at.clock_ref != at.clock_ref
                    or revision.authored_at.offset > revision.available_at.offset or revision.available_at.offset > at.offset
                    or not revision.effective_window.contains(revision.authored_at)):
                raise TaskConflict('Supplement transfer substitutes original agency/material/revision route')
            grant, function = reading.resolve(revision.author_authority_ref), reading.resolve(revision.author_function_ref)
            if (not isinstance(grant, Authorization) or grant.ref != revision.author_authority_ref
                    or not isinstance(function, RoleAssignment) or function.function_ref != revision.author_function_ref
                    or function.role != 'Government' or grant.actor_id != revision.author_actor_id
                    or grant.organization_id != identity.organization_id or grant.function_ref != function.function_ref
                    or 'GOV-A06' not in grant.action_ids or not grant.validity.contains(revision.authored_at)
                    or not any(scope_covers(covered, context.scope) for covered in grant.scopes)):
                raise TaskConflict('Supplement transfer lacks independent revision author authority')
            proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            bases.update(profile=profile, revision=revision,
                input_lists={field: [ref_type(kind).model_validate(ref) for ref in raw[field]] for field, kind in _LISTS.items()})
            versions.append(bases)
        old, current = versions
        if (tuple(condition.object_refs) != (old['case_ref'].ref, old['revision'].ref, old['current_submission_ref'].ref)
                or old['case_ref'].status in {'closed', 'withdrawn'} or old['current_submission_ref'].status != 'active'
                or old['current_submission_ref'].receipt_status != 'received'
                or old['profile'].coverage != 'complete' or old['profile'].as_of != original_context.business_time
                or {ref.key() for ref in old['profile'].issue_refs} != {ref.key() for ref in old['input_lists']['issue_refs']}
                or {ref.key() for ref in old['profile'].response_refs} != {ref.key() for ref in old['input_lists']['response_refs']}):
            raise TaskConflict('Supplement transfer differs from original emitted new-case revision wait')
        if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                or old['profile'].ref.key()[:2] != current['profile'].ref.key()[:2]
                or old['profile'].choice != current['profile'].choice
                or old['case_ref'].applicant_id != current['case_ref'].applicant_id
                or old['case_ref'].matter_ref != current['case_ref'].matter_ref
                or old['case_ref'].procedure_ref.key()[:2] != current['case_ref'].procedure_ref.key()[:2]
                or old['case_ref'].jurisdiction_ref.key()[:2] != current['case_ref'].jurisdiction_ref.key()[:2]
                or identities(old['case_ref'].task_refs) - identities(current['case_ref'].task_refs)
                or any(identities(getattr(old['profile'], field)) - identities(getattr(current['profile'], field))
                    for field in ('issue_refs', 'response_refs', 'assessment_refs'))
                or old['revision'].ref.key()[:2] != current['revision'].ref.key()[:2]
                or any(old[field].content_sha256 != current[field].content_sha256
                    or identities(old[field].component_refs) != identities(current[field].component_refs)
                    for field in ('original_submission_ref', 'current_submission_ref'))
                or any(identities(old['input_lists'][field]) - identities(current['input_lists'][field]) for field in _LISTS)
                or identities(old['case_ref'].linked_submission_refs) - identities(current['case_ref'].linked_submission_refs)):
            raise TaskConflict('Supplement transfer rewrites original material or retained histories')
        new_case, received = transfer.new_case, transfer.received_submission
        now, prior_case = context.business_time, old['case_ref']
        if (transfer.source_identity_sha256 != task_digest(source['identity']) or transfer.run_id != identity.run_id
                or transfer.organization_id != identity.organization_id or transfer.original_case_ref != current['case_ref'].ref
                or transfer.revision_basis_ref != current['revision'].ref
                or transfer.revised_submission_ref != current['current_submission_ref'].ref
                or transfer.revised_content_sha256 != current['current_submission_ref'].content_sha256
                or new_case.ref.key()[:2] == prior_case.ref.key()[:2] or new_case.organization_id != identity.organization_id
                or new_case.status != 'accepted' or received.status != 'active' or received.receipt_status != 'received'
                or new_case.current_submission_ref != received.ref or received.ref not in new_case.linked_submission_refs
                or received.prior_case_ref is None or received.prior_case_ref.key()[:2] != prior_case.ref.key()[:2]
                or received.content_sha256 != transfer.revised_content_sha256
                or new_case.applicant_id != prior_case.applicant_id or received.applicant_id != prior_case.applicant_id
                or new_case.matter_ref != prior_case.matter_ref or received.matter_ref != new_case.matter_ref
                or received.procedure_ref != new_case.procedure_ref or received.jurisdiction_ref != new_case.jurisdiction_ref
                or received.recipient_organization_id != identity.organization_id
                or not scope_covers(context.scope, new_case.scope) or not scope_covers(context.scope, received.scope)
                or any(point.clock_ref != now.clock_ref for point in (transfer.received_at, received.submitted_at,
                    new_case.available_at, received.available_at, original_context.business_time))
                or transfer.received_at.offset < original_context.business_time.offset or transfer.received_at.offset > now.offset
                or received.submitted_at.offset > transfer.received_at.offset
                or received.available_at.offset < transfer.received_at.offset or received.available_at.offset > now.offset
                or new_case.available_at.offset > now.offset or not new_case.effective_window.contains(now)
                or not received.effective_window.contains(now)):
            raise TaskConflict('Supplement transfer lacks actual distinct-case receipt of the original revised content')
        if len({ref.key() for ref in transfer.evidence_refs}) != len(transfer.evidence_refs):
            raise TaskConflict('Supplement transfer duplicates its observed receipt evidence')
        grant, function = reading.resolve(transfer.authority_ref), reading.resolve(transfer.function_ref)
        if (not isinstance(grant, Authorization) or grant.ref != transfer.authority_ref
                or not isinstance(function, RoleAssignment) or function.function_ref != transfer.function_ref
                or function.role != 'Government' or grant.actor_id != transfer.actor_id
                or grant.organization_id != identity.organization_id or grant.function_ref != transfer.function_ref
                or 'GOV-A02' not in grant.action_ids or not grant.validity.contains(transfer.received_at)
                or not any(scope_covers(covered, received.scope) for covered in grant.scopes)):
            raise TaskConflict('Supplement transfer receipt lacks independently authorized actual intake')
        proof_refs.extend([*transfer.evidence_refs, *grant.basis_refs, *function.basis_refs])
        proof_rows.extend([new_case, received])
        proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
        evidence = {}
        for ref in proof_refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Supplement transfer requires observed original material/intake evidence')
            evidence[ref.key()] = row.model_dump(mode='json')
        resolution = dict(schema_version='government-supplement-new-case-resolution.v1',
            transfer=transfer.model_dump(mode='json'), original_action_input=deepcopy(selected.original_action_input),
            action_input=deepcopy(selected.action_input), original_context=original_context.model_dump(mode='json'),
            context=context.model_dump(mode='json'), supplement_sources=deepcopy(selected.supplement_sources),
            unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()))
        if validate_relation(source_identity=deepcopy(source['identity']), condition_code=NEW_CASE_CODE,
                terminal_transfer=True, resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Supplement transfer lacks native new-case receipt and terminal handoff authentication')
        reading.recheck()
        reader._check()
        previous = store.wait_resolution(identity)
        if previous is not None:
            if previous['resolution']['transfer'] != transfer.model_dump(mode='json'):
                raise TaskConflict('Supplement transfer rewrites archived original handoff')
            return previous
        return store.resolve_wait(identity, source['revision'], resolution=resolution,
            validate_resolution=lambda current_source, _: current_source == source)
    finally:
        reading.recheck()
        reader._check()
