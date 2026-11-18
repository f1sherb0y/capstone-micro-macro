"""Exact fixed-location, constant-rate capacity on half-open intervals."""
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import ClockRef, EvidenceRef, Measured, Reference, StrictRecord, TextId, TimeWindow, ref_type
from src.methods.registry import MethodRegistry


CAPACITY_METHOD = ref_type("Method")(kind="Method", id="micro.capacity.fixed_location", version="1")


class ExactAmount(StrictRecord):
    numerator: Annotated[int, Field(ge=0)]
    denominator: Annotated[int, Field(gt=0)]

    @classmethod
    def from_fraction(cls, value):
        return cls(numerator=value.numerator, denominator=value.denominator)

    def fraction(self):
        return Fraction(self.numerator, self.denominator)


class CapacityDemand(StrictRecord):
    resource_kind: TextId
    region_id: TextId
    unit: TextId
    amount: ExactAmount
    window: TimeWindow
    basis_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class CapacityResource(StrictRecord):
    resource_ref: ref_type("Resource") | ref_type("ResourcePool")
    resource_kind: TextId
    region_id: TextId
    total: Measured
    effective_window: TimeWindow


class CapacityCommitment(StrictRecord):
    commitment_ref: ref_type("ResourceCommitment")
    resource_ref: ref_type("Resource") | ref_type("ResourcePool")
    quantity: Measured
    window: TimeWindow


