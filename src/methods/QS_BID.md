# QS sourced bid comparison v1

Normalize an original bid price using a supplied positive evidenced FX coefficient, then add the exactly declared signed target-currency adjustments. The processor requires original source/target scope, region and price time to match their saved basis, and requires one distinct adjustment for every declared difference. No coefficient, scope allowance or adjustment is inferred. Same-currency FX must be one. Reject negative normalized amounts. Exact rational arithmetic preserves finite decimal prices.

Compare only known eligible and comparable bids. Each explicitly selected criterion is price or a sourced risk metric, with an explicit positive weight and positive scale in the same unit. Lower sum(weight × value / scale) is preferred. Preserve equal-score groups; do not invent a unique winner. Without selected criteria or a saved ranking result, return evaluations with no ranking reference.

These methods verify declared arithmetic, not market conversion validity or regulatory compliance. Original bid prices are immutable. Unknown eligibility is a clarification, technical errors are technical failures, and neither is an exclusion finding. An independent buyer grant and original failed rule are required for an exclusion decision. No result awards a contract or changes obligations/cash.
