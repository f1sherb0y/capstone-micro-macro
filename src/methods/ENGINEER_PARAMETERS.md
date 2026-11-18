# Finite engineering parameter domain validation v1

For an explicit numeric catalog, accept value x only when its declared unit matches, minimum <= x <= maximum, positive step, and (x-minimum)/step is an integer. Arithmetic uses exact rational decimal values. Invalid bounds/step are invalid input. Missing values or bounds remain unknown; no rounding or unit conversion occurs.

For a discrete catalog, membership compares the complete kind/id/version identity. The original parameter, catalog and source references must remain bound by the caller to the saved execution. This method checks a supplied finite domain only. It does not validate the engineering truth of that domain or establish capacity, structural safety, fire performance, permit, professional qualification, or physical compatibility. These require separate applicable methods and original evidence.
