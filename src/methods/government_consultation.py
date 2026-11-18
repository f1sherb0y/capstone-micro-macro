"""Procedure coverage is independent of the opinions expressed."""
import hashlib
from pathlib import Path
from typing import Literal

from src.actions.contracts.common import Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs

CONSULTATION_METHOD = ref_type('Method')(kind='Method', id='micro.government.consultation_coverage', version='1')


class ConsultationChannel(StrictRecord):
    channel_key: TextId
    required: bool
    delivered: ValueState[bool]
    response_event_ids: list[TextId]
    public_channel: bool
    participation_verified: ValueState[bool]


class ConsultationCoverageInput(StrictRecord):
    applicable: ValueState[bool]
    channels: list[ConsultationChannel]
    source_refs: list[Reference]


class ConsultationCoverageReport(StrictRecord):
    finding: Literal['conforms', 'unknown', 'not_applicable']
    pending_channel_keys: list[TextId]
    response_event_ids: list[TextId]


def check_coverage(data):
    unique_refs(data.source_refs)
    if len({row.channel_key for row in data.channels}) != len(data.channels):
        raise ValueError('Consultation channels repeat original identity')
    events = [event for row in data.channels for event in row.response_event_ids]
    if len(set(events)) != len(events):
        raise ValueError('One response event cannot complete multiple channels')
    if data.applicable.state != 'known':
        return ConsultationCoverageReport(finding='unknown', pending_channel_keys=[r.channel_key for r in data.channels if r.required], response_event_ids=events)
    if not data.applicable.value:
        return ConsultationCoverageReport(finding='not_applicable', pending_channel_keys=[], response_event_ids=events)
    pending = [row.channel_key for row in data.channels if row.required and (
        row.delivered.state != 'known' or not row.delivered.value or not row.response_event_ids
        or (row.public_channel and (row.participation_verified.state != 'known' or not row.participation_verified.value)))]
    return ConsultationCoverageReport(finding='unknown' if pending or not data.channels else 'conforms',
        pending_channel_keys=pending, response_event_ids=events)


def register_government_consultation_method(registry):
    basis = Path(__file__).with_name('GOVERNMENT_CONSULTATION.md')
    registry.register({'method_ref': CONSULTATION_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': 'micro-gov-consultation.v1:input', 'output_schema_id': 'micro-gov-consultation.v1:report',
        'action_ids': ['GOV-A05'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Original required consultation channels, actual deliveries and distinct received opinion events',
            'Public participation independently verified; missing reply or coverage stays unknown', 'Original explicit applicability basis'],
        'basis_locator': 'src/methods/GOVERNMENT_CONSULTATION.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only', 'limitations': ['Procedure coverage only; no unanimity, veto, approval or substantive finding inferred',
            'No silence consequence, channel creation, disclosure, notification or business effect',
            'Actual response provenance and public participation require independent host evidence']},
        ConsultationCoverageInput, ConsultationCoverageReport, check_coverage)
