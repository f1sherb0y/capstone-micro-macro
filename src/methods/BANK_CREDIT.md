# BANK-A03: declared risk intervals and indicative cash constraints

These local calculators are mathematical methods, not calibrated credit models.
The bank source card is `zwtnew/04_roles/04_roles/bank.md`, BANK-A03 and its
BankFinding, BankCondition and BankIndicativeRange definitions. The public
RiskMethod and FinanceFeasibilityMethod retain their kinds; authorized received
projections explicitly bind them to these host Method versions.

Each risk dimension compares the whole supplied interval with its own supplied
threshold and unit. For `at_most`, upper <= threshold is acceptable and lower >
threshold is unacceptable; `at_least` reverses these comparisons. An interval
that straddles the threshold, or an unknown observation, stays unknown. No score,
average, weight or compensating dimension is computed. The processor owns hard
condition policy, missing evidence and remedial requirements.

Indicative affordability uses actual opening unrestricted cash per original
account, all disclosed remaining obligations, and explicitly hypothetical
ordinary forecasts. Inflows use the forecast lower bound and outflows the upper
bound. Neither a forecast nor an indicative loan adds actual cash. Accounts do
not pool money. Overdue obligations are charged at the review point; future
flows cannot erase a negative earlier checkpoint.

For every account and every supplied event time through the declared horizon:

`ordinary_free_cash(t) + principal * cumulative_loan_factor(t) >= 0`.

The hypothetical loan affects only its named account. Draw factors sum to one,
principal repayment factors sum to one and repayment never precedes cumulative
draw. Costs are separate nonnegative per-unit assumptions. The exact rational
intersection of every cash constraint, product limits and request gives the
unrounded interval. Its lower endpoint is rounded upward and its upper endpoint
downward to the explicitly declared monetary precision. If no positive monetary
unit remains, the interval is infeasible; no fake zero loan is reported.

For BANK-A03/A04, before invocation the processor intersects the product maximum with current
LendingCapacity less every original reserved/committed item in the bank's complete
visible FinancePortfolio. An explicitly released item requires source evidence;
an expired-looking record does not silently release capacity. Unknown occupancy
or incomplete coverage is missing information. This is an indicative bound, not
an atomic reservation or a substitute for the final formal capacity recheck.

BANK-A13 reuses the same interval comparisons and cash inequalities for one
explicitly disclosed advisory scenario at a time. Its opening amount and ordinary
flows are scenario assumptions, not assertions about actual account balances.
Unknown opening funds produce unknown monetary endpoints without invoking the
cash solver. The complete selected scenario excludes its hypothetical financing;
alternative options are never pooled or added into available funds. Advisory
limits do not establish formal product approval or reserve lending capacity.

All arithmetic uses Fraction constructed from decimal transport strings. No
global Decimal precision, guessed rates, discounting, currency conversion,
cross-account transfers, inferred debt completeness or empirical probability is
used. One exact clock and currency, at most 64 accounts, 512 ordinary flows and
256 hypothetical loan factors are supported. Different regions require explicit
product and account path checks by the processor. Floating/partial/revolving
draws or unknown debt schedules need other declared methods/data.

Source completeness, original identities, authority, evidence validity,
conditions and dependencies are checked by the authorized action processor.
Host calls retain strict method provenance and audit. A calculator call is not
professional work registration, resource use, approval, commitment, loan,
payment, reservation, receipt or formal feedback.

BANK-A04 uses the same registered pure methods under its own current action
authority. It rechecks disclosed risk/obligations and the explicitly supplied
current bank capacity, then replaces the hypothetical loan calendar with each
allowed PricingRule's actual proposed full draw, principal/interest factors and
FeeRule charges. Fixed fees become separate outflows; proportional fees remain
cost factors. Each quote is recalculated and independently capped by its sourced
quotation authority. Arrangement and per-draw conditions remain distinct source
Requirement stages. This permits mathematical repricing; it does not promote an
old indicative bound into approval or create liquidity, reservation or a receipt.
