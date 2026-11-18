from copy import deepcopy
from decimal import getcontext
import random

import pytest

from src.actions.contracts.common import EvidenceRef
from src.actions.contracts.references import ActionReadView
from src.methods.capacity import (
    CAPACITY_METHOD,
    CapacityInput,
    ExactAmount,
    compare_capacity,
    local_method_registry,
)
from src.methods.registry import MethodRegistry
from src.organization.registry import AccessDenied


def ref(kind, identity, version="1"):
    return {"kind": kind, "id": identity, "version": version}


def window(start, end, clock="clock-1"):
    return {"start": {"clock_ref": ref("ClockProfile", clock), "offset": start},
            "end": {"clock_ref": ref("ClockProfile", clock), "offset": end},
            "bounds": "closed_open"}


def measured(value, unit="line"):
    return {"value": value, "unit": unit, "basis_ref": ref("Evidence", "basis")}


def demand(amount="1", unit="line", start=0, end=10):
    return {"resource_kind": "production_line", "region_id": "HK", "unit": unit,
            "amount": ExactAmount(numerator=int(amount), denominator=1),
            "window": window(start, end), "basis_refs": [EvidenceRef.model_validate(ref("Evidence", "basis"))]}


def resource(total="1", unit="line", identity="line-1", version="1"):
    return {"resource_ref": ref("Resource", identity, version), "resource_kind": "production_line",
            "region_id": "HK", "total": measured(total, unit), "effective_window": window(0, 10)}


def base_input(**updates):
    value = {"clock_ref": ref("ClockProfile", "clock-1"), "demands": [demand()],
             "resources": [resource()], "commitments": [], "source_refs": [ref("Resource", "line-1")]}
    value.update(updates)
    return CapacityInput.model_validate(value)


def test_fraction_comparison_is_independent_of_decimal_context():
    original = getcontext().prec
    try:
        getcontext().prec = 2
        exact_demand = demand() | {"amount": ExactAmount(numerator=100000000000000000000000000000001,
                                                       denominator=100000000000000000000000000000000)}
        low_precision = compare_capacity(base_input(demands=[exact_demand]))
        getcontext().prec = 80
        high_precision = compare_capacity(base_input(demands=[exact_demand]))
    finally:
        getcontext().prec = original
    assert low_precision == high_precision
    assert low_precision.feasible is False


def test_adjacent_half_open_commitments_do_not_overlap():
    value = base_input(demands=[demand(amount="1") | {"amount": ExactAmount(numerator=1, denominator=2)}], commitments=[
        {"commitment_ref": ref("ResourceCommitment", "first"), "resource_ref": ref("Resource", "line-1"),
         "quantity": measured("0.5"), "window": window(0, 5)},
        {"commitment_ref": ref("ResourceCommitment", "second"), "resource_ref": ref("Resource", "line-1"),
         "quantity": measured("0.5"), "window": window(5, 10)},
    ])
    report = compare_capacity(value)
    assert report.feasible is True
    assert [(segment.window.start.offset, segment.window.end.offset, segment.available)
            for segment in report.segments] == [(0, 5, ExactAmount(numerator=1, denominator=2)),
                                                 (5, 10, ExactAmount(numerator=1, denominator=2))]


def test_duplicate_resource_identity_across_versions_is_rejected():
    with pytest.raises(ValueError, match="identity repeated"):
        base_input(resources=[resource(), resource(identity="line-1", version="2")])


def test_unit_mismatch_is_rejected_without_conversion():
    with pytest.raises(ValueError, match="does not convert"):
        base_input(resources=[resource(unit="kg")])


def test_shortage_is_reported_by_segment_evidence():
    report = compare_capacity(base_input(resources=[resource("0.5")]))
    assert report.feasible is False
    assert report.segments[0].needed == ExactAmount(numerator=1, denominator=1)
    assert report.segments[0].available == ExactAmount(numerator=1, denominator=2)


