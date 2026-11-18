"""The retained-read fix extends a declaration, not the current access guard."""
import pytest
import json
from contextlib import nullcontext
from types import SimpleNamespace

from integration.final_account_discussion_development import initial_sources
from integration.origin_lifecycle_sources import InitialLateSources
from src.actions.contracts.common import ActionContext
from src.organization.registry import AccessDenied, OrganizationRegistry, OrganizationSnapshot


def test_final_read_keeps_expiry_identity_and_revocation_guards(tmp_path):
    config = {'run_id': 'origin-read-test', 'tender_open_tick': 1,
        'late_money_scale': '1', 'contract_duration': 24, 'ticks': 48}
    snapshot, document = initial_sources(run_id=config['run_id'], project_id='p',
        with_qs=False, successor=False)
    transform = InitialLateSources(tmp_path/'declarations', config=config)
    checked = OrganizationSnapshot.model_validate(transform.transform(snapshot))
    registry = OrganizationRegistry(config['run_id'])
    for org in checked.organizations:
        registry.register(org)
    for grant in checked.authorizations:
        registry.authorize(grant)
    context = ActionContext.model_validate(transform.transform(document['plans'][0]['context']))
    current = context.model_copy(update={'business_time': context.business_time.model_copy(update={'offset': 48})})
    grants = registry.grants(current, current.contract_ref.id, 'Owner')
    assert grants and all(g.organization_id == 'owner' for g in grants)
    with pytest.raises(AccessDenied):
        registry.grants(current.model_copy(update={'actor_id': 'wrong-actor'}), current.contract_ref.id, 'Owner')
    with pytest.raises(AccessDenied):
        registry.grants(current.model_copy(update={'business_time': current.business_time.model_copy(
            update={'offset': 49})}), current.contract_ref.id, 'Owner')
    registry.revoke(current.authorization_refs[0])
    with pytest.raises(AccessDenied):
        registry.grants(current, current.contract_ref.id, 'Owner')


def test_raw_native_result_is_retained_when_component_export_is_denied(tmp_path, monkeypatch):
    from integration import front_to_closeout_case as entry
    from integration.module_host import GbaModuleHostExtension

    simulation = {'simulation_id': 'capture-test', 'status': 'completed',
        'current_tick': 48, 'project_results': []}
    engine = SimpleNamespace(status='completed', events=SimpleNamespace(events=[]),
        response=lambda: SimpleNamespace(model_dump=lambda **_: simulation))

    def denied():
        raise AccessDenied('current private read denied')

    original = GbaModuleHostExtension(version='capture-test', evidence=denied,
        close=lambda: None, writer_guard=nullcontext)
    monkeypatch.setattr(entry, 'configure_front', lambda **_: original)
    extension = entry.configure_assembly(assembly=SimpleNamespace(engine=engine),
        request=None, output_directory=tmp_path, offline=True, configuration={})
    with pytest.raises(AccessDenied, match='current private read denied'):
        extension.evidence()
    captured = json.loads((tmp_path/'native-run-state.json').read_bytes())
    assert captured['simulation'] == simulation
    assert captured['original_global_events'] == []
