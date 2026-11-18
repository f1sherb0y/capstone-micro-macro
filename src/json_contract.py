from __future__ import annotations


JSON_CONTRACT = (
    "\n\nReturn one valid JSON object only. Do not put markdown fences, comments, "
    "or any text outside the JSON object. The response must start with { and end with }. "
    "String fields that contain agent messages, "
    "explanations, notes, reports, or proposals may use escaped markdown for readability. "
    "Markdown line breaks inside string values must be encoded as \\n, not raw line breaks. "
    "Do not use raw double quote characters inside JSON string values; use apostrophes, "
    "parentheses, or no quote marks instead. "
    "If a double quote is unavoidable inside a string value, escape it with a backslash. "
    "Keep all wording inside the fictional simulation and use capability-fit language."
)


def with_json_contract(system_prompt: str) -> str:
    return system_prompt + JSON_CONTRACT
