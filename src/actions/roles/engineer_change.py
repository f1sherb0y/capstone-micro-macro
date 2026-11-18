"""ENGINEER-A09 appends remedy/revision/recheck proposals without undoing history."""
import hashlib
import json
from types import SimpleNamespace
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeDeliverableView, EngineerChangeIssueView, EngineerChangeObligationView,
    EngineerChangeProfileView, EngineerChangeInstructionView, EngineerChangeBasisView,
    EngineerChangeQuestionView, EngineerChangeCheckView, EngineerChangeCheckResultView,
    EngineerChangeScopeView, EngineerChangeMethodView, EngineerChangeDependencyView,
    EngineerChangeMethodProjection,
    EngineerRemedyAuthorityView,
    EngineerChangeIndependenceView,
    EngineerChangeCheckPreparation,
    EngineerChangeParameterPreparation,
    EngineerChangeRevisionCheckPreparation,
)
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignTaskView, EngineerDesignProfileView, EngineerValidatedParameterView,
    EngineerResearchFactView, EngineerPlanningWorkFactView,
)
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.engineer_design import compile_professional_design, _compile_professional_design
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD, EngineerInterfaceInput, check_interface
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def handle_professional_change(context, action_input, reading):
    return _handle_professional_change(context, action_input, reading)


def recheck_original_engineer_change_candidate_limit(context, action_input, reading):
    """Reproduce the original A09 candidate gate without producing another revision."""
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A09':
        raise ValueError('Original revision candidate recheck requires the actual A09 contract')
    reading.check_method_context(context, 'ENGINEER-A09')
    before = reading.method_evidence()
    try:
        result = _handle_professional_change(context, action_input, reading, original_candidate_wait_only=True)
        if (not isinstance(result, dict) or result.get('kind') != 'deferred'
                or result.get('reason_code') != 'original_professional_candidate_revision_limit_reached'):
            raise ValueError('Original A09 sources do not reproduce the candidate/revision limit wait')
        return result
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical revision candidate recheck cannot execute design methods')


def recheck_original_engineer_change_work_limit(context, action_input, reading):
    """Reproduce original A09 effort/cost limits without producing another revision."""
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A09':
        raise ValueError('Original revision work recheck requires the actual A09 contract')
    reading.check_method_context(context, 'ENGINEER-A09')
    before = reading.method_evidence()
    try:
        result = _handle_professional_change(context, action_input, reading, original_work_wait_only=True)
        if (not isinstance(result, dict) or result.get('kind') != 'deferred'
                or result.get('reason_code') != 'original_professional_work_limit_reached'):
            raise ValueError('Original A09 sources do not reproduce the effort/cost limit wait')
        return result
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical revision work recheck cannot execute design methods')


def recheck_original_engineer_change_submission(context, action_input, reading):
    """Reproduce the original A09 registration query without producing another revision."""
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A09':
        raise ValueError('Original revision submission recheck requires the actual A09 contract')
    reading.check_method_context(context, 'ENGINEER-A09')
    before = reading.method_evidence()
    try:
        result = _handle_professional_change(context, action_input, reading, original_submission_wait_only=True)
        if (not isinstance(result, dict) or result.get('kind') != 'deferred'
                or result.get('reason_code') != 'query_original_professional_submission_before_reproduction'):
            raise ValueError('Original A09 sources do not reproduce the prior submission query')
        return result
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical revision submission recheck cannot execute design methods')


def prepare_engineer_change_check_input(context, action_input, reading, preparation):
    """Reuse original obligation/independence/work without consuming future checks."""
    preparation = EngineerChangeCheckPreparation.model_validate(preparation).model_copy(deep=True)
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A09':
        raise ValueError('Change check preparation requires original Engineer A09 contract')
    reading.check_method_context(context, 'ENGINEER-A09')
    before = reading.method_evidence()
    future = {ref.key() for ref in action_input.method_result_refs}

    def recheck_preparation():
        if reading.method_evidence() != before or future.intersection(reading._reads):
            raise ValueError('Change preparation cannot execute methods or consume future checks')

    recheck_preparation()
    try:
        return _handle_professional_change(context, action_input, reading, check_preparation=preparation)
    finally:
        reading.recheck()
        recheck_preparation()


def prepare_engineer_change_parameter_input(context, action_input, reading, preparation):
    """Prepare an authorized revision without consuming or computing future results."""
    preparation = EngineerChangeParameterPreparation.model_validate(preparation).model_copy(deep=True)
    return _prepare_engineer_change_revision_input(context, action_input, reading, parameter_preparation=preparation)


