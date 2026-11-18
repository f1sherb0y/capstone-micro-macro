"""Bind queried actual QS issuance to the existing Owner reception protocols."""
from copy import deepcopy
from dataclasses import replace

from integration.module_host import module_factory_descriptor
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.qs_payment_certificate_submission import QSPaymentCertificateIssuedObservation
from integration.qs_payment_results import SavedQSPayment
from src.coordination.tasks import TaskConflict, task_digest


class _IssuedCertificateOwnerBinding:
    VERSION = 'qs-issued-certificate-owner-sources.v1'

    def __init__(self, sources, read_native_issuance, validate_native_reception):
        self.sources = sources
        self.read_native_issuance = read_native_issuance
        self.validate_native_reception = validate_native_reception
        self.original_callbacks = (read_native_issuance, validate_native_reception)
        self.configuration = self._configuration()

    def _configuration(self):
        return {'schema_version': self.VERSION, 'owner_source_version': self.sources.version,
            'read_native_issuance': module_factory_descriptor(self.read_native_issuance, 'read_native_issuance'),
            'validate_native_reception': module_factory_descriptor(self.validate_native_reception, 'validate_native_reception')}

    def _check(self, context):
        if (context.execution_mode == 'offline_fixture' or self._configuration() != self.configuration
                or self.read_native_issuance is not self.original_callbacks[0]
                or self.validate_native_reception is not self.original_callbacks[1]):
            raise TaskConflict('Actual certificate reception requires unchanged formal source bindings')

    def _observe(self, saved, receipt, context):
        if (not isinstance(saved, SavedQSPayment) or saved.context.execution_mode == 'offline_fixture'
                or saved.audit.get('reading', {}).get('source_mode') != 'formal'
                or saved.identity.action_id != 'QS-A08' or saved.result.kind != 'completed'
                or saved.result.payload.choice not in {'certify', 'correct_certificate'}
                or saved.identity.run_id != context.run_id):
            raise TaskConflict('Actual issuance requires the original completed formal QS certification')
        observed = self.read_native_issuance(context=context.model_copy(deep=True),
            source_task_sha256=saved.identity.key)
        expected = {'schema_version': 'qs-payment-certificate-issued-reception.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256}
        if (not isinstance(observed, dict) or set(observed) != {*expected, 'submission_receipt', 'observation'}
                or any(observed[key] != value for key, value in expected.items())):
            raise TaskConflict('Actual issuance is unknown or belongs to another original QS result')
        observed = deepcopy(observed)
        observation = QSPaymentCertificateIssuedObservation.model_validate(observed['observation'])
        certificate = observation.certificate
        if (certificate != receipt.certificate or receipt.source_task_sha256 != saved.identity.key
                or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != expected['source_result_sha256']
                or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.run_id != context.run_id):
            raise TaskConflict('Owner reception substitutes the actual issued certificate or original QS provenance')
        envelope = observed['submission_receipt']
        correlation = {'run_id': saved.identity.run_id, 'organization_id': saved.identity.organization_id,
            'request_id': saved.identity.request_id, 'task_sha256': task_digest(saved.identity.as_dict()),
            'output_sha256': expected['source_result_sha256']}
        if (not isinstance(envelope, dict)
                or set(envelope) != {*correlation, 'binding_id', 'macro_version', 'receipt_id', 'disposition', 'original_receipt'}
                or any(envelope[key] != value for key, value in correlation.items())
                or envelope['disposition'] != 'accepted'
                or any(not isinstance(envelope[key], str) or not envelope[key].strip()
                    for key in ('binding_id', 'macro_version', 'receipt_id'))
                or not isinstance(envelope['original_receipt'], dict) or not envelope['original_receipt']):
            raise TaskConflict('Actual issuance lacks its correlated accepted native submission receipt')
        native = {'schema_version': 'qs-payment-certificate-native-issuance.v1',
            'receipt_identity': {**correlation, 'binding_id': envelope['binding_id'], 'macro_version': envelope['macro_version']},
            'original_receipt': envelope['original_receipt'], 'source_identity': saved.identity.as_dict(),
            'source_record_sha256': saved.record_sha256, 'source_reading_sha256': saved.source_reading_sha256,
            'statement': saved.result.payload.statement.model_dump(mode='json'),
            'certificate': certificate.model_dump(mode='json'),
            'issuance_history': [row.model_dump(mode='json') for row in observation.issuance_history],
            'coverage': 'complete'}
        evidence = observation.native_evidence
        if (observation.native_payload != native or evidence.source_kind == 'synthetic'
                or evidence.basis_kind != 'observed' or evidence.content_hash != task_digest(native)
                or evidence.ref not in certificate.evidence_refs
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Actual issuance lacks complete observed native evidence bound to its original request')
        history = {row.ref.key(): row for row in observation.issuance_history}
        if (len(history) != len(observation.issuance_history) or history.get(certificate.ref.key()) != certificate
                or certificate.status != 'active'
                or any(row.contract_ref != certificate.contract_ref for row in history.values())
                or len({(row.certificate_key, row.sequence) for row in history.values()}) != len(history)
                or sum(row.status == 'active' and row.certificate_key == certificate.certificate_key
                    for row in history.values()) != 1):
            raise TaskConflict('Actual issuance history repeats or replaces active certificate versions')
        for row in history.values():
            if row.predecessor_ref is not None:
                prior = history.get(row.predecessor_ref.key())
                if (prior is None or prior.status != 'superseded' or prior.certificate_key != row.certificate_key
                        or prior.sequence >= row.sequence):
                    raise TaskConflict('Actual correction history omits its superseded predecessor')
        points = [saved.context.business_time, certificate.authored_at, certificate.available_at,
            receipt.received_at, receipt.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
            raise TaskConflict('Actual issuance changes original decision, reception or availability chronology')
        return observed

    def _validate(self, saved_decisions, receipts, obligations, components, context):
        self._check(context)
        if (not saved_decisions or len(saved_decisions) != len(receipts)
                or len({saved.identity.key for saved in saved_decisions}) != len(saved_decisions)
                or len({receipt.ref.key() for receipt in receipts}) != len(receipts)):
            raise TaskConflict('Actual reception requires unique complete original QS decisions and receipts')
        observations = []
        for saved, receipt in zip(saved_decisions, receipts):
            current = self.sources.read_qs_payment(context=context.model_copy(deep=True),
                source_task_sha256=saved.identity.key)
            if current != saved:
                raise TaskConflict('Actual certificate reception changed the original authorized QS journal result')
            observations.append(self._observe(saved, receipt, context))
        if self.validate_native_reception(observations=deepcopy(observations),
                saved_decisions=deepcopy(saved_decisions), receipts=deepcopy(receipts),
                obligations=deepcopy(obligations), components=deepcopy(components),
                context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Actual receiver did not confirm lawful sharing and complete native Owner financial mapping')
        self._check(context)

    def _recheck_decisions(self, saved_decisions, context):
        for saved in saved_decisions:
            if self.sources.read_qs_payment(context=context.model_copy(deep=True),
                    source_task_sha256=saved.identity.key) != saved:
                raise TaskConflict('Owner reception changed the original authorized QS result during validation')
        self._check(context)

    def validate_reception(self, *, saved, receipt, certificate, obligation, context):
        with self.sources.read_guard(context):
            if certificate != receipt.certificate:
                raise TaskConflict('Owner reception changed the selected issued certificate')
            self._validate([saved], [receipt], [obligation], [], context)
            if self.sources.validate_payment_certificate_reception(saved=deepcopy(saved),
                    receipt=deepcopy(receipt), certificate=deepcopy(certificate), obligation=deepcopy(obligation),
                    context=context.model_copy(deep=True)) is not True:
                raise TaskConflict('Owner rejected original certificate reception or financial history')
            self._recheck_decisions([saved], context)
            return True

    def validate_mapping(self, *, saved_decisions, receipts, obligations, components, context):
        with self.sources.read_guard(context):
            self._validate(saved_decisions, receipts, obligations, components, context)
            if self.sources.validate_payment_certificate_mapping(saved_decisions=deepcopy(saved_decisions),
                    receipts=deepcopy(receipts), obligations=deepcopy(obligations), components=deepcopy(components),
                    context=context.model_copy(deep=True)) is not True:
                raise TaskConflict('Owner rejected original complete certificate allocation or financial history')
            self._recheck_decisions(saved_decisions, context)
            return True

    def evidence(self):
        if self._configuration() != self.configuration:
            raise TaskConflict('Actual certificate source configuration changed')
        return {**deepcopy(self.sources.evidence()), 'actual_certificate_reception': deepcopy(self.configuration)}


def bind_qs_issued_certificate_owner_sources(sources, *, read_native_issuance, validate_native_reception):
    """Decorate existing formal Owner sources without creating certificates or debt.

    read_native_issuance(context, source_task_sha256) must authorize the current
    Owner's access and query the original QSPaymentCertificateSubmission through
    its source guard. Return query_issued_certificate's complete reception or
    None when unknown. No issuance, resubmission or task rerun is allowed here.

    validate_native_reception(observations, saved_decisions, receipts, obligations,
    components, context) checks native authenticity, current lawful sharing and
    the complete receiver registration/financial relation. Single reception
    supplies an empty components list: the receiver must read and validate all
    original components identified by receipt/obligation under its own guard.
    Existing Owner single/group validators remain mandatory. Their original
    certificate_inputs selection and generic financial checks are unchanged.
    """
    if (not isinstance(sources, OwnerRoleContractSources) or not callable(sources.read_qs_payment)
            or not callable(read_native_issuance) or not callable(validate_native_reception)
            or not any(callable(callback) for callback in (sources.validate_payment_certificate_reception,
                sources.validate_payment_certificate_mapping))):
        raise ValueError('Actual certificate binding requires existing Owner reception sources and explicit native reader/validator')
    binding = _IssuedCertificateOwnerBinding(sources, read_native_issuance, validate_native_reception)
    return replace(sources, version=sources.version + '+' + binding.VERSION, evidence=binding.evidence,
        validate_payment_certificate_reception=binding.validate_reception
            if sources.validate_payment_certificate_reception is not None else None,
        validate_payment_certificate_mapping=binding.validate_mapping
            if sources.validate_payment_certificate_mapping is not None else None)
