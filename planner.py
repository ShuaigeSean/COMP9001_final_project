"""Earliest-deadline-first study planning and deadline risk calculation."""

from datetime import date, timedelta


def week_start(day):
    """Return the Monday of the week containing day."""
    return day - timedelta(days=day.weekday())


def available_minutes(data, day):
    """Use the dated week's daily capacity, or zero when unset."""
    return data["week_capacity"].get(week_start(day).isoformat(), [0] * 7)[day.weekday()]


def actual_minutes_on(data, day):
    """Count all recorded work, including activities outside course tasks."""
    return sum(entry.actual_minutes for entry in data["study_log"]
               if entry.date == day.isoformat())


def remaining_capacity(data, day):
    """Actual work already done consumes that day's study budget."""
    return max(0, available_minutes(data, day) - actual_minutes_on(data, day))


def _ordered(tasks):
    """Break equal deadlines by larger remaining work, then stable task ID."""
    return sorted(tasks, key=lambda task: (task.due, -task.remaining_minutes, task.id))


def _allocate(tasks, capacity, remaining):
    """Fill one day's capacity and return (task ID, allocated minutes) pairs."""
    allocations = []
    for task in tasks:
        minutes = min(capacity, remaining[task.id])
        if minutes:
            allocations.append((task.id, minutes))
            remaining[task.id] -= minutes
            capacity -= minutes
        if capacity == 0:
            break
    return allocations, capacity


def generate_plan(data, start, days, earliest_day=None):
    """Schedule remaining work and check deadlines within the display window.

    Deadline day is usable. Active tasks take priority over overdue catch-up.
    Plans never change the Task objects or saved progress.
    """
    if not isinstance(start, date) or type(days) is not int or days < 1 or days > 366:
        raise ValueError("Plan needs a start date and 1 to 366 days.")
    if earliest_day is None:
        earliest_day = start
    if not isinstance(earliest_day, date):
        raise ValueError("Earliest planning day must be a date.")
    try:
        end = start + timedelta(days=days - 1)
    except OverflowError as exc:
        raise ValueError("The plan extends beyond the supported date range.") from exc
    if not start <= earliest_day <= end:
        raise ValueError("The first planning day must be inside the plan window.")
    tasks = [task for task in data["tasks"] if not task.complete]
    active = _ordered([task for task in tasks if task.due >= earliest_day.isoformat()])
    overdue = _ordered([task for task in tasks if task.due < earliest_day.isoformat()])

    display_remaining = {task.id: task.remaining_minutes for task in tasks}
    schedule = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        capacity = available_minutes(data, day)
        actual = actual_minutes_on(data, day)
        free_time = remaining_capacity(data, day)
        if day < earliest_day:
            schedule.append({"date": day.isoformat(), "capacity": capacity,
                             "actual": actual, "remaining_capacity": free_time,
                             "allocations": [], "unused": free_time, "past": True})
            continue
        eligible = [task for task in active if task.due >= day.isoformat()]
        allocations, free = _allocate(eligible, free_time, display_remaining)
        late_allocations, unused = _allocate(overdue, free, display_remaining)
        schedule.append({"date": day.isoformat(), "capacity": capacity,
                         "actual": actual, "remaining_capacity": free_time,
                         "allocations": [(task_id, minutes, False) for task_id, minutes in allocations]
                         + [(task_id, minutes, True) for task_id, minutes in late_allocations],
                         "unused": unused, "past": False})

    status = []
    for task in _ordered(tasks):
        status.append({"task_id": task.id,
                       "overdue": task.due < earliest_day.isoformat(),
                       "window_unallocated": display_remaining[task.id],
                       "deadline_shortfall": None if task in overdue or
                       task.due > schedule[-1]["date"] else display_remaining[task.id]})
    return {"start": start.isoformat(), "days": days,
            "schedule": schedule, "status": status}


def expected_minutes_for_task(data, day, task_id):
    """Use a saved daily baseline, never reconstruct a past plan from progress.

    A date/task budget is attached to its first log only; later sessions get
    only any unclaimed budget, so splitting a session cannot multiply Expected.
    """
    draft = data["plan_drafts"].get(week_start(day).isoformat(), {})
    planned = draft.get("allocations", {}).get(day.isoformat(), {}).get(str(task_id), 0)
    already_logged = sum(entry.expected_minutes for entry in data["study_log"]
                         if entry.date == day.isoformat() and entry.task_id == task_id)
    return max(0, planned - already_logged)


