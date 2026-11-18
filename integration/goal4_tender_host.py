"""Expose actual native global events alongside the existing tender host evidence."""
from integration.contractor_tender_formation_development import configure_assembly as configure_original
from integration.module_host import GbaModuleHostExtension


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    original = configure_original(assembly=assembly, request=request,
        output_directory=output_directory, offline=offline, configuration=configuration)

    def evidence():
        return {**original.evidence(), 'original_global_events': [
            event.model_dump(mode='json') for event in assembly.engine.events.events]}

    return GbaModuleHostExtension(version='goal4-original-tender-evidence.v1',
        evidence=evidence, close=original.close, writer_guard=original.writer_guard)
