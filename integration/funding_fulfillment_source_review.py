"""Reviewed detailed funding sources, distinct from aggregate financing/payment."""
from copy import deepcopy
from pathlib import Path

from integration.contractor_construction_source_review import _source


_ACTIONS = {
    'BANK-A06': ('bank_draw', 'decide_draw',
        'Original borrower-authored draw request, exact facility/terms, complete current usage and execution history, '
        'independent stage-specific conditions, purpose, transfer/fee lines and current original approval authority.', {
        'approve_draw': ('Active original facility and submitted request, supported draw window, satisfied original conditions and sufficient unused capacity.',
                         'Draw approval intention; no transfer or account/debt posting.',
                         'Original batch-approval issuer and independently recorded approval; existing draw handoff then BANK-A07.'),
        'decline_draw': ('Original request and independently sourced condition conclusions under the same facility and current authority.',
                         'Draw refusal with original condition results; no facility release.',
                         'Original borrower recipient and draw-decision reception; retain the same batch identity.'),
    }),
    'BANK-A07': ('bank_execution', 'handle_execution',
        'Original arrangement, exact approved transfer batch or existing command context, same-currency account/path '
        'and reservations, actual obligations/fees, independently received execution receipts and current authority.', {
        'execute': ('Actual recorded original approval with complete execution history, exact approved lines and sufficient current unrestricted account cash.',
                    'Original payment-command intention; no cash movement or principal creation.',
                    'Original payment issuer and command/transaction query; preserve unknown command identity, then original borrower receipt reader.'),
        'reconcile': ('Existing original commands and independently verified original receipts with exact arrangement, approval, beneficiaries and fee/principal effects.',
                      'Reconciliation of original execution identities.',
                      'Existing execution reception/reader and original command query; never issue a replacement transfer to resolve unknown outcome.'),
        'cancel_unexecuted': ('Exact original pending command history, supported cancellation state and original unexecuted scope.',
                             'Cancellation request, preserving already executed amounts.',
                             'Original command cancellation endpoint and actual cancellation query; no reversal or restored capacity is inferred.'),
    }),
    'BANK-A08': ('bank_monitoring', 'monitor_arrangement',
        'Actual original facility/covenant version, current authorized disclosure reports, original notice history '
        'and independently verified service evidence/contractual measure gates.', {
        'continue': ('Original monitoring profile and applicable arrangement/disclosures/covenants.',
                     'Continue monitoring; no amendment or waiver.', 'Authorized next monitoring consumer on the original facility.'),
        'request_evidence': ('Explicit original covenant requirements and authorized responsible borrower/verifier.',
                            'Evidence request.', 'Original responsible recipient and independent delivery/material reception before a later review.'),
        'issue_notice': ('Original contractual notice gate and verified current fact basis, with any required prior service/remedy deadline.',
                         'Notice intention.', 'Original notice issuer and independently verified service query; drafting is not service.'),
        'restrict_scope': ('Original contractual restriction gate, exact affected scope, verified facts and any required served notice/expired remedy window.',
                           'Scoped restriction request.', 'Original facility restriction issuer/query; no limit or capacity is changed by the result.'),
        'release_restriction': ('Existing actual active restriction on the same scope and independently verified original release gate.',
                                'Release request.', 'Original restriction-release issuer/query; retain original restrictions until observed release.'),
    }),
    'BANK-A09': ('bank_debt', 'account_debt',
        'Original facility terms, complete debt components and posting/execution history, exact currency/calendar '
        'and verified actual receipts with nonduplicated original transaction/principal effects.', {
        'calculate_due': ('Supported original rate/calendar calculation, exact accrual window and original debt/event timeline without an already posted accrual.',
                          'Debt calculation request.', 'Original accrual/posting issuer and actual ledger query; projected interest is not a posted debt or cash receipt.'),
        'allocate_receipt': ('Verified unallocated actual repayment receipts, exact existing components and original contractual allocation priority.',
                             'Receipt allocation intention within actual remaining receipt/component amounts.',
                             'Original allocation-posting issuer/query; preserve original receipt identities and actual principal effects.'),
        'reconcile': ('Existing original execution references and independently verified transaction/posting history.',
                      'Original history reconciliation.', 'Original transaction/debt query; no replacement payment or synthetic receipt.'),
        'correct_accrual': ('Existing original accrual posting, exact supported correction calculation/window and full prior posting chain.',
                            'Correction request retaining the original posting history.',
                            'Original correction-posting issuer/query; do not overwrite prior debt or convert a calculation into cash.'),
    }),
    'BANK-A10': ('bank_resolution', 'resolve_debt',
        'Original arrangement, actual unpaid obligations/notices, complete remedy/execution/security history and '
        'independent current resolution rights, authored proposals and original party evidence.', {
        'request_remedy': ('Concrete original requested items and an authorized future response window under the original remedy procedure.',
                           'Remedy request.', 'Original borrower/remedy recipient and actual response reception.'),
        'propose_restructure': ('Itemized original proposal, unchanged parties and supported revised terms with exact original affected debts/security.',
                               'Restructuring proposal.', 'Original counterparty proposal recipient and independently received acceptances.'),
        'accept_restructure': ('Exact original proposal and independently authenticated required party acceptances, with no unresolved conflicting execution.',
                              'Restructuring acceptance intention.', 'Original agreement/amendment issuer and actual effective terms query before later draw/debt consumers use it.'),
        'enforce': ('Actual original enforcement rights/security, verified trigger and notice procedure for the exact affected scope.',
                    'Enforcement request.', 'Original enforcement executor and actual outcome; no recovery cash or security release is inferred.'),
        'accounting_writeoff': ('Actual original debt and independently authorized original bank writeoff policy for the same scope.',
                               'Accounting-writeoff intention; legal debt/security remain distinct.',
                               'Original accounting posting/query; accounting treatment does not prove borrower repayment or release.'),
        'decline_remedy': ('Actually received original remedy proposal and the bank original applicable refusal profile/authority.',
                          'Refusal of that remedy.', 'Original proposal author and independently received response; retain unresolved debt and rights.'),
    }),
    'BANK-A11': ('bank_closeout', 'close_arrangement',
        'Complete current original facility/commitment/debt/security/issue and execution ledgers, authentic actual '
        'cash receipts and exact source-linked remaining obligations, with original closure authority.', {
        'retain': ('Original current ledgers and explicit remaining obligations, without release candidates or security-close instructions.',
                   'Retain the original facility and unresolved obligations.', 'Original continued monitoring/collection consumers; retain all source-linked obligations.'),
        'close_unused': ('Actual original unused commitments and eligible release candidates, with no unobserved overlapping closure execution.',
                         'Unused-commitment closure request; debt/security clearance remains separate.',
                         'Original commitment closure/release issuer and actual capacity query; expiry alone does not clear debt.'),
        'close_cleared_scope': ('Exact original cleared debt scope, actual verified cash history and independent security/issue clearance conditions.',
                                'Scoped closure request; not proof of a fully discharged loan.',
                                'Original facility/security closure issuer/query; preserve obligations outside the cleared scope.'),
    }),
    'OWN-A06': ('owner_payment', 'instruct_cash',
        'Original authorized decision/scope and only the sources required by the chosen branch: pay/repay need '
        'actual accounts/funding, draw needs facility terms, dispute/negotiate need scoped original obligations, '
        'and reconciliation needs original execution/receipt history. Preserve parties, currency, clock and unknown outcomes.', {
        'draw_request': ('Actual active original arrangement/draw terms, permitted purpose/conditions and independent borrower draw authority.',
                         'Draw request intention.', 'Original request publisher and bank reception, then original BANK-A06; aggregate financing selection is not a draw receipt.'),
        'pay': ('Actual due trade obligations and complete current actual account/reservation/execution history with exact authorized payment lines.',
                'Payment instruction intention.', 'Original payment-command issuer/query; existing Owner execution reader and actual creditor reception before any cash/settlement claim.'),
        'repay': ('Actual original principal/interest/fee debt, matching facility/terms and complete current actual account and pending execution history.',
                  'Repayment instruction intention.', 'Original repayment issuer and independently verified transaction/principal query before Bank debt allocation.'),
        'dispute': ('Actually sourced original obligation references and independent authorized dispute decision; actual native payment evidence can support a private position.',
                    'Private scoped dispute; no debt cancellation or cash execution.',
                    'Authorized counterparty/private-position consumer; retain unknown amounts and all outstanding obligations.'),
        'negotiate': ('Actually sourced original obligations and authorized negotiation decision; actual native payment/settlement evidence remains an observation.',
                      'Private scoped negotiation; no settlement agreement or payment.',
                      'Existing authorized final-account communication/response consumer, or original payment counterparty, with actual reception evidence.'),
        'reconcile': ('Exact original own execution references and independently received original receipts, including current pending/unknown commands.',
                      'Original execution reconciliation.', 'Existing Owner payment execution reader and original command query; unknown outcomes never authorize resubmission.'),
    }),
}

