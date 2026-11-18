# SUPPLIER-A03 — Quote and delivery plan

Use only the host-selected Supplier function, current authorization and frozen
reading. This action forms a quote for the exact inquiry and proposed products;
it cannot form an order, reserve stock/capacity, move goods or confirm payment.
Read the shared decision basics and the declared pricing/capacity methods.

Before quoting, check recipient, buyer, payer, scope, currency, active response
window and exact product proposal versions. A pending product proposal can be
quoted with the explicit requirement that the buyer confirm that exact version.
Never demand that a transaction already exist before making its quote. Rejected
or withdrawn proposals cannot be quoted. Alternatives require an explicit unique
policy priority; do not choose by incidental list order or invent prices.

Commercial review checks binding cost applicability, complete included service
responsibility, known currency/quantity units, payment milestone fractions and
offer validity. Production review checks actual usable stock minus commitments,
shared physical pools and manufacturing schedule assumptions. Logistics review
checks destination, batch windows, included services and current feasibility.
All member facts are authorized projections, not new business truth.

Map every inquiry requirement exactly once to the chosen proposal. Split it into
positive batches whose total equals the proposed quantity. Stock is actual
usable uncommitted inventory; future batches and plans do not count as stock.
Apply manufacture demands to the unstocked quantity and transport demands to
the whole delivered quantity. Sum simultaneous demands on each pool with its
existing commitments; one physical pool never becomes multiple capacities.
Rates are explicit sourced per-product constant-rate assumptions for the stated
schedule, not inferred production technology. This method supports fixed source
regions, one clock, identical units and nonempty half-open windows only.

Use `micro.supply.declared_cost_markup:1` for each batch: declared quantity ×
the costs per unit for every included service, plus batch-fixed costs, times
(1 + sourced markup); round upward by the explicit minor-unit policy. The price
field is the batch total covering precisely those services. No implicit tax, FX,
margin formula or quantity-unit conversion is allowed. Use
`micro.capacity.fixed_location:1` for complete overlapping demands. Save the
method input, result and content digest in the normal action audit.

`quote` returns the exact buyer/payer, delivery lines, positive binding batch
prices, same-version terms, validity, prerequisites, cost basis and proposed
allocations. It preserves product deviations and all explicit prerequisites.
`decline_quote` carries only choice and reason note: known commercial refusal,
unusable proposals, failed logistics, insufficient actual stock or shared
capacity may justify it. A failed model/method is never a business refusal.

Use `needs_information` for unknown cost, payer, currency, delivery responsibility,
incomplete scope, uncertain logistics or stale resources. Indicative costs must
be revalidated before becoming binding. Use `unsupported` for missing pricing
methods or unsupported clocks/units; technical failures keep their own status.
Recheck reading/authority after calculations. Formal submission, resource
reservation, order acceptance, receipts and feedback require real macro bindings
which are not supplied by this local action. CHECK-SUPPLIER-004/022/024/036/049
remain partial until the corresponding formal lifecycle evidence exists.
