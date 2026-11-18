"""Formal QS certificate submission and independent actual issuance observation."""
from copy import deepcopy
from fractions import Fraction
from typing import Annotated, Callable, Literal

from pydantic import Field

from integration.qs_submission import QSResultSubmission, QSSubmissionCallbacks
from src.actions.contracts.common import EvidenceRecord, StrictRecord, TimePoint
from src.actions.contracts.qs_payment_objects import QSPaymentCertificateView, QSPaymentCorrectionView, QSPaymentCertificationView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


class QSPaymentCertificateIssuedObservation(StrictRecord):
    schema_version: Literal['qs-payment-certificate-issued-observation.v1']
    certificate: QSPaymentCertificateView
    issuance_history: Annotated[list[QSPaymentCertificateView], Field(min_length=1)]
    coverage: Literal['complete']
    native_payload: dict
    native_evidence: EvidenceRecord


class QSPaymentCertificateSubmission(QSResultSubmission):
    """Issue/correct through supplied actual endpoints, then separately observe issuance.

    The original boundary keeps formal sources, current submit/read permissions,
    commit-before-transport and unknown-query recovery. read_native_issuance is
    the actual application's independent native observation/authenticity gate;
    it may return None while issuance is unknown. Registration receipts and
    actual signed certificates remain separate evidence.
    """
    VERSION = 'qs-payment-certificate-submission.v2'

    def __init__(self, *, worker, binding_id, binding_version, macro_version,
            callbacks: QSSubmissionCallbacks, read_native_issuance: Callable):
        if not callable(read_native_issuance) or callbacks.query is None:
            raise ValueError('Certificate submission requires actual read-only query and independent issuance observation')
        self.read_native_issuance = read_native_issuance
        self._original_native_reader = read_native_issuance
        super().__init__(worker=worker, action_id='QS-A08', binding_id=binding_id,
            binding_version=binding_version, macro_version=macro_version,
            supported_choices=['certify', 'correct_certificate'], callbacks=callbacks)

    def _configuration(self):
        from integration.module_host import module_factory_descriptor
        return {**super()._configuration(), 'native_issuance_reader': module_factory_descriptor(
            self.read_native_issuance, 'read_native_issuance')}

    def _check_binding(self):
        if self.read_native_issuance is not self._original_native_reader:
            raise TaskConflict('Certificate submission substituted its original independent native observer')
        super()._check_binding()

    def query_issued_certificate(self, identity):
        """Query original native identity; never issue again or rerun the QS task.

        Caller holds the actual source/authorization guard, as with the original
        QS submission host. An accepted request need not have an issued document.
        This observation does not replace the original saved registration receipt.
        """
        request, record, snapshot, row = self._original(identity)
        if row['submission'] is None:
            raise TaskConflict('Certificate issuance query requires the original submitted request')
        raw = self._query(request)
        if raw is None:
            return None
        receipt = self._submission._receipt(request, deepcopy(raw))
        self._submission._check_receipt_observation(request, receipt)
        if receipt['disposition'] != 'accepted':
            return None
        observed = self.read_native_issuance(request=deepcopy(request), record=deepcopy(record),
            snapshot=deepcopy(snapshot), receipt=deepcopy(receipt))
        if observed is None:
            return None
        observation = QSPaymentCertificateIssuedObservation.model_validate(observed).model_copy(deep=True)
        certificate = observation.certificate
        payload = record['result']['payload']
        statement = payload['statement']
        correction = payload['choice'] == 'correct_certificate'
        basis_ref = payload['correction_basis_ref' if correction else 'certification_basis_ref']
        originals = {task_digest(item['ref']): item['projection'] for item in record['source_reading']}
        basis_type = QSPaymentCorrectionView if correction else QSPaymentCertificationView
        basis = basis_type.model_validate(originals[task_digest(basis_ref)])
        report = originals[task_digest(statement['calculation_ref'])]['report']
        original_time = TimePoint.model_validate(snapshot['context']['business_time'])
        if (certificate.authored_at.clock_ref != original_time.clock_ref
                or certificate.available_at.clock_ref != original_time.clock_ref
                or certificate.authored_at.offset < original_time.offset
                or certificate.available_at.offset < certificate.authored_at.offset
                or not certificate.effective_window.contains(certificate.authored_at)
                or not basis.effective_window.contains(certificate.authored_at)):
            raise TaskConflict('Native issuance changes original certification or document availability chronology')
        if (certificate.status != 'active' or certificate.contract_ref.model_dump(mode='json') != statement['contract_ref']
                or certificate.application_ref.model_dump(mode='json') != statement['source_application_ref']
                or certificate.calculation_ref.model_dump(mode='json') != statement['calculation_ref']
                or certificate.scope.model_dump(mode='json') != statement['covered_scope']
                or certificate.certificate_key != basis.certificate_key or certificate.certification_authority_ref != basis.authority_ref
                or certificate.author_actor_id != snapshot['context']['actor_id']
                or certificate.author_function_ref.model_dump(mode='json') != snapshot['context']['function_ref']
                or certificate.author_action_id != 'QS-A08'
                or certificate.author_authority_ref.model_dump(mode='json') not in snapshot['context']['authorization_refs']
                or not scope_covers(basis.scope, certificate.scope)
                or basis.statement_sha256 != task_digest(statement)
                or correction and certificate.predecessor_ref != basis.prior_certificate_ref
                or not correction and certificate.predecessor_ref is not None):
            raise TaskConflict('Actual issued certificate changes original verified statement, independent power or correction identity')
        for money, expected in ((certificate.assessed_contribution, report['assessed_period_delta']),
                (certificate.net_contribution, report['net_period_delta']),
                (certificate.retention_contribution, report['retention_period_delta'])):
            if 'state' in expected:
                if expected['state'] != 'known':
                    raise TaskConflict('Actual certificate requires original known signed contribution')
                expected = expected['value']
            if money.currency != expected['currency'] or Fraction(money.value) != Fraction(expected['value']):
                raise TaskConflict('Actual certificate changes original assessed, net or retained contribution')
        history = {item.ref.key(): item for item in observation.issuance_history}
        if (len(history) != len(observation.issuance_history) or history.get(certificate.ref.key()) != certificate
                or any(item.contract_ref != certificate.contract_ref for item in history.values())
                or len({(item.certificate_key, item.sequence) for item in history.values()}) != len(history)
                or sum(item.status == 'active' and item.certificate_key == certificate.certificate_key
                    for item in history.values()) != 1):
            raise TaskConflict('Actual complete issuance history repeats or replaces signed certificate versions')
        for item in history.values():
            if item.predecessor_ref is not None:
                prior = history.get(item.predecessor_ref.key())
                if (prior is None or prior.status != 'superseded' or prior.certificate_key != item.certificate_key
                        or prior.sequence >= item.sequence):
                    raise TaskConflict('Actual certificate correction omits its original superseded predecessor')
        native = {'schema_version': 'qs-payment-certificate-native-issuance.v1',
            'receipt_identity': request.receipt_identity(), 'original_receipt': deepcopy(receipt['original_receipt']),
            'source_identity': request.identity.as_dict(), 'source_record_sha256': record['record_sha256'],
            'source_reading_sha256': record['source_reading_sha256'], 'statement': deepcopy(statement),
            'certificate': certificate.model_dump(mode='json'),
            'issuance_history': [item.model_dump(mode='json') for item in observation.issuance_history], 'coverage': 'complete'}
        if (task_digest(observation.native_payload) != task_digest(native) or observation.native_evidence.source_kind == 'synthetic'
                or observation.native_evidence.basis_kind != 'observed'
                or observation.native_evidence.content_hash != task_digest(native)
                or observation.native_evidence.ref not in certificate.evidence_refs):
            raise TaskConflict('Certificate issuance lacks authentic complete native observation correlated with original submission')
        self._check_request(request)
        if self.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Certificate receipt-read authority changed while observing actual issuance')
        self._submission._check_receipt_observation(request, receipt)
        return {'schema_version': 'qs-payment-certificate-issued-reception.v1',
            'source_identity': request.identity.as_dict(), 'source_record_sha256': record['record_sha256'],
            'source_result_sha256': request.output_sha256, 'source_reading_sha256': record['source_reading_sha256'],
            'submission_receipt': deepcopy(receipt), 'observation': observation.model_dump(mode='json')}