_SUBMISSIONS = {
    'BANK-A06': ('bank_draw_submission', 'BankDrawSubmission'),
    'BANK-A07': ('bank_execution_submission', 'BankExecutionSubmission'),
    'BANK-A08': ('bank_monitoring_submission', 'BankMonitoringSubmission'),
    'BANK-A09': ('bank_debt_submission', 'BankDebtSubmission'),
    'BANK-A10': ('bank_resolution_submission', 'BankResolutionSubmission'),
    'BANK-A11': ('bank_closeout_submission', 'BankCloseoutSubmission'),
    'OWN-A06': ('owner_payment_submission', 'OwnerPaymentSubmission'),
}


def funding_fulfillment_reviews(root: Path, macro_backend: Path) -> dict:
    """Describe these exact producer/consumer boundaries without changing support."""
    native = [_source(macro_backend, 'agents/bank_agent.py', 'BankAgent.' + name)
              for name in ('consider_financing', 'decide_monthly_operation')]
    native += [_source(macro_backend, 'simulation/simulation_engine.py', 'SimulationEngine._arrange_project_financing'),
               _source(macro_backend, 'simulation/project_state_update_engine.py', 'ProjectStateUpdateEngine._record_payment_event'),
               _source(macro_backend, 'simulation/project_lifecycle_engine.py', 'ProjectLifecycleEngine._handle_final_account')]
    for row in native:
        row['path'] = (macro_backend / row['path']).relative_to(root).as_posix()
    result = {}
    for action_id, (module, symbol, common, choices) in _ACTIONS.items():
        micro = _source(root, 'src/actions/roles/' + module + '.py', symbol)
        module, symbol = _SUBMISSIONS[action_id]
        submission = _source(root, 'integration/' + module + '.py', symbol)
        result[action_id] = {
            choice: {
                'status': 'source_requirements_reviewed_runtime_unverified',
                'micro_source': deepcopy(micro), 'reviewed_native_sources': deepcopy(native),
                'existing_submission_component': deepcopy(submission),
                'required_producer_outputs': common + ' Branch: ' + required,
                'micro_result_semantics': effect,
                'next_code_step': 'Reuse the existing original typed worker, submission and authenticated reader/handoff. Connect: ' + consumer,
                'native_source_boundary': (
                    'Reviewed project financing requests carry amount, borrower capacity, risk and financing environment '
                    'and record aggregate Bank offer/Owner selection. _record_payment_event calculates progress-based '
                    'payment_amount and approved/delayed status; it does not itself issue a bank transfer or post account '
                    'transactions. _handle_final_account records aggregate settlement/closure, not the detailed facility, '
                    'cash, debt/security and execution sources required above. Other equivalent original issuers/readers '
                    'remain to be located; no global macro capability absence is inferred.'),
                'existing_transport_boundary': (
                    'Existing action-specific submissions require original application transport, validators and '
                    'independent receipts. Private confirmations/calculations and these classes are not themselves '
                    'installed original cash/facility issuers. Private dispute/negotiate processing remains supported '
                    'by its own actual communication evidence; this review does not downgrade or promote it.'),
                'acceptance_effect': 'none',
            } for choice, (required, effect, consumer) in choices.items()}
    return result
