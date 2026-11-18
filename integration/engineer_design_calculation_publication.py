"""Atomically publish original parameter and check results at one A05 read point."""
from copy import deepcopy
import json

from integration.engineer_parameter_publication import EngineerParameterPublicationStore
from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore
from src.actions.contracts.common import ActionContext, Reference
from src.coordination.tasks import TaskConflict, canonical, task_digest


def publish_engineer_design_calculations(*, parameters, checks, parameter_record_sha256s,
        check_record_sha256s, source_context, next_context):
    """Caller holds actual source guard; publish all original input results together.

    Both stores use the same durable journal, registry and authority. Validate
    their independent actual sources before a single transaction writes either
    boundary. Existing immutable boundaries may only match the complete batch.
    No methods, designs or formal engineering consequences execute here.
    """
    if (type(parameters) is not EngineerParameterPublicationStore
            or type(checks) is not EngineerInterfaceCheckPublicationStore):
        raise TaskConflict('Joint design publication requires original same-journal parameter/check stores')
    return _publish_engineer_joint_calculations(parameters=parameters, checks=checks,
        parameter_record_sha256s=parameter_record_sha256s, check_record_sha256s=check_record_sha256s,
        source_context=source_context, next_context=next_context)


def _publish_engineer_joint_calculations(*, parameters, checks, parameter_record_sha256s,
        check_record_sha256s, source_context, next_context):
    """Shared transaction after the role-specific entry checks exact store types."""
    if (parameters.ACTION_ID != checks.ACTION_ID
            or any(getattr(parameters, name) is not getattr(checks, name)
                for name in ('store', 'registry', 'methods', 'organizations'))):
        raise TaskConflict('Joint publication requires original same-action and same-journal stores')
    source = ActionContext.model_validate(source_context).model_copy(deep=True)
    context = ActionContext.model_validate(next_context).model_copy(deep=True)
    source_grants, grants = parameters._grants(source), parameters._grants(context)
    if (source.read_token == context.read_token or source_grants[0].organization_id != grants[0].organization_id
            or any(getattr(source, name) != getattr(context, name) for name in
                ('run_id','actor_id','function_ref','contract_ref','scope','business_time','execution_mode'))):
        raise TaskConflict('Joint publication requires original same-time identity and fresh authorized token')
    permitted = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
    original_input = original_cache = None
    retained, publications, targets = [], [], set()
    for store, digests in ((parameters,parameter_record_sha256s),(checks,check_record_sha256s)):
        if (not isinstance(digests,(list,tuple)) or not digests
                or any(not isinstance(value,str) for value in digests) or len(set(digests)) != len(digests)):
            raise TaskConflict('Joint publication requires nonempty unique original executions for both result kinds')
        objects = []
        for record_sha in sorted(digests):
            with store.store._lock:
                raw = store.store._db.execute(f'SELECT record FROM {store.RECORDS_TABLE} WHERE record_sha256=?',
                    (record_sha,)).fetchone()
            if raw is None:
                raise TaskConflict('Joint publication requires already persisted original executions')
            record = json.loads(raw[0])
            original, projection = store._validate(record)
            if original_input is None:
                original_input, original_cache = record['action_input'], record['prepared']['source_reading']
            if (record['record_sha256'] != record_sha or original != source
                    or record['organization_id'] != grants[0].organization_id
                    or record['action_input'] != original_input or record['prepared']['source_reading'] != original_cache
                    or projection.ref.key() in targets
                    or any(ref.key() not in permitted for ref in store._publication_refs(record,projection)
                        if ref != store.METHOD_REF)
                    or store.validate_source(deepcopy(record),context.model_copy(deep=True)) is not True):
                raise TaskConflict('Joint publication substitutes original input/cache/target or actual source authority')
            store._validate(record)
            retained.append((store,record_sha,raw))
            targets.add(projection.ref.key())
            objects.append(store._publication_content(projection)['object'])
        publication = {'schema_version':store.PUBLICATION_SCHEMA if len(digests)==1 else store.BATCH_PUBLICATION_SCHEMA,
            'context':context.model_dump(mode='json'),'organization_id':grants[0].organization_id}
        if len(digests)==1:
            publication.update(execution_sha256=digests[0],object=objects[0])
        else:
            publication.update(execution_sha256s=sorted(digests),objects=objects)
        publication['record_sha256'] = task_digest(publication)
        publications.append((store,publication))
    expected = {Reference.model_validate(ref).key() for ref in original_input['method_result_refs']}
    if targets != expected:
        raise TaskConflict('Joint publication must cover every original task result target exactly once')
    key = task_digest([context.run_id,grants[0].organization_id,context.read_token])
    with parameters.store._transaction():
        if parameters._grants(source) != source_grants or parameters._grants(context) != grants:
            raise TaskConflict('Joint publication authority changed during validation')
        for store,record_sha,raw in retained:
            if store.store._db.execute(f'SELECT record FROM {store.RECORDS_TABLE} WHERE record_sha256=?',
                    (record_sha,)).fetchone() != raw:
                raise TaskConflict('Original design execution changed before joint publication')
        for store,publication in publications:
            prior = store.store._db.execute(f'SELECT record FROM {store.PUBLICATIONS_TABLE} WHERE boundary_key=?',
                (key,)).fetchone()
            if prior is not None and json.loads(prior[0]) != publication:
                raise TaskConflict('Joint publication cannot replace an original read point')
            if prior is None:
                store.store._db.execute(f'INSERT INTO {store.PUBLICATIONS_TABLE} VALUES (?,?)',
                    (key,canonical(publication)))
    return {'kind':'published','context':context.model_dump(mode='json'),
        'publications':[deepcopy(publication) for _,publication in publications],
        'source_reading_sha256':task_digest(original_cache), 'input_sha256':task_digest(original_input)}
