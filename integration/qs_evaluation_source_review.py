"""Original QS bid branch sources and distinct native proposal/final capabilities."""
from copy import deepcopy
from pathlib import Path

from integration.contractor_construction_source_review import _source


_BRANCHES = {
    'evaluate': (
        'Actual submitted same-round bids and independently authorized procurement document, eligibility, '
        'coverage and comparable prices; original normalization/ranking calculations when requested. '
        'The native score requires its own bounded score evidence and is not inferred from a price.',
        'Private same-round evaluations and optional ranking; the original bid prices remain unchanged.',
        'Existing QSBidNativeBridge comparable rows return independently evidenced per-bid scores. '
        'Original native Owner selection commits the actual published result; existing later QS-A12 reads it.'),
    'clarify': (
        'Exact original missing bid/eligibility/coverage/pricing checks, current question references, '
        'authorized responsible recipients and original same-round bid/document versions.',
        'Scoped questions only; no received answer, admissible bid, score, exclusion or award.',
        'Connect actual question publication, recipient and independently received new-version bid clarification '
        'before a new evaluation invocation. Reuse existing communication components only after checking '
        'their question schema and publication authority; a QS-A05 tender-document answer is not automatically '
        'a QS-A06 received bid clarification.'),
    'no_valid_bid': (
        'The complete original submitted bid set and known original eligibility/exclusion rules, '
        'with every original failure source retained. Unknown evidence does not establish invalidity.',
        'Private finding that no bid passes the original checks; no Owner decision or formal exclusion.',
        'Explicit --exclude-all-bids declares independent failed qualifications and delegations for both '
        'original bids before sealing. Distinct actual reviews run the original no_valid_bid finding and '
        'per-bid authorized exclusions; the original Owner selection stays deferred and later QS-A12 '
        'consumes that actual earlier deferral and both exclusion results. Submitted bids are retained. '
        'The private finding alone never creates an empty native ranking or terminal buyer refusal.'),
    'exclude_authorized': (
        'Exact original failed bid and rule, received effective QSBidExclusionAuthorityView, actual buyer '
        'OWN-A09 authority and matching delegate actor/organization/function. Permission must be explicitly '
        'known true; original grant, availability, document and round versions must match.',
        'Original scoped authorized exclusion decision; saving the micro result alone does not remove a native bid.',
        'Existing opt-in --exclude-contractor-id sources feed QSBidAdmissibility and the native '
        'qs_bid_evaluation exclude_bid negative final, retaining the separately evidenced positive '
        'evaluate_bid proposal. The later QS-A12 consumes original exclusion identity/result plus '
        'proposal/final/event provenance. Reuse that path; private delivery to an excluded bidder, '
        'resource release, missing-delegation reception and additional combinations remain separate work. '
        'Do not return an exclude_bid proposal: the proposal contract only allows a positive score.'),
}


def qs_evaluation_reviews(root: Path, macro_backend: Path) -> dict:
    micro = _source(root, 'src/actions/roles/qs_bid.py', '_evaluate_bids')
    native = [
        _source(macro_backend, 'simulation/project_lifecycle_engine.py', 'ProjectLifecycleEngine._handle_bid_evaluation'),
        _source(macro_backend, 'agents/qs_agent.py', 'QSAgent.evaluate_bid'),
        _source(macro_backend, 'agents/operation_specs.py', 'get_operation_contract'),
    ]
    for row in native:
        row['path'] = (macro_backend/row['path']).relative_to(root).as_posix()
    components = [_source(root, path, symbol) for path,symbol in [
        ('integration/qs_bid_native.py','QSBidNativeBridge'),
        ('integration/qs_bid_native_development.py','build_bundle'),
        ('integration/qs_bid_actions.py','QSBidActionAssembler'),
        ('integration/qs_bid_results.py','QSBidResultWorker'),
        ('integration/qs_evaluation_learning.py','read_own_completed_evaluations'),
    ]]
    for path,symbol in [('integration/qs_bid_admissibility.py','QSBidAdmissibility'),
            ('integration/qs_bid_admissibility_development.py','prepare_admissibility_sources'),
            ('integration/qs_no_valid_outcome.py','read_no_valid_evaluation'),
            ('integration/qs_bid_all_excluded_development.py','prepare_all_excluded_rounds')]:
        if (root/path).is_file():components.append(_source(root,path,symbol))
    return {'QS-A06':{choice:{
        'status':'source_requirements_reviewed_runtime_not_promoted',
        'micro_source':deepcopy(micro),'reviewed_native_sources':deepcopy(native),
        'existing_source_components':deepcopy(components),
        'required_producer_outputs':required,'micro_result_semantics':semantics,'next_code_step':consumer,
        'native_source_boundary':(
            'The existing native lifecycle explicitly allows evaluate_bid/exclude_bid in its final '
            'qs_bid_evaluation request, skips rejected bids and lets the original Owner select from the '
            'accepted evaluations. Its evaluate_bid proposal contract separately only allows a positive '
            'evaluate_bid score. The native final exclusion capability exists; current missing per-bid '
            'micro wiring or delegation sources do not establish native capability absence.'),
        'existing_component_boundary':(
            'The default source generator retains one full-round comparison and evaluate-only candidate. '
            'Explicit --exclude-contractor-id additionally declares the separate original per-bid '
            'delegation/decision sources, preserving original comparison objects and all submitted prices. '
            'The native bridge handles comparable rows and this bounded authorized final exclusion; '
            'an explicitly fully delegated no-valid-bid round retains native selection deferral; '
            'it does not publish questions or infer invalidity from unknown evidence. Reuse original '
            'assemblers/workers and the original proposal/final transport; do not bypass its validators '
            'or rewrite sealed inputs to resolve a saved unknown or missing delegation.'),
        'acceptance_effect':'none',
    } for choice,(required,semantics,consumer) in _BRANCHES.items()}}
