"""Configure actual V3 reception sources for the existing Government/Architect hosts."""
from copy import deepcopy
from dataclasses import dataclass, replace
import importlib
from pathlib import Path
from typing import Callable, Literal

from integration.architect_publication_reader import ArchitectPublicationReader, bind_architect_material_sources
from integration.architect_review_opinion_reader import ArchitectReviewOpinionReader, bind_review_opinion_sources
from integration.architect_review_task_reader import ArchitectReviewTaskReader, bind_review_task_sources
from integration.architect_role_contract_host import ArchitectRoleContractSources
from integration.government_role_contract_host import GovernmentRoleContractSources
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import TaskConflict, task_digest


_SOURCE_VERSION = 'configured-v3-formal-reception-sources.v1'
_ROUTES = (
    (ArchitectPublicationReader, GovernmentRoleContractSources, bind_architect_material_sources,
        'validate_reception', 'GOV-A02'),
    (ArchitectReviewTaskReader, ArchitectRoleContractSources, bind_review_task_sources,
        'validate_mapping', 'ARCHITECT-A08'),
    (ArchitectReviewOpinionReader, ArchitectRoleContractSources, bind_review_opinion_sources,
        'validate_mapping', 'ARCHITECT-A08'),
)


def _route(reader):
    # Opinion readers inherit the task-reader checks but have a distinct route.
    for route in _ROUTES:
        if type(reader) is route[0]:
            return route
    raise ValueError('V3 reception requires one of the concrete original publication/task/opinion readers')


class V3ReceptionSourceSettings(StrictRecord):
    schema_version: Literal['lifecycle-v3-reception-source-config.v1']
    application_factory: TextId
    application_version: TextId
    application_settings: dict


@dataclass(frozen=True)
class V3ReceptionApplication:
    """Actual components; sources.close owns all successfully returned resources.

    The application owns partial cleanup before return, including original
    producer resources borrowed by its reader. validate_receiver is independent
    actual material-reception validation or reviewer/author-input mapping,
    according to the concrete route. Factory assembly executes no action/model.
    """
    version: str
    sources: GovernmentRoleContractSources | ArchitectRoleContractSources
    reader: ArchitectPublicationReader | ArchitectReviewTaskReader | ArchitectReviewOpinionReader
    validate_receiver: Callable

    def __post_init__(self):
        route = _route(self.reader)
        if (not isinstance(self.version, str) or not self.version.strip()
                or not isinstance(self.sources, route[1]) or not callable(self.validate_receiver)):
            raise ValueError('V3 application requires matching actual role sources and independent receiver validator')


def build_sources(*, request, output_directory, offline, settings):
    """Open one explicitly configured actual application and bind its original route."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = V3ReceptionSourceSettings.model_validate(settings).model_copy(deep=True)
    if (offline is not False or request.context.execution_mode != 'llm'
            or request.context.contract_ref.id not in {'GOV-A02', 'ARCHITECT-A08'}
            or request.execution_path == 'deterministic'):
        raise ValueError('V3 source factory requires an explicit formal reception invocation')
    specification = settings.application_factory
    if specification.count(':') != 1:
        raise ValueError('V3 application factory requires module:callable syntax')
    module, name = specification.split(':')
    if not module or not name.isidentifier():
        raise ValueError('V3 application factory requires module:callable syntax')
    factory = getattr(importlib.import_module(module), name, None)
    if not callable(factory) or factory is build_sources:
        raise ValueError('V3 sources require a distinct actual application factory')
    descriptor = module_factory_descriptor(factory, specification)
    settings_sha256 = task_digest(settings.model_dump(mode='json'))
    application = factory(request=request.model_copy(deep=True), output_directory=Path(output_directory),
        offline=False, settings=deepcopy(settings.application_settings))
    if not isinstance(application, V3ReceptionApplication):
        raise ValueError('V3 application must return V3ReceptionApplication and own partial cleanup')
    original_sources = application.sources
    components = (original_sources, application.reader, application.validate_receiver)
    try:
        route = _route(application.reader)
        if (application.version != settings.application_version
                or request.context.contract_ref.id != route[4]
                or application.reader.settings.recipient_context != request.context
                or module_factory_descriptor(factory, specification) != descriptor):
            raise TaskConflict('V3 application changes declared version, recipient route or original factory')
        bound = route[2](sources=original_sources, reader=application.reader, version=_SOURCE_VERSION,
            **{route[3]: application.validate_receiver})
        declaration = {'schema_version': 'lifecycle-v3-application-source.v1',
            'application_version': application.version, 'application_factory': deepcopy(descriptor),
            'source_settings_sha256': settings_sha256,
            'request_sha256': task_digest(request.model_dump(mode='json')),
            'reader_type': route[0].__module__ + ':' + route[0].__qualname__}

        def evidence():
            current = (application.sources, application.reader, application.validate_receiver)
            if (any(now is not original for now, original in zip(current, components))
                    or application.version != settings.application_version
                    or task_digest(settings.model_dump(mode='json')) != settings_sha256
                    or module_factory_descriptor(factory, specification) != descriptor):
                raise TaskConflict('V3 actual application components, configuration or factory changed')
            original = bound.evidence()
            if 'v3_application_source' in original:
                raise TaskConflict('V3 source evidence cannot replace original application provenance')
            return {**original, 'v3_application_source': deepcopy(declaration)}

        return replace(bound, evidence=evidence)
    except Exception:
        original_sources.close()
        raise