def test_registry_contains_only_explicit_local_bindings():
    from src.methods.product import PRODUCT_METHOD
    from src.methods.pricing import PRICING_METHOD
    from src.methods.owner_proposal import SCALE_METHOD, PROPOSAL_METHOD
    from src.methods.owner_study import STUDY_METHOD
    from src.methods.owner_investment import COMPARISON_METHOD, CASH_METHOD
    from src.methods.owner_commission import COMMISSION_METHOD
    from src.methods.owner_financing import FINANCING_METHOD, FINANCING_CASH_METHOD
    from src.methods.bank_credit import CREDIT_RISK_METHOD, CREDIT_CASH_METHOD
    registry = local_method_registry()
    catalog = registry.catalog()
    by_id = {row["definition"]["method_ref"]["id"]: row for row in catalog}
    assert set(by_id) == {CAPACITY_METHOD.id, PRODUCT_METHOD.id, PRICING_METHOD.id, SCALE_METHOD.id, PROPOSAL_METHOD.id, STUDY_METHOD.id, COMPARISON_METHOD.id, CASH_METHOD.id, COMMISSION_METHOD.id, FINANCING_METHOD.id, FINANCING_CASH_METHOD.id, CREDIT_RISK_METHOD.id, CREDIT_CASH_METHOD.id, 'micro.qs.declared_quantity_cost', 'micro.qs.sourced_change_valuation', 'micro.qs.sourced_payment_valuation', 'micro.government.declared_rule_check', 'micro.government.consultation_coverage', 'micro.qs.sourced_bid_normalization', 'micro.qs.declared_bid_comparison', 'micro.qs.sourced_plan_normalization', 'micro.qs.declared_plan_comparison', 'micro.architect.declared_option_comparison', 'micro.engineer.declared_interface_code', 'micro.owner.declared_tender_comparison', 'micro.contractor.declared_bid_price', 'micro.contractor.declared_duration_bounds', 'micro.supplier.declared_advice_estimates', 'micro.bank.sourced_debt_accrual', 'micro.architect.area_schedule_sum', 'micro.engineer.finite_parameter_domain', 'micro.supply.contract_claim_amount', 'micro.owner.declared_evidence_update', 'micro.bank.verified_prediction_error', 'micro.architect.declared_feedback_rules', 'micro.architect.declared_training_estimate', 'micro.qs.original_final_account', 'micro.qs.original_forecast_comparability', 'micro.qs.comparable_forecast_error', 'micro.commercial.verified_lesson_summary', 'micro.architect.declared_change_impact', 'micro.architect.original_interface_reference_consistency', 'micro.engineer.declared_research_estimate', 'micro.architect.declared_research_estimate'}
    assert all(row["definition"]["method_ref"]["version"] == "1" for row in catalog)
    catalog = [by_id[ref.id] for ref in (CAPACITY_METHOD, PRODUCT_METHOD, PRICING_METHOD)]
    for ref in (SCALE_METHOD, PROPOSAL_METHOD):
        assert by_id[ref.id]["definition"]["action_ids"] == ["OWN-A16"]
        assert by_id[ref.id]["definition"]["calibration"] == "mathematical_only"
    assert catalog[0]["definition"]["calibration"] == "mathematical_only"
    assert catalog[0]["definition"]["action_ids"] == ["CONTRACTOR-A01", "OWN-A02", "OWN-A03", "OWN-A04", "SUPPLIER-A01", "SUPPLIER-A03", "SUPPLIER-A04", "ARCHITECT-A03", "ENGINEER-A03", "QS-A03", "ARCHITECT-A01", "ENGINEER-A01", "OWN-A10", "CONTRACTOR-A02", "CONTRACTOR-A03", "CONTRACTOR-A04", "ARCHITECT-A04", "ENGINEER-A04", "ENGINEER-A08", "GOV-A03", "GOV-A10", "GOV-A11", "CONTRACTOR-A05", "CONTRACTOR-A08", "SUPPLIER-A05", "OWN-A15", "ARCHITECT-A11", "ENGINEER-A11", "QS-A11", "GOV-A12", "CONTRACTOR-A12", "SUPPLIER-A12"]
    assert catalog[1]["definition"]["action_ids"] == ["SUPPLIER-A02"]
    assert catalog[1]["definition"]["calibration"] == "mathematical_only"
    assert catalog[2]["definition"]["action_ids"] == ["SUPPLIER-A03"]
    assert catalog[2]["definition"]["calibration"] == "mathematical_only"
    assert by_id[STUDY_METHOD.id]["definition"]["action_ids"] == ["OWN-A02"]
    assert by_id[STUDY_METHOD.id]["definition"]["calibration"] == "mathematical_only"
    assert by_id[COMMISSION_METHOD.id]["definition"]["action_ids"] == ["OWN-A04"]
    assert by_id[COMMISSION_METHOD.id]["definition"]["calibration"] == "mathematical_only"
    for ref in (FINANCING_METHOD, FINANCING_CASH_METHOD):
        assert by_id[ref.id]['definition']['action_ids'] == ['OWN-A05']
        assert by_id[ref.id]['definition']['calibration'] == 'mathematical_only'
    for ref in (CREDIT_RISK_METHOD, CREDIT_CASH_METHOD):
        assert by_id[ref.id]['definition']['action_ids'] == ['BANK-A03', 'BANK-A04', 'BANK-A13']
        assert by_id[ref.id]['definition']['calibration'] == 'mathematical_only'
    for ref in (COMPARISON_METHOD, CASH_METHOD):
        assert by_id[ref.id]["definition"]["action_ids"] == (["OWN-A03", "CONTRACTOR-A04"] if ref == CASH_METHOD else ["OWN-A03"])
        assert by_id[ref.id]["definition"]["calibration"] == "mathematical_only"


