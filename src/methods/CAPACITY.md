# Local Fixed-Location Capacity Method v1

The host method `micro.capacity.fixed_location:1` is a micro calculation
registration, not a saved macro Method object. It consumes known rates from
trusted role processors after their product, qualification, geography, policy,
version, evidence, completeness and authority checks. It is not exposed as an
external tool and does not confer a new action or reading permission.

## Input and Units

All demanded rates and resource capacities in a physical resource kind and
region use the same declared unit. A rate derived from a total quantity is
quantity / productivity / window duration. Quantity and productivity have
explicit units, and offsets use one exact ClockProfile version. An exact
numerator/denominator carries non-terminating rates without decimal rounding.
Resource and commitment IDs cannot be repeated across versions in one snapshot.
Missing source or evidence provenance remains needs_information. Invalid input
units, references or intervals remain invalid_input at the method boundary;
role adapters check unsupported domains before invoking this method.

## Mathematical Basis

For a resource i on a half-open interval, let capacity be c_i when the resource
is effective, otherwise zero. Let u_i be the sum of its active commitments.
Its available rate is max(0, c_i - u_i). Available rates may be added only within
the same physical kind, region and unit. Demanded rates are added within that
same group. The group is feasible exactly when demand does not exceed available
capacity on every segment with positive demand.

Every input rate and activation predicate is constant between consecutive
endpoints of demands, resources and commitments. Checking each such segment is
therefore sufficient for the entire requested window. Endpoint membership uses
start <= t < end, so adjacent half-open obligations do not overlap. Arithmetic
uses exact fractions of finite decimal strings, independent of Decimal context
precision. The output retains the needed and available rate for each segment.

Independent tests compare the implementation against a per-tick oracle on
generated integer-boundary examples and hand-worked rational examples. This is
mathematical validation only. The method does not establish that a supplied
factory, crew, productivity, operating region or commitment is real or complete.

## Failure and Effects

No registered exact version or action support yields unsupported, with no
fallback. Invalid schemas yield field issues without echoing private inputs.
Execution exceptions yield technical_error, never infeasible or business refusal.
Source and evidence reads use the action's run, token and current grants;
revocation or changed facts reject the call. Result digests bind run, actor,
action, operation, business time, method contents and input. Calls are recorded
in the local action audit, including false feasibility as a valid method result.

This method changes no project, order, stock, cash, resource reservation or
macro receipt. Actual commitment and conflict arbitration require an authorized
formal macro entry and receipt. Professional service, production, logistics,
cash, jurisdiction and other methods need separate registration and calibration.
