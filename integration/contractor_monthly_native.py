"""Reuse the existing monthly transport with original Contractor A01 screening."""
from typing import Literal
from integration.professional_monthly_native import ProfessionalMonthlyApplication,ProfessionalMonthlyPlan
from integration.contractor_screening_actions import ContractorScreeningActionAssembler
from integration.contractor_screening_results import ContractorScreeningResultWorker
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension


class ContractorMonthlyPlan(ProfessionalMonthlyPlan):
    role: Literal['Contractor']


class ContractorMonthlyApplication(ProfessionalMonthlyApplication):
    VERSION='contractor-monthly-screening.v1'
    PREFIX='contractor_monthly_request:'
    PLAN_TYPE=ContractorMonthlyPlan
    INPUT_SCHEMA='contractor-monthly-input.v1'
    COMPONENTS={'Contractor':(ContractorScreeningActionAssembler,ContractorScreeningResultWorker)}
    OPERATIONS={'Contractor':'scan_tender_opportunities'}
    PARTICIPATION_CHOICE='participate'
    COMPLETED_CHOICES={'participate','decline'}
    SCOPE_KEY='native_contractor_monthly_scope'

    def evidence(self):
        result=super().evidence()
        result['boundary']='Actual bounded monthly public tender screening only. Initial qualifications, physical capacities, existing commitments and public dossier are independent synthetic disclosures, not macro score-derived physical facts. No bid submission, quote, award, invitation publication, new resource commitment or formal strategy/region/partner/relationship execution.'
        return result


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Contractor monthly development requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=ContractorMonthlyApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
