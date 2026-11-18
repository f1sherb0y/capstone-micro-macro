# Declared limited-study budget checks, version 1

Choose at most one sourced candidate per invocation from an explicitly bounded
set of at most 64. Candidate scope, qualification, permission, history and
capacity are checked by the host action before this method is invoked.

All amounts use one declared currency and exact decimal transport parsed into
fractions. A positive proposed cap must not exceed the current spending limit.
Known future costs plus already incurred costs must fit that cap. Future costs
must also fit current actual cash less disjoint committed/restricted deductions.
For narrowing, the cap cannot exceed the exact existing plan's cap. Incurred
cost includes earned-but-unpaid service; unpaid balances are not deducted a
second time from that incurred amount or silently considered paid.

Feasible candidates use explicit ascending ordinal priority. A tie at the best
priority requests information; enumeration order never chooses a winner.
This method compares declared numbers, not realistic costs, values, forecasts
or calibrated preferences. It does not create a task, spend cash, settle a
debt, sign a commission, release resources or register a formal project.
