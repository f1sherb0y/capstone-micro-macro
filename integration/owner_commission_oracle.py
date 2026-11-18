"""Independent source reconstruction for synthetic OWN-A04 verification.

No production processor or mathematical executor is called here. This validates
the evidence supplied to the local decision, not real-world source truth.
"""
from fractions import Fraction


def source_oracle(data, result, audit, projections):
    def key(ref): return ref['kind'],ref['id'],ref['version']
    source={key(row['ref']):row['value'] for row in projections}
    def get(ref): return source[key(ref)]
    def require(test,message):
        if not test: raise ValueError(message)
    def known(state):
        require(state['state']=='known','Success uses an unknown source fact')
        return state['value']
    def number(amount): return Fraction(amount['value'])
    def same_scope(a,b): return a['kind']==b['kind'] and a['ref']==b['ref']
    def covers(a,b):
        return same_scope(a,b) and (not a['coverage_refs'] or {key(ref) for ref in b['coverage_refs']} <= {key(ref) for ref in a['coverage_refs']})
    now=data['business_time']
    def current(window):
        require(window['start']['clock_ref']==now['clock_ref']==window['end']['clock_ref'],'Source clock mismatch')
        left=window['start']['offset'] <= now['offset'] if window['bounds'].startswith('closed') else window['start']['offset'] < now['offset']
        right=now['offset'] <= window['end']['offset'] if window['bounds'].endswith('closed') else now['offset'] < window['end']['offset']
        return left and right
    def received(time):
        require(time['clock_ref']==now['clock_ref'],'Received source clock mismatch')
        return time['offset']<=now['offset']
    def authority(ref,organization,actor,fn,action,scope):
        grant=get(ref)
        role=get(fn)['role']
        prefix={'Owner':'OWN','Government':'GOV'}.get(role,role.upper())
        return (grant['organization_id']==organization and grant['actor_id']==actor and grant['function_ref']==fn
            and action.startswith(prefix+'-A') and action in grant['action_ids'] and current(grant['validity'])
            and any(covers(value,scope) for value in grant['scopes'])
            and (role not in {'Architect','Engineer','QS'} or action==prefix+'-A02'))
    for row in data['objects']:
        require(get(row['ref'])==row['value'],'Projection differs from the frozen input source')
    profile=get(data['input']['procurement_profile_ref'])
    service=get(data['input']['service_scope_ref'])
    capacity=get(data['input']['capacity_ref'])
    owner=data['organization_id']
    work_refs={key(ref) for ref in service['scope_ref']['coverage_refs']}

    def capable(cap_ref,organization,fn,scope):
        cap=get(cap_ref)
        require(cap['organization_id']==organization and cap['function_ref']==fn,'Capability changes organization/function')
        role=get(fn)['role']
        if not current(cap['effective_window']) or role not in service['permitted_roles'] or role not in profile['permitted_roles']:
            return False
        works=[get(ref) for ref in scope['coverage_refs']]
        codes={value for work in works for value in work['service_codes']}
        uses={value for work in works for value in work['requested_uses']}
        responsibilities={value for work in works for value in work['responsibility_codes']}
        if (service['region_id'] not in known(cap['region_ids']) or not codes <= set(known(cap['service_codes']))
                or not uses <= set(known(cap['allowed_uses'])) or not responsibilities <= set(known(cap['responsibility_codes']))):
            return False
        require(cap['qualification_coverage']=='complete','Success uses incomplete qualification coverage')
        qualifications=set()
        for ref in cap['qualification_refs']:
            row=get(ref)
            require(row['organization_id']==organization and row['function_ref']==fn,'Qualification identity mismatch')
            require(received(row['verified_at']),'Qualification uses future information')
            if current(row['effective_window']) and service['region_id'] in row['region_ids'] and codes <= set(row['service_codes']):
                if known(row['standing']): qualifications.add(row['code'])
        if not set(service['required_qualification_codes']) <= qualifications:
            return False
        if not {key(ref) for ref in service['required_method_refs']} <= {key(ref) for ref in known(cap['method_refs'])}:
            return False
        for ref in service['required_method_refs']:
            row=get(ref)
            require(received(row['available_at']),'Professional method uses future information')
            if (not current(row['effective_window']) or service['region_id'] not in row['region_ids'] or role not in row['permitted_roles']
                    or not codes <= set(row['service_codes']) or not uses <= set(row['allowed_uses'])):
                return False
        return True

    def permitted_conditions(refs,terms_ref):
        for ref in {key(ref):ref for ref in refs}.values():
            row=get(ref)
            require(row['service_scope_ref']==service['ref'] and covers(row['scope_ref'],service['scope_ref']), 'Condition scope mismatch')
            require(row['terms_ref'] is None or row['terms_ref']==terms_ref,'Condition uses another terms version')
            require(current(row['effective_window']) and received(row['verified_at']),'Condition is stale/future')
            if not known(row['permitted']): return False
        return True

    def eligible_offers():
        eligible=[]
        for ref in data['input']['candidates']:
            offer=get(ref)
            require(offer['service_scope_ref']==service['ref'] and received(offer['received_at']),'Unreceived/mismatched offer')
            if offer['status']!='offered' or not current(offer['effective_window']): continue
            require(offer['provider_ref'] in data['input']['candidate_provider_refs'],'Offer uses unlisted provider')
            provider=get(offer['provider_ref'])
            if provider['status']!='active' or not current(provider['effective_window']): continue
            require(received(provider['available_at']),'Future provider source')
            require(provider['organization_id']!=owner,'Self appointment is not an external service')
            require(offer['author_actor_id']==provider['actor_id'] and offer['author_function_ref']==provider['function_ref'],'Offer author mismatch')
            if not authority(offer['authority_ref'],provider['organization_id'],provider['actor_id'],provider['function_ref'],offer['authority_action_id'],service['scope_ref']): continue
            terms=get(offer['terms_ref'])
            require(terms['service_scope_ref']==service['ref'] and terms['scope_ref']==service['scope_ref']
                and terms['employer_organization_id']==owner and terms['provider_organization_id']==provider['organization_id']
                and terms['window_ref']==service['window_ref'] and received(terms['issued_at']),'Terms identity/scope/window mismatch')
            if terms['status']!='offered' or not current(terms['effective_window']): continue
            for field in ('service_codes','requested_uses','responsibility_codes'):
                require(set(known(terms[field]))==set(service[field]),'Terms omit or import required service responsibilities')
            require({key(ref) for ref in terms['deliverable_refs']}=={key(ref) for ref in service['deliverable_refs']},'Terms change deliverables')
            if not set(known(terms['authority_limits'])) <= set(known(profile['permitted_authority_codes'])): continue
            require(get(terms['payer_function_ref'])['role']=='Owner' and terms['payer_authority_action_id']=='OWN-A04','Payer commercial authority is advisory')
            if not authority(terms['payer_authority_ref'],terms['payer_organization_id'],terms['payer_actor_id'],terms['payer_function_ref'],terms['payer_authority_action_id'],service['scope_ref']): continue
            if not permitted_conditions(profile['required_condition_refs']+terms['condition_refs'],terms['ref']): continue
            if not capable(provider['capability_ref'],provider['organization_id'],provider['function_ref'],service['scope_ref']): continue
            eligible.append({'offer_ref':offer['ref'],'terms_ref':terms['ref'],'priority':known(offer['priority']),'fee':known(terms['fee'])})
        return eligible

    choice=result.payload.choice if result.kind=='completed' else None
    report={'choice':choice,'capacity':[],'selection':None,'scope_checked':False}
    if choice in {'accept','internal'}:
        require(profile['organization_id']==owner==service['employer_organization_id']==capacity['organization_id'],'Success changes owner')
        require(profile['scope_ref']==service['scope_ref']==data['input']['scope_ref'],'Success changes commissioned scope')
        require(authority(data['input']['authority_ref'],owner,data['actor_id'],get(data['input']['authority_ref'])['function_ref'],'OWN-A04',service['scope_ref']), 'Owner commercial authority absent')
        require(current(profile['effective_window']) and current(service['effective_window']) and received(service['available_at'])
            and received(profile['available_at']),'Success uses stale/future base inputs')
        for field in ('service_codes','requested_uses','responsibility_codes','deliverable_refs'):
            values=[value for ref in service['scope_ref']['coverage_refs'] for value in get(ref)[field]]
            actual={key(value) if isinstance(value,dict) else value for value in values}
            expected={key(value) if isinstance(value,dict) else value for value in service[field]}
            require(actual==expected,'Source work omits/imports service requirements')
        report['scope_checked']=True

    calls=audit['method_calls']
    capacity_calls=[call for call in calls if call['method_ref']['id']=='micro.capacity.fixed_location']
    for call in capacity_calls:
        internal=get(profile['internal_plan_ref'])['allocations'] if known(profile['policy'])=='internal' else []
        allocations=[(row,'management') for row in profile['management_allocations']]+[(row,'internal_service') for row in internal]
        expected_resources,expected_loads,expected_demands={},[],[]
        expected_sources={key(profile['ref']),key(service['ref']),key(capacity['ref'])}
        if internal: expected_sources.add(key(profile['internal_plan_ref']))
        management_covered=set()
        for allocation,purpose in allocations:
            pool=get(allocation['resource_ref'])
            expected_sources.update((key(pool['ref']),key(allocation['window_ref'])))
            require(pool['ref'] in capacity['resource_refs'] and pool['organization_id']==owner,'Capacity uses foreign/unlisted resource')
            require(capacity['as_of']==now==pool['as_of'] and capacity['coverage']==pool['coverage']=='complete','Capacity is stale/incomplete')
            require(purpose in pool['purpose_codes'] and pool['region_id']==service['region_id'],'Capacity imports a resource of another purpose/region')
            target=allocation['task_target']
            assigned=target['scope_ref'] if target['kind']=='proposed' else get(target['task_ref'])['scope_ref']
            require(covers(service['scope_ref'],assigned),'Capacity allocation imports unrelated work')
            if target['kind']=='existing':
                expected_sources.add(key(target['task_ref']))
                task=get(target['task_ref'])
                require(task['organization_id']==owner and task['service_scope_ref']==service['ref'] and task['status']=='active'
                    and received(task['available_at']) and current(task['effective_window']),'Capacity uses an invalid existing task')
            require(authority(pool['authority_ref'],owner,data['actor_id'],get(data['input']['authority_ref'])['function_ref'],'OWN-A04',assigned),'Owner pool allocation authority absent')
            if purpose=='management': management_covered.update(key(ref) for ref in assigned['coverage_refs'])
            desired=get(allocation['window_ref'])
            require(desired==get(service['window_ref']) and desired['start']['offset']>=now['offset'],'Capacity changes declared future work window')
            expected_demands.append({'resource_kind':pool['ref']['id'],'region_id':pool['region_id'],
                'unit':known(pool['total'])['unit'],'amount':{'numerator':number(allocation['quantity']).numerator,
                    'denominator':number(allocation['quantity']).denominator},'window':desired,'basis_refs':[allocation['quantity']['basis_ref']]})
            if key(pool['ref']) not in expected_resources:
                expected_resources[key(pool['ref'])]={'resource_ref':pool['ref'],'resource_kind':pool['ref']['id'],
                    'region_id':pool['region_id'],'total':known(pool['total']),'effective_window':pool['effective_window']}
                expected_loads.extend({'commitment_ref':row['ref'],'resource_ref':pool['ref'],'quantity':row['quantity'],'window':row['window']} for row in pool['commitments'])
        actual=call['input']
        require(management_covered==work_refs,'Management plan omits part of the service')
        require(actual['demands']==expected_demands and actual['resources']==list(expected_resources.values())
            and actual['commitments']==expected_loads and actual['clock_ref']==now['clock_ref'], 'Capacity method input omits/changes source demand, pool or commitments')
        require({key(ref) for ref in actual['source_refs']}==expected_sources,'Capacity method omits/changes the source plan, window, task or pool references')
        if call['result']['kind']!='ok': continue
        segments=[]
        groups={(d['resource_kind'],d['region_id'],d['unit']) for d in expected_demands}
        for kind,region,unit in sorted(groups):
            demands=[d for d in expected_demands if (d['resource_kind'],d['region_id'],d['unit'])==(kind,region,unit)]
            pools=[p for p in expected_resources.values() if (p['resource_kind'],p['region_id'],p['total']['unit'])==(kind,region,unit)]
            loads=[row for row in expected_loads if key(row['resource_ref']) in {key(p['resource_ref']) for p in pools}]
            points=sorted({t for row in demands+loads+pools for t in (
                (row.get('window') or row['effective_window'])['start']['offset'],
                (row.get('window') or row['effective_window'])['end']['offset'])})
            for start,end in zip(points,points[1:]):
                demand=sum((Fraction(d['amount']['numerator'],d['amount']['denominator']) for d in demands
                    if d['window']['start']['offset']<=start<d['window']['end']['offset']),Fraction())
                if not demand: continue
                free=Fraction()
                for pool in pools:
                    total=number(pool['total']) if pool['effective_window']['start']['offset']<=start<pool['effective_window']['end']['offset'] else Fraction()
                    used=sum((number(row['quantity']) for row in loads if row['resource_ref']==pool['resource_ref']
                        and row['window']['start']['offset']<=start<row['window']['end']['offset']),Fraction())
                    free+=max(Fraction(),total-used)
                segments.append((kind,region,unit,start,end,demand,free))
        actual_segments=call['result']['value']['segments']
        require(len(actual_segments)==len(segments),'Capacity report omits source segments')
        for raw,expected in zip(actual_segments,segments):
            require((raw['resource_kind'],raw['region_id'],raw['unit'],raw['window']['start']['offset'],raw['window']['end']['offset'],
                Fraction(raw['needed']['numerator'],raw['needed']['denominator']),Fraction(raw['available']['numerator'],raw['available']['denominator']))==expected,
                'Capacity report contradicts independent physical segment calculation')
        feasible=all(row[-2]<=row[-1] for row in segments)
        require(call['result']['value']['feasible']==feasible,'Capacity feasibility contradicts independent source calculation')
        if choice in {'accept','internal'}: require(feasible,'Successful service conflicts with shared capacity')
        report['capacity'].append({'feasible':feasible,'segments':len(segments)})

    selection_calls=[call for call in calls if call['method_ref']['id']=='micro.owner.declared_service_selection']
    for call in selection_calls:
        rows=eligible_offers()
        cap=known(profile['fee_cap'])
        require(call['input']['candidates']==rows and call['input']['fee_cap']==cap,'Service method omitted or changed an eligible received offer or cap')
        eligible=[row for row in rows if number(row['fee'])<=number(cap)]
        excluded=[key(row['offer_ref']) for row in rows if number(row['fee'])>number(cap)]
        tied=[row['offer_ref'] for row in eligible if row['priority']==min(r['priority'] for r in eligible)] if eligible else []
        if call['result']['kind']!='ok': continue
        value=call['result']['value']
        require(value['selected_ref']==(tied[0] if len(tied)==1 else None), 'Service preference contradicts source priority/cap')
        require({key(ref) for ref in value['excluded_refs']}==set(excluded)
            and {key(ref) for ref in value['ambiguous_refs']}==({key(ref) for ref in tied} if len(tied)>1 else set()),'Service preference loses exclusion/tie evidence')
        report['selection']={'eligible_offers':len(rows),'within_cap':len(eligible),'tied_preferred':len(tied)}
        if choice=='accept':
            payload=result.payload.model_dump(mode='json')
            require(payload['offer_ref']==value['selected_ref'] and payload['terms_ref']==get(payload['offer_ref'])['terms_ref'], 'Acceptance changes the exact preferred offer/terms')
    if choice in {'accept','internal'}:
        require(len(capacity_calls)==1,'Success omits/repeats shared capacity method')
    if choice=='accept': require(len(selection_calls)==1,'Acceptance omits/repeats service comparison method')
    if choice=='internal':
        require(not selection_calls,'Internal work must not generate an external fee comparison')
        plan=get(profile['internal_plan_ref'])
        require(result.payload.model_dump(mode='json')['allocations']==plan['allocations'],'Internal output changes the exact authorized plan')
        require(permitted_conditions(profile['required_condition_refs'],None),'Internal work bypasses a necessary condition')
        covered=set()
        for allocation in plan['allocations']:
            pool=get(allocation['resource_ref'])
            target=allocation['task_target']
            assigned=target['scope_ref'] if target['kind']=='proposed' else get(target['task_ref'])['scope_ref']
            require(covers(service['scope_ref'],assigned),'Internal task imports unrelated work')
            require(capable(pool['capability_ref'],owner,pool['function_ref'],assigned),'Internal work lacks applicable qualification')
            require(authority(pool['service_authority_ref'],owner,pool['service_actor_id'],pool['function_ref'],pool['service_authority_action_id'],assigned),'Internal work lacks professional authority')
            covered.update(key(ref) for ref in assigned['coverage_refs'])
        require(covered==work_refs,'Internal work omits part of the service scope')
    return report
