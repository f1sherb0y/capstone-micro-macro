# SUPPLIER-A02: product specification review

Review the exact received inquiry, its full set of requirements, visible product
candidates and the current sourced compatibility method. The commercial function
uses only explicit unique supplier priorities when several products are feasible.
The product function checks specification, factory, destination scope, intended
use and property evidence; supplier opinions may reflect its own interests.

Invoke `micro.product.declared_constraints:1` for exact categorical-set and
inclusive numeric-bound comparisons. This method has no inferred engineering
standards, unit conversions or performance-score approval. The sourced method
must explicitly cover the current factory, use and property codes. Missing
interface algorithms or unsupported domains return `unsupported`.

Propose an original product only with no departures from the requested product
code or properties. Every substitute departure needs a versioned, applicable
SpecificationDeviation record and ProductEvidence. Never silently substitute a
factory, purpose, product version or design basis. Missing evidence or property
values remain `needs_information`; known hard restrictions may produce `decline`.
Return `clarify` only for the inquiry's explicit registered questions. An empty
candidate or incomplete requirement set is missing information, not a refusal.

A catalog proposal can exist without design deliverables. Preserve each required
but unverified professional interface check as a sourced unresolved Issue. Use
a design check only for the exact product/requirement/factory/use combination,
within its permitted purpose, scope, time and named author's bounded authority.
Unknown checks stay unresolved; known failed checks prevent that product proposal.

Return the frozen SupplierA02Payload, with positive inquiry quantities, complete
requirement coverage, exact candidate versions, product evidence and explicit
deviations. Recheck current reading, authorization and candidate choice permissions.
Identity mismatch and read failures remain technical errors; no failure becomes
an automatic commercial refusal. Method inputs, results and digests enter audit.

This action only submits a local proposal. It grants no professional or procurement
approval, changes no design, permits no production or installation, and reserves
no stock or capacity. Synthetic tests establish local behavior and mathematical
comparison only; actual compatibility, formal submission, receipts and feedback
remain separate dependencies.
