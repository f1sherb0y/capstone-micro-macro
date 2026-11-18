"""Match actual quoted deviations to independently declared Contractor permissions."""
from copy import deepcopy

from src.coordination.tasks import TaskConflict, task_digest


def quoted_substitutions(*, disclosure, offer, draft, objects, quote, scope):
    get=lambda reference:next(r['value'] for r in objects if r['ref']==reference)
    selected={task_digest(s.supply_requirement_ref.model_dump(mode='json')):s for s in disclosure.substitutions}
    if len(selected)!=len(disclosure.substitutions):
        raise TaskConflict('Contractor substitution repeats an independent requirement permission')
    terms=[r['projection'] for r in quote['source_reading'] if r['ref']==draft['terms_ref']]
    if len(terms)!=1:
        raise TaskConflict('Contractor substitution lost the exact quoted terms source')
    used=set();bindings=[]
    for line,quoted in zip(offer['lines'],draft['lines']):
        actual=quoted['product'];deviations=actual['deviation_refs'];key=task_digest(line['requirement_ref'])
        if not deviations:
            continue
        permission=selected.get(key);requirement=get(line['requirement_ref'])
        if (permission is None or len({task_digest(r) for r in deviations})!=len(deviations)
                or [r.model_dump(mode='json') for r in permission.deviation_refs]!=deviations
                or requirement['substitution_authority_ref']!=permission.authority_ref.model_dump(mode='json')):
            raise TaskConflict('Contractor quote lacks its exact independently declared substitution permission')
        authority=get(permission.authority_ref.model_dump(mode='json'))
        # Original A05 reads substitution permission at the requirement level,
        # before choosing an offer. Keep that contract; the disclosure and the
        # exact quote checks bind this permission to the received offer below.
        if (authority['requirement_refs']!=[line['requirement_ref']] or authority['offer_ref'] is not None
                or authority['terms_ref'] is not None or authority['scope']!=scope):
            raise TaskConflict('Contractor substitution authority changes its exact requirement-level permission or scope')
        sources=[]
        for reference in deviations:
            rows=[r['projection'] for r in quote['source_reading'] if r['ref']==reference]
            if len(rows)!=1:
                raise TaskConflict('Contractor quote lost its exact original versioned deviation source')
            original=rows[0]
            if (original['product_ref']!=actual['product_ref'] or original['requirement_ref'] not in actual['requirement_refs']
                    or original['scope']!=scope or original['inquiry_ref']!=terms[0]['inquiry_ref']):
                raise TaskConflict('Quoted substitution changes its original product, requirement, inquiry or scope')
            sources.append({'ref':deepcopy(reference),'source_sha256':task_digest(original)})
        used.add(key)
        bindings.append({'supply_requirement_ref':deepcopy(line['requirement_ref']),
            'offer_ref':deepcopy(offer['ref']),'terms_ref':deepcopy(offer['terms_ref']),
            'authority_ref':permission.authority_ref.model_dump(mode='json'),
            'authority_sha256':task_digest(authority),'deviations':sources})
        # Deliberately do not turn a false/unknown permission into an adapter
        # acceptance or rejection. Original A05 reads the actual authority and
        # produces its own unresolved result when permission is unavailable.
    if set(selected)!=used:
        raise TaskConflict('Contractor substitution declares permission outside the actual quoted deviation set')
    return bindings