@pytest.mark.parametrize("mutation", ["clock", "bounds", "empty", "negative_resource", "zero_demand",
                                    "commitment_version", "commitment_unit", "commitment_identity", "sources"])
def test_capacity_rejects_unsupported_or_inconsistent_input(mutation):
    data = base_input().model_dump(mode="python")
    commitment = {"commitment_ref": ref("ResourceCommitment", "allocated"),
                  "resource_ref": ref("Resource", "line-1"), "quantity": measured("0.5"),
                  "window": window(0, 10)}
    if mutation == "clock":
        data["resources"][0]["effective_window"] = window(0, 10, "foreign-clock")
    elif mutation == "bounds":
        data["demands"][0]["window"]["bounds"] = "closed_closed"
    elif mutation == "empty":
        data["demands"][0]["window"] = window(1, 1)
    elif mutation == "negative_resource":
        data["resources"][0]["total"]["value"] = "-1"
    elif mutation == "zero_demand":
        data["demands"][0]["amount"]["numerator"] = 0
    elif mutation == "commitment_version":
        commitment["resource_ref"]["version"] = "2"
        data["commitments"] = [commitment]
    elif mutation == "commitment_unit":
        commitment["quantity"]["unit"] = "kg"
        data["commitments"] = [commitment]
    elif mutation == "commitment_identity":
        revised = deepcopy(commitment)
        revised["commitment_ref"]["version"] = "2"
        data["commitments"] = [commitment, revised]
    else:
        data["source_refs"] *= 2
    with pytest.raises(ValueError):
        CapacityInput.model_validate(data)


