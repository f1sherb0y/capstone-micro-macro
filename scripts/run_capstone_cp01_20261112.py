"""Explicit independent CP01 runner. Merely importing/preflighting never calls."""
import argparse
import asyncio

from capstone_cp_common_20261112 import CP01, PARENT, engine_binding, read, sha, verify_input_protocol


def verify_frozen():
    from run_capstone_expansion_20261109 import verify_frozen as verify_old
    verify_old()
    protocol = verify_input_protocol(CP01)
    if sha(PARENT / 'protocol.json') != protocol['parent_protocol_sha256']:
        raise ValueError('Parent frozen protocol changed')
    return protocol


def run(authorized_cap=None):
    if type(authorized_cap) is not int or authorized_cap != 240:
        raise ValueError('CP01 requires its own explicit 240-call scope; no historical cap or balance')
    p = verify_frozen()
    if not read(CP01 / 'preflight.json')['passed']:
        raise ValueError('CP01 zero-call preflight required')
    if (CP01 / 'run').exists() or (CP01 / 'authorization.json').exists():
        raise ValueError('Existing or unknown CP01 attempt: no automatic replay')
    with engine_binding(CP01, verify_frozen) as engine:
        client = engine.OpenAICompatibleClient.from_env(model=p['model'])
        store = None
        try:
            policy = client.request_policy()
            if policy['provider'] != 'deepseek' or policy['internal_retries'] != 0:
                raise ValueError('Unexpected transport or hidden retry')
            client._chat_model.max_tokens = p['max_output_tokens']
            params = client._chat_model._default_params
            if params.get('max_tokens', params.get('max_completion_tokens')) != 4096:
                raise ValueError('Output limit not bound')
            engine.save(CP01 / 'authorization.json', {'at': engine.utc_now(), 'max_calls': 240,
                        'protocol_sha256': sha(CP01 / 'protocol.json'), 'transport': policy,
                        'scope': 'CP01 new24 only; no previous balance or macro run'})
            store = engine.TaskStore(run_id=p['run_id'], organization_ids=['experiment-host'], path=CP01 / 'run/budget.sqlite')
            budget = engine.ModelCallBudget(store=store, budget_id=p['budget_id'], max_calls=240)
            logger = engine.LLMCallAuditLogger(CP01 / 'run', 'CP01-NEW24', client)

            async def perform():
                try:
                    await engine.perform(client, budget, logger, p, read(CP01 / 'windows.json'))
                finally:
                    engine.save(CP01 / 'run/budget_usage.json', budget.usage())
                    await client._chat_model.root_async_client.close()
            asyncio.run(perform())
        finally:
            if store is not None:
                store.close()
            client._chat_model.root_client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-max-calls', type=int)
    run(parser.parse_args().authorize_max_calls)
