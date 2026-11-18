"""Bind formal V2 readers to application-owned role sources without executing them."""
from copy import deepcopy
from dataclasses import dataclass, replace
import importlib
from pathlib import Path
from typing import Callable, Literal

from integration.contractor_bid_publication_reader import ContractorBidPublicationReader
from integration.contractor_role_contract_host import ContractorRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.owner_award_publication_reader import OwnerAwardPublicationReader
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.owner_tender_evaluation_reader import OwnerTenderEvaluationReader
from integration.owner_tender_publication_reader import OwnerTenderPublicationReader
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import TaskConflict, task_digest


_ROUTES = (
    (OwnerTenderPublicationReader, ContractorRoleContractSources, 'Contractor',
        'read_owner_tender', 'validate_received_tender', False),
    (ContractorBidPublicationReader, OwnerRoleContractSources, 'Owner',
        'read_contractor_bid', 'validate_contractor_bid_reception', False),
    (OwnerTenderEvaluationReader, OwnerRoleContractSources, 'Owner',
        'read_tender_evaluation', 'validate_tender_award_selection', True),
    (OwnerAwardPublicationReader, ContractorRoleContractSources, 'Contractor',
        'read_owner_award', 'validate_received_award', False),
)

_SOURCE_VERSION = 'configured-v2-formal-reception-sources.v1'


class V2ReceptionSourceSettings(StrictRecord):
    schema_version: Literal['lifecycle-v2-reception-source-config.v1']
    application_factory: TextId
    application_version: TextId
    application_settings: dict


@dataclass(frozen=True)
class V2ReceptionApplication:
    """Application supplies actual components and owns all partial resources.

    On successful return, sources.close owns factory-opened resources, including
    any producer resources the application owns. Readers themselves borrow them.
    """
    version: str
    sources: OwnerRoleContractSources | ContractorRoleContractSources
    reader: object
    validate_reception: Callable

    def __post_init__(self):
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, (OwnerRoleContractSources, ContractorRoleContractSources))
                or not any(isinstance(self.reader, route[0]) for route in _ROUTES)
                or not callable(self.validate_reception)):
            raise ValueError('V2 application requires actual role sources, concrete reader and reception validator')


def bind_v2_reception_sources(*, sources, reader, validate_reception, version):
    """Complete one source factory's explicit reception wiring.

    Pass a reader built from original producer components and a distinct actual
    native reception/mapping validator. The returned sources retain application
    resources, guards, cleanup and other callbacks; no application is opened,
    no model is created and no decision, registration or receipt is generated.
    Declare the returned version in the receiver host's source configuration.
    """
    routes = [route for route in _ROUTES if isinstance(reader, route[0])]
    if len(routes) != 1 or not callable(validate_reception) or not isinstance(version, str) or not version.strip():
        raise ValueError('V2 source binding requires one concrete reader, receiver validator and explicit version')
    reader_type, source_type, role, reader_field, validator_field, same_owner = routes[0]
    if not isinstance(sources, source_type):
        raise ValueError('V2 reception source role differs from the original reader route')
    if getattr(sources, reader_field) is not None or getattr(sources, validator_field) is not None:
        raise TaskConflict('V2 reception binding cannot replace an existing application reader or validator')
    recipient = reader.settings.recipient_context.model_copy(deep=True)
    source_settings_sha256 = task_digest(reader.settings.model_dump(mode='json'))
    receiver_org = None

    def check_binding():
        reader._check()
        if (task_digest(reader.settings.model_dump(mode='json')) != source_settings_sha256
                or reader.settings.recipient_context != recipient
                or sources.store.run_id != recipient.run_id or sources.organizations.run_id != recipient.run_id):
            raise TaskConflict('V2 reception binding changed its original current recipient or producer settings')
        registration = sources.registry.get(recipient.contract_ref.id)
        grants = sources.organizations.grants(recipient, recipient.contract_ref.id, role)
        current_org = grants[0].organization_id
        if (registration.role != role or not registration.implemented or registration.skill is None
                or (current_org == reader.settings.identity.organization_id) != same_owner
                or receiver_org is not None and current_org != receiver_org):
            raise TaskConflict('V2 reception binding changes current recipient authority or legal party relation')
        return current_org

    receiver_org = check_binding()
    declaration = {'schema_version': 'lifecycle-v2-source-binding.v1',
        'run_id': recipient.run_id, 'recipient_organization_id': receiver_org,
        'recipient_context_sha256': task_digest(recipient.model_dump(mode='json')),
        'reader_field': reader_field, 'validator_field': validator_field,
        'reader_type': reader_type.__module__ + ':' + reader_type.__qualname__,
        'reader_settings_sha256': source_settings_sha256,
        'reader': module_factory_descriptor(reader.read, reader_field),
        'receiver_validator': module_factory_descriptor(validate_reception, validator_field),
        'bound_source_version': version}

    def evidence():
        check_binding()
        original = sources.evidence()
        if not isinstance(original, dict) or 'v2_reception_binding' in original:
            raise TaskConflict('V2 source evidence requires original application evidence without binding collision')
        check_binding()
        return {**deepcopy(original), 'v2_reception_binding': deepcopy(declaration)}

    return replace(sources, version=version, evidence=evidence,
        **{reader_field: reader.read, validator_field: validate_reception})


def build_sources(*, request, output_directory, offline, settings):
    """Invoke an explicitly configured application once; produce no fixture facts."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = V2ReceptionSourceSettings.model_validate(settings).model_copy(deep=True)
    if offline is not False or request.context.execution_mode != 'llm':
        raise ValueError('Formal V2 application source factory requires an explicit formal role invocation')
    specification = settings.application_factory
    if specification.count(':') != 1:
        raise ValueError('V2 application factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('V2 application factory requires module:callable syntax')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory) or factory is build_sources:
        raise ValueError('V2 source factory requires a distinct callable actual application factory')
    descriptor = module_factory_descriptor(factory, specification)
    settings_sha256 = task_digest(settings.model_dump(mode='json'))
    application = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(settings.application_settings))
    if not isinstance(application, V2ReceptionApplication):
        raise ValueError('V2 application factory must return V2ReceptionApplication and own partial cleanup')
    try:
        if (application.version != settings.application_version
                or application.reader.settings.recipient_context != request.context
                or module_factory_descriptor(factory, specification) != descriptor):
            raise TaskConflict('V2 application changes declared version, recipient or original factory')
        bound = bind_v2_reception_sources(sources=application.sources, reader=application.reader,
            validate_reception=application.validate_reception, version=_SOURCE_VERSION)
        declaration = {'schema_version': 'lifecycle-v2-application-source.v1',
            'application_version': application.version, 'application_factory': deepcopy(descriptor),
            'source_settings_sha256': settings_sha256,
            'request_sha256': task_digest(request.model_dump(mode='json'))}

        def evidence():
            if (application.version != settings.application_version
                    or task_digest(settings.model_dump(mode='json')) != settings_sha256
                    or module_factory_descriptor(factory, specification) != descriptor):
                raise TaskConflict('V2 actual application source configuration or code changed')
            original = bound.evidence()
            if 'v2_application_source' in original:
                raise TaskConflict('V2 application source evidence cannot replace existing application provenance')
            return {**original, 'v2_application_source': deepcopy(declaration)}

        return replace(bound, evidence=evidence)
    except Exception:
        application.sources.close()
        raise