def test_generated_segments_match_independent_per_tick_oracle():
    rng = random.Random(61006)
    for _ in range(100):
        resources = [resource(str(rng.randint(0, 8)), identity=f"line-{i}") for i in range(3)]
        commitments = []
        demands = []
        for i in range(5):
            start, end = sorted(rng.sample(range(11), 2))
            demands.append(demand(str(rng.randint(1, 4)), start=start, end=end))
            start, end = sorted(rng.sample(range(11), 2))
            commitments.append({"commitment_ref": ref("ResourceCommitment", f"commit-{i}"),
                "resource_ref": resources[rng.randrange(3)]["resource_ref"],
                "quantity": measured(str(rng.randint(1, 5))), "window": window(start, end)})
        for row in resources:
            start, end = sorted(rng.sample(range(11), 2))
            row["effective_window"] = window(start, end)
        report = compare_capacity(base_input(resources=resources, commitments=commitments, demands=demands))
        oracle = []
        for tick in range(10):
            needed = sum(row["amount"].numerator for row in demands
                         if row["window"]["start"]["offset"] <= tick < row["window"]["end"]["offset"])
            if not needed:
                continue
            available = 0
            for row in resources:
                total = int(row["total"]["value"]) if row["effective_window"]["start"]["offset"] <= tick < row["effective_window"]["end"]["offset"] else 0
                used = sum(int(item["quantity"]["value"]) for item in commitments
                           if item["resource_ref"] == row["resource_ref"]
                           and item["window"]["start"]["offset"] <= tick < item["window"]["end"]["offset"])
                available += max(0, total - used)
            segment = next(row for row in report.segments if row.window.start.offset <= tick < row.window.end.offset)
            assert segment.needed.fraction() == needed
            assert segment.available.fraction() == available
            oracle.append(needed <= available)
        assert report.feasible == all(oracle)


@pytest.fixture(scope="module")
def action_catalog():
    from src.actions.contracts.catalog import ContractCatalog
    return ContractCatalog()


def method_host(action_catalog, methods=None, method_refs=(CAPACITY_METHOD,)):
    from tests.test_supplier_screening import build_run, facts
    run = build_run(facts(), catalog=action_catalog)
    reading = ActionReadView(run.context, run.runner.references, run.runner.organizations,
                            "SUPPLIER-A01", "Supplier", methods=methods or local_method_registry(),
                            method_refs=method_refs)
    return run, reading


def method_input(run):
    data = base_input().model_dump(mode="python")
    clock = run.context.business_time.clock_ref.model_dump()
    data["clock_ref"] = clock
    for row in [*data["resources"], *data["demands"]]:
        w = row.get("window", row.get("effective_window"))
        for endpoint in ("start", "end"):
            w[endpoint]["clock_ref"] = clock
    basis = ref("Evidence", "synthetic-basis")
    data["resources"][0]["total"]["basis_ref"] = basis
    data["demands"][0]["basis_refs"] = [basis]
    data["source_refs"] = [run.input["capacity_ref"]]
    return data


def test_method_result_binds_run_provenance_and_audit_without_side_effects(action_catalog):
    run, reading = method_host(action_catalog)
    before = deepcopy(run.objects)
    data = method_input(run)
    result = reading.calculate(CAPACITY_METHOD, data)
    assert result.kind == "ok" and result.value.feasible
    assert result.method_ref == CAPACITY_METHOD
    assert len(result.input_digest) == 64
    assert result.input_refs[0].data_space.id == run.context.run_id
    assert result.input_refs[0].ref.model_dump() == run.input["capacity_ref"]
    assert result.basis_refs[0].id == "synthetic-basis"
    assert reading.calculate(CAPACITY_METHOD, data).input_digest == result.input_digest
    assert reading.method_evidence()[0]["result"]["input_digest"] == result.input_digest
    assert run.objects == before
    other, other_reading = method_host(action_catalog)
    context = other.context.model_copy(update={"operation_id": "another-operation"})
    reading2 = ActionReadView(context, other.runner.references, other.runner.organizations,
                             "SUPPLIER-A01", "Supplier", methods=local_method_registry(), method_refs=[CAPACITY_METHOD])
    assert reading2.calculate(CAPACITY_METHOD, method_input(other)).input_digest != result.input_digest


def test_missing_provenance_remains_needs_information(action_catalog):
    run, reading = method_host(action_catalog)
    data = method_input(run)
    data["source_refs"] = []
    assert reading.calculate(CAPACITY_METHOD, data).kind == "needs_information"


def test_invalid_input_never_echoes_private_values(action_catalog):
    run, reading = method_host(action_catalog)
    data = method_input(run)
    data["private"] = "secret-private-quantity"
    result = reading.calculate(CAPACITY_METHOD, data)
    assert result.kind == "invalid_input"
    assert "secret-private-quantity" not in result.model_dump_json()


