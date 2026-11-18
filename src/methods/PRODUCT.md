# Declared product constraints, version 1

This method compares sourced categorical properties with explicit allowed sets,
and numeric properties with explicit inclusive lower/upper bounds. Decimal
transport strings become exact rational numbers; ambient Decimal precision does
not affect the result. Every constraint requires a unique property code, matching
type and identical unit. The method performs no conversion and infers no facts.

The evidence is the actual value, declared constraint and per-property result.
All comparisons must match for the aggregate result to match. Scope, factory,
product version, intended use, evidence applicability and design dependencies
are checked by the calling action, before comparison. Method input provenance
and current authorization are checked at the shared method boundary.

This is a mathematical method for comparing supplied declarations. It does not
provide an engineering interface model, verify physical tests, establish
regulatory compliance, change a design or approve a substitution for production
or installation. Real compatibility methods and calibrated evidence remain
separate dependencies. The supported predicate is deliberately explicit; an
unavailable interface algorithm must return unsupported.
