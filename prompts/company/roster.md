You are designing the internal member-agent roster for one company.

Act as if this company is preparing for a construction package simulation.
Choose members that fit the company's role, profile, strengths, weaknesses, and eligible packages.
Do not copy a generic department template when the company profile suggests a different internal emphasis.
This is a compact prototype roster, not a full organization chart. Create 4 to 6 key members only. Prefer distinct decision perspectives over many similar job titles. Do not split one repeated viewpoint into separate assistants, coordinators, or deputies.
Keep member duties inside the company simulation. Use internal/client-facing wording such as stakeholder coordination, site reporting, owner interface, quality review, package coordination, cost control, resource planning, design coordination, payment review, payment assessment, cost review, documentation discipline, and quality target tracking.
Give every member an independent personal profile. The profile should describe how this person thinks under pressure, what they notice first, and what tension they tend to bring into discussion. Do not make profiles identical.

Return JSON with:
members.
The top-level JSON must be an object with the `members` key.
Do not return a bare JSON array.
`members` must be a JSON array.
Each member must include:
agent_name, department, position, personal_profile, responsibilities, decision_authority, communication_style.

`responsibilities` must be an array of short strings.
At least one member must have decision_authority exactly `final`.
