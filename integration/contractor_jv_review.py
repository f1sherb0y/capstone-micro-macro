"""Reuse original regional monthly transport for distinct JV candidate review."""
from integration.contractor_region_review import ContractorRegionReviewApplication,RegionReviewPlan,bind_sources
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from src.actions.contracts.common import ref_type
from src.actions.contracts.contractor_jv_review import JVPartnerReviewJudgment
from src.coordination.tasks import TaskConflict

BOUNDARY=('Original monthly private JV candidate review for cross-region delivery risk sharing only. '
    'Original A01 qualification, method and nonempty resource/commitment checks remain. Public candidate disclosures, review weights and own effort ratios are independently declared synthetic initial inputs. '
    'Priority = actual native regional friction * private review weight - own review effort ratio; this is not actual risk transfer, mitigation, money or promised capacity. '
    'Counterparty consent, committed partner capacity and formal entry permission stay unknown. No outreach, JV agreement, bid, new reservation, spending or capability improvement is inferred.')


class JVReviewPlan(RegionReviewPlan):
    observation_ref:ref_type('JVPartnerReviewObservation')


def result_judgment(saved):
    if saved['result']['kind']!='completed' or saved['result']['payload']['choice'] not in {'participate','decline'}:
        raise TaskConflict('JV review requires original completed A01 eligibility')
    j=JVPartnerReviewJudgment.model_validate_json(saved['result']['payload']['note'])
    if j.screening_choice!=saved['result']['payload']['choice']:raise TaskConflict('JV review replaces original A01 eligibility')
    return j


class ContractorJVReviewApplication(ContractorRegionReviewApplication):
    VERSION='contractor-monthly-jv-review.v1'
    PREFIX='contractor_jv_review_request:'
    OPERATIONS={'Contractor':'seek_joint_venture_partner'}
    PLAN_TYPE=JVReviewPlan
    INPUT_SCHEMA='contractor-jv-review-input.v1'
    SCOPE_KEY='native_contractor_jv_review_scope'
    LABEL='Original private JV candidate risk-sharing review'
    POLICY_KIND='JVPartnerReviewPolicy'
    RESULT_JUDGMENT=staticmethod(result_judgment)
    BOUNDARY=BOUNDARY


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('JV candidate scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=ContractorJVReviewApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