def prepare_engineer_change_revision_check_input(context, action_input, reading, preparation):
    """Prepare the original revision check without consuming future executions."""
    preparation = EngineerChangeRevisionCheckPreparation.model_validate(preparation).model_copy(deep=True)
    return _prepare_engineer_change_revision_input(context, action_input, reading, revision_check_preparation=preparation)


def _prepare_engineer_change_revision_input(context, action_input, reading, **preparation):
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A09':
        raise ValueError('Revision method preparation requires original Engineer A09 contract')
    reading.check_method_context(context, 'ENGINEER-A09')
    before = reading.method_evidence()
    future = {ref.key() for ref in action_input.method_result_refs}

    def recheck_preparation():
        if reading.method_evidence() != before or future.intersection(reading._reads):
            raise ValueError('Revision preparation cannot execute methods or consume future results')

    recheck_preparation()
    try:
        return _handle_professional_change(context, action_input, reading, **preparation)
    finally:
        reading.recheck()
        recheck_preparation()


def _handle_professional_change(context, action_input, reading, *, check_preparation=None,
        parameter_preparation=None, revision_check_preparation=None, original_candidate_wait_only=False,
        original_work_wait_only=False, original_submission_wait_only=False):
    if (sum(value is not None for value in (check_preparation, parameter_preparation, revision_check_preparation))
            + int(original_candidate_wait_only) + int(original_work_wait_only) + int(original_submission_wait_only) > 1):
        raise ValueError('Change preparation requires one explicit original branch')
    now,organization=context.business_time,reading.organization_id

    def same(left,right):return left.key()==right.key()

    def keys(refs):
        unique_refs(refs);return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref:_unsupported('engineer-change-clock-alignment')

    def evidence(refs,historical=False):
        rows=[]
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):_unsupported('engineer-change-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now):_needs('current_original_engineering_change_evidence',[ref])
            rows.append(row)
        return rows

    def read(ref,schema,historical=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema):_unsupported('engineer-change-projection:'+ref.kind)
        if hasattr(row,'scope') and not scope_covers(action_input.scope,row.scope):raise ValueError('Engineering change widens original scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset:_needs('received_original_engineering_change_record',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now):_needs('effective_original_engineering_change_record',[ref])
        evidence(getattr(row,'evidence_refs',[]),historical);return row

    def authorize(ref,actor,function_ref,org,action,at):
        grant=read(ref,Authorization);function=read(function_ref,RoleAssignment)
        roles={'ENGINEER':'Engineer','ARCHITECT':'Architect','QS':'QS','CONTRACTOR':'Contractor','OWN':'Owner','GOV':'Government','SUPPLIER':'Supplier','BANK':'Bank'}
        if (grant.actor_id!=actor or not same(grant.function_ref,function_ref) or grant.organization_id!=org
                or action not in grant.action_ids or function.role!=roles.get(action.split('-')[0])
                or not any(scope_covers(s,action_input.scope) for s in grant.scopes)):
            raise ValueError('Engineering change lacks independent original author/function/action authority')
        clock(grant.validity.start);clock(at)
        if not grant.validity.contains(at):_needs('valid_original_engineering_change_authority',[ref])
        evidence([*grant.basis_refs,*function.basis_refs],at!=now);return grant

    def completed(choice,**fields):
        reading.recheck();return {'kind':'completed','payload':{'choice':choice,'scope':action_input.scope,'note':profile.note,**fields}}

    def deferred(code,refs):
        reading.recheck();return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':refs,'earliest_time':None,'condition_code':code}}

    def questions():
        result=[]
        for ref in profile.question_refs:
            gap=read(ref,EngineerChangeQuestionView);question=gap.question
            if (not same(gap.issue_ref,issue.ref) or not same(gap.used_deliverable_ref,original.ref)
                    or question.scope!=action_input.scope or not question.recipient_ids or ref.key() not in keys(question.target_refs)):
                raise ValueError('Engineering remedy question changes original issue/version/scope')
            response=read(question.response_requirement_ref,ServiceResponseRequirementView)
            if not set(question.recipient_ids)<=set(response.recipient_ids):raise ValueError('Engineering remedy exceeds original response recipients')
            for ref in question.target_refs:
                target=read(ref,EngineerChangeQuestionView)
                if not same(target.issue_ref,issue.ref) or not same(target.used_deliverable_ref,original.ref) or target.question!=question:
                    raise ValueError('Engineering remedy question changes original target/content')
            evidence(question.evidence_refs);result.append(question.model_dump(mode='python'))
        return result

    def bound(row):
        if (not same(row.issue_ref,issue.ref) or not same(row.obligation_ref,obligation.ref)
                or not same(row.used_deliverable_ref,original.ref) or row.original_content_sha256!=original.content_sha256):
            raise ValueError('Engineering instruction changes original issue/obligation/version/content')

    def method_domain(method):
        template=read(original.engineering_profile_ref,EngineerDesignProfileView)
        if (profile.discipline_code not in method.discipline_codes or profile.function_code not in method.function_codes
                or template.region_id not in method.region_ids or template.object_type not in method.object_types
                or profile.requested_use not in method.allowed_uses):_unsupported('engineer-change-method-professional-object-use-domain')

    def original_facts(spec, at):
        facts, basis_refs = [], []
        for ref in (spec.left_fact_ref, spec.right_fact_ref):
            if ref is None:
                facts.append(None)
                continue
            fact = read(ref, EngineerResearchFactView)
            if (not same(fact.target_ref, original.ref) or not same(fact.engineering_scope_ref, spec.engineering_scope_ref)
                    or fact.available_at.offset > at.offset or not fact.effective_window.contains(at)):
                raise ValueError('Engineering recheck changes actual current-version fact/coverage/time')
            facts.append(fact)
            basis_refs.extend(fact.evidence_refs)
        refs = [ref for ref in (spec.left_fact_ref, spec.right_fact_ref) if ref is not None]
        states = [fact.value if fact else {'state': 'unknown', 'reason_code': 'original_recheck_fact_missing',
            'missing_refs': []} for fact in facts]
        return facts, basis_refs, refs, states

    try:
        if context.scope!=action_input.scope:raise ValueError('Engineering change changes original action scope')
        original=read(action_input.prior_deliverable_ref,EngineerChangeDeliverableView,True)
        issue=read(action_input.issue_ref,EngineerChangeIssueView)
        obligation=read(action_input.obligation_ref,EngineerChangeObligationView)
        profile=read(issue.change_profile_ref,EngineerChangeProfileView)
        if (not same(issue.used_deliverable_ref,original.ref) or not same(issue.obligation_ref,obligation.ref)
                or not same(obligation.deliverable_ref,original.ref) or obligation.organization_id!=organization
                or not same(profile.issue_ref,issue.ref) or not same(profile.obligation_ref,obligation.ref)):
            raise ValueError('Engineering remedy borrows original issue/obligation/version')
        if issue.issue_status=='closed' or obligation.status=='terminated':_needs('original_open_issue_and_effective_work_obligation')
        reading.resolve(obligation.contract_ref)
        authorize(profile.authority_ref,context.actor_id,context.function_ref,organization,'ENGINEER-A09',now)
        clock(original.authored_at)
        if original.authored_at.offset>min(now.offset,original.available_at.offset):_needs('original_professional_work_authored_before_received')
        authorize(original.author_authority_ref,original.author_actor_id,original.author_function_ref,
            original.author_organization_id,original.author_action_id,original.authored_at)
        if (profile.discipline_code not in obligation.discipline_codes or profile.function_code not in obligation.function_codes
                or profile.requested_use not in obligation.requested_uses):raise ValueError('Engineering remedy leaves original professional obligation scope')
        if profile.choice not in obligation.permitted_choices:_needs('original_authorized_engineering_remedy_choice')
        if keys(action_input.evidence_refs)!=keys(profile.input_evidence_refs) or keys(action_input.method_result_refs)!=keys(profile.method_result_refs):
            _needs('all_original_engineering_change_evidence_and_executions')
        evidence(action_input.evidence_refs)
        instruction=None
        if action_input.instruction_ref is not None:
            instruction=read(action_input.instruction_ref,EngineerChangeInstructionView);bound(instruction);clock(instruction.issued_at)
            if (not same(instruction.contract_ref,obligation.contract_ref)
                    or instruction.issuer_organization_id not in obligation.permitted_instruction_issuer_ids
                    or instruction.issuer_action_id not in obligation.permitted_instruction_action_ids):
                raise ValueError('Engineering change instruction changes contract or permitted issuer')
            if instruction.issued_at.offset>min(now.offset,instruction.available_at.offset):_needs('engineering_instruction_issued_before_received')
            authorize(instruction.issuer_authority_ref,instruction.issuer_actor_id,instruction.issuer_function_ref,
                instruction.issuer_organization_id,instruction.issuer_action_id,instruction.issued_at)
        if not profile.affected_refs or not keys(profile.affected_refs)<=keys(obligation.permitted_affected_deliverable_refs):
            raise ValueError('Engineering remedy invents or omits original affected versions')
        for ref in profile.affected_refs:read(ref,EngineerChangeDeliverableView,True)
        if check_preparation is not None and profile.choice != 'reassess':
            raise ValueError('Change check preparation requires original reassess branch')
        if parameter_preparation is not None and profile.choice != 'revise':
            raise ValueError('Change parameter preparation requires original revise branch')
        if revision_check_preparation is not None and profile.choice != 'revise':
            raise ValueError('Revision check preparation requires original revise branch')
        if (original_candidate_wait_only or original_work_wait_only or original_submission_wait_only) and profile.choice != 'revise':
            raise ValueError('Historical revision limit recheck requires the original revise branch')
        if profile.choice=='propose_remedy':
            request=profile.remedy_request
            if request is None:_needs('original_bounded_remedy_task_request')
            if (request.scope!=action_input.scope or keys(request.authority_basis_refs)!={obligation.remedy_authority_ref.key()}
                    or not {issue.ref.key(),obligation.ref.key(),original.ref.key()}<=keys(request.input_refs)):
                raise ValueError('Remedy request changes original scope/input/work authority')
            # A pending request does not manufacture a Task, allocation or numeric effort execution.
            if isinstance(request.effort_estimate,Known):_unsupported('engineer-change-unbound-remedy-effort-estimator')
            grant=read(obligation.remedy_authority_ref,EngineerRemedyAuthorityView)
            if (grant.organization_id!=organization or grant.actor_id!=context.actor_id
                    or not same(grant.issue_ref,issue.ref) or not same(grant.obligation_ref,obligation.ref)
                    or request.purpose not in grant.permitted_purposes or not keys(request.input_refs)<=keys(grant.permitted_input_refs)):
                raise ValueError('Remedy request changes independent original application authority')
            if not _known(grant.permission,'original_remedy_application_permission'):_needs('authorized_original_remedy_application')
            for ref in [*request.input_refs,*request.output_requirement_refs,*request.dependency_refs]:reading.resolve(ref)
            if request.work_profile_ref is not None:reading.resolve(request.work_profile_ref)
            if isinstance(request.desired_window,Known):
                clock(request.desired_window.value.start)
                if request.desired_window.value.start.offset>=request.desired_window.value.end.offset:
                    raise ValueError('Requested remedy work window must be nonempty')
            for state in (request.effort_estimate,request.desired_window):
                if state.state=='unknown':evidence(state.missing_refs)
            questions()
            if request.questions!=[read(ref,EngineerChangeQuestionView).question for ref in profile.question_refs]:
                raise ValueError('Remedy request changes original work questions')
            return completed('propose_remedy',request=request.model_dump(mode='python'),affected_refs=profile.affected_refs)
        if profile.choice=='request_test':
            if profile.test_method_ref is None:_needs('original_engineering_remedy_test_method')
            method=read(profile.test_method_ref,EngineerChangeMethodView);method_domain(method)
            if method.purpose!='test':raise ValueError('Engineering remedy test request changes original method purpose')
            result=questions()
            if not result:_needs('specific_original_engineering_remedy_test_questions')
            return completed('request_test',questions=result,method_ref=method.ref)
        if profile.choice=='revise':
            if original.author_organization_id!=organization or original.author_action_id not in {'ENGINEER-A05','ENGINEER-A09'}:
                return deferred('original_author_or_authorized_integrator_must_revise_other_design',[original.ref,issue.ref])
            if (obligation.instruction_required_for_revision and not (issue.kind=='defect' and obligation.defect_remedy_authorized)
                    and (instruction is None or instruction.status!='authorized')):
                return deferred('original_revision_instruction_required',[issue.ref,obligation.ref])
            if instruction is not None and instruction.status!='authorized':return deferred('original_revision_instruction_not_authorized',[instruction.ref])
            if profile.revision_task_ref is None or profile.change_basis_ref is None:_needs('original_revision_task_and_change_basis')
            task=read(profile.revision_task_ref,EngineerDesignTaskView)
            if task.draft is None or task.choice!='produce' or not same(task.appointment_ref,obligation.appointment_ref):
                raise ValueError('Engineering revision lacks original producing task/appointment')
            if (not same(task.brief_ref,original.brief_ref) or not same(task.engineering_profile_ref,original.engineering_profile_ref)
                    or task.discipline_code!=profile.discipline_code or task.function_code!=profile.function_code
                    or task.requested_use!=profile.requested_use or task.draft.parent_option_ref is None
                    or not same(task.draft.parent_option_ref,original.option_ref)):
                raise ValueError('Engineering revision changes original profile/task/professional parent')
            for ref in task.question_refs:
                gap=read(ref,EngineerChangeQuestionView)
                if gap.task_ref is None or gap.brief_ref is None:_needs('original_revision_question_task_and_brief')
            basis=read(profile.change_basis_ref,EngineerChangeBasisView);clock(basis.verified_at)
            draft_hash=hashlib.sha256(json.dumps(task.draft.model_dump(mode='json'),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            if (not same(basis.issue_ref,issue.ref) or not same(basis.obligation_ref,obligation.ref)
                    or not same(basis.prior_deliverable_ref,original.ref) or basis.original_content_sha256!=original.content_sha256
                    or basis.instruction_ref!=action_input.instruction_ref or basis.draft_sha256!=draft_hash):
                raise ValueError('Engineering change basis alters original obligation/version/instruction/proposed draft')
            if basis.verified_at.offset>min(now.offset,basis.available_at.offset):_needs('original_engineering_change_basis_received')
            if (basis.author_organization_id!=organization or basis.author_action_id!='ENGINEER-A09'):
                raise ValueError('Engineering revision basis needs original organization A09 authority')
            authorize(basis.author_authority_ref,basis.author_actor_id,basis.author_function_ref,basis.author_organization_id,basis.author_action_id,basis.verified_at)
            if not _known(basis.authorized,'original_verified_engineering_change_basis'):_needs('authorized_original_engineering_change_basis')
            catalogs=set();new_values={};old_values={}
            for ref in task.draft.selected_parameter_refs:
                parameter=read(ref,EngineerValidatedParameterView);catalogs.add(parameter.catalog_ref.key())
                new_values[parameter.catalog_ref.key()]=parameter.value
            keys(original.parameter_refs)
            for ref in original.parameter_refs:
                parameter=read(ref,EngineerValidatedParameterView,True)
                if not same(parameter.engineering_profile_ref,original.engineering_profile_ref) or parameter.catalog_ref.key() in old_values:
                    raise ValueError('Original professional design repeats or changes parameter catalog')
                old_values[parameter.catalog_ref.key()]=parameter.value
            changed_catalogs={key for key in set(old_values)|set(new_values) if old_values.get(key)!=new_values.get(key)}
            if not changed_catalogs<=keys(obligation.permitted_parameter_catalog_refs):raise ValueError('Engineering revision widens permitted changed parameter catalogs')
            if instruction is not None and (not changed_catalogs<=keys(instruction.permitted_parameter_catalog_refs)
                    or not keys(profile.affected_refs)<=keys(instruction.affected_deliverable_refs)):
                raise ValueError('Engineering revision widens original instructed parameter/affected scope')
            expected_dependencies=set()
            for ref in original.dependency_refs:
                dependency=read(ref,EngineerChangeDependencyView,True)
                if not same(dependency.used_deliverable_ref,original.ref):raise ValueError('Engineering dependency changes original version')
                if dependency.status!='released' and keys(dependency.parameter_catalog_refs)&changed_catalogs:expected_dependencies.add(ref.key())
            if not expected_dependencies<=keys(profile.affected_dependency_refs) or not keys(profile.affected_dependency_refs)<=keys(original.dependency_refs):
                raise ValueError('Engineering revision drops or invents original affected dependencies')
            inputs=SimpleNamespace(scope=action_input.scope,brief_ref=original.brief_ref,task_ref=task.ref,
                engineering_profile_ref=original.engineering_profile_ref,evidence_refs=action_input.evidence_refs,
                method_result_refs=action_input.method_result_refs,prior_option_ref=original.option_ref)
            if parameter_preparation is not None or revision_check_preparation is not None:
                result = _compile_professional_design(context, inputs, reading, action_id='ENGINEER-A09',
                    parameter_preparation=parameter_preparation, check_preparation=revision_check_preparation)
                if result['kind'] == 'prepared':
                    if revision_check_preparation is not None:
                        spec = result['spec']
                        if (not isinstance(spec, EngineerChangeCheckView)
                                or spec.original_content_sha256 != original.content_sha256):
                            raise ValueError('Revision interface check replaces original parent content version')
                    result.update(issue=issue, original=original, obligation=obligation,
                        change_profile=profile, change_basis=basis, instruction=instruction)
                return result
            if original_candidate_wait_only or original_work_wait_only or original_submission_wait_only:
                return _compile_professional_design(context,inputs,reading,action_id='ENGINEER-A09',
                    original_candidate_wait_only=original_candidate_wait_only, original_work_wait_only=original_work_wait_only,
                    original_submission_wait_only=original_submission_wait_only)
            result=compile_professional_design(context,inputs,reading,action_id='ENGINEER-A09')
            if result['kind']!='completed':return result
            if result['payload']['choice']!='produce':raise ValueError('Engineering revision helper must produce exact original professional draft')
            return completed('revise',draft=result['payload']['draft'],change_basis_ref=basis.ref)
        if profile.reassessment_task_ref is None:_needs('original_actual_reassessment_task')
        task=read(profile.reassessment_task_ref,EngineerDesignTaskView)
        if (task.organization_id!=organization or task.status!='authorized' or not same(task.appointment_ref,obligation.appointment_ref)
                or not same(task.brief_ref,original.brief_ref) or not same(task.engineering_profile_ref,original.engineering_profile_ref)
                or task.discipline_code!=profile.discipline_code or task.function_code!=profile.function_code or task.requested_use!=profile.requested_use):
            raise ValueError('Engineering reassessment changes original task/appointment/professional scope')
        authorize(task.authority_ref,context.actor_id,context.function_ref,organization,'ENGINEER-A09',now)
        if obligation.independence_rule!='no_requirement':
            if profile.reassessment_independence_ref is None:_needs('original_required_reassessment_independence_check')
            check=read(profile.reassessment_independence_ref,EngineerChangeIndependenceView)
            if (not same(check.issue_ref,issue.ref) or not same(check.target_ref,original.ref)
                    or check.reviewer_organization_id!=organization or check.reviewer_actor_id!=context.actor_id
                    or set(check.reviewer_personnel_ids)!=set(profile.reviewer_personnel_ids)
                    or check.author_organization_id!=original.author_organization_id
                    or set(check.author_personnel_ids)!=set(original.author_personnel_ids)):
                raise ValueError('Reassessment independence changes original issue/target/authors/reviewers')
            if (not profile.reviewer_personnel_ids or len(set(profile.reviewer_personnel_ids))!=len(profile.reviewer_personnel_ids)
                    or len(set(check.author_personnel_ids))!=len(check.author_personnel_ids)
                    or len(set(check.reviewer_personnel_ids))!=len(check.reviewer_personnel_ids)):
                raise ValueError('Reassessment independence repeats or omits actual personnel')
            if check.coverage!='complete' or check.as_of!=now:_needs('complete_current_original_reassessment_independence')
            clock(check.verified_at)
            if check.verified_at.offset>min(now.offset,check.available_at.offset):_needs('original_reassessment_independence_received')
            if check.verifier_action_id!='ENGINEER-A03':raise ValueError('Reassessment independence needs original A03 authority')
            authorize(check.verifier_authority_ref,check.verifier_actor_id,check.verifier_function_ref,
                check.verifier_organization_id,check.verifier_action_id,check.verified_at)
            if context.actor_id==original.author_actor_id or set(profile.reviewer_personnel_ids)&set(original.author_personnel_ids):
                _needs('reassessment_personnel_independent_of_original_authors')
            if obligation.independence_rule=='unrelated_organization_and_personnel':
                related=_known(check.related_organization_ids,'original_reassessment_organization_relations')
                if original.author_organization_id in {organization,*related}:_needs('reassessment_organization_independent_of_original_authors')
        if keys(task.method_result_refs)!=keys(action_input.method_result_refs):
            _needs('all_original_reassessment_task_executions')
        if action_input.method_result_refs:
            invested=Fraction();investments=set()
            keys(task.work_fact_refs)
            for ref in task.work_fact_refs:
                fact=read(ref,EngineerPlanningWorkFactView,True);clock(fact.window.start)
                if (not same(fact.task_ref,task.ref) or fact.organization_id!=organization or fact.investment_key in investments):
                    raise ValueError('Engineering recheck repeats investment or borrows another task')
                if fact.status!='committed' or fact.window.end.offset>min(now.offset,fact.available_at.offset):
                    _needs('actual_confirmed_reassessment_work')
                if fact.effort.unit!=task.required_effort.unit:_unsupported('engineer-change-recheck-effort-unit-conversion')
                effort=decimal_fraction(fact.effort.value)
                if effort<0 or decimal_fraction(fact.internal_cost.value)<0:raise ValueError('Recheck investment/cost cannot be negative')
                evidence([fact.effort.basis_ref,fact.internal_cost.basis_ref],True)
                invested+=effort;investments.add(fact.investment_key)
            evidence([task.required_effort.basis_ref])
            if decimal_fraction(task.required_effort.value)<=0 or invested<decimal_fraction(task.required_effort.value):
                _needs('actual_work_for_original_reassessment_executions')
        scopes={ref.key():read(ref,EngineerChangeScopeView) for ref in profile.reassessment_scope_refs};keys(profile.reassessment_scope_refs)
        for row in scopes.values():
            if not same(row.used_deliverable_ref,original.ref) or row.discipline_code!=profile.discipline_code or not row.physical_keys:
                raise ValueError('Engineering recheck changes original scope/discipline')
        specs={ref.key():read(ref,EngineerChangeCheckView) for ref in profile.reassessment_check_refs};keys(profile.reassessment_check_refs)
        if check_preparation is not None:
            mappings = task.check_result_targets
            keys([row.check_spec_ref for row in mappings]); keys([row.calculation_ref for row in mappings])
            if (keys(task.check_spec_refs) != set(specs)
                    or not {row.check_spec_ref.key() for row in mappings} <= set(specs)
                    or not {row.calculation_ref.key() for row in mappings} <= keys(action_input.method_result_refs)):
                raise ValueError('Change check mapping leaves original reassessment task/spec/results')
            selected = next((row for row in mappings if row.check_spec_ref == check_preparation.check_spec_ref), None)
            if selected is None:
                _needs('original_declared_reassessment_result_target', [task.ref])
            if selected.calculation_ref != check_preparation.calculation_ref or type(selected.calculation_ref.version) is not str:
                raise ValueError('Change preparation replaces original versioned result target')
            for spec in specs.values():
                if (not same(spec.target_ref, original.ref) or not same(spec.brief_ref, original.brief_ref)
                        or spec.original_content_sha256 != original.content_sha256 or spec.engineering_scope_ref.key() not in scopes
                        or spec.discipline_code != profile.discipline_code or spec.function_code != profile.function_code
                        or profile.requested_use not in spec.allowed_uses):
                    raise ValueError('Engineering recheck specification changes original version/use')
                keys(spec.issue_refs)
                for ref in spec.issue_refs:
                    problem = read(ref, EngineerChangeIssueView)
                    if not same(problem.used_deliverable_ref, original.ref) or problem.issue_status == 'closed':
                        raise ValueError('Engineering recheck claims issue closure or changes affected version')
            spec = specs[selected.check_spec_ref.key()]
            if spec.method_ref != ENGINEER_INTERFACE_METHOD:
                _unsupported('engineer-change-unbound-professional-recheck-method')
            method = read(spec.method_ref, EngineerChangeMethodView)
            method_domain(method)
            if method.purpose != 'professional_check':
                _unsupported('engineer-change-recheck-method-purpose')
            _, basis_refs, fact_refs, states = original_facts(spec, now)
            evidence(basis_refs)
            source_refs = list({ref.key(): ref for ref in [task.ref, issue.ref, obligation.ref, profile.ref,
                original.ref, spec.ref, scopes[spec.engineering_scope_ref.key()].ref, method.ref,
                *fact_refs, *basis_refs, *task.work_fact_refs, *action_input.evidence_refs,
                *task.evidence_refs, *issue.evidence_refs, *obligation.evidence_refs, *profile.evidence_refs,
                *original.evidence_refs, *spec.evidence_refs, *method.evidence_refs]}.values())
            data = EngineerInterfaceInput(requested_check=spec.requested_check,
                left_code=states[0], right_code=states[1], source_refs=source_refs)
            if check_preparation.input != data:
                raise ValueError('Change preparation substitutes original issue/content/facts or input sources')
            reading.recheck()
            return {'kind': 'prepared', 'preparation': check_preparation, 'task': task, 'issue': issue,
                'original': original, 'profile': profile, 'spec': spec, 'input_fact_refs': fact_refs}
        saved={}
        for ref in action_input.method_result_refs:
            wrapped=read(ref,EngineerChangeMethodProjection)
            row=wrapped.record
            if not isinstance(row,EngineerChangeCheckResultView):_unsupported('engineer-change-reassessment-execution-schema')
            if (not same(row.ref,ref) or not same(row.task_ref,task.ref) or not same(row.issue_ref,issue.ref)
                    or row.original_content_sha256!=original.content_sha256 or not same(row.target_ref,original.ref)
                    or not same(row.brief_ref,original.brief_ref) or row.check_spec_ref.key() not in specs):
                raise ValueError('Engineering recheck borrows old version/issue/task/check result')
            clock(row.executed_at);clock(row.available_at)
            clock(row.effective_window.start)
            if (row.executed_at.offset>min(now.offset,row.available_at.offset) or row.available_at.offset>now.offset
                    or not row.effective_window.contains(now) or not scope_covers(action_input.scope,row.scope)):
                _needs('original_received_applicable_engineering_recheck_execution')
            authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,organization,'ENGINEER-A09',row.executed_at)
            evidence(row.evidence_refs)
            if row.check_spec_ref.key() in saved:raise ValueError('Engineering recheck repeats original check execution')
            if row.status!='ok' and row.result is not None:raise ValueError('Technical recheck failure cannot imply new version passed')
            saved[row.check_spec_ref.key()]=row
        items=[];uncovered=set(scopes)
        for key,spec in specs.items():
            if (not same(spec.target_ref,original.ref) or not same(spec.brief_ref,original.brief_ref)
                    or spec.original_content_sha256!=original.content_sha256 or spec.engineering_scope_ref.key() not in scopes
                    or spec.discipline_code!=profile.discipline_code or spec.function_code!=profile.function_code
                    or profile.requested_use not in spec.allowed_uses):raise ValueError('Engineering recheck specification changes original version/use')
            row=saved.get(key);value,missing,basis_refs,evidence_status=None,['method_execution'],[],'missing'
            if row is not None:
                if spec.method_ref is None or not same(row.method_ref,spec.method_ref):raise ValueError('Engineering recheck changes original method')
                if row.status=='ok':
                    if not same(row.method_ref,ENGINEER_INTERFACE_METHOD):_unsupported('engineer-change-unbound-professional-recheck-method')
                    method=read(row.method_ref,EngineerChangeMethodView);method_domain(method)
                    if not method.effective_window.contains(row.executed_at):_needs('original_recheck_method_valid_when_executed')
                    facts,basis_refs,original_refs,states=original_facts(spec,row.executed_at)
                    if row.input_fact_refs!=original_refs:raise ValueError('Engineering recheck changes exact original input versions')
                    replay=check_interface(EngineerInterfaceInput(requested_check=spec.requested_check,left_code=states[0],right_code=states[1],source_refs=original_refs))
                    if row.result!=replay:raise ValueError('Engineering recheck differs from declared method/facts')
                    value,missing=replay.result,replay.missing_field_paths
                    records=evidence(basis_refs)
                    if all(fact is not None and isinstance(fact.value,Known) for fact in facts):
                        evidence_status='sufficient' if all(fact.basis=='observed' for fact in facts) and all(record.basis_kind=='observed' for record in records) else 'assumption_based'
                else:missing=['method_execution:'+row.status]
            issue_refs=list(spec.issue_refs);keys(issue_refs)
            for ref in issue_refs:
                problem=read(ref,EngineerChangeIssueView)
                if not same(problem.used_deliverable_ref,original.ref) or problem.issue_status=='closed':raise ValueError('Engineering recheck claims issue closure or changes affected version')
            if value=='satisfied' and evidence_status=='sufficient' and not issue_refs:uncovered.discard(spec.engineering_scope_ref.key())
            items.append({'check_spec_ref':spec.ref,'evidence_refs':list({ref.key():ref for ref in basis_refs}.values()),'evidence_status':evidence_status,
                'method_result_ref':row.ref if row else None,'result':value,'missing_field_paths':missing,'issue_refs':issue_refs})
        for spec,item in zip(specs.values(),items):
            if item['result']!='satisfied' or item['evidence_status']!='sufficient' or item['issue_refs']:uncovered.add(spec.engineering_scope_ref.key())
        findings=[item['result'] for item in items]
        opinion=('revise' if 'conflict' in findings else 'investigate' if not findings or any(value in {None,'undetermined'} for value in findings)
            else 'reserve_interpretation' if uncovered or 'out_of_scope' in findings else 'support_limited_option')
        return completed('reassess',assessment={'target_ref':original.ref,'task_ref':task.ref,'check_items':items,'opinion':opinion,
            'requested_use':profile.requested_use,'uncovered_scope_refs':[scopes[key].ref for key in sorted(uncovered)],
            'explanation':profile.note+'; original issue and physical history retained, recheck does not itself close issues or grant use permission'})
    except ObservationGap as gap:
        reading.recheck();return gap.result
