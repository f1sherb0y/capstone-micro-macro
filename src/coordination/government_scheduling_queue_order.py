"""Rejudge an original FIFO wait without deleting earlier cases or receipt times."""
from src.coordination.tasks import TaskConflict


def government_scheduling_queue_order_history(*, original, current, waited, now):
    histories, selections, earlier_versions = [], [], []
    for version, time, is_current in ((original, original['queue_ref'].as_of, False), (current, now, True)):
        case, queue, profile = (version[field] for field in ('case_ref', 'queue_ref', 'ordering_profile_ref'))
        if profile.choice != 'assign' or profile.priority_basis_ref is not None or version['rule'].ordering != 'fifo':
            raise TaskConflict('Government FIFO recovery changes its original assignment choice or unselected priority')
        if case.status in {'closed', 'withdrawn'} or queue.coverage != 'complete' or queue.as_of != time:
            if is_current:
                return 'waiting', None
            raise TaskConflict('Government FIFO wait lacks its original open case and complete lawful queue')
        entries = sorted(queue.entries, key=lambda row: (row.entered_at.offset, repr(row.case_ref.key())))
        if (len({row.case_ref.key()[:2] for row in entries}) != len(entries)
                or any(row.entered_at.clock_ref != time.clock_ref or row.entered_at.offset > time.offset for row in entries)):
            raise TaskConflict('Government FIFO recovery duplicates cases or changes original receipt clock/time')
        selected = next((row for row in entries if row.case_ref == case.ref), None)
        if selected is None or selected.status not in {'ready', 'assigned'}:
            if is_current:
                return 'waiting', None
            raise TaskConflict('Government FIFO wait lacks its original input-ready selected case')
        earlier = [row.case_ref for row in entries if row.status == 'ready'
            and row.entered_at.offset < selected.entered_at.offset]
        selections.append(selected)
        earlier_versions.append(earlier)
        histories.append(dict(selected_entry=selected.model_dump(mode='json'),
            earlier_case_refs=[ref.model_dump(mode='json') for ref in earlier]))
    if (not earlier_versions[0] or selections[0].status == 'assigned'
            or tuple(waited) != (original['queue_ref'].ref, *earlier_versions[0])):
        raise TaskConflict('Government FIFO wait differs from exact original ordered earlier-case references')
    old_entries = {row.case_ref.key()[:2]: row for row in original['queue_ref'].entries}
    current_entries = {row.case_ref.key()[:2]: row for row in current['queue_ref'].entries}
    if any(old_entries[key].entered_at != current_entries[key].entered_at for key in old_entries.keys() & current_entries.keys()):
        raise TaskConflict('Government FIFO recovery rewrites an existing lawful queue receipt time')
    if earlier_versions[1] and selections[1].status != 'assigned':
        return 'waiting', None
    if selections[1].status == 'assigned' and not current['assignments']:
        return 'waiting', None
    return 'ready', dict(original=histories[0], current=histories[1],
        removed_queue_case_refs=[row.case_ref.model_dump(mode='json') for key, row in old_entries.items()
            if key not in current_entries])
