"""Owner ranking of original eligible same-basis bids; equal score groups retained."""
import hashlib
from pathlib import Path

from src.actions.contracts.common import ref_type
from src.methods.qs_bid import BidRankInput, BidRankReport, rank_bids

OWNER_TENDER_METHOD = ref_type('Method')(kind='Method', id='micro.owner.declared_tender_comparison', version='1')


def register_owner_tender_method(registry):
    basis = Path(__file__).with_name('OWNER_TENDER.md')
    registry.register({'method_ref': OWNER_TENDER_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': OWNER_TENDER_METHOD.id + ':input', 'output_schema_id': OWNER_TENDER_METHOD.id + ':report',
        'action_ids': ['OWN-A09'], 'support_domain': ['Original eligible/compliant same-round and same-pricing-basis bids',
            'Explicit positive weights/scales and exact known units; equal score groups preserved'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/OWNER_TENDER.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['No inferred FX, cost, eligibility, qualification, risk, funding or bidder acceptance',
            'Stable order inside equal groups expresses no strict preference; award requires an explicit authorized selection',
            'No contract, reserve, debt, cash or old-round termination effects']}, BidRankInput, BidRankReport, rank_bids)
