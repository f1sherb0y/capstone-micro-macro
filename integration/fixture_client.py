"""Explicit offline fixture. Its environmental response is NOT research evidence."""
import json

from src.mock_llm import MockLLMClient


class IntegrationFixtureClient(MockLLMClient):
    def __init__(self):
        self.requests = []

    def chat(self, messages, temperature=0.2):
        self.requests.append(messages)
        prompt = messages[-1]["content"]
        marker = prompt.splitlines()[0]
        context = json.loads(prompt.split("Authorized decision context:\n", 1)[1]) if "Authorized decision context:\n" in prompt else {}
        spec = context.get("public", {}).get("package", {})
        if marker == "MANAGEMENT_DECISION" and spec.get("kind") == "construction":
            lead = spec["candidate_ids"][0]
            decision = "bid_with_consortium" if context["own_state"]["entity_id"] == lead else "bid"
            return self._json(thoughts="Offline consortium coverage", decision=decision,
                              reason="Deterministic offline fixture; not a business quality finding", content=decision,
                              **self._condition_disposition(prompt))
        if marker == "CONSORTIUM" and spec.get("kind") == "construction":
            members = spec["candidate_ids"][:2]
            return self._json(status="formed", consortium_name="Offline test consortium", member_company_ids=members,
                              formation_reason="Exercise shared-ID consortium execution", role_split={m: "Shared works" for m in members},
                              agreement_summary="Deterministic fixture; every member must separately authorize")
        if marker in {"CONSORTIUM_ACCEPTANCE", "CONTRACT_ACCEPTANCE"}:
            return self._json(action="accept", reason="Offline fixture independently accepts the supplied terms")
        if marker == "CONTRACT_CLARIFICATION":
            return self._json(scope_and_interfaces="The authorized package scope remains binding.",
                              price_and_change_control="Fixed canonical price for the authorized scope; no automatic adjustment.",
                              payment_terms="Payment follows accepted milestone deliverables within the contract price.",
                              delivery_and_review="Future deliverables require buyer review before acceptance; no external approval is claimed.",
                              response_to_feedback="Clarifications proposed for independent acceptance by every party.")
        if marker == "CONTRACT_ALLOCATION":
            terms = json.loads(prompt.split("\n", 1)[1].split("\nAuthorized decision context:", 1)[0])
            return self._json(work_shares={m: 1 / len(terms["members"]) for m in terms["members"]})
        response = super().chat(messages, temperature)
        if marker == "OWNER_PACKAGE_BRIEF":
            data = json.loads(response)
            spec = context["public"]["package"]
            kind = {"construction": "contractor", "cost_consulting": "supervision", "supply": "supplier"}.get(spec["kind"], spec["kind"])
            role = {"design": "designer", "construction": "contractor", "cost_consulting": "supervisor", "supply": "supplier"}[spec["kind"]]
            package = self._package(spec["package_id"], kind, spec["name"], role)
            package["scope"] = spec["scope"]
            data["package_plan"] = [package]
            return self._json(**data)
        if marker == "EVALUATION":
            data = json.loads(response)
            consortium = next((b for b in data["bid_evaluations"] if b["bidder_id"].startswith("consortium_")), None)
            if consortium:
                data["recommended_bidder_id"] = consortium["bidder_id"]
                data["comparison_summary"] = "Offline fixture selects a consortium to exercise multi-member execution; not a quality finding."
            return self._json(**data)
        if marker == "BID_DOCUMENT":
            data = json.loads(response)
            public = context["public"]
            price = round(public["package_budget"] * 0.70 * (0.6 + 0.4 * public["environment"]["material_price_index"]), 2)
            data["quotation"] = price
            data["quotation_breakdown"] = [{"item": "Scenario package works", "amount": price, "basis": "Deterministic offline fixture, not empirical cost calibration"}]
            data["submission_summary"] = "Offline scope and price fixture"
            return self._json(**data)
        return response
