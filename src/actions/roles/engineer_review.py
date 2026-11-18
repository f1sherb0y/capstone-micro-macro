"""ENGINEER-A06 preserves each scoped check and actual coordination issue."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.engineer_review_objects import (
    EngineerReviewTargetView, EngineerReviewRequestView, EngineerReviewTaskView,
    EngineerReviewSpecView, EngineerReviewMethodView, EngineerReviewResultView,
    EngineerReviewIndependenceView, EngineerReviewInterfaceView, EngineerReviewScopeView,
    EngineerReviewQuestionView, ArchitectReviewIssueView, EngineerReviewFactView,
    EngineerAppointmentView, EngineerServiceTermsView, EngineerIndependenceRequirementView,
    EngineerOrganizationRelationsView, EngineerReviewCheckPreparation,
)
from src.actions.contracts.architect_appointment_objects import service_terms_digest
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD, EngineerInterfaceInput, check_interface
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def assess_professional_work(context, action_input, reading):
    return _assess_professional_work(context, action_input, reading)


def prepare_engineer_review_check_input(context, action_input, reading, preparation):
    """Prepare independently authorized A06 facts without consuming future findings."""
    preparation = EngineerReviewCheckPreparation.model_validate(preparation).model_copy(deep=True)
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A06':
        raise ValueError('Review check preparation requires its original Engineer A06 contract')
    reading.check_method_context(context,'ENGINEER-A06')
    before = reading.method_evidence()
    future = {ref.key() for ref in action_input.method_result_refs}

    def recheck_preparation():
        if reading.method_evidence() != before or future.intersection(reading._reads):
            raise ValueError('Review preparation cannot execute methods or consume future results')

    recheck_preparation()
    try:
        return _assess_professional_work(context,action_input,reading,check_preparation=preparation)
    finally:
        reading.recheck()
        recheck_preparation()


def _assess_professional_work(context, action_input, reading, *, check_preparation=None):
    now, organization = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('engineer-review-clock-alignment')

    def evidence(refs, historical=False):
        rows = []
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('engineer-review-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_professional_review_evidence', [ref])
            rows.append(row)
        return rows

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported('engineer-review-projection:' + ref.kind)
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise ValueError('Professional review input leaves original authorized scope')
        for field in ('available_at', 'received_at'):
            point = getattr(row, field, None)
            if point is not None:
                clock(point)
                if point.offset > now.offset: _needs('received_original_professional_review_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('effective_original_professional_review_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def authorize(ref, actor, function_ref, org, action, at):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        roles = {'ARCHITECT':'Architect','ENGINEER':'Engineer','QS':'QS','OWN':'Owner','GOV':'Government',
                 'CONTRACTOR':'Contractor','SUPPLIER':'Supplier','BANK':'Bank'}
        if (grant.actor_id != actor or not same(grant.function_ref, function_ref) or grant.organization_id != org
                or action not in grant.action_ids or function.role != roles.get(action.split('-')[0])
                or not any(scope_covers(s, action_input.scope) for s in grant.scopes)):
            raise ValueError('Professional review lacks independent original author/action/scope authority')
        clock(grant.validity.start); clock(at)
        if not grant.validity.contains(at): _needs('valid_original_professional_review_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], at != now)
        return grant

    def bound(row):
        if (not same(row.review_request_ref, request.ref) or not same(row.target_ref, target.ref)
                or row.content_sha256 != target.content_sha256):
            raise ValueError('Professional review changes original request/target/version/content')

    def completed(choice, **fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,'scope':action_input.scope,'note':request.explanation,**fields}}

    def independence():
        if request.independence_check_ref != action_input.independence_check_ref:
            raise ValueError('Professional review changes original independence check version')
        requirement_ref = terms.independence_requirement_ref
        if requirement_ref is None:
            if task.function_code == 'independent_review' or action_input.independence_check_ref is not None:
                _needs('original_required_professional_review_independence_template')
            return
        requirement = read(requirement_ref, EngineerIndependenceRequirementView)
        if (not same(requirement.request_ref, appointment.request_ref)
                or target.ref.key() not in keys(requirement.target_refs)):
            raise ValueError('Professional independence template changes original request/target')
        if requirement.template_code not in {'separate_personnel_v1','separate_organization_and_personnel_v1'}:
            _unsupported('engineer-review-independence-template')
        if action_input.independence_check_ref is None: _needs('original_professional_review_independence_check')
        check = read(action_input.independence_check_ref, EngineerReviewIndependenceView)
        if (not same(check.review_request_ref, request.ref) or not same(check.target_ref,target.ref)
                or not same(check.requirement_ref,requirement.ref) or check.reviewer_organization_id != organization
                or check.reviewer_actor_id != context.actor_id or set(check.reviewer_personnel_ids) != set(request.reviewer_personnel_ids)
                or check.author_organization_id != target.author_organization_id
                or set(check.author_personnel_ids) != set(target.author_personnel_ids)):
            raise ValueError('Professional independence check changes actual original authors/reviewers/template')
        if len(set(check.reviewer_personnel_ids)) != len(check.reviewer_personnel_ids) or len(set(check.author_personnel_ids)) != len(check.author_personnel_ids):
            raise ValueError('Professional independence repeats real personnel')
        if check.coverage != 'complete' or check.as_of != now: _needs('complete_current_professional_review_independence')
        if check.verifier_organization_id != organization: raise ValueError('Independence verifier changes original reviewing organization')
        clock(check.verified_at)
        if check.verified_at.offset > min(now.offset,check.available_at.offset): _needs('professional_independence_verified_before_received')
        if check.verifier_action_id != 'ENGINEER-A03': raise ValueError('Professional review independence needs original A03 verifier authority')
        authorize(check.verifier_authority_ref,check.verifier_actor_id,check.verifier_function_ref,
                  check.verifier_organization_id,check.verifier_action_id,check.verified_at)
        if context.actor_id == target.author_actor_id or set(request.reviewer_personnel_ids) & set(target.author_personnel_ids):
            _needs('professional_reviewers_independent_of_original_authors')
        if requirement.template_code == 'separate_organization_and_personnel_v1':
            relations=read(requirement.relations_ref,EngineerOrganizationRelationsView)
            if relations.organization_id != organization or relations.as_of != now or relations.coverage != 'complete':
                _needs('complete_current_professional_review_organization_relations')
            related=_known(relations.related_organization_ids,'original_professional_review_relations')
            if _known(check.related_organization_ids,'verified_professional_review_relations') != related:
                raise ValueError('Independence check changes original actual organization relationships')
            if target.author_organization_id in {organization,*related}: _needs('professional_review_organization_independent_of_authors')

    def make_questions():
        output=[]
        for ref in request.question_refs:
            row=read(ref,EngineerReviewQuestionView);question=row.question
            if (not same(row.review_request_ref,request.ref) or not same(row.target_ref,target.ref)
                    or question.scope != action_input.scope or not question.recipient_ids or ref.key() not in keys(question.target_refs)):
                raise ValueError('Professional evidence question changes original request/target/scope')
            response=read(question.response_requirement_ref,ServiceResponseRequirementView)
            if not same(response.request_ref,appointment.request_ref) or not set(question.recipient_ids) <= set(response.recipient_ids):
                raise ValueError('Professional question exceeds original request/recipient authority')
            for target_ref in question.target_refs:
                original=read(target_ref,EngineerReviewQuestionView)
                if (not same(original.review_request_ref,request.ref) or not same(original.target_ref,target.ref)
                        or original.question != question): raise ValueError('Professional question invents target or changes original content')
            evidence(question.evidence_refs);output.append(question.model_dump(mode='python'))
        if not output: _needs('specific_original_professional_review_evidence_questions')
        return output

    def method_domain(spec, at):
        if spec.method_ref is None or not same(spec.method_ref,ENGINEER_INTERFACE_METHOD):
            _unsupported('engineer-review-unbound-professional-method')
        method=read(spec.method_ref,EngineerReviewMethodView)
        if (task.discipline_code not in method.discipline_codes or task.function_code not in method.function_codes
                or region not in method.region_ids or object_type not in method.object_types
                or request.requested_use not in method.allowed_uses or not method.effective_window.contains(at)):
            _unsupported('engineer-review-method-professional-object-use-domain')
        return method

    def original_facts(spec, at):
        facts,basis=[],[]
        for ref in (spec.left_fact_ref,spec.right_fact_ref):
            if ref is None:
                facts.append(None)
                continue
            fact=read(ref,EngineerReviewFactView)
            if (not same(fact.target_ref,target.ref) or not same(fact.engineering_scope_ref,spec.engineering_scope_ref)
                    or fact.content_sha256 != target.content_sha256):
                raise ValueError('Professional interface facts change target/coverage')
            if fact.available_at.offset > at.offset or not fact.effective_window.contains(at):
                raise ValueError('Professional execution borrows facts unavailable or inapplicable when executed')
            facts.append(fact);basis.extend(fact.evidence_refs)
        refs=[ref for ref in (spec.left_fact_ref,spec.right_fact_ref) if ref is not None]
        states=[fact.value if fact else {'state':'unknown','reason_code':'original_interface_fact_missing','missing_refs':[]} for fact in facts]
        return facts,basis,refs,states

    try:
        if context.scope != action_input.scope: raise ValueError('Professional review changes authorized action scope')
        target=read(action_input.target_ref,EngineerReviewTargetView)
        request=read(action_input.review_request_ref,EngineerReviewRequestView)
        if not same(request.target_ref,target.ref) or request.content_sha256 != target.content_sha256:
            raise ValueError('Professional review request changes original target version/content')
        if request.organization_id != organization or request.status != 'authorized': _needs('original_authorized_professional_review_request')
        authorize(request.authority_ref,context.actor_id,context.function_ref,organization,'ENGINEER-A06',now)
        clock(target.authored_at)
        if target.authored_at.offset > min(now.offset,target.available_at.offset): _needs('professional_target_authored_before_received')
        authorize(target.author_authority_ref,target.author_actor_id,target.author_function_ref,
                  target.author_organization_id,target.author_action_id,target.authored_at)
        if not request.reviewer_personnel_ids or len(set(request.reviewer_personnel_ids)) != len(request.reviewer_personnel_ids):
            raise ValueError('Professional review needs actual distinct reviewer personnel')
        if len(set(target.author_personnel_ids)) != len(target.author_personnel_ids): raise ValueError('Professional target repeats original authors')
        task=read(request.task_ref,EngineerReviewTaskView)
        if (task.organization_id != organization or not same(task.review_request_ref,request.ref)
                or not same(task.appointment_ref,request.appointment_ref) or not same(task.target_ref,target.ref)
                or task.requested_use != request.requested_use): raise ValueError('Professional review changes original task/appointment/target/use')
        authorize(task.authority_ref,context.actor_id,task.function_ref,organization,'ENGINEER-A06',now)
        if task.status != 'authorized': _needs('original_authorized_professional_review_task')
        appointment=read(request.appointment_ref,EngineerAppointmentView)
        if appointment.provider_organization_id != organization or appointment.status != 'active': _needs('original_active_professional_review_appointment')
        terms=read(appointment.terms_ref,EngineerServiceTermsView,True)
        if service_terms_digest(terms) != appointment.terms_digest: raise ValueError('Professional review changes original accepted terms content')
        if (task.discipline_code not in _known(terms.discipline_codes,'accepted_review_disciplines')
                or task.function_code != _known(terms.function_code,'accepted_review_function')
                or request.requested_use not in _known(terms.requested_uses,'accepted_review_uses')
                or request.requested_use not in target.reviewable_uses):
            raise ValueError('Professional review changes accepted discipline/function/use')
        region=_known(terms.region_id,'accepted_review_region');object_type=_known(terms.object_type,'accepted_review_object_type')
        for name,original in (('check_spec_refs','required_check_refs'),('method_result_refs','received_method_result_refs'),('interface_refs','interface_refs')):
            if keys(getattr(action_input,name)) != keys(getattr(request,original)): _needs('all_original_professional_review_'+name)
        independence()
        if check_preparation is not None and request.choice != 'assess':
            raise ValueError('Review method preparation cannot replace original evidence or coordination requests')
        if request.choice == 'request_evidence': return completed('request_evidence',questions=make_questions())
        scopes={ref.key():read(ref,EngineerReviewScopeView) for ref in request.engineering_scope_refs}
        keys(request.engineering_scope_refs)
        for row in scopes.values():
            bound(row)
            if row.discipline_code != task.discipline_code: raise ValueError('Professional review coverage changes discipline')
        specs={ref.key():read(ref,EngineerReviewSpecView) for ref in action_input.check_spec_refs}
        issues={ref.key():ref for ref in target.unresolved_issue_refs}
        keys(target.unresolved_issue_refs)
        for spec in specs.values():
            bound(spec)
            if (spec.engineering_scope_ref.key() not in scopes or spec.discipline_code != task.discipline_code
                    or spec.function_code != task.function_code or spec.requested_use != request.requested_use
                    or not keys(spec.interface_refs) <= keys(request.interface_refs)):
                raise ValueError('Professional check changes original scope/discipline/function/use/interfaces')
            issues.update({ref.key():ref for ref in spec.issue_refs});keys(spec.issue_refs)
        interfaces=[read(ref,EngineerReviewInterfaceView) for ref in action_input.interface_refs]
        interface_gap_scopes=set()
        for interface in interfaces:
            bound(interface)
            if interface.engineering_scope_ref.key() not in scopes or not keys(interface.check_spec_refs) <= set(specs):
                raise ValueError('Professional interface invents scope or check specification')
            expected={spec.ref.key() for spec in specs.values() if interface.ref.key() in keys(spec.interface_refs)}
            if keys(interface.check_spec_refs) != expected: raise ValueError('Professional interface loses original check links')
            if not expected: interface_gap_scopes.add(interface.engineering_scope_ref.key())
            for key in expected:
                if not same(specs[key].engineering_scope_ref,interface.engineering_scope_ref):
                    raise ValueError('Professional interface check changes original engineering coverage')
            issues.update({ref.key():ref for ref in interface.issue_refs});keys(interface.issue_refs)
        if check_preparation is not None:
            mappings=task.check_result_targets
            keys([row.check_spec_ref for row in mappings]);keys([row.calculation_ref for row in mappings])
            if (not {row.check_spec_ref.key() for row in mappings} <= set(specs)
                    or not {row.calculation_ref.key() for row in mappings} <= keys(action_input.method_result_refs)):
                raise ValueError('Review check target mapping leaves original task/spec/result inputs')
            selected=next((row for row in mappings if same(row.check_spec_ref,check_preparation.check_spec_ref)),None)
            if selected is None: _needs('original_declared_review_check_result_target',[task.ref])
            if (not same(selected.calculation_ref,check_preparation.calculation_ref)
                    or type(selected.calculation_ref.version) is not str or task.function_ref != context.function_ref):
                raise ValueError('Review preparation substitutes original result target or current reviewer function')
            for ref in issues.values():
                issue=read(ref,ArchitectReviewIssueView)
                if not same(issue.target_ref,target.ref) or issue.status=='closed':
                    raise ValueError('Review preparation removes original open issue or changes target')
            if target.issue_coverage!='complete': _needs('complete_original_visible_professional_review_issues')
            spec=specs[selected.check_spec_ref.key()]
            method_domain(spec,now)
            _,basis,fact_refs,states=original_facts(spec,now)
            source_refs=list({ref.key():ref for ref in [task.ref,request.ref,target.ref,spec.ref,
                scopes[spec.engineering_scope_ref.key()].ref,*fact_refs,*spec.evidence_refs,*basis,
                *task.evidence_refs,*request.evidence_refs,*target.evidence_refs]}.values())
            original=EngineerInterfaceInput(requested_check=spec.requested_check,left_code=states[0],
                right_code=states[1],source_refs=source_refs)
            if check_preparation.input != original:
                raise ValueError('Review preparation changes original target content, fact values or input versions')
            reading.recheck()
            return {'kind':'prepared','preparation':check_preparation,'task':task,'request':request,'target':target,
                'spec':spec,'input_fact_refs':fact_refs,'issue_refs':list(issues.values())}
        saved_results={}
        for ref in action_input.method_result_refs:
            row=read(ref,EngineerReviewResultView);bound(row);clock(row.executed_at)
            spec=specs.get(row.check_spec_ref.key())
            if (spec is None or not same(row.task_ref,task.ref) or spec.method_ref is None or not same(row.method_ref,spec.method_ref)
                    or row.requested_use != request.requested_use or row.executed_at.offset > min(now.offset,row.available_at.offset)):
                raise ValueError('Professional result changes original task/spec/method/use/time')
            if row.check_spec_ref.key() in saved_results: raise ValueError('Professional check has unreconciled duplicate results')
            authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_organization_id,row.author_action_id,row.executed_at)
            if row.status != 'ok' and row.result is not None: raise ValueError('Technical failure cannot have substantive professional findings')
            issues.update({ref.key():ref for ref in row.issue_refs});keys(row.issue_refs)
            saved_results[row.check_spec_ref.key()]=row
        for ref in issues.values():
            issue=read(ref,ArchitectReviewIssueView)
            if not same(issue.target_ref,target.ref) or issue.status=='closed':
                raise ValueError('Original unresolved professional issue changes target or invents closure')
        if request.choice=='request_coordination':
            if not request.coordination_issue_refs or not keys(request.coordination_issue_refs) <= set(issues):
                _needs('original_professional_issues_for_coordination')
            if request.coordination_requirement_ref is None or request.coordination_recipient_id is None:
                _needs('original_authorized_professional_coordinator')
            response=read(request.coordination_requirement_ref,ServiceResponseRequirementView)
            if not same(response.request_ref,appointment.request_ref) or request.coordination_recipient_id not in response.recipient_ids:
                raise ValueError('Coordination exceeds original request/recipient authority')
            return completed('request_coordination',issue_refs=request.coordination_issue_refs,recipient_id=request.coordination_recipient_id)
        if target.issue_coverage!='complete': _needs('complete_original_visible_professional_review_issues')
        items=[];uncovered=set(scopes)-{spec.engineering_scope_ref.key() for spec in specs.values()} | interface_gap_scopes
        for key,spec in specs.items():
            saved=saved_results.get(key);value,missing,basis,evidence_status=None,['method_execution'],[],'missing'
            if spec.method_ref is None: missing.append('method_ref')
            item_issues={ref.key():ref for ref in [*target.unresolved_issue_refs,*spec.issue_refs]}
            for interface in interfaces:
                if same(interface.engineering_scope_ref,spec.engineering_scope_ref):
                    item_issues.update({ref.key():ref for ref in interface.issue_refs})
            if saved is not None:
                item_issues.update({ref.key():ref for ref in saved.issue_refs})
                if saved.status=='ok':
                    if not same(saved.method_ref,ENGINEER_INTERFACE_METHOD): _unsupported('engineer-review-unbound-professional-method')
                    method_domain(spec,saved.executed_at)
                    facts,fact_basis,original_refs,states=original_facts(spec,saved.executed_at)
                    basis.extend(fact_basis)
                    if saved.input_fact_refs != original_refs: raise ValueError('Professional method result changes exact original fact versions')
                    execution_grant=read(saved.author_authority_ref,Authorization)
                    if not keys(original_refs) <= keys(execution_grant.readable_refs):
                        raise ValueError('Professional execution author lacks original input read authority')
                    replay=check_interface(EngineerInterfaceInput(requested_check=spec.requested_check,left_code=states[0],right_code=states[1],source_refs=original_refs))
                    if saved.result != replay: raise ValueError('Professional saved output differs from original declared method and facts')
                    value,missing=replay.result,replay.missing_field_paths
                    records=evidence(basis)
                    if all(fact is not None and isinstance(fact.value,Known) for fact in facts):
                        evidence_status='sufficient' if all(fact.basis=='observed' for fact in facts) and all(row.basis_kind=='observed' for row in records) else 'assumption_based'
                else: missing=['method_execution:'+saved.status]
            if value in {None,'undetermined','out_of_scope'} or evidence_status!='sufficient' or item_issues:
                uncovered.add(spec.engineering_scope_ref.key())
            items.append({'check_spec_ref':spec.ref,'evidence_refs':list({ref.key():ref for ref in basis}.values()),
                'evidence_status':evidence_status,'method_result_ref':saved.ref if saved else None,'result':value,
                'missing_field_paths':missing,'issue_refs':list(item_issues.values())})
        findings=[row['result'] for row in items]
        opinion=('revise' if 'conflict' in findings else 'investigate' if not findings or any(value in {None,'undetermined'} for value in findings)
                 else 'reserve_interpretation' if uncovered or issues or 'out_of_scope' in findings else 'support_limited_option')
        explanation=request.explanation
        if uncovered or not items: explanation+='; original unverified or uncovered professional scope remains; no project-wide approval'
        return completed('assess',assessment={'target_ref':target.ref,'task_ref':task.ref,'check_items':items,'opinion':opinion,
            'requested_use':request.requested_use,'uncovered_scope_refs':[scopes[key].ref for key in sorted(uncovered)],'explanation':explanation})
    except ObservationGap as gap:
        reading.recheck();return gap.result
