"""Configure original V5 payment readers on actual Owner/Bank/Contractor sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
import importlib
import json
from pathlib import Path
from typing import Callable, Literal

from integration.bank_arrangement_reader import BankArrangementReader, bind_payment_arrangement_sources
from integration.bank_execution_reader import BankExecutionReader, bind_bank_execution_sources
from integration.bank_execution_reception_reader import (
    BankExecutionReceptionReader, bind_bank_execution_reception_sources,
)
from integration.bank_quote_reader import BankQuoteReader, bind_financing_offer_sources
from integration.bank_role_contract_host import BankRoleContractSources
from integration.contractor_role_contract_host import ContractorRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.owner_draw_request_reader import OwnerDrawRequestReader, bind_owner_draw_request_sources
from integration.owner_financing_application_reader import (
    OwnerFinancingApplicationReader, bind_owner_financing_application_sources,
)
from integration.owner_financing_acceptance_reader import (
    OwnerFinancingAcceptanceReader, bind_owner_financing_acceptance_sources,
)
from integration.owner_payment_execution_reader import OwnerPaymentExecutionReader, bind_contractor_payment_reader
from integration.owner_payment_reconciliation_reader import (
    OwnerPaymentReconciliationReader, bind_own_payment_reconciliation_sources,
)
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.qs_payment_certificate_reader import QSPaymentCertificateReader, bind_payment_certificate_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.implementation import callable_implementation
from src.coordination.tasks import TaskConflict, canonical, task_digest


_SOURCE_VERSION = 'configured-v5-formal-payment-sources.v2'
_ROUTES = {
    'application': (OwnerFinancingApplicationReader, BankRoleContractSources,
        'BANK-A02', bind_owner_financing_application_sources, False),
    'acceptance': (OwnerFinancingAcceptanceReader, BankRoleContractSources,
        'BANK-A05', bind_owner_financing_acceptance_sources, False),
    'certificate': (QSPaymentCertificateReader, OwnerRoleContractSources, 'OWN-A06', bind_payment_certificate_sources, True),
    'offer': (BankQuoteReader, OwnerRoleContractSources, 'OWN-A05', bind_financing_offer_sources, False),
    'arrangement': (BankArrangementReader, OwnerRoleContractSources, 'OWN-A06', bind_payment_arrangement_sources, False),
    'bank_execution': (BankExecutionReader, OwnerRoleContractSources, 'OWN-A06', bind_bank_execution_sources, False),
    'bank_execution_reception': (BankExecutionReceptionReader, BankRoleContractSources,
        'BANK-A07', bind_bank_execution_reception_sources, False),
    'draw_request': (OwnerDrawRequestReader, BankRoleContractSources, 'BANK-A06', bind_owner_draw_request_sources, False),
    'contractor_payment': (OwnerPaymentExecutionReader, ContractorRoleContractSources,
        'CONTRACTOR-A10', bind_contractor_payment_reader, False),
    'own_reconciliation': (OwnerPaymentReconciliationReader, OwnerRoleContractSources,
        'OWN-A06', bind_own_payment_reconciliation_sources, True),
}


class V5PaymentSourceSettings(StrictRecord):
    schema_version: Literal['lifecycle-v5-payment-source-config.v1']
    application_factory: TextId
    application_version: TextId
    application_settings: dict


@dataclass(frozen=True)
class V5PaymentBinding:
    """Explicit original tasks and independent validators for one reception route."""
    kind: Literal['application', 'acceptance', 'certificate', 'offer', 'arrangement', 'bank_execution',
        'bank_execution_reception', 'draw_request', 'contractor_payment', 'own_reconciliation']
    readers: tuple
    validate_reception: Callable | None = None
    validate_mapping: Callable | None = None

    def __post_init__(self):
        route = _ROUTES.get(self.kind)
        if (route is None or not isinstance(self.readers, tuple) or not self.readers
                or any(type(reader) is not route[0] for reader in self.readers)
                or not route[4] and len(self.readers) != 1):
            raise ValueError('V5 binding requires concrete original readers for its declared route')
        callbacks = (self.validate_reception, self.validate_mapping)
        if (any(callback is not None and not callable(callback) for callback in callbacks)
                or self.kind == 'certificate' and all(callback is None for callback in callbacks)
                or self.kind != 'certificate' and (
                    self.validate_reception is None or self.validate_mapping is not None)):
            raise ValueError('V5 binding requires independent validators matching its reception route')


@dataclass(frozen=True)
class V5PaymentApplication:
    """Actual application owns partial cleanup and all borrowed producer resources.

    On successful return sources.close owns every resource. Owner A06 may
    combine certificate, arrangement, bank-execution and own-reconciliation
    routes. Assembly observes no payment, executes no action and calls no model.
    """
    version: str
    sources: OwnerRoleContractSources | BankRoleContractSources | ContractorRoleContractSources
    bindings: tuple[V5PaymentBinding, ...]

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.bindings, tuple) or not self.bindings
                or any(not isinstance(binding, V5PaymentBinding) for binding in self.bindings)):
            raise ValueError('V5 application requires a version and explicit original payment bindings')
        routes = [_ROUTES[binding.kind] for binding in self.bindings]
        if (len({binding.kind for binding in self.bindings}) != len(self.bindings)
                or len({route[2] for route in routes}) != 1
                or any(not isinstance(self.sources, route[1]) for route in routes)):
            raise ValueError('V5 application repeats a route or mixes recipient actions/role sources')


def _binding_evidence(binding):
    return {'kind': binding.kind,
        'readers': [{'reader_type': type(reader).__module__ + ':' + type(reader).__qualname__,
            'settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
            'reader': module_factory_descriptor(reader.read, binding.kind),
            **({'original_payment_reader_configuration': reader.configuration_evidence()}
                if isinstance(reader, OwnerPaymentExecutionReader) else {}),
            **({'original_certificate_reader_configuration': reader.configuration_evidence()}
                if isinstance(reader, QSPaymentCertificateReader) else {}),
            **({'original_bank_reader_configuration': reader.configuration_evidence()}
                if isinstance(reader, BankQuoteReader) else {})} for reader in binding.readers],
        'validators': {name: module_factory_descriptor(callback, name)
            for name, callback in (('reception', binding.validate_reception), ('mapping', binding.validate_mapping))
            if callback is not None},
        'validator_implementations': {name: callable_implementation(callback)
            for name, callback in (('reception', binding.validate_reception), ('mapping', binding.validate_mapping))
            if callback is not None}}


def build_sources(*, request, output_directory, offline, settings):
    """Open one configured actual application and compose only its declared routes."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = V5PaymentSourceSettings.model_validate(settings).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id not in {'OWN-A05', 'OWN-A06', 'BANK-A02', 'BANK-A05', 'BANK-A06', 'BANK-A07', 'CONTRACTOR-A10'}
            or request.execution_path == 'deterministic'):
        raise ValueError('V5 sources require an explicit formal payment reception invocation')
    specification = settings.application_factory
    if specification.count(':') != 1:
        raise ValueError('V5 application factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('V5 application factory requires module:callable syntax')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory) or factory is build_sources:
        raise ValueError('V5 sources require a distinct actual application factory')
    descriptor = module_factory_descriptor(factory, specification)
    factory_implementation = callable_implementation(factory)
    settings_sha256 = task_digest(settings.model_dump(mode='json'))
    application = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(settings.application_settings))
    if not isinstance(application, V5PaymentApplication):
        raise ValueError('V5 application must return V5PaymentApplication and own partial cleanup')
    original_sources, bindings = application.sources, application.bindings
    source_store = original_sources.store
    original_source_version = original_sources.version
    source_components = (source_store, original_sources.registry, original_sources.organizations,
        original_sources.provider, original_sources.read_guard, original_sources.validators,
        original_sources.evidence, original_sources.close)
    components = tuple((binding, binding.readers, binding.validate_reception, binding.validate_mapping)
        for binding in bindings)
    try:
        if (application.version != settings.application_version
                or module_factory_descriptor(factory, specification) != descriptor
                or callable_implementation(factory) != factory_implementation
                or source_store.run_id != request.context.run_id):
            raise TaskConflict('V5 application changes its declared version or original factory')
        bound = original_sources
        for binding in bindings:
            route = _ROUTES[binding.kind]
            if (request.context.contract_ref.id != route[2]
                    or any(reader.settings.recipient_context != request.context for reader in binding.readers)):
                raise TaskConflict('V5 binding changes the requested action or exact current recipient context')
            kwargs = {'sources': bound, 'validate_reception': binding.validate_reception}
            kwargs['readers' if route[4] else 'reader'] = binding.readers if route[4] else binding.readers[0]
            if binding.kind != 'contractor_payment':
                kwargs['version'] = _SOURCE_VERSION
            if binding.kind == 'certificate':
                kwargs['validate_mapping'] = binding.validate_mapping
            bound = route[3](**kwargs)
        declarations = [_binding_evidence(binding) for binding in bindings]
        declaration = {'schema_version': 'lifecycle-v5-application-source.v2',
            'application_version': application.version, 'application_factory': deepcopy(descriptor),
            'application_factory_implementation': deepcopy(factory_implementation),
            'original_source_version': original_source_version,
            'source_settings_sha256': settings_sha256,
            'request_sha256': task_digest(request.model_dump(mode='json')), 'bindings': declarations}
        # Keep a stable key for this actual invocation, not a digest of the
        # configuration being checked: a changed dependency must conflict with
        # the original pin on restart rather than create a second declaration.
        metadata_key = 'v5_payment_source_configuration:' + task_digest({
            'run_id': request.context.run_id, 'actor_id': request.context.actor_id,
            'action_id': request.context.contract_ref.id, 'operation_id': request.context.operation_id,
            'application_factory': specification})
        with source_store._transaction():
            prior = source_store._db.execute('SELECT value FROM metadata WHERE key=?', (metadata_key,)).fetchone()
            if prior is None:
                source_store._db.execute('INSERT INTO metadata VALUES (?,?)', (metadata_key, canonical(declaration)))
            elif json.loads(prior[0]) != declaration:
                raise TaskConflict('V5 original invocation payment dependencies changed; no silent restart migration')

        def check_application():
            if (application.sources is not original_sources or application.bindings is not bindings
                    or application.version != settings.application_version
                    or original_sources.version != original_source_version
                    or task_digest(settings.model_dump(mode='json')) != settings_sha256
                    or module_factory_descriptor(factory, specification) != descriptor
                    or callable_implementation(factory) != factory_implementation):
                raise TaskConflict('V5 actual application components, configuration or factory changed')
            current_sources = (original_sources.store, original_sources.registry, original_sources.organizations,
                original_sources.provider, original_sources.read_guard, original_sources.validators,
                original_sources.evidence, original_sources.close)
            if any(current is not original for current, original in zip(current_sources, source_components)):
                raise TaskConflict('V5 actual application changed original source resources or authorization boundary')
            for binding, readers, reception, mapping in components:
                if (binding.readers is not readers or binding.validate_reception is not reception
                        or binding.validate_mapping is not mapping):
                    raise TaskConflict('V5 payment binding replaced original readers or independent validators')
            if [_binding_evidence(binding) for binding in bindings] != declarations:
                raise TaskConflict('V5 original reader settings or validator declarations changed')
            with source_store._lock:
                saved = source_store._db.execute('SELECT value FROM metadata WHERE key=?', (metadata_key,)).fetchone()
                if saved is None or json.loads(saved[0]) != declaration:
                    raise TaskConflict('V5 original invocation payment dependency evidence is missing or changed')

        check_application()

        def evidence():
            check_application()
            original = bound.evidence()
            if not isinstance(original, dict) or 'v5_application_source' in original:
                raise TaskConflict('V5 sources cannot replace original application provenance')
            check_application()
            return {**deepcopy(original), 'v5_application_source': deepcopy(declaration)}

        return replace(bound, version=_SOURCE_VERSION, evidence=evidence)
    except Exception:
        source_components[-1]()
        raise