def test_unregistered_method_and_missing_skill_permission_are_unsupported(action_catalog):
    run, reading = method_host(action_catalog, method_refs=())
    assert reading.calculate(CAPACITY_METHOD, method_input(run)).kind == "unsupported"
    run, reading = method_host(action_catalog)
    future = CAPACITY_METHOD.model_copy(update={"version": "2"})
    assert reading.calculate(future, method_input(run)).kind == "unsupported"


def test_method_cannot_expand_source_visibility_or_context(action_catalog):
    run, reading = method_host(action_catalog)
    data = method_input(run)
    data["source_refs"] = [ref("SupplierCapacity", "competitor-private")]
    with pytest.raises(AccessDenied):
        reading.calculate(CAPACITY_METHOD, data)
    with pytest.raises(AccessDenied, match="context"):
        local_method_registry().invoke(CAPACITY_METHOD, method_input(run),
            context=run.context.model_copy(update={"run_id": "foreign"}), action_id="SUPPLIER-A01", reading=reading)


def broken_executor(value):
    raise RuntimeError("private executor details")


def revoking_executor(value):
    revoking_executor.revoke()
    return compare_capacity(value)


def custom_registry(executor, *, action_ids=None):
    from src.methods.capacity import CapacityReport
    definition = next(row['definition'] for row in local_method_registry().catalog()
                      if row['definition']['method_ref']['id'] == CAPACITY_METHOD.id)
    if action_ids is not None:
        definition["action_ids"] = action_ids
    registry = MethodRegistry()
    registry.register(definition, CapacityInput, CapacityReport, executor)
    return registry.snapshot()


def test_executor_failure_is_technical_error(action_catalog):
    run, reading = method_host(action_catalog, methods=custom_registry(broken_executor))
    result = reading.calculate(CAPACITY_METHOD, method_input(run))
    assert result.kind == "technical_error" and result.error.code == "method_execution_failed"
    assert "private executor" not in result.model_dump_json()


def test_action_support_does_not_fall_back_to_another_action(action_catalog):
    run, reading = method_host(action_catalog, methods=custom_registry(compare_capacity, action_ids=["CONTRACTOR-A01"]))
    assert reading.calculate(CAPACITY_METHOD, method_input(run)).kind == "unsupported"


def test_revoked_authorization_rejects_method_result_after_execution(action_catalog):
    run, reading = method_host(action_catalog, methods=custom_registry(revoking_executor))
    revoking_executor.revoke = lambda: run.runner.organizations.revoke(run.context.authorization_refs[0])
    with pytest.raises(AccessDenied):
        reading.calculate(CAPACITY_METHOD, method_input(run))


def revoking_failed_executor(value):
    revoking_failed_executor.revoke()
    raise RuntimeError("failure after revocation")


def test_revoked_authorization_also_rejects_failed_method_execution(action_catalog):
    run, reading = method_host(action_catalog, methods=custom_registry(revoking_failed_executor))
    revoking_failed_executor.revoke = lambda: run.runner.organizations.revoke(run.context.authorization_refs[0])
    with pytest.raises(AccessDenied):
        reading.calculate(CAPACITY_METHOD, method_input(run))


def test_role_runner_audits_real_method_calls_for_both_roles(action_catalog):
    from tests.test_supplier_screening import build_run, facts
    from tests.test_contractor_screening import build_screening_run, facts as contractor_facts
    for run in (build_run(facts(), catalog=action_catalog),
                build_screening_run(contractor_facts(), catalog=action_catalog)):
        result = run.execute()
        assert result.kind == "completed"
        record = run.runner.audit_records[-1].as_dict()
        assert record["method_registry_digest"] == run.runner.methods.content_digest
        assert record["method_calls"]
        assert all(call["result"]["kind"] == "ok" for call in record["method_calls"])
        assert all(call["result"]["input_refs"][0]["data_space"]["id"] == run.context.run_id
                   for call in record["method_calls"])
