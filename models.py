"""Simple data objects used by StudyFlow."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class Task:
    """Keep baseline estimate, real study time and remaining forecast separate."""

    id: int
    course: str
    name: str
    due: str  # ISO date (YYYY-MM-DD)
    total_minutes: int
    remaining_minutes: int
    spent_minutes: int = 0

    @property
    def complete(self):
        return self.remaining_minutes == 0

    @property
    def overrun_minutes(self):
        """Actual study beyond the current total estimate."""
        return max(0, self.spent_minutes - self.total_minutes)

    def record_study(self, minutes, revised_remaining=None):
        """Record real work, requesting a fresh estimate if planned time runs out."""
        if type(minutes) is not int or minutes <= 0:
            raise ValueError("Enter positive study time.")
        if self.complete:
            if revised_remaining is not None:
                raise ValueError("Edit remaining hours to reopen a completed task first.")
            # A completed task can still receive a missing actual study record.
            self.spent_minutes += minutes
            return
        if minutes >= self.remaining_minutes:
            if type(revised_remaining) is not int or revised_remaining < 0:
                raise ValueError("Enter revised remaining minutes, or zero if complete.")
            self.remaining_minutes = revised_remaining
        else:
            if revised_remaining is not None:
                raise ValueError("A revised estimate is not needed yet.")
            self.remaining_minutes -= minutes
        self.spent_minutes += minutes


@dataclass
class StudyEntry:
    """One day's recorded activity; a task ID is optional for other work."""

    id: int
    date: str
    task_id: Optional[int]
    activity: str
    expected_minutes: int
    actual_minutes: int


def add_study_entry(data, day, task, activity, expected, actual, revised_remaining=None):
    """Save an actual activity and update its linked task in one operation."""
    today = date.today()
    first_day = today - timedelta(days=today.weekday())
    if not isinstance(day, date) or not first_day <= day <= today:
        raise ValueError("Choose a date from this Monday through today.")
    if (not isinstance(activity, str) or not activity.strip() or
            type(expected) is not int or expected < 0 or expected > 1440 or
            type(actual) is not int or actual <= 0 or actual > 1440):
        raise ValueError("Enter an activity and valid expected and actual hours (maximum 24).")
    used_today = sum(entry.actual_minutes for entry in data["study_log"]
                     if entry.date == day.isoformat())
    if used_today + actual > 1440:
        raise ValueError("Total actual study on one date cannot exceed 24 hours.")
    if task is not None:
        if not any(existing is task for existing in data["tasks"]):
            raise ValueError("Choose an existing task.")
        task.record_study(actual, revised_remaining)
    elif revised_remaining is not None or expected != 0:
        raise ValueError("Other activities have no task progress or planned task hours.")
    entry = StudyEntry(data["next_log_id"], day.isoformat(),
                       None if task is None else task.id, activity.strip(), expected, actual)
    data["study_log"].append(entry)
    data["next_log_id"] += 1
    return entry


def empty_data():
    """Return independent, editable data for a new user."""
    return {"courses": [], "tasks": [], "week_capacity": {},
            "study_log": [], "next_id": 1, "next_log_id": 1,
            "archived_overrides": {}, "plan_drafts": {}}


def create_course(data, name):
    """Add a nonempty course only once and report whether it was added."""
    if not name.strip() or name in data["courses"]:
        return False
    data["courses"].append(name)
    return True


def create_task(data, course, name, due, minutes):
    """Create a task with the next ID after the interface validates its fields."""
    task = Task(data["next_id"], course, name, due, minutes, minutes)
    data["tasks"].append(task)
    data["next_id"] += 1
    return task


def create_demo_data(today):
    """Build the same relative-date demo for both user interfaces."""
    data = empty_data()
    data["courses"] = ["COMP9001", "MATH1001", "HIST1001"]
    monday = today - timedelta(days=today.weekday())
    data["week_capacity"] = {monday.isoformat(): [120] * 7,
                             (monday + timedelta(days=7)).isoformat(): [120] * 7}
    examples = [("COMP9001", "Python project", 1, 240),
                ("MATH1001", "Problem set", 2, 300),
                ("HIST1001", "Essay draft", 4, 720),
                ("COMP9001", "Revision", 14, 180)]
    for course, name, offset, minutes in examples:
        create_task(data, course, name, (today + timedelta(days=offset)).isoformat(), minutes)
    return data
