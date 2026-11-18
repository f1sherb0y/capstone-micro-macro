# Contractor participation

Capacity comparison uses the declared host-local pure method
`micro.capacity.fixed_location:1`. The runtime records its registry digest,
input provenance and segment results in the action audit. No exact method
binding means unsupported, without a fallback or formal resource reservation.

## Goal

Screen the visible invitation and procurement package for this contractor.

## Preconditions

Read the exact package, capability, qualification, invitation, commitment and
screening-profile projections through the authorized action read view. Bare
visible references are insufficient. Use the organization's own records and
the supplied evidence versions; do not infer qualification from its role,
registration region, title or a capability score.

## Members

The commercial member checks the exact procurement package and invitation.
The technical member checks work types and declared method support. The
resource member checks existing commitments and same-location capacity. The
compliance member checks qualification coverage, region, work type and expiry.
The final intent follows the explicit screening policy after these checks.

## Decision

1. Bind the package version, decision scope, business clock and organization.
2. Check the participation window. A public package needs no invitation; an
   invitation-only package needs a current invitation for this actor, employer
   and exact package version.
3. Check work types, declared methods and applicable qualifications for the
   requested region and work window. Unknown qualification is an information
   gap. Known incompatible capability or complete qualification records with
   no applicable qualification can support `decline`.
4. Compare concurrent demands with unique-resource capacity minus existing
   commitments. The local comparison supports explicit common units, fixed
   locations, one clock and half-open windows. It uses exact decimal values.
   No relocation, conversion, reservation, production or engineering result is
   inferred. Unsupported units or time models remain `unsupported`.
5. Return `clarify` for supplied unresolved requirement references bound to the
   exact package. Missing underlying facts return `needs_information`.
6. Apply the declared funding-signal and new-work policy. Choose `participate`
   only when required checks pass and this policy permits participation.

Preserve the package reference in every completed branch and include the
authorized evidence used. Expired evidence or an outdated commitment snapshot
requires refreshed information. Transport or processor failures remain
technical errors, never a commercial refusal. No tools or model calls are
required by this deterministic screening implementation.

## Output

Return the action payload. A completed payload is a micro decision; it does not
create a contract, reserve resources, or claim a formal macro receipt.
