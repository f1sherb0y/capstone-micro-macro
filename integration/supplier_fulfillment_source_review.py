"""Concrete Supplier fulfilment source work; never a business acceptance record."""
from copy import deepcopy
from pathlib import Path

from integration.contractor_construction_source_review import _source


# Each branch retains its own producer requirement and authorized next consumer.
# Existing private processors and handoffs are reused, not reimplemented here.
_ACTIONS = {
    'SUPPLIER-A05': ('supplier_planning', 'plan_supply', {
        'plan_manufacture': ('Effective work mandate, exact output requirements, supported recipe, actual stock allocations and concurrent capacity.', 'Proposed manufacturing tasks.', 'Original plan/task formation and production-release issuer, then original A06.'),
        'plan_purchase': ('Effective mandate and original output demand, explicit upstream acquisition requirements and purchase tasks.', 'Proposed purchase tasks.', 'Original upstream inquiry/order formation and goods-receipt readers, then A06 reconcile_upstream.'),
        'split_plan': ('Complete original output demand partitioned exactly once across supported task modes, material inputs, resources and acyclic dependencies.', 'Partitioned task proposal.', 'Original plan/task formation; preserve each physical quantity and task dependency in the A06 handoff.'),
        'revise_plan': ('Original prior plan and its current commitments, exact replacement commitments, complete remaining demand and new feasible tasks.', 'Replacement-plan proposal; no commitment is released.', 'Original plan revision/reservation issuer; query actual replacement before handing new tasks to A06.'),
        'request_quote': ('Original authorized acquisition requirements, exact product lines and distinct independent upstream recipients.', 'Inquiry intention.', 'Authorized upstream recipients and independently received offers; no local offer fabricator.'),
        'accept_upstream_offer': ('Actually received current offer, exact selected lines, independent payer/procurement authority and complete commitment history.', 'Acceptance intention for those lines.', 'Original upstream order/commitment issuer and query; retain an already accepted or unknown original identity.'),
        'seek_delivery_change': ('Effective original order and affected lines, authorized proposed delivery window on the same clock.', 'Delivery-window change request.', 'Original counterparty change recipient and actual agreed order version before logistics uses the new window.'),
    }),
    'SUPPLIER-A06': ('supplier_execution', 'request_supply_execution', {
        'execute': ('Original manufacture/rework task, authentic production release and gate, supported recipe/rule, actual exclusive resource and stock allocations.', 'Production-input intention.', 'Original production executor and actual execution/stock-movement query; A07 consumes actual batches, not this intention.'),
        'rebalance': ('The same original released task and complete execution history, with exact replacement input allocations within current actual stock/capacity.', 'Revised production-input intention.', 'Original production/input-change executor and query; do not run again while any original command is unknown.'),
        'reconcile_upstream': ('Effective independent purchase order, original upstream deliveries, receipt authority and actual goods-receipt/inspection evidence.', 'Reconciled original delivery references.', 'Existing original delivery/receipt readers; no manufacture, receipt or stock posting is inferred.'),
        'reconcile_execution': ('Nonempty original execution references, original command contents, actual core-event/stock history and query status.', 'Reconciled original execution references.', 'Existing execution reader and original receipt query; unknown/not_queried keeps the original business unresolved.'),
        'request_maintenance': ('Actual own resource, unresolved original fault and authored actual observation evidence.', 'Maintenance request.', 'Authorized maintenance recipient and independently observed remedy; no resource repair or availability increase is inferred.'),
    }),
    'SUPPLIER-A07': ('supplier_quality', 'request_batch_quality', {
        'self_check': ('Actual original batch, complete requirements/visible defects, observed evidence and supported self-inspection executor/method.', 'Self-inspection request.', 'Original inspection executor and result reader; an A07 request is not a passed inspection.'),
        'request_external_check': ('Actual batch and requirements with supported independent executor where external verification is required.', 'Independent inspection request.', 'Original external inspection recipient and actual authored result before dispatch release.'),
        'isolate': ('Actual remaining physical batch, observed defect/test basis and independent owner/custody isolation right with exact quantity limits/history.', 'Isolation request.', 'Original batch-disposition executor and physical-stock query; custody permission does not authorize scrapping another owner stock.'),
        'rework': ('Original visible defects, actual physical slices, owner disposition right and feasible authored rework plan with supported inputs/dependencies.', 'Rework-task proposal.', 'Original task formation/release and production execution; later authentic recheck is required before usable release.'),
        'scrap': ('Actual unprocessed batch quantity, complete original disposition history and independently authorized scrap right.', 'Scrap request.', 'Original disposition/stock-movement executor and query; preserve physical lineage without restoring inputs.'),
        'propose_deviation': ('Original batch, concrete affected requirements and authored supported deviation proposal.', 'Deviation proposal.', 'Authorized requirement/design decision recipient and actual approval; do not turn the proposal into usable stock or design acceptance.'),
    }),
    'SUPPLIER-A08': ('supplier_logistics', 'arrange_transport', {
        'dispatch': ('Effective original order, actual dispatchable batch/ledger and independent release, physical slices, route/receiving windows and exclusive transport allocations.', 'Shipment-plan request.', 'Original dispatch executor and actual shipment query; original A09 also requires independent arrival/customer receipt.'),
        'split': ('The same dispatch sources with multiple concrete plans whose physical slices do not overlap or exceed original order/batch quantities.', 'Split shipment-plan request.', 'Original dispatch executor with separate correlated plans; query actual shipments without duplicating physical stock.'),
        'reroute': ('Existing dispatched/in-transit shipment, actual current position, supported replacement route and feasible current allocations/receiving window.', 'Route-change request.', 'Original shipment/route-change issuer and query; preserve original shipment and position identities.'),
        'reschedule': ('Effective original order lines or existing shipments, explicit target kind and authorized proposed future window.', 'Rescheduling request.', 'Original counterparty/schedule-change recipient and actual accepted window; no schedule is changed by the draft.'),
        'reconcile': ('Nonempty original shipment history, original dispatch commands/events and actual query statuses.', 'Original shipment reconciliation.', 'Existing transport reader and original shipment query; unknown shipments are queried instead of dispatched again.'),
    }),
    'SUPPLIER-A09': ('supplier_receiving', 'respond_to_receiving', {
        'acknowledge_receipt': ('Actual original shipment/arrivals, independent recorded customer receipt and exact selected fact components with nonduplicated physical quantities.', 'Acknowledgment of received facts.', 'Authorized customer receipt consumer; acknowledgment does not create stock, inspection acceptance or use release.'),
        'supplement_evidence': ('Original shipment/problem, authored problem-linked supplement and actually received attachment references.', 'Supplement transmission intention.', 'Original problem recipient and independent supplement-reception query; no local attachment is a reception receipt.'),
        'propose_replacement': ('Current unresolved receipt discrepancy, complete original replacement history and concrete requirement/deviation-bound replacement lines within remaining quantity.', 'Replacement proposal.', 'Authorized customer remedy recipient and original replacement/order decision, then separate physical supply execution.'),
        'contest_discrepancy': ('Original unresolved component-specific discrepancy and authored contest supplement with matching attachments/receipt components.', 'Contestation of specific facts.', 'Original discrepancy recipient and actual response; disagreement does not resolve the original issue.'),
    }),
    'SUPPLIER-A10': ('supplier_payment', '_manage_supplier_cash', {
        'request_payment': ('Effective original order/payment nodes, actual delivery/inspection evidence, saved supported node-amount calculation and complete prior claim history.', 'Payment claim.', 'Original claim recipient and independent registration/query; no payable debt or cash receipt is created by the claim.'),
        'authorize_payment': ('Complete current actual own account/funding and obligation/execution ledgers, due payable debts and independently authorized exact allocations.', 'Payment authorization intention.', 'Original bank/cash execution issuer and transaction query; preserve existing and pending original commands.'),
        'reconcile': ('Original execution references and actual independent payment receipts under current own read authority.', 'Original cash-history reconciliation.', 'Existing payment recovery reader and original transaction query; unknown outcomes stay unknown.'),
        'dispute': ('Existing original obligations and specific supported dispute basis, with complete current payment/claim history.', 'Scoped obligation dispute.', 'Authorized counterparty/dispute recipient and actual response; obligations and cash remain unchanged.'),
        'seek_finance': ('Original authored financing-application draft and independently authorized financial sources.', 'Financing application intention.', 'Original application publication/reception and bank intake; an aggregate project financing offer is not this application receipt.'),
    }),
    'SUPPLIER-A11': ('supplier_remedy', 'propose_supply_remedy', {
        'propose_change': ('Effective original order, actual problem and affected lines, complete remedy history and independent contract remedy procedure.', 'Supply change proposal.', 'Original contract-change recipient and actual agreement/version before new performance uses it.'),
        'repair': ('Original observed defects/physical slices, owner/site disposition rights, authored feasible repair tasks and actual supported resource/material intentions.', 'Repair-task proposal.', 'Original task/release and physical-remedy executors, then authentic recheck; no repair or defect closure is inferred.'),
        'replace': ('Original defective physical scope and independent disposition rights, separate new supply inputs and distinct removal/return/new-supply/install steps where installed.', 'Replacement-task proposal.', 'Original remedy/task/order executors and actual physical receipts; replacement cannot reuse removed stock as new supply.'),
        'propose_refund': ('Actual original received transactions, complete unrefunded history, authorized remedy procedure and supported amount assessment where required.', 'Refund proposal within actual unrefunded amount.', 'Original refund agreement and cash execution/query; proposal neither refunds cash nor clears an obligation.'),
        'claim': ('Original contract/problem and affected order lines, authorized claim procedure and supported amount/basis.', 'Claim proposal.', 'Original claim recipient and independently registered response; no liability/debt or cash is posted.'),
        'decline_request': ('Actually received original remedy request, specific authored refusal basis and applicable original remedy procedure.', 'Refusal response.', 'Original requesting party and response reception; no defect or outstanding obligation is cleared.'),
    }),
}

