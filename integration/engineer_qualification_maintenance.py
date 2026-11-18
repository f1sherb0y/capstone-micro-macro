"""Existing Engineer A12 chooses native monthly knowledge upkeep, not credential issuance."""
from integration.professional_methods_native import ProfessionalMethodsApplication, COMPONENTS
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension


OPERATION = 'maintain_professional_qualifications'
BOUNDARY = ('Background review of professional obligations and regional compliance knowledge only. '
    'No issued, renewed, verified or applied credential is produced. Formal qualifications and private training '
    'history remain unknown. Native capability updates are original random mechanics and not credential evidence.')


class EngineerQualificationMaintenanceApplication(ProfessionalMethodsApplication):
    VERSION = 'engineer-qualification-maintenance.v1'
    PREFIX = 'engineer_qualification_maintenance_request:'
    COMPONENTS = {'Engineer': COMPONENTS['Engineer']}
    OPERATIONS = {'Engineer': OPERATION}
    LABEL = 'Original Engineer background qualification-knowledge upkeep'

    def evidence(self):
        result = super().evidence()
        result['boundary'] = BOUNDARY
        return result


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True:
        raise ValueError('The fixed qualification-upkeep scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app = EngineerQualificationMaintenanceApplication(assembly=assembly,
        settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION, evidence=app.evidence,
        close=app.authority.close, writer_guard=app.read_guard)
