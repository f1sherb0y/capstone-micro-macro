"""Produce private learning assessments through fixed role-specific routes."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_learning_objects import QSLearningAssessmentView
from src.actions.contracts.architect_learning_objects import ArchitectLearningAssessmentView
from src.actions.contracts.engineer_learning_objects import EngineerLearningAssessmentView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_learning import prepare_qs_learning_assessment_input
from src.actions.roles.architect_learning import prepare_architect_learning_assessment_input
from src.actions.roles.engineer_learning import prepare_engineer_learning_assessment_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_learning import LEARNING_METHOD
from src.organization.models import Authorization


def prepare_service_learning_assessment(*, context, action_input, reading,
        assessment_ref, author_authority_ref, validate_current, action_id):
    """Invoke the declared rule method once after independent actual-source checks.

    Caller holds the actual source/authorization writer guard. Cost-learning
    samples retain original comparable/error report dependencies; the source
    gate must verify their saved execution provenance. No strategy is applied,
    feedback recognized or capability improved by creating this assessment.
    """
    context=ActionContext.model_validate(context).model_copy(deep=True)
    # Only code-defined routes select types and input preparation; source data
    # cannot select arbitrary projection classes or executable functions.
    if action_id == 'QS-A12':
        role, assessment_kind = 'QS', 'QSLearningAssessment'
        projection_model = QSLearningAssessmentView
        prepare_input = prepare_qs_learning_assessment_input
    elif action_id == 'ARCHITECT-A12':
        role, assessment_kind = 'Architect', 'ArchitectLearningAssessment'
        projection_model = ArchitectLearningAssessmentView
        prepare_input = prepare_architect_learning_assessment_input
    elif action_id == 'ENGINEER-A12':
        role, assessment_kind = 'Engineer', 'EngineerLearningAssessment'
        projection_model = EngineerLearningAssessmentView
        prepare_input = prepare_engineer_learning_assessment_input
    else:
        raise TaskConflict('Learning assessment requires a supported fixed action route')
    assessment_ref=ref_type(assessment_kind).model_validate(assessment_ref).model_copy(deep=True)
    author_authority_ref=ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading,ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind!='ActionContract' or context.contract_ref.id!=action_id
            or action_input.scope!=context.scope or type(assessment_ref.version) is not str):
        raise TaskConflict('Learning assessment requires original action reading and immutable authorized target')
    reading.check_method_context(context,action_id)
    mode='fixture' if context.execution_mode=='offline_fixture' else 'formal'
    if reading._resolver.source_mode!=mode:
        raise TaskConflict('Learning assessment substitutes its original explicit source mode')
    before=reading.method_evidence()
    prepared=prepare_input(context,action_input,reading)
    if reading.method_evidence()!=before:
        raise TaskConflict('Learning assessment input must not rerun original cost comparison/error methods')
    if prepared['kind']!='prepared':
        return prepared
    if (prepared['assessment_ref'] is not None and prepared['assessment_ref'] != assessment_ref
            or any(row['ref'] == assessment_ref.model_dump(mode='json') for row in reading.evidence())):
        raise TaskConflict('Learning assessment must use its predeclared target without replacing a supplied report')
    data=prepared['input']
    grant=reading.resolve(author_authority_ref)
    if (not isinstance(grant,Authorization) or author_authority_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context,action_id,role)
            or assessment_ref not in context.visible_refs or assessment_ref not in grant.readable_refs):
        raise TaskConflict('Learning assessment lacks actual current role author and target read authority')
    for ref in grant.basis_refs:
        evidence=reading.resolve(ref)
        if (not isinstance(evidence,EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Learning assessment author lacks current actual evidence')
    methods=reading._methods
    registry_sha256=methods.content_digest if methods is not None else None
    if validate_current(context=context.model_copy(deep=True),action_input=action_input.model_copy(deep=True),
            assessment_input=data.model_copy(deep=True),assessment_ref=assessment_ref.model_copy(deep=True),
            dependencies={name:row.model_copy(deep=True) for name,row in prepared['dependencies'].items()},
            reading=reading) is not None:
        raise TaskConflict('Learning assessment requires independent current original feedback/rule/dependency validation')
    reading.recheck()
    if (reading.method_evidence()!=before or reading._methods is not methods
            or methods is not None and methods.content_digest!=registry_sha256):
        raise TaskConflict('Learning assessment source gate executed a method or changed its registry')
    if mode=='formal' and any(row['ref']['kind']=='Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind=='synthetic' for row in reading.evidence()):
        raise TaskConflict('Formal learning assessment cannot use synthetic source evidence')
    result=reading.calculate(LEARNING_METHOD,data)
    executions=reading.method_evidence()
    if (len(executions)!=len(before)+1 or executions[:-1]!=before
            or executions[-1]['input']!=data.model_dump(mode='json')
            or executions[-1]['result']!=result.model_dump(mode='json')
            or executions[-1]['registry_digest']!=registry_sha256 or reading._methods is not methods
            or methods is not None and methods.content_digest!=registry_sha256):
        raise TaskConflict('Learning assessment lost original declared-rule execution proof')
    reading.recheck()
    if result.kind!='ok':
        return result.model_dump(mode='python')
    sources=reading.evidence()
    now=context.business_time
    projection=projection_model(ref=assessment_ref,organization_id=reading.organization_id,
        strategy_ref=prepared['strategy_ref'],learning_profile_ref=prepared['learning_profile_ref'],data=data,
        input_sha256=task_digest(data.model_dump(mode='json')),report=result.value,status='ok',scope=context.scope,
        author_actor_id=context.actor_id,author_organization_id=reading.organization_id,
        author_function_ref=context.function_ref,author_authority_ref=author_authority_ref,author_action_id=action_id,
        authored_at=now,available_at=now,effective_window={'start':now,'end':now,'bounds':'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind']=='Evidence'])
    return {'kind':'prepared','projection':projection,'projection_sha256':task_digest(projection.model_dump(mode='json')),
        'context_sha256':task_digest(context.model_dump(mode='json')),'input_sha256':task_digest(action_input.model_dump(mode='json')),
        'source_mode':mode,'source_reading':sources,'reading_sha256':task_digest(sources),
        'author_authority_ref':author_authority_ref.model_dump(mode='json'),
        'dependencies':{name:row.model_dump(mode='json') for name,row in prepared['dependencies'].items()},
        'method_execution':executions[-1],'method_registry_sha256':registry_sha256,
        'limitations':['Declared finite feedback rules only; no causal proof of learning effectiveness.',
            'Persist and publish before use; no strategy, feedback history, capability, training or cash effect.']}
