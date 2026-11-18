# Role Fixtures

`eight_role_initial.v2.json` contains eight synthetic test organizations. Role
assignments are scenario assumptions. No qualifications, approved projects,
cash, resource quantities, inventory, professional methods or executable macro
capabilities are inferred from these labels. Missing initial values remain
unknown.

Rebuild this generated test fixture with:

```bash
python -m integration.role_fixtures --output tests/fixtures/roles/eight_role_initial.v2.json --refresh-test-fixture
```

The refresh option is restricted to this repository's role-fixture directory.
Historical runtime outputs cannot be refreshed by this command.
