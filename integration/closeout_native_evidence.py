"""Read-only global event export around the existing shared closeout host."""
from integration.financing_professional_native import configure_assembly as configure_chain
from integration.module_host import GbaModuleHostExtension
from src.coordination.tasks import TaskConflict


class CloseoutNativeEvidence:
    VERSION='native-closeout-evidence.v1'

    def __init__(self,assembly,base):
        self.assembly,self.base=assembly,base

    def evidence(self):
        with self.base.writer_guard():
            self.assembly._validate_components()
            chain=self.base.evidence()
            events=[e.model_dump(mode='json') for e in self.assembly.engine.events.events]
            if len({e['event_id'] for e in events})!=len(events):
                raise TaskConflict('Original global closeout history has duplicate identities')
            return {'version':self.VERSION,'chain':chain,'original_global_events':events,
                'boundary':'Read-only administrative evidence export; no new observer, command, micro decision or business receipt.'}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    base=configure_chain(assembly=assembly,request=request,output_directory=output_directory,
        offline=offline,configuration=configuration)
    app=CloseoutNativeEvidence(assembly,base)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=base.close,
        writer_guard=base.writer_guard,checkpoint_validator=base.checkpoint_validator)
