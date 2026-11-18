"""ENGINEER-A12 submits qualification evidence without automatically renewing it."""
from src.actions.contracts.common import Known
from src.actions.contracts.engineer_learning_objects import (
    engineer_learning_types, EngineerQualificationView, EngineerQualificationEventView, EngineerQualificationUpdateBasisView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import _needs
from src.actions.roles.qs_change import content_digest
from src.actions.roles.service_learning import update_service_experience


def maintain_engineering_experience(context, action_input, reading):
    return _maintain_engineering_experience(context, action_input, reading)


def prepare_engineer_learning_assessment_input(context, action_input, reading):
    """Prepare feedback rules while retaining the original qualification checks."""
    result = _maintain_engineering_experience(context, action_input, reading, prepare_assessment=True)
    if result['kind'] == 'prepared':
        return {**result, 'dependencies': {}}
    return result


def prepare_engineer_training_estimate_input(context, action_input, reading):
    """Prepare original training work while retaining qualification checks."""
    return _maintain_engineering_experience(context, action_input, reading, prepare_training=True)


def _maintain_engineering_experience(context, action_input, reading, *, prepare_assessment=False,
        prepare_training=False):
    now,org=context.business_time,reading.organization_id

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def true(value): return isinstance(value,Known) and value.value is True

    def qualification_action(state,decision,strategy,capability,read,author,evidence,clock,complete,wait):
        supplied=keys(action_input.qualification_refs)
        if supplied!=keys(state.qualification_refs) or supplied!=keys(capability.qualification_refs):
            _needs('complete_original_engineer_qualification_state')
        qualifications={};credentials=set()
        for ref in action_input.qualification_refs:
            row=read(ref,EngineerQualificationView,historic=True);author(row)
            clock(row.as_of);clock(row.validity.start);clock(row.validity.end)
            if (row.organization_id!=org or row.author_organization_id!=row.issuer_organization_id
                    or row.credential_key in credentials or row.as_of!=now or row.coverage!='complete'):
                _needs('current_complete_original_engineer_credential_history',[ref])
            credentials.add(row.credential_key);keys(row.event_refs);qualifications[ref.key()]=row
        if decision.choice!='request_qualification_update': return None
        if decision.qualification_ref is None or decision.qualification_ref.key() not in qualifications or decision.qualification_update_basis_ref is None:
            _needs('original_qualification_and_independent_update_basis')
        qualification=qualifications[decision.qualification_ref.key()]
        basis=read(decision.qualification_update_basis_ref,EngineerQualificationUpdateBasisView);author(basis)
        if (basis.organization_id!=org or basis.qualification_ref!=qualification.ref
                or basis.issuer_organization_id!=qualification.issuer_organization_id
                or basis.author_organization_id!=qualification.issuer_organization_id
                or basis.credential_key!=qualification.credential_key or not true(basis.permitted)):
            _needs('original_issuer_authorized_qualification_verification_basis',[basis.ref])
        if basis.qualification_event_ref.key() not in keys(qualification.event_refs):
            _needs('original_received_qualification_event_history')
        event=read(basis.qualification_event_ref,EngineerQualificationEventView,historic=True);author(event)
        clock(event.occurred_at);clock(event.effective_at);clock(event.received_at)
        if (event.organization_id!=org or event.qualification_ref!=qualification.ref
                or event.issuer_organization_id!=qualification.issuer_organization_id
                or event.author_organization_id!=qualification.issuer_organization_id
                or event.credential_key!=qualification.credential_key or event.kind!=basis.allowed_event_kind
                or event.occurred_at.offset>event.authored_at.offset or event.available_at.offset>event.received_at.offset):
            raise ValueError('Qualification update substitutes original issuer, credential, event or chronology')
        if event.received_at.offset>now.offset or event.status!='verified' or not true(event.verified):
            _needs('actually_received_verified_qualification_event',[event.ref])
        keys(state.applied_qualification_event_refs)
        physical={}
        for ref in qualification.event_refs:
            original=read(ref,EngineerQualificationEventView,historic=True);author(original)
            clock(original.received_at);clock(original.occurred_at)
            if original.received_at.offset>now.offset: _needs('actually_received_qualification_event_history',[ref])
            if original.available_at.offset>original.received_at.offset or original.occurred_at.offset>original.authored_at.offset:
                raise ValueError('Qualification event history changes original knowledge chronology')
            if (original.qualification_ref!=qualification.ref or original.organization_id!=org
                    or original.credential_key!=qualification.credential_key
                    or original.issuer_organization_id!=qualification.issuer_organization_id
                    or original.author_organization_id!=qualification.issuer_organization_id):
                raise ValueError('Qualification event history changes original credential or issuer')
            digest=content_digest(original.model_copy(update={'ref':event.ref,'available_at':event.available_at,
                'effective_window':event.effective_window,'received_at':event.received_at}))
            prior=physical.get(original.event_key)
            if prior is not None and prior!=digest: raise ValueError('Qualification physical event changes original content')
            physical[original.event_key]=digest
        for ref in state.applied_qualification_event_refs:
            applied=read(ref,EngineerQualificationEventView,historic=True);author(applied)
            clock(applied.received_at)
            if (applied.organization_id!=org or applied.author_organization_id!=applied.issuer_organization_id
                    or applied.received_at.offset>now.offset or applied.status!='verified' or not true(applied.verified)):
                raise ValueError('Qualification history applies another holder or an unreceived/unverified issuer event')
            if (applied.issuer_organization_id,applied.credential_key,applied.event_key)==(event.issuer_organization_id,event.credential_key,event.event_key):
                normalized=applied.model_copy(update={'ref':event.ref,'available_at':event.available_at,
                    'effective_window':event.effective_window,'received_at':event.received_at})
                if content_digest(normalized)!=content_digest(event):
                    raise ValueError('Previously applied qualification event changes original content')
                return wait(state.ref,'qualification_event_already_applied')
        if event.kind in {'issuance','renewal','scope_amendment'}:
            if event.next_validity is None or not event.next_discipline_codes or not event.next_region_ids or not event.next_service_codes:
                _needs('original_issuer_approved_qualification_scope_and_validity',[event.ref])
            clock(event.next_validity.start);clock(event.next_validity.end)
            if (event.next_validity.end.offset<=event.next_validity.start.offset
                    or not event.next_validity.contains(event.effective_at)):
                raise ValueError('Qualification event substitutes original approved effective validity')
        refs={r.key():r for row in (event,basis) for r in row.evidence_refs}
        if not refs: _needs('original_qualification_verification_evidence')
        evidence(list(refs.values()))
        return complete(qualification_ref=qualification.ref,evidence_refs=list(refs.values()))

    return update_service_experience(context,action_input,reading,action_id='ENGINEER-A12',
        learning_types=engineer_learning_types(),capability_from_state=True,additional_action=qualification_action,
        prepare_assessment=prepare_assessment,prepare_training=prepare_training)