_REUSE = {
    'SUPPLIER-A05': [('integration/supplier_order_planning_fixture_sources.py', '_OrderPlanningReception')],
    'SUPPLIER-A06': [('integration/supplier_planning_handoff.py', 'prepare_supplier_planning_handoff'),
                     ('integration/supplier_execution_reader.py', 'SupplierExecutionReader')],
    'SUPPLIER-A07': [('integration/supplier_quality_reader.py', 'SupplierQualityReader')],
    'SUPPLIER-A08': [('integration/supplier_quality_logistics_fixture_sources.py', '_QualityDispatchReception'),
                     ('integration/supplier_transport_reader.py', 'SupplierTransportReader')],
    'SUPPLIER-A09': [('integration/supplier_logistics_handoff.py', 'prepare_supplier_logistics_handoff'),
                     ('integration/supplier_receiving_reader.py', 'SupplierReceivingReader')],
    'SUPPLIER-A10': [('integration/supplier_payment_recovery_reader.py', 'SupplierPaymentRecoveryReader')],
    'SUPPLIER-A11': [('integration/supplier_remedy_recovery_reader.py', 'SupplierRemedyRecoveryReader')],
}


def supplier_fulfillment_reviews(root: Path, macro_backend: Path) -> dict:
    """Review these exact call sites only; other equivalent native producers remain open."""
    native = [
        _source(macro_backend, 'agents/supplier_agent.py', 'SupplierAgent.' + symbol)
        for symbol in ('consider_supply_order', 'decide_monthly_operation')]
    native += [_source(macro_backend, 'simulation/project_lifecycle_engine.py',
                       'ProjectLifecycleEngine._select_supplier_after_contract')]
    native += [_source(macro_backend, 'simulation/project_state_update_engine.py',
                       'ProjectStateUpdateEngine.' + symbol)
               for symbol in ('update_supply_state', 'record_construction_process_events')]
    for row in native:
        row['path'] = (macro_backend / row['path']).relative_to(root).as_posix()
    transport = _source(root, 'integration/supplier_submission.py', 'SupplierResultSubmission')
    result = {}
    for action_id, (module, symbol, choices) in _ACTIONS.items():
        source = _source(root, 'src/actions/roles/' + module + '.py', symbol)
        reuse = [_source(root, path, name) for path, name in _REUSE[action_id]]
        result[action_id] = {
            choice: {
                'status': 'source_requirements_reviewed_runtime_unverified',
                'micro_source': deepcopy(source), 'reviewed_native_sources': deepcopy(native),
                'existing_submission_component': deepcopy(transport),
                'existing_source_components': deepcopy(reuse),
                'required_producer_outputs': required, 'micro_result_semantics': semantics,
                'next_code_step': 'Reuse the existing typed worker/reader/handoff. Connect: ' + consumer,
                'native_source_boundary': (
                    'Reviewed supplier selection records accepted offers, selected enterprise and aggregate '
                    'engagement. update_supply_state calculates aggregate availability, reliability and quality; '
                    'record_construction_process_events records aggregate progress/supply_delay and invokes '
                    'existing payment/inspection event helpers. Supplier monthly operation describes an enterprise '
                    'choice. These reviewed methods do not themselves produce the detailed order, production '
                    'release, physical batch, inspection, shipment, customer receipt or transaction required here. '
                    'Other original equivalent issuers/readers remain to be located; no global absence is inferred.'),
                'existing_transport_boundary': (
                    'SupplierResultSubmission requires independently supplied submit/query and current validators. '
                    'Its existence is not an installed original native endpoint or a detailed execution receipt. '
                    'Referenced readers/handoffs validate externally supplied original formation, release and receipt '
                    'records. Fixture source factories retain their declared synthetic provenance; none is '
                    'promoted here into an original macro issuer or a currently installed consumer.'),
                'acceptance_effect': 'none',
            } for choice, (required, semantics, consumer) in choices.items()}
    return result
