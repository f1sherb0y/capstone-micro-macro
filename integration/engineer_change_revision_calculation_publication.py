"""Atomically publish every original A09 revision parameter and interface check."""
from integration.engineer_design_calculation_publication import _publish_engineer_joint_calculations
from integration.engineer_change_parameter_publication import EngineerChangeParameterPublicationStore
from integration.engineer_change_revision_check_publication import EngineerChangeRevisionCheckPublicationStore
from src.coordination.tasks import TaskConflict


def publish_engineer_change_revision_calculations(*, parameters, checks, parameter_record_sha256s,
        check_record_sha256s, source_context, next_context):
    """Caller holds actual source guard; retain the complete original revise batch.

    Exact A09 revision stores rebuild original issue, obligation, parent/content,
    change basis, task and current authority through independent source gates.
    All records must retain identical original input and source cache, cover
    every reserved task result exactly once, and use one fresh authorized token.
    The shared transaction writes both immutable boundaries together; it executes
    no method, revision registration, issue closure or obligation discharge.
    """
    if (type(parameters) is not EngineerChangeParameterPublicationStore
            or type(checks) is not EngineerChangeRevisionCheckPublicationStore):
        raise TaskConflict('Joint revision publication requires original A09 parameter and revision-check stores')
    return _publish_engineer_joint_calculations(parameters=parameters, checks=checks,
        parameter_record_sha256s=parameter_record_sha256s, check_record_sha256s=check_record_sha256s,
        source_context=source_context, next_context=next_context)
