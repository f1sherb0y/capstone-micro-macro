# SUPPLIER-A04 — Independent order acceptance and commitment proposal

Use the host-selected Supplier function, frozen authorized projections and
shared decision basics. A selected quote does not itself express the supplier's
acceptance. This action compares the exact final proposal with the quoted
product versions, quantities, batch-total prices, destinations, delivery windows,
included services, buyer, payer, prerequisites and payment terms.

Changes may be accepted only when the sourced supplier policy explicitly permits
each changed field and binds its review to the final agreement digest. Recheck
all commercial floors, products, terms, prerequisites and resources against the
final proposal. A changed payer needs the new payer's independent authority and
acceptance. Old acceptances of the original quote cannot carry into amended
terms. Changes outside that review policy require revision; explicit review
never waives unmet original prerequisites or creates a macro contract.

Commercial review checks the active offer, final agreement and sourced formation
policy. Every counterparty acceptance must identify this run, proposal, offer,
terms, scope and agreement digest. Verify its actual author, function and party
against the sourced authorization, bounded action and scope, at creation and now.
Check the acceptance's Evidence and the author's grant/function Evidence basis
at its actual `created_at`, with the same clock and no future creation time.
Resolve other authorization basis by its original reference type through the
authorized reading; keep those sources in the audit. Current acceptance and
grant validity remain separate checks, as do current supplier funds, stock and
capacity. Do not infer an unavailable receipt or authorship timestamp.
Distinct buyer/payer organizations must independently accept the same version;
one party cannot impersonate the other. A revised or rejected agreement requires
fresh confirmation, and unknown/missing confirmation remains missing information.

Production review reads actual usable stock minus commitments, never proposed
batches as stock. Sum batch usage across all lines once. Check product version,
source location and actual factory. Manufacturing demands apply to the quantity
not supplied from stock; transport demands apply to the complete accepted batch.
Logistics review checks all included responsibilities and final delivery windows.
Finance review checks current sourced actual cash minus committed cash against
the plan's explicit sourced working capital. Future receipts and unknown cash
cannot become available funding; no financial method or credit is invented.

Input assembly and saved-result reads share the same original source checks.
Retain the exact proposal, offer, formation profile, inventory, capacity, funding
and every supplied counterparty acceptance. Verify the proposal recipient and
scope against the original context, private snapshot ownership, and the profile's
exact offer/proposal references. A historical result cannot omit these original
inputs or replace them with another supplier's sources. Historical reads do not
reevaluate those snapshots as current funds, stock, capacity or authority.

Use `micro.capacity.fixed_location:1` through the host MethodRegistry to check
all simultaneous line demands together with existing shared pool commitments.
The supported domain is explicit sourced constant rates, fixed regions, exact
units, one clock and nonempty half-open windows. Keep its input, result, method
digest and authorization in the action audit. Do not duplicate physical capacity.

`accept` returns all exact proposed positive delivery lines and proposed resource
allocations only after full independent confirmation and current feasibility.
`accept_partial` returns a sourced plan with each quantity no greater than the
corresponding final line and at least one reduction or omission. Preserve product,
scope, requirements, deviations, destination, delivery window, service and terms
versions. Its explicit batch price must satisfy the final proposal's unit price and sourced
commercial floors; do not invent a proportional price. Partial plans require a
unique declared priority. This is a counterproposal awaiting new same-version
buyer/payer confirmation; uncovered quantities remain unaccepted.

`revise` identifies explicit sourced changed requirements. `reject` contains only
choice and reason; inactive/expired offers, known business refusal or infeasible
current funding, stock or shared capacity cannot leave a phantom order behind.
Unknown prerequisites/resources, stale or incomplete snapshots and ambiguous
plan priorities return `needs_information`. Unsupported algorithms, clocks or
conversions return `unsupported`; invalid projections and method technical errors
retain their own statuses. Recheck authority and reading after calculations.

All outputs are micro decisions and commitment drafts. No formal order, plan
batch, inventory, reservation, obligation or payment is created. The macro core
must apply its real formation rules, perform current conflict checks and return
receipts. CHECK-SUPPLIER-003/004/005/006/037 remain partial until formal submission,
formation, receipts, feedback and recovery are bound and verified.
