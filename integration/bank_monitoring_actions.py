"""Prepare original BANK-A08 from supplied covenant, report and notice sources."""
from dataclasses import dataclass

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_monitoring_objects import (
    BankMonitoringArrangementView, BankMonitoringCovenantView, BankMonitoringNoticeView,
    BankMonitoringProfileView, BankMonitoringReportView, bank_monitoring_schemas,
)
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs


def validate_monitoring_selection(action_input, *, organization_id, resolve):
    """Check source identities without treating risk estimates as contractual facts."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Monitoring selection changes an original typed source reference')
        return row

    arrangement = read(action_input.arrangement_ref, BankMonitoringArrangementView)
    profile = read(action_input.monitoring_profile_ref, BankMonitoringProfileView)
    if (arrangement.lender_id != organization_id or profile.organization_id != organization_id
            or profile.arrangement_ref.key() != arrangement.ref.key()):
        raise ValueError('Monitoring selection changes original bank, facility or profile')
    for refs, schema in ((action_input.covenant_refs, BankMonitoringCovenantView),
            (action_input.disclosure_refs, BankMonitoringReportView),
            (action_input.notice_refs, BankMonitoringNoticeView)):
        for ref in refs:
            row = read(ref, schema)
            if row.arrangement_ref.key() != arrangement.ref.key():
                raise ValueError('Monitoring selection changes the original covenant, report or notice facility')
            if isinstance(row, BankMonitoringNoticeView) and (
                    row.lender_id != organization_id or row.borrower_id != arrangement.borrower_id):
                raise ValueError('Monitoring notice changes the original lender or borrower')
    # Keep historical covenant/terms versions, missing-report continuation and
    # incomplete-history/notice queries intact. The original processor owns
    # independent fact verification, contractual gates and remedy deadlines.


@dataclass(frozen=True)
class PreparedBankMonitoring(PreparedBankIntake):
    """A local monitoring decision, without issuing notices or enforcing restrictions."""


class BankMonitoringActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A08'
    SOURCE_SCHEMAS = staticmethod(bank_monitoring_schemas)

    def build(self, context, *, arrangement_ref, disclosure_refs, covenant_refs, notice_refs, monitoring_profile_ref):
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in
            (('disclosure_refs', disclosure_refs), ('covenant_refs', covenant_refs), ('notice_refs', notice_refs))}
        for refs in selected.values():
            unique_refs(refs)
        return self._prepare_supplied_snapshot(context, input_values={**selected,
            'arrangement_ref': Reference.model_validate(arrangement_ref),
            'monitoring_profile_ref': Reference.model_validate(monitoring_profile_ref)},
            prepared_type=PreparedBankMonitoring, validate_sources=validate_monitoring_selection)