def planned_minutes_on(data, day):
    """Include planned work even when the user never recorded an activity."""
    draft = data["plan_drafts"].get(week_start(day).isoformat(), {})
    allocations = draft.get("allocations", {}).get(day.isoformat())
    if allocations is not None:
        return sum(allocations.values())
    # Legacy logs preserve their original expected values, but missing plans
    # cannot be reconstructed accurately.
    return sum(entry.expected_minutes for entry in data["study_log"]
               if entry.date == day.isoformat())


def save_plan_snapshot(data, plan):
    """Save text and daily allocations without changing actual task progress.

    Replanning can change unlogged future dates. Past dates and dates already
    logged keep their baseline so later work cannot rewrite the comparison.
    """
    key = week_start(date.fromisoformat(plan["start"])).isoformat()
    previous = data["plan_drafts"].get(key, {})
    baselines = {day: dict(tasks) for day, tasks in previous.get("allocations", {}).items()}
    logged_dates = {entry.date for entry in data["study_log"]}
    for day in plan["schedule"]:
        day_text = day["date"]
        if day["past"] or day_text in logged_dates:
            continue
        baselines[day_text] = {str(task_id): minutes for task_id, minutes, _ in day["allocations"]}
    snapshot = {"saved_on": date.today().isoformat(), "text": render_plan(plan, data),
                "allocations": baselines}
    data["plan_drafts"][key] = snapshot
    return snapshot


def format_minutes(minutes):
    """Display an exact number of minutes without floating-point rounding."""
    hours, remainder = divmod(minutes, 60)
    return f"{hours}h {remainder:02d}m"


def render_plan(plan, data):
    """Show configured capacity, actual work, and new planned work separately."""
    tasks = {task.id: task for task in data["tasks"]}
    lines = [f"StudyFlow plan: {plan['start']} for {plan['days']} day(s)",
             "Deadline day is included. Late catch-up is never counted as on-time.", ""]
    for day in plan["schedule"]:
        if day["past"]:
            logged = sum(entry.actual_minutes for entry in data["study_log"]
                         if entry.date == day["date"])
            lines.append(f"{day['date']} | configured capacity {format_minutes(day['capacity'])} | "
                         f"past day, no new plan | actual logged {format_minutes(logged)}")
            continue
        used = sum(minutes for _, minutes, _ in day["allocations"])
        lines.append(f"{day['date']} | capacity {format_minutes(day['capacity'])} | "
                     f"actual logged {format_minutes(day['actual'])} | "
                     f"available now {format_minutes(day['remaining_capacity'])} | planned {format_minutes(used)}")
        if not day["allocations"]:
            lines.append("  No study scheduled.")
        for task_id, minutes, late in day["allocations"]:
            task = tasks[task_id]
            label = " [OVERDUE CATCH-UP]" if late else ""
            lines.append(f"  #{task_id} {task.course}: {task.name} - {format_minutes(minutes)}{label}")
    lines.extend(["", "Task outlook:"])
    if not plan["status"]:
        lines.append("  No unfinished tasks.")
    for item in plan["status"]:
        task = tasks[item["task_id"]]
        if item["overdue"]:
            message = "OVERDUE; any scheduled work is catch-up."
        elif item["deadline_shortfall"] is None:
            message = "Deadline is after this week; risk is not evaluated yet."
        elif item["deadline_shortfall"]:
            message = f"AT RISK: {format_minutes(item['deadline_shortfall'])} cannot fit by the deadline."
        else:
            message = "Can fit by the deadline with current availability."
        if item["window_unallocated"]:
            message += f" {format_minutes(item['window_unallocated'])} not shown in this plan window."
        if task.overrun_minutes:
            message += f" Actual study is {format_minutes(task.overrun_minutes)} over the estimate."
        lines.append(f"  #{task.id} due {task.due}: {message}")
    return "\n".join(lines) + "\n"
