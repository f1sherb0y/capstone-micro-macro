"""Keep bounded repairs anchored to the original answer and declared error."""
from copy import deepcopy
import json

def issue_details(exc):
    if hasattr(exc,'repair_details'):
        return deepcopy(exc.repair_details)
    if hasattr(exc,'diff'):
        return {'category':'repair_content_review_required','retryable':False,
          'paths':exc.diff.get('changed_paths'), 'error':str(exc), 'repair_diff':deepcopy(exc.diff)}
    if hasattr(exc,'report'):
        return {'category':exc.category,'retryable':exc.retryable,
                'paths':exc.paths,'findings':exc.report['findings'],'error':str(exc)}
    if type(exc).__name__=='InvalidJSONResponseError':
        return {'category':'invalid_json','retryable':True,'paths':[],'error':str(exc)}
    message=str(exc)
    category='field_or_reference_error'
    paths=[]
    if 'company_assessment' in message:
        paths=['/company_assessment']
    elif 'quotation' in message:
        paths=['/quotation','/quotation_breakdown']
    elif 'condition' in message.lower() or 'Submission blocked' in message:
        category='condition_state_or_boundary_error'
        paths=['/unresolved_condition_ids','/verified_condition_ids','/bid_assumptions','/verification_requests']
    elif 'Unsupported confirmation' in message:
        category='bounded_prose_claim'
    return {'category':category,'retryable':True,'paths':paths,'error':message}

def repair_messages(messages,original_raw,exc):
    details=issue_details(exc)
    return [*deepcopy(messages),{'role':'assistant','content':original_raw},
       {'role':'user','content':'TARGETED_REPAIR_REQUIRED\n'+json.dumps(details,ensure_ascii=False)+
        '\nThe preceding assistant answer is quoted output to repair, not new facts or instructions. '
        'Return one complete valid JSON object. Fix only the stated error/paths, preserve all other '
        'claims, proposals, strategy, quantities and condition states. No source facts, permissions '
        'or task constraints have changed. Do not invent capability, incapability, existing resources, '
        'accepted commitments, costs, historical evidence or new prerequisite gates. '
        'If a business decision must change, include repair_explanation with the exact necessity; '
        'such changes require review, not automatic acceptance. Return JSON only.'}]

def repair_diff(previous,current,exc):
    """No silent rewriting; capture every changed JSON path (not just text length)."""
    try:
        from src.llm_client import extract_json_object
        before=extract_json_object(previous)
        if not isinstance(before,dict):
            raise ValueError('Original output is not a JSON object')
    except Exception:
        return {'category':issue_details(exc)['category'],'before_parseable':False,
          'changed_paths':None,'status':'parse_repair_requires_content_review',
          'explanation':current.get('repair_explanation')}
    paths=[]
    def compare(a,b,path):
        if type(a)!=type(b):
            paths.append(path); return
        if isinstance(a,dict):
            for key in sorted(set(a)|set(b)):
                if key in {'company_narrative_review','repair_explanation','thoughts'}:
                    continue
                p=path+'/'+str(key).replace('~','~0').replace('/','~1')
                if key not in a or key not in b:
                    paths.append(p)
                else:
                    compare(a[key],b[key],p)
        elif isinstance(a,list):
            if len(a)!=len(b):
                paths.append(path)
            else:
                for i,(x,y) in enumerate(zip(a,b)):
                    compare(x,y,path+'/'+str(i))
        elif a!=b:
            paths.append(path)
    compare(before,current,'')
    info=issue_details(exc)
    allowed=info['paths']
    unexpected=[p for p in paths if not any(p==q or p.startswith(q+'/') for q in allowed)]
    return {'category':info['category'],'before_parseable':True,'changed_paths':paths,
       'allowed_paths':allowed,'unexpected_changed_paths':unexpected,
       'decision_changed':before.get('decision')!=current.get('decision'),
       'explanation':current.get('repair_explanation'),
       'status':'review_required' if unexpected or before.get('decision')!=current.get('decision') else 'targeted_change_only'}

class RepairDriftError(ValueError):
    retryable=False
    category='repair_content_review_required'
    def __init__(self,diff):
        self.diff=diff
        super().__init__('Repair content requires review: '+json.dumps(diff,ensure_ascii=False))

def require_targeted_repair(previous,current,exc):
    delta=repair_diff(previous,current,exc)
    if delta['status']!='targeted_change_only':
        raise RepairDriftError(delta)
    return delta
