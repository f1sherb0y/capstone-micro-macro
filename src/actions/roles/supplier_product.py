"""SUPPLIER-A02 product proposals; never approval or permission to use a product."""
from decimal import Decimal

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.supplier_objects import SupplyInquiryView
from src.actions.contracts.supplier_product_objects import (
    ProductRequirementView, ProductSpecificationView, ProductCompatibilityMethodView,
    ProductEvidenceView, ProductDeviationView, ProductIssueView, ProductDesignView,
)
from src.actions.roles.supplier import SupplyGap, _known, _needs, _unsupported
from src.methods.product import PRODUCT_METHOD, ProductComparisonInput
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def propose_products(context, action_input, reading):
    def current(window, field):
        if window.start.clock_ref != context.business_time.clock_ref:
            _unsupported("product-review-clock")
        if not window.contains(context.business_time):
            _needs(field)

    def available(point, field):
        if point.clock_ref != context.business_time.clock_ref:
            _unsupported("product-review-clock")
        if point.offset > context.business_time.offset:
            _needs(field)

    def evidence(refs):
        for ref in refs:
            record = reading.resolve(ref)
            if not isinstance(record, EvidenceRecord):
                _unsupported("product-review-evidence-schema")
            if record.effective_window is not None:
                current(record.effective_window, "current_product_review_evidence")

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"product-review-projection:{ref.kind}")
        evidence(value.evidence_refs)
        return value

    def completed(choice, note, **fields):
        return {"kind": "completed", "payload": {"choice": choice, "note": note, **fields}}

    try:
        inquiry = read(action_input.inquiry_ref, SupplyInquiryView)
        if (inquiry.recipient_id != context.actor_id
                or inquiry.recipient_organization_id != reading.organization_id
                or not scope_covers(context.scope, inquiry.scope)):
            raise ValueError("Product inquiry recipient or scope mismatch")
        available(inquiry.received_at, "received_product_inquiry")
        current(inquiry.response_window, "active_product_response_window")
        if inquiry.status != "active":
            _needs("active_product_inquiry", [inquiry.ref])
        requirements = [read(ref, ProductRequirementView) for ref in action_input.requirement_refs]
        lines = {line.requirement_ref.key(): line for line in inquiry.lines}
        if len(requirements) != len(lines) or {row.ref.key() for row in requirements} != set(lines):
            _needs("complete_inquiry_requirement_versions", [line.requirement_ref for line in inquiry.lines])
        for requirement in requirements:
            line = lines[requirement.ref.key()]
            if requirement.inquiry_ref != inquiry.ref or requirement.scope != line.scope:
                raise ValueError("Requirement is not the exact inquiry line")
            for dependency in requirement.design_dependencies:
                evidence(dependency.evidence_refs)
                issue = read(dependency.issue_ref, ProductIssueView)
                if (issue.inquiry_ref != inquiry.ref or issue.requirement_ref != requirement.ref
                        or issue.scope != requirement.scope or issue.check_code != dependency.check_code):
                    raise ValueError("Design issue identity mismatch")
        if inquiry.clarification_requirement_refs:
            if any(ref not in action_input.requirement_refs for ref in inquiry.clarification_requirement_refs):
                raise ValueError("Clarification names an unsupplied requirement version")
            return completed("clarify", "Clarify the exact registered requirements before product proposal",
                             requirement_refs=inquiry.clarification_requirement_refs)

        method = read(action_input.compatibility_method_ref, ProductCompatibilityMethodView)
        if method.organization_id != reading.organization_id:
            raise ValueError("Compatibility method belongs to another supplier")
        current(method.effective_window, "current_compatibility_method")
        if method.algorithm_code != "declared_constraints_v1":
            _unsupported("product-interface-method")
        authorities = {ref.key(): reading.resolve(ref) for ref in action_input.design_authority_refs}
        for authority in authorities.values():
            if not isinstance(authority, Authorization):
                _unsupported("product-design-authority-schema")
            evidence(authority.basis_refs)
        designs = [read(ref, ProductDesignView) for ref in action_input.design_refs]
        for design in designs:
            if design.inquiry_ref != inquiry.ref or not scope_covers(inquiry.scope, design.scope):
                raise ValueError("Design inquiry or scope mismatch")
            current(design.effective_window, "current_product_design")
            available(design.available_at, "available_product_design")
            if design.allowed_purpose != "product_proposal_review":
                _needs("design_allowed_for_product_proposal", [design.ref])
            authority = authorities.get(design.authorization_ref.key())
            if authority is None:
                _needs("design_authority", [design.authorization_ref])
            if (authority.actor_id != design.author_actor_id
                    or authority.organization_id != design.author_organization_id
                    or authority.function_ref != design.author_function_ref):
                raise ValueError("Design author differs from its authorization")
            current(authority.validity, "current_design_authority")
            if (design.authority_action_id not in authority.action_ids
                    or design.authority_action_id not in method.design_action_ids
                    or not any(scope_covers(scope, design.scope) for scope in authority.scopes)):
                _needs("bounded_design_authority", [authority.ref])

        if not action_input.product_candidates:
            _needs("product_candidates")
        products = [read(ref, ProductSpecificationView) for ref in action_input.product_candidates]
        if len({(row.ref.kind, row.ref.id) for row in products}) != len(products):
            raise ValueError("Product identity repeated across versions")
        for product in products:
            if product.supplier_organization_id != reading.organization_id:
                raise ValueError("Product is not supplied by the current organization")
            current(product.effective_window, "current_product_specification")

        selected = []
        selected_evidence = {}
        unresolved = {}
        substitute = False
        for requirement in requirements:
            line = lines[requirement.ref.key()]
            code = _known(line.product_code, "requested_product_code")
            quantity = _known(line.quantity, "product_quantity")
            evidence([quantity.basis_ref])
            if Decimal(quantity.value) <= 0:
                raise ValueError("Product proposal quantity must be positive")
            use = _known(requirement.intended_use_code, "product_intended_use")
            factories = _known(requirement.allowed_factory_ids, "product_factory_restrictions")
            constraints = _known(requirement.constraints, "declared_product_constraints")
            if not constraints or not factories:
                _needs("explicit_product_constraints_and_factories", [requirement.ref])
            if use not in method.supported_use_codes or not {c.property_code for c in constraints} <= set(method.supported_property_codes):
                _unsupported("product-method-use-or-property-domain")
            feasible = []
            for product in products:
                product_code = _known(product.product_code, "candidate_product_code")
                factory = _known(product.factory_id, "candidate_factory")
                uses = _known(product.use_codes, "candidate_uses")
                properties = _known(product.properties, "candidate_properties")
                if factory not in method.supported_factory_ids:
                    _unsupported("product-method-factory-domain")
                if factory not in factories or use not in uses:
                    continue
                if product.quantity_unit != quantity.unit:
                    _unsupported("product-quantity-unit")
                product_basis = []
                covered = set()
                for ref in product.product_evidence_refs:
                    proof = read(ref, ProductEvidenceView)
                    if proof.product_ref != product.ref:
                        raise ValueError("Product evidence version mismatch")
                    # Evidence from another factory/use/scope cannot prove this application.
                    if (proof.factory_id != factory or proof.intended_use_code != use
                            or not scope_covers(proof.scope, requirement.scope)):
                        continue
                    current(proof.effective_window, "current_applicable_product_evidence")
                    available(proof.available_at, "available_product_evidence")
                    product_basis.append(proof.ref)
                    covered.update(proof.property_codes)
                codes = {c.property_code for c in constraints}
                if not codes <= covered:
                    _needs("applicable_product_evidence", [product.ref, requirement.ref])
                actuals = {row.property_code: row for row in properties}
                if not codes <= set(actuals):
                    _needs("candidate_property_values", [product.ref])
                if any(actuals[c.property_code].kind != c.kind
                       or (c.kind == "range" and actuals[c.property_code].unit != c.unit) for c in constraints):
                    _unsupported("product-property-type-or-unit")
                comparison = reading.calculate(PRODUCT_METHOD, ProductComparisonInput(
                    constraints=constraints, properties=properties,
                    source_refs=[requirement.ref, product.ref, method.ref, *product_basis]))
                if comparison.kind != "ok":
                    if comparison.kind == "invalid_input":
                        raise ValueError("Invalid product comparison input")
                    result = comparison.model_dump(mode="python")
                    if comparison.kind == "needs_information":
                        result["requested_refs"] = []
                    raise SupplyGap(result)
                changed = {check.property_code for check in comparison.value.checks if not check.matches}
                if not changed <= set(requirement.substitutable_property_codes):
                    continue
                if product_code != code:
                    if not requirement.allow_product_substitution:
                        continue
                    changed.add("product_code")
                deviations = []
                described = set()
                for ref in product.deviation_refs:
                    deviation = read(ref, ProductDeviationView)
                    if deviation.product_ref != product.ref:
                        raise ValueError("Deviation product version mismatch")
                    if deviation.requirement_ref != requirement.ref or deviation.inquiry_ref != inquiry.ref:
                        continue
                    if (deviation.factory_id != factory or deviation.intended_use_code != use
                            or deviation.scope != requirement.scope):
                        _needs("applicable_substitution_deviation", [deviation.ref])
                    current(deviation.effective_window, "current_substitution_deviation")
                    if deviation.property_code in changed:
                        described.add(deviation.property_code)
                        deviations.append(deviation.ref)
                if described != changed:
                    _needs("explicit_substitution_deviations", [product.ref, requirement.ref])
                pending = []
                rejected = False
                for dependency in requirement.design_dependencies:
                    checks = []
                    for design in designs:
                        if not scope_covers(design.scope, requirement.scope):
                            continue
                        for check in design.checks:
                            if (check.requirement_ref == requirement.ref and check.product_ref == product.ref
                                    and check.factory_id == factory and check.intended_use_code == use
                                    and check.check_code == dependency.check_code):
                                evidence(check.evidence_refs)
                                checks.append(check)
                    if len(checks) > 1:
                        _needs("unambiguous_current_design_check", [product.ref, requirement.ref])
                    if checks and checks[0].compatible.state == "not_supported":
                        raise SupplyGap({"kind": "unsupported", "capability_ref": checks[0].compatible.capability_ref})
                    if not checks or checks[0].compatible.state != "known":
                        pending.append(dependency.issue_ref)
                    elif not checks[0].compatible.value:
                        rejected = True
                if not rejected:
                    feasible.append((product, deviations, product_basis, pending))
            if not feasible:
                return completed("decline", "Known product restrictions prevent a proposal for the complete inquiry; no approval or production effect")
            if len(feasible) > 1:
                priorities = {row.product_ref.key(): row for row in method.selection_priorities}
                ranks = []
                for candidate in feasible:
                    policy = priorities.get(candidate[0].ref.key())
                    if policy is None:
                        _needs("explicit_product_selection_priority", [candidate[0].ref])
                    evidence(policy.evidence_refs)
                    ranks.append(_known(policy.priority, "known_product_selection_priority"))
                lowest = min(ranks)
                if ranks.count(lowest) != 1:
                    _needs("unique_product_selection_priority")
                chosen = feasible[ranks.index(lowest)]
            else:
                chosen = feasible[0]
            product, deviations, proofs, pending = chosen
            selected.append({"product_ref": product.ref, "destination_scope_ref": requirement.scope,
                "quantity": quantity, "requirement_refs": [requirement.ref], "deviation_refs": deviations})
            selected_evidence.update((ref.key(), ref) for ref in proofs)
            unresolved.update((ref.key(), ref) for ref in pending)
            substitute = substitute or bool(deviations)
        return completed("propose_substitute" if substitute else "propose_original",
            "Proposal limited to evidenced catalog properties; listed design checks remain unresolved. Procurement and professional approval are required before production or installation",
            lines=selected, evidence_refs=list(selected_evidence.values()), unresolved_refs=list(unresolved.values()))
    except SupplyGap as gap:
        return gap.result
    except (ValueError, KeyError):
        return {"kind": "technical_error", "error": {"kind": "unrecorded", "correlation_id": context.operation_id,
            "code": "product_projection_invalid"}, "retryability": "non_retryable"}
