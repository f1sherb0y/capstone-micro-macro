"""Declare initial model tender options before the existing bundle is sealed."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import argparse
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, StrictRecord, TextId


class TenderModelDevelopmentSettings(StrictRecord):
    strategy: Literal['single_agent', 'organization_discussion']
    provider: TextId
    model: TextId
    alternate_markup_fraction: DecimalString
    max_calls: Annotated[int, Field(gt=0)] = 16
    max_prompt_chars: Annotated[int, Field(gt=0)] = 300000

    @model_validator(mode='after')
    def distinct_explicit_policy(self):
        value = Decimal(self.alternate_markup_fraction)
        if not value.is_finite() or not Decimal('0') <= value <= Decimal('1') or value == Decimal('0.1'):
            raise ValueError('Declare a distinct initial markup between zero and one; the original is 0.1')
        return self

    def host_settings(self, run_id):
        return {'namespace': run_id + '-tender-options', 'strategy': self.strategy,
            'host': {'host_id': run_id + '-model', 'budget_id': run_id + '-model-budget',
                'max_calls': self.max_calls, 'action_ids': ['CONTRACTOR-A01', 'CONTRACTOR-A02'],
                'max_options': 2, 'max_prompt_chars': self.max_prompt_chars, 'max_members': 3}}


def add_initial_model_options(*, config, snapshots, quantity_snapshots, plans, authorizations):
    """Only author initial own pricing policy, candidate/read rights and sources.

    No persisted authority is migrated, and no result, formal bid or receipt is
    produced. Explicit later decline policies retain their sole original input.
    """
    alternatives = {}
    for snapshot in snapshots:
        rows = snapshot['projection']['objects']
        profiles = [row['value'] for row in rows if row['ref']['kind'] == 'ContractorPricingProfile']
        if not profiles or profiles[0]['choice'] != 'submit_bid':
            continue
        original = profiles[0]
        alternative = deepcopy(original)
        alternative['ref']['id'] += '-model-alternative'
        alternative['markup_fraction'] = config.alternate_markup_fraction
        alternative['decline_reason'] = 'Explicit assumed initial alternative commercial pricing policy.'
        rows.append({'ref': alternative['ref'], 'value': alternative})
        reference = alternative['ref']
        alternatives[(original['organization_id'], original['ref']['id'])] = reference
        if reference not in snapshot['context']['visible_refs']:
            snapshot['context']['visible_refs'].append(reference)
        candidate = next(row['value'] for row in rows if row['ref'] == snapshot['context']['candidate_set_ref'])
        candidate['candidates'].append({'ref': reference, 'permitted_choices': ['submit_bid']})
        grant = authorizations[original['organization_id']]
        if reference not in grant['readable_refs']:
            grant['readable_refs'].append(reference)
    for plan in plans:
        bid = plan.get('bid_plan')
        if bid is None:
            continue
        reference = alternatives.get((plan['organization_id'], bid['pricing_profile_ref']['id']))
        if reference is not None and reference not in bid['bid_context']['visible_refs']:
            bid['bid_context']['visible_refs'].append(reference)
    for snapshot in [*snapshots, *quantity_snapshots]:
        for row in snapshot['projection']['objects']:
            if row['ref']['kind'] == 'Authorization':
                grant = authorizations.get(row['value']['organization_id'])
                if grant is not None and row['ref'] == grant['ref']:
                    row['value'] = deepcopy(grant)


def write_model_launch_files(directory):
    from integration.contractor_tender_development import _write_launch_files, NOTE
    _write_launch_files(directory, offline=False,
        assembly_hook='integration.model_tender_native:configure_assembly',
        agent_client_factory='integration.model_tender_native:build_agent_client',
        source_note=NOTE + ' Two initial own pricing policies are explicitly assumed. Only configured Contractor actions use a model; other routes retain declared native behavior.',
        readme_override=('Explicit model tender input. Run run.ps1 with a new output directory. '
            'This loads the configured environment transport and may make paid requests within max_calls. '
            'A01 retains its original input; A02 selects between two original-processor-validated pricing policies. '
            'Explicit subsequent decline policies retain their sole original option. '
            'Other routes are native behavior, not model coverage. All initial business sources remain synthetic assumptions. '
            'No bid, receipt, award, work or payment is supplied as an input.'))


def main(argv=None):
    from integration.contractor_tender_development import build_bundle, build_feedback_bundle
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--strategy', choices=['single_agent', 'organization_discussion'], required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--alternate-markup-fraction', required=True)
    parser.add_argument('--max-calls', type=int, default=16)
    parser.add_argument('--with-feedback', action='store_true')
    args = parser.parse_args(argv)
    config = TenderModelDevelopmentSettings(strategy=args.strategy, provider=args.provider, model=args.model,
        alternate_markup_fraction=args.alternate_markup_fraction, max_calls=args.max_calls)
    builder = build_feedback_bundle if args.with_feedback else build_bundle
    result = builder(args.output, run_id=args.run_id, model_options=config.model_dump(mode='json'))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