class CapacityInput(StrictRecord):
    clock_ref: ClockRef
    demands: Annotated[list[CapacityDemand], Field(min_length=1)]
    resources: list[CapacityResource]
    commitments: list[CapacityCommitment]
    source_refs: list[Reference]

    @model_validator(mode="after")
    def supported_domain(self):
        for rows, field in ((self.resources, "resource_ref"), (self.commitments, "commitment_ref")):
            keys = [(getattr(row, field).kind, getattr(row, field).id) for row in rows]
            if len(set(keys)) != len(keys):
                raise ValueError("Resource or commitment identity repeated across versions")
        if len({ref.key() for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("Method source repeated")
        resources = {row.resource_ref.key(): row for row in self.resources}
        for row in self.resources:
            if Decimal(row.total.value) < 0:
                raise ValueError("Resource capacity must be nonnegative")
        for row in self.commitments:
            resource = resources.get(row.resource_ref.key())
            if resource is None or row.quantity.unit != resource.total.unit:
                raise ValueError("Commitment must name an exact supplied resource version with the same unit")
            if Decimal(row.quantity.value) <= 0:
                raise ValueError("Commitment must be positive")
        windows = [row.window for row in self.demands + self.commitments] + [row.effective_window for row in self.resources]
        if any(w.start.clock_ref != self.clock_ref or w.bounds != "closed_open"
               or w.start.offset >= w.end.offset for w in windows):
            raise ValueError("Capacity method requires one exact clock and nonempty half-open intervals")
        for demand in self.demands:
            if demand.amount.numerator <= 0:
                raise ValueError("Capacity demand must be positive")
            if any(row.resource_kind == demand.resource_kind and row.region_id == demand.region_id
                   and row.total.unit != demand.unit for row in self.resources):
                raise ValueError("Capacity method does not convert resource units")
        return self


class CapacitySegment(StrictRecord):
    resource_kind: TextId
    region_id: TextId
    unit: TextId
    window: TimeWindow
    needed: ExactAmount
    available: ExactAmount


class CapacityReport(StrictRecord):
    feasible: bool
    segments: Annotated[list[CapacitySegment], Field(min_length=1)]

    @model_validator(mode="after")
    def consistent_comparison(self):
        if self.feasible != all(row.needed.fraction() <= row.available.fraction() for row in self.segments):
            raise ValueError("Capacity conclusion differs from segment evidence")
        return self


def compare_capacity(data: CapacityInput) -> CapacityReport:
    segments = []
    groups = {(row.resource_kind, row.region_id, row.unit) for row in data.demands}
    for kind, region, unit in sorted(groups):
        demands = [row for row in data.demands if (row.resource_kind, row.region_id, row.unit) == (kind, region, unit)]
        pool = [row for row in data.resources if (row.resource_kind, row.region_id, row.total.unit) == (kind, region, unit)]
        commitments = [row for row in data.commitments if row.resource_ref.key() in {p.resource_ref.key() for p in pool}]
        windows = [row.window for row in demands + commitments] + [row.effective_window for row in pool]
        points = sorted({point for w in windows for point in (w.start.offset, w.end.offset)})
        for start, end in zip(points, points[1:]):
            needed = sum((row.amount.fraction() for row in demands if row.window.start.offset <= start < row.window.end.offset), Fraction())
            if not needed:
                continue
            available = Fraction()
            for resource in pool:
                total = Fraction(Decimal(resource.total.value)) if resource.effective_window.start.offset <= start < resource.effective_window.end.offset else Fraction()
                used = sum((Fraction(Decimal(row.quantity.value)) for row in commitments
                            if row.resource_ref == resource.resource_ref and row.window.start.offset <= start < row.window.end.offset), Fraction())
                available += max(Fraction(), total - used)
            w = demands[0].window.model_copy(update={
                "start": demands[0].window.start.model_copy(update={"offset": start}),
                "end": demands[0].window.end.model_copy(update={"offset": end})})
            segments.append(CapacitySegment(resource_kind=kind, region_id=region, unit=unit, window=w,
                needed=ExactAmount.from_fraction(needed), available=ExactAmount.from_fraction(available)))
    return CapacityReport(feasible=all(row.needed.fraction() <= row.available.fraction() for row in segments), segments=segments)


def local_method_registry():
    import hashlib
    root = Path(__file__).resolve().parents[2]
    basis = root / "src/methods/CAPACITY.md"
    registry = MethodRegistry()
    registry.register({"method_ref": CAPACITY_METHOD, "namespace": "micro_local", "effect_kind": "pure_calculation",
        "invocation": "trusted_processor", "input_schema_id": "micro-capacity.v1:input", "output_schema_id": "micro-capacity.v1:report",
        "action_ids": ["CONTRACTOR-A01", "OWN-A02", "OWN-A03", "OWN-A04", "SUPPLIER-A01", "SUPPLIER-A03", "SUPPLIER-A04", "ARCHITECT-A03", "ENGINEER-A03", "QS-A03", "ARCHITECT-A01", "ENGINEER-A01", "OWN-A10", "CONTRACTOR-A02", "CONTRACTOR-A03", "CONTRACTOR-A04", "ARCHITECT-A04", "ENGINEER-A04", "ENGINEER-A08", "GOV-A03", "GOV-A10", "GOV-A11", "CONTRACTOR-A05", "CONTRACTOR-A08", "SUPPLIER-A05", "OWN-A15", "ARCHITECT-A11", "ENGINEER-A11", "QS-A11", "GOV-A12", "CONTRACTOR-A12", "SUPPLIER-A12"], "unit_rule": "exact_declared_units_no_conversion",
        "support_domain": ["Fixed physical region", "Constant capacity rates", "Single declared clock", "Nonempty half-open intervals", "Fully known resource and commitment snapshot"],
        "basis_locator": "src/methods/CAPACITY.md", "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest(),
        "calibration": "mathematical_only", "limitations": ["No unit conversion or moving resources", "No formal reservation or business effect",
            "Productivity and physical capacity are supplied facts; their real validity is not established by this algorithm"]},
        CapacityInput, CapacityReport, compare_capacity)
    from src.methods.product import register_product_method
    register_product_method(registry)
    from src.methods.pricing import register_pricing_method
    register_pricing_method(registry)
    from src.methods.owner_proposal import register_owner_proposal_methods
    register_owner_proposal_methods(registry)
    from src.methods.owner_study import register_owner_study_method
    register_owner_study_method(registry)
    from src.methods.owner_investment import register_owner_investment_methods
    register_owner_investment_methods(registry)
    from src.methods.owner_commission import register_owner_commission_method
    register_owner_commission_method(registry)
    from src.methods.owner_financing import register_owner_financing_methods
    register_owner_financing_methods(registry)
    from src.methods.bank_credit import register_bank_credit_methods
    register_bank_credit_methods(registry)
    from src.methods.qs_cost import register_qs_cost_method
    register_qs_cost_method(registry)
    from src.methods.qs_change import register_qs_change_method
    register_qs_change_method(registry)
    from src.methods.qs_payment import register_qs_payment_method
    register_qs_payment_method(registry)
    from src.methods.government_rules import register_government_rule_method
    register_government_rule_method(registry)
    from src.methods.government_consultation import register_government_consultation_method
    register_government_consultation_method(registry)
    from src.methods.qs_bid import register_qs_bid_methods
    register_qs_bid_methods(registry)
    from src.methods.qs_research import register_qs_research_methods
    register_qs_research_methods(registry)
    from src.methods.architect_research import register_architect_research_method
    register_architect_research_method(registry)
    from src.methods.architect_change_impact import register_architect_change_impact_method
    register_architect_change_impact_method(registry)
    from src.methods.engineer_checks import register_engineer_interface_method
    register_engineer_interface_method(registry)
    from src.methods.engineer_research_estimates import register_engineer_research_estimate_method
    register_engineer_research_estimate_method(registry)
    from src.methods.architect_research_estimates import register_architect_research_estimate_method
    register_architect_research_estimate_method(registry)
    from src.methods.owner_tender import register_owner_tender_method
    register_owner_tender_method(registry)
    from src.methods.contractor_bid import register_contractor_bid_method
    register_contractor_bid_method(registry)
    from src.methods.contractor_advice import register_contractor_advice_method
    register_contractor_advice_method(registry)
    from src.methods.supplier_advice import register_supplier_advice_method
    register_supplier_advice_method(registry)
    from src.methods.bank_debt import register_bank_debt_method
    register_bank_debt_method(registry)
    from src.methods.architect_area import register_architect_area_method
    register_architect_area_method(registry)
    from src.methods.architect_interfaces import register_architect_interface_consistency_method
    register_architect_interface_consistency_method(registry)
    from src.methods.engineer_parameters import register_engineer_parameter_method
    register_engineer_parameter_method(registry)
    from src.methods.supplier_payment import register_supplier_payment_method
    register_supplier_payment_method(registry)
    from src.methods.owner_learning import register_owner_learning_method
    register_owner_learning_method(registry)
    from src.methods.bank_learning import register_bank_learning_method
    register_bank_learning_method(registry)
    from src.methods.architect_learning import register_architect_learning_methods
    register_architect_learning_methods(registry)
    from src.methods.qs_final_account import register_final_account_method
    register_final_account_method(registry)
    from src.methods.qs_learning import register_qs_learning_methods
    register_qs_learning_methods(registry)
    from src.methods.commercial_learning import register_commercial_learning_method
    register_commercial_learning_method(registry)
    return registry.snapshot()
