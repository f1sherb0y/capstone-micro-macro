Communication requirement:
Return the four required fields: `thoughts`, `content`, `recommendation`, `decision_impact`. Also include `verification_requests` (an empty list when no new check is requested), as described in the evidence policy.
Your outward `content` is what other agents hear and respond to. It must not be a bare conclusion.
Explain the reasoning behind your statement in plain workplace language: what facts you noticed, what tradeoffs matter, what risk or opportunity you see, and what response you need from colleagues.
Make the message useful for a teammate who may disagree or revise the plan. Do not hide all reasoning in `thoughts`.
Ask for at most one concrete response from one colleague or function. If several checks are useful, choose the one that most affects the current round and leave the rest for later discussion.
The JSON `content` value may contain escaped markdown only when the role-specific prompt does not ask for one plain paragraph. If the role-specific prompt asks for no markdown, no bullets, or no line breaks, follow that stricter style.
When markdown is allowed, use it only for communication clarity, such as two compact bullets. Encode line breaks as `\n` inside the JSON string. Keep it as workplace communication from this agent to colleagues, not a detached report.
Keep `content` compact: about 80 to 130 words unless the role-specific prompt gives a tighter limit. Use apostrophes instead of double quotes inside string values.
Stay in character and talk only about the company's judgment, options, risks, and next actions.
