# Bank application intake

## Goal

Review the exact submitted finance application, borrower authority and product
conditions to decide whether it can enter this bank's review process.

## Preconditions

Read typed projections through the authorized action read view. Bare visible
references do not establish legal standing, authority or product eligibility.
Preserve the submitted borrower, lender, scope, amount, currency, purpose,
authority and disclosure versions. Do not modify a request during intake.

## Members

The intake member checks the submitted application and material versions. The
compliance member checks legal-standing evidence and applicant authority at
submission. The product member separately checks registration, operating and
project regions, purpose, stage, currency, exact amount and required materials.
The final choice follows applicable declared product priorities; list order
does not express the bank's preference.

## Decision

1. Verify that every repeated field agrees with the submitted application
   version and that it addresses this bank within the invocation scope.
2. Preserve draft/future submissions as information gaps. A withdrawn version
   cannot be accepted. Check current borrower/purpose evidence; unknown legal
   standing remains `needs_information`, known ineligibility can be `decline`.
3. Check borrower authority separately from this bank's invocation authority.
   Match applicant actor/function, originating finance action, borrower,
   scope and submission time. An expired authority can support a submission
   made during its validity; this never authorizes a new borrowing action.
   Resolve the exact applicant FunctionAssignment as a RoleAssignment and
   match its function identity and Owner/Contractor/Supplier role to the
   originating OWN-A05/CONTRACTOR-A10/SUPPLIER-A10 action. Check both grant and
   function Evidence basis at submitted_at; resolve other basis kinds through
   the authorized reading using their declared schemas. An authority document
   alone does not establish the actual originating role.
4. Compare only supplied product versions. Registration, all supplied operating
   regions and project region must separately satisfy the declared profile.
   Check purpose, stage and currency. An assessment case is eligible only if
   the product supports its actual stage; no formal project is invented.
5. Compare exact decimal request limits in the declared currency. Missing
   currency conversion or clock alignment returns `unsupported`. Missing
   evidence/categories returns `needs_information`, not a commercial refusal.
6. Read specific product conditions within the exact application scope. For
   multiple eligible products use the unique best declared intake priority;
   absent or tied priorities require a selection clarification. If no product
   is eligible and applicability is fully known, choose `decline`.

Disclosure supplementation retains the application ID and uses an explicitly
new submitted material version. Old read tokens and results cannot be reused
as evidence for changed material. No tools or model calls are required for
this deterministic intake path. Technical failures remain technical failures.

Actual Owner application reception reads every receipt.evidence_refs through
the current authorized read view and checks Evidence type and validity at the
real received_at. Native registration evidence uses that same reception point,
retaining observed basis, exact hash and formal/fixture provenance. Ordered
same-clock decision/submission/reception/availability checks run first; the
receipt remains required to be current, and the host independently validates
registration, complete disclosure mapping/history and lawful access. Historical
reception does not establish current borrower/product eligibility or approval.

Owner application reception also compares the actual applicant RoleAssignment
with its complete original Owner snapshot. Every grant/function basis source,
including non-Evidence kinds, must be currently readable with exact original
saved content; Evidence must be valid both at the original Owner decision and
actual submitted_at. The existing original grant, actor, role/function, scope,
source/audit hashes and independent actual receiver validation remain required.

## Output

Return the exact application reference, selected eligible product and applicable
condition references. Do not invent a finding ID, review task or receipt. An
`accept_for_review` payload forms a local decision; formal intake still needs
the supported macro registration entry. It creates no loan, quote, facility,
funds, debt or formal approval.
