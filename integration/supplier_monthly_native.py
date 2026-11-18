"""Original Supplier A01 governs bounded monthly contract seeking."""
from typing import Literal
from integration.professional_monthly_native import ProfessionalMonthlyApplication, ProfessionalMonthlyPlan
from integration.supplier_screening_actions import SupplierScreeningActionAssembler
from integration.supplier_screening_results import SupplierScreeningResultWorker
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension


class SupplierMonthlyPlan(ProfessionalMonthlyPlan):
    role: Literal['Supplier']


class SupplierMonthlyApplication(ProfessionalMonthlyApplication):
    VERSION = 'supplier-monthly-screening.v1'
    PREFIX = 'supplier_monthly_request:'
    PLAN_TYPE = SupplierMonthlyPlan
    INPUT_SCHEMA = 'supplier-monthly-input.v1'
    COMPONENTS = {'Supplier': (SupplierScreeningActionAssembler, SupplierScreeningResultWorker)}
    OPERATIONS = {'Supplier': 'seek_supply_contract'}
    PARTICIPATION_CHOICE = 'respond'
    COMPLETED_CHOICES = {'respond', 'decline'}
    SCOPE_KEY = 'native_supplier_monthly_scope'

    def evidence(self):
        result = super().evidence()
        result['boundary'] = ('Actual bounded monthly contract seeking and own feedback only. Initial inquiry dossier, '
            'products, methods, physical capacities and nonempty existing commitments are independent synthetic '
            'disclosures, not native inquiry receipts. No quote, order, reservation, inventory adjustment, price '
            'publication, logistics or physical reliability improvement is proved.')
        return result


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True:
        raise ValueError('Supplier monthly development requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app = SupplierMonthlyApplication(assembly=assembly, settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION, evidence=app.evidence,
        close=app.authority.close, writer_guard=app.read_guard)
