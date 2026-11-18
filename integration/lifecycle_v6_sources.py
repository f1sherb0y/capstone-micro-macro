"""Configure original V6 handover/history readers on actual current Owner sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
import importlib
from pathlib import Path
from typing import Callable, Literal

from integration.contractor_handover_reader import ContractorHandoverReader, bind_contractor_handover_reader_sources
from integration.module_host import module_factory_descriptor
from integration.owner_closeout_feedback_reader import OwnerCloseoutFeedbackReader, bind_closeout_feedback_reader_sources
from integration.owner_role_contract_host import OwnerRoleContractSources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import TaskConflict, task_digest


_SOURCE_VERSION = 'configured-v6-formal-closeout-sources.v1'
_ROUTES = {
    'handover': (ContractorHandoverReader, 'OWN-A12', bind_contractor_handover_reader_sources, 'validate_reception'),
    'continuation': (OwnerCloseoutFeedbackReader, 'OWN-A13', bind_closeout_feedback_reader_sources, 'validate_relation'),
}


class V6CloseoutSourceSettings(StrictRecord):
    schema_version: Literal['lifecycle-v6-closeout-source-config.v1']
    application_factory: TextId
    application_version: TextId
    application_settings: dict


@dataclass(frozen=True)
class V6CloseoutApplication:
    """Application owns partial cleanup and all resources after returning sources.

    The receiver validator independently authenticates actual Owner reception
    for handover or complete lawful current residual-duty mapping for continuation.
    Opening/binding sources executes no action, transport, feedback or model.
    """
    version: str
    sources: OwnerRoleContractSources
    kind: Literal['handover', 'continuation']
    reader: ContractorHandoverReader | OwnerCloseoutFeedbackReader
    validate_reception: Callable

    def __post_init__(self):
        route = _ROUTES.get(self.kind)
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, OwnerRoleContractSources) or route is None
                or type(self.reader) is not route[0] or not callable(self.validate_reception)):
            raise ValueError('V6 application requires actual Owner sources, concrete matching reader and independent validator')


def _reader_evidence(application):
    reader = application.reader
    return {'kind': application.kind, 'reader_type': type(reader).__module__ + ':' + type(reader).__qualname__,
        'settings_sha256': task_digest(reader.settings.model_dump(mode='json')),
        'reader': module_factory_descriptor(reader.read, application.kind),
        'validator': module_factory_descriptor(application.validate_reception, _ROUTES[application.kind][3])}


def build_sources(*, request, output_directory, offline, settings):
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = V6CloseoutSourceSettings.model_validate(settings).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id not in {'OWN-A12', 'OWN-A13'}
            or request.execution_path == 'deterministic'):
        raise ValueError('V6 source factory requires an explicit formal Owner closeout/continuation invocation')
    specification = settings.application_factory
    if specification.count(':') != 1:
        raise ValueError('V6 application factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('V6 application factory requires module:callable syntax')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory) or factory is build_sources:
        raise ValueError('V6 sources require a distinct actual application factory')
    descriptor = module_factory_descriptor(factory, specification)
    settings_sha256 = task_digest(settings.model_dump(mode='json'))
    application = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(settings.application_settings))
    if not isinstance(application, V6CloseoutApplication):
        raise ValueError('V6 application must return V6CloseoutApplication and own partial cleanup')
    original_sources, reader, validator = application.sources, application.reader, application.validate_reception
    route = _ROUTES[application.kind]
    try:
        if (application.version != settings.application_version
                or original_sources.store.run_id != request.context.run_id
                or original_sources.organizations.run_id != request.context.run_id
                or request.context.contract_ref.id != route[1] or reader.settings.recipient_context != request.context
                or module_factory_descriptor(factory, specification) != descriptor):
            raise TaskConflict('V6 application changes declared version, original run, reader route or exact current recipient')
        bound = route[2](sources=original_sources, reader=reader,
            version=_SOURCE_VERSION, **{route[3]: validator})
        reader_declaration = _reader_evidence(application)
        declaration = {'schema_version': 'lifecycle-v6-application-source.v1',
            'application_version': application.version, 'application_factory': deepcopy(descriptor),
            'source_settings_sha256': settings_sha256, 'request_sha256': task_digest(request.model_dump(mode='json')),
            'binding': reader_declaration}

        def check_application():
            if (application.sources is not original_sources or application.reader is not reader
                    or application.validate_reception is not validator or application.version != settings.application_version
                    or application.kind != reader_declaration['kind']
                    or task_digest(settings.model_dump(mode='json')) != settings_sha256
                    or module_factory_descriptor(factory, specification) != descriptor
                    or _reader_evidence(application) != reader_declaration):
                raise TaskConflict('V6 actual application components, reader settings, validator or factory changed')

        def evidence():
            check_application()
            original = bound.evidence()
            if not isinstance(original, dict) or 'v6_application_source' in original:
                raise TaskConflict('V6 sources cannot replace original application provenance')
            check_application()
            return {**deepcopy(original), 'v6_application_source': deepcopy(declaration)}

        return replace(bound, version=_SOURCE_VERSION, evidence=evidence)
    except Exception:
        original_sources.close()
        raise
