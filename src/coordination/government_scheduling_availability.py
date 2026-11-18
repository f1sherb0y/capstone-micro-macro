"""Authenticate original reviewer availability gaps without creating occupancy."""
from src.actions.contracts.common import Known
from src.actions.contracts.government_scheduling_objects import GovReviewResourceView
from src.coordination.tasks import TaskConflict


def government_scheduling_availability_history(*, original, current, task_key, waited, now, read):
    old_task, task = original['tasks'][task_key], current['tasks'][task_key]
    old_calendar, calendar = original['capacity_ref'], current['capacity_ref']
    if (waited[1] != old_calendar.ref or old_task.status != 'authorized'
            or old_calendar.coverage != 'complete' or old_calendar.as_of != old_task.as_of):
        raise TaskConflict('Government availability wait replaces its original task or complete calendar')

    def covers(validity, planned):
        return (validity.bounds == planned.bounds == 'closed_open'
            and validity.start.clock_ref == planned.start.clock_ref
            and planned.end.offset > planned.start.offset
            and validity.start.offset <= planned.start.offset and validity.end.offset >= planned.end.offset)

    def index(calendar):
        refs = {row.ref.key(): row for row in calendar.resources}
        if (len(refs) != len(calendar.resources)
                or len({row.ref.key()[:2] for row in calendar.resources}) != len(calendar.resources)):
            raise TaskConflict('Government availability calendar repeats physical reviewer resources')
        return refs

    old_region, region = original['case_ref'].region_id, current['case_ref'].region_id
    if not isinstance(old_region, Known):
        raise TaskConflict('Government availability wait lacks its original known agency region')
    old_resources, resources = index(old_calendar), index(calendar)
    original_rows, current_rows, gaps = [], [], []
    for share in old_task.resource_shares:
        embedded = old_resources.get(share.resource_ref.key())
        if embedded is None:
            gaps.append(share.resource_ref.model_dump(mode='json'))
            continue
        resource = read(share.resource_ref, GovReviewResourceView)
        if resource != embedded or resource.organization_id != old_task.organization_id:
            raise TaskConflict('Government availability recovery replaces original reviewer projection')
        original_rows.append(resource.model_dump(mode='json'))
        if resource.region_id != old_region.value or not covers(resource.effective_window, old_task.planned_window):
            gaps.append(resource.ref.model_dump(mode='json'))
    if not gaps:
        raise TaskConflict('Government availability recovery does not match an original unavailable reviewer')
    if calendar.coverage != 'complete' or calendar.as_of != now or not isinstance(region, Known):
        return 'waiting', None
    planned = task.planned_window
    duration = planned.end.offset - planned.start.offset
    if (planned.bounds != 'closed_open' or planned.start.clock_ref != now.clock_ref
            or duration <= 0 or planned.start.offset < now.offset
            or duration > current['work'].maximum_assignment_ticks):
        return 'waiting', None
    people = set()
    for share in task.resource_shares:
        embedded = resources.get(share.resource_ref.key())
        if embedded is None:
            return 'waiting', None
        resource = read(share.resource_ref, GovReviewResourceView)
        if resource != embedded or resource.organization_id != task.organization_id:
            raise TaskConflict('Government availability recovery substitutes current reviewer projection')
        if (resource.available_at.clock_ref != now.clock_ref or resource.available_at.offset > now.offset
                or resource.region_id != region.value or not covers(resource.effective_window, planned)
                or not isinstance(resource.personnel_ids, Known) or not resource.personnel_ids.value):
            return 'waiting', None
        persons = resource.personnel_ids.value
        if len(set(persons)) != len(persons) or people.intersection(persons):
            raise TaskConflict('Government availability recovery duplicates actual reviewer personnel')
        people.update(persons)
        current_rows.append(resource.model_dump(mode='json'))
    return 'ready', dict(original_resources=original_rows, resources=current_rows,
        original_unavailable_resource_refs=gaps)
