"""Connect actual Supplier A06 task, production and inventory sources to Runner."""
from dataclasses import dataclass, replace

from integration.supplier_planning_handoff import supplier_planning_handoff_schemas
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_execution_objects import (
    SupplierActualInventoryView, SupplierExecutionProfileView, SupplierExecutionTaskView,
    SupplierExternalDeliveryView, SupplierProductionAllocationView,
    SupplierProductionExecutionView, supplier_execution_schemas, validate_supplier_reconciliation_task,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierExecution(PreparedSupplierQuote):
    """Original request/query invocation; execution does not itself change stock."""


class SupplierExecutionActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit provider/model-host setup with A06's actual source schemas.

    The host selects the original production, purchase or reconciliation setup.
    Task release/gates, real materials and reservations, submitted command
    history and actual deliveries remain original processor checks. Neither an
    A05 plan nor an arrived delivery is promoted into usable inventory. Unknown
    execution receipts do not initiate retries or invent production effects.
    """
    SOURCE_SCHEMAS = staticmethod(supplier_planning_handoff_schemas)

    def build(self, context, *, task_ref, available_input_refs, inventory_ref,
            upstream_delivery_refs, prior_execution_refs, execution_setup):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A06':
            raise ValueError('Supply execution assembly requires its original A06 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture execution sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A06')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Supply execution assembly requires its original Supplier Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('available_input_refs', available_input_refs), ('upstream_delivery_refs', upstream_delivery_refs),
            ('prior_execution_refs', prior_execution_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'task_ref': Reference.model_validate(task_ref), 'inventory_ref': Reference.model_validate(inventory_ref),
            'execution_setup': execution_setup})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref.key() != ref.key():
                raise ValueError('Supply execution requires its exact original concrete source version')
            return row

        try:
            task = read(action_input.task_ref, SupplierExecutionTaskView)
            profile = read(task.profile_ref, SupplierExecutionProfileView)
            inventory = read(action_input.inventory_ref, SupplierActualInventoryView)
            if (any(row.organization_id != reading.organization_id for row in (task, profile, inventory))
                    or not scope_covers(context.scope, task.scope) or profile.scope != context.scope
                    or profile.task_ref != task.ref or profile.actor_id != context.actor_id
                    or profile.function_ref != context.function_ref
                    or profile.authority_ref not in context.authorization_refs):
                raise ValueError('Supply execution changes original Supplier, task, scope or profile authority')
            for ref in action_input.available_input_refs:
                allocation = read(ref, SupplierProductionAllocationView)
                if allocation.organization_id != reading.organization_id or allocation.task_ref != task.ref:
                    raise ValueError('Supply resource allocation names another original Supplier or task')
            for ref in action_input.prior_execution_refs:
                execution = read(ref, SupplierProductionExecutionView)
                if action_input.execution_setup.kind == 'reconciliation':
                    original_task = read(execution.task_ref, SupplierExecutionTaskView)
                    validate_supplier_reconciliation_task(original_task, task, execution,
                        run_id=context.run_id, organization_id=reading.organization_id)
                elif execution.task_ref != task.ref:
                    raise ValueError('New production history substitutes another exact task version')
                if (execution.organization_id != reading.organization_id
                        or execution.run_id != context.run_id):
                    raise ValueError('Supply execution history changes original run, Supplier or task')
            for ref in action_input.upstream_delivery_refs:
                read(ref, SupplierExternalDeliveryView)
            # Resolve the explicitly selected setup only. Reconciliation never
            # gains a manufactured current TaskRelease or production method.
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Supply execution requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierExecution(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_planning(self, context, *, planning_worker, planning_identity,
            planning_execution_versions, basis_ref, validate_history, validate_current, **execution_refs):
        """Attach exact saved A05 lineage to the host-selected actual A06 task."""
        from integration.supplier_planning_results import SupplierPlanningResultWorker

        if (not isinstance(planning_worker, SupplierPlanningResultWorker)
                or planning_worker.registry is not self.registry
                or planning_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Planning execution source requires original worker/registry and explicit host checks')
        invocation = self.build(context, **execution_refs)
        setup = invocation.action_input.execution_setup
        handoff = planning_worker.prepare_execution_handoff(planning_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=planning_execution_versions, basis_ref=basis_ref,
            task_ref=invocation.action_input.task_ref,
            release_ref=setup.release_ref if setup.kind == 'production' else None,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation,
            reading_sha256=task_digest(invocation.reading.evidence()))}
