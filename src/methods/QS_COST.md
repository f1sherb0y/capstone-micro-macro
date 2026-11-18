# QS declared quantity cost method v1

For each declared line, multiply an original known nonnegative quantity by its applicable known nonnegative unit rate, using exact rational arithmetic and an exact finite decimal result. Units and currency must match; no conversion or inferred rate is supplied. A recorded proxy quantity must retain its upstream method and limitations; this method does not create or calibrate that proxy.

Coverage keys identify original physical cost coverage, including price inclusions. If any key belongs to multiple lines, neither overlapping line contributes an amount or subtotal until the original scope is split/corrected. This covers installation inclusions, parent/child totals and repeated regional views. Names and price component IDs cannot bypass coverage checks.

Sum only successfully computed disjoint lines. No computable line means unknown subtotal. A supported, evidenced zero quantity can produce zero. A complete total requires every declared required line to be computed. Missing quantity, price, incompatible currency/unit or unresolved overlap keeps the total empty. Endpoints, contingencies and confidence ranges are not invented.

This is a mathematical method, with synthetic boundary validation; quantities, prices, scope, applicability and authorization require their own original evidence. It does not establish real project cost, design safety, budget, obligations, incurred cost, cash or physical work.
