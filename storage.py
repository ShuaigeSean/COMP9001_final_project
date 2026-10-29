"""Validated JSON storage with atomic replacement on successful writes."""

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from models import StudyEntry, Task, empty_data


DATA_PATH = Path(__file__).resolve().parent / "studyflow_data.json"


class DataError(Exception):
    """The saved file cannot be read or does not contain valid StudyFlow data."""


def valid_date(value):
    """Accept only canonical ISO dates, including valid leap days."""
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def valid_minutes(value, allow_zero=True, maximum=None):
    """Reject booleans, floats and values outside the expected range."""
    return (type(value) is int and value >= (0 if allow_zero else 1)
            and (maximum is None or value <= maximum))


def _decode_courses(raw):
    """Validate the saved course names."""
    courses = raw["courses"]
    if (not isinstance(courses, list) or
            any(not isinstance(c, str) or not c.strip() for c in courses) or
            len(courses) != len(set(courses))):
        raise DataError("Data file has invalid courses.")
    return courses


def _decode_week_capacity(raw, has_weekly_template):
    """Validate weekly hours and migrate a legacy template."""
    if has_weekly_template:
        weekly = raw["weekly"]
        if not isinstance(weekly, list) or len(weekly) != 7 or any(not valid_minutes(x, maximum=1440) for x in weekly):
            raise DataError("Data file has invalid weekly availability.")
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_capacity = {monday.isoformat(): weekly}
    else:
        week_capacity = raw["week_capacity"]
        if not isinstance(week_capacity, dict):
            raise DataError("Data file has invalid dated weekly capacity.")
        for monday_text, hours in week_capacity.items():
            if (not valid_date(monday_text) or date.fromisoformat(monday_text).weekday() != 0 or
                    not isinstance(hours, list) or len(hours) != 7 or
                    any(not valid_minutes(x, maximum=1440) for x in hours)):
                raise DataError("Data file has invalid dated weekly capacity.")
    return week_capacity


def _decode_archived_overrides(raw, legacy_file):
    """Preserve and validate old date overrides."""
    archived = raw["overrides"] if legacy_file else raw["archived_overrides"]
    if (not isinstance(archived, dict) or
            any(not valid_date(k) or not valid_minutes(v, maximum=1440) for k, v in archived.items())):
        raise DataError("Data file has invalid archived date settings.")
    return archived


def _decode_tasks(raw, courses):
    """Validate tasks and restore old progress records."""
    if not valid_minutes(raw["next_id"], allow_zero=False):
        raise DataError("Data file has an invalid next task ID.")
    if not isinstance(raw["tasks"], list):
        raise DataError("Data file has invalid tasks.")
    tasks = []
    ids = set()
    for item in raw["tasks"]:
        required = {"id", "course", "name", "due", "total_minutes", "remaining_minutes"}
        if not isinstance(item, dict) or set(item) not in (required, required | {"spent_minutes"}):
            raise DataError("Data file has an invalid task.")
        legacy = "spent_minutes" not in item
        if (not valid_minutes(item["id"], allow_zero=False) or item["id"] in ids or
                item["course"] not in courses or not isinstance(item["name"], str) or
                not item["name"].strip() or not valid_date(item["due"]) or
                not valid_minutes(item["total_minutes"], allow_zero=False) or
                not valid_minutes(item["remaining_minutes"]) or
                (legacy and item["remaining_minutes"] > item["total_minutes"]) or
                (not legacy and not valid_minutes(item["spent_minutes"]))):
            raise DataError("Data file has an invalid task.")
        ids.add(item["id"])
        if legacy:
            # Older files stored only total and remaining. This is the best
            # available estimate of past study; mark-complete history is unknown.
            item = {**item, "spent_minutes": item["total_minutes"] - item["remaining_minutes"]}
        tasks.append(Task(**item))
    if ids and raw["next_id"] <= max(ids):
        raise DataError("Data file has an invalid next task ID.")
    return tasks, ids


def _decode_study_log(raw, legacy_file, tasks, ids):
    """Validate log entries and their links to task totals."""
    study_log = []
    daily_actual = {}
    task_actual = {}
    historical_task_ids = set(ids)
    if not legacy_file:
        if not isinstance(raw["study_log"], list) or not valid_minutes(raw["next_log_id"], allow_zero=False):
            raise DataError("Data file has an invalid study log.")
        log_ids = set()
        for item in raw["study_log"]:
            fields = {"id", "date", "task_id", "activity", "expected_minutes", "actual_minutes"}
            if not isinstance(item, dict) or set(item) != fields:
                raise DataError("Data file has an invalid study entry.")
            if (not valid_minutes(item["id"], allow_zero=False) or item["id"] in log_ids or
                    not valid_date(item["date"]) or
                    (item["task_id"] is not None and not valid_minutes(item["task_id"], allow_zero=False)) or
                    not isinstance(item["activity"], str) or not item["activity"].strip() or
                    not valid_minutes(item["expected_minutes"], maximum=1440) or
                    not valid_minutes(item["actual_minutes"], allow_zero=False, maximum=1440)):
                raise DataError("Data file has an invalid study entry.")
            log_ids.add(item["id"])
            daily_actual[item["date"]] = daily_actual.get(item["date"], 0) + item["actual_minutes"]
            if daily_actual[item["date"]] > 1440:
                raise DataError("Recorded actual work exceeds 24 hours on one date.")
            if item["task_id"] is not None:
                historical_task_ids.add(item["task_id"])
                task_actual[item["task_id"]] = task_actual.get(item["task_id"], 0) + item["actual_minutes"]
            study_log.append(StudyEntry(**item))
        if log_ids and raw["next_log_id"] <= max(log_ids):
            raise DataError("Data file has an invalid next study entry ID.")
    for task in tasks:
        if task.spent_minutes < task_actual.get(task.id, 0):
            raise DataError("A task's actual time is smaller than its recorded study logs.")
    return study_log, historical_task_ids


def _decode_plan_drafts(raw, historical_task_ids):
    """Validate saved plans and historical task IDs."""
    drafts = raw.get("plan_drafts", {})
    if not isinstance(drafts, dict):
        raise DataError("Data file has invalid saved week plans.")
    for monday_text, draft in drafts.items():
        if (not valid_date(monday_text) or date.fromisoformat(monday_text).weekday() != 0 or
                not isinstance(draft, dict) or set(draft) not in
                ({"saved_on", "text"}, {"saved_on", "text", "allocations"}) or
                not valid_date(draft["saved_on"]) or
                not isinstance(draft["text"], str) or not draft["text"].strip()):
            raise DataError("Data file has invalid saved week plans.")
        allocations = draft.get("allocations", {})
        if not isinstance(allocations, dict):
            raise DataError("Data file has invalid saved daily allocations.")
        monday = date.fromisoformat(monday_text)
        for day_text, assignments in allocations.items():
            if (not valid_date(day_text) or not 0 <= (date.fromisoformat(day_text) - monday).days < 7 or
                    not isinstance(assignments, dict)):
                raise DataError("Data file has invalid saved daily allocations.")
            for task_id, minutes in assignments.items():
                if (not isinstance(task_id, str) or not task_id.isascii() or not task_id.isdigit() or
                        len(task_id) > 20 or int(task_id) < 1 or str(int(task_id)) != task_id or
                        not valid_minutes(minutes, allow_zero=False, maximum=1440)):
                    raise DataError("Data file has invalid saved daily allocations.")
                historical_task_ids.add(int(task_id))
            if sum(assignments.values()) > 1440:
                raise DataError("Saved daily allocations exceed 24 hours.")
    if historical_task_ids and raw["next_id"] <= max(historical_task_ids):
        raise DataError("The next task ID would reuse an existing or historical task ID.")
    return drafts


def decode(raw):
    """Validate the entire file before making any of it available to the app."""
    old_keys = {"courses", "tasks", "weekly", "overrides", "next_id"}
    middle_keys = {"courses", "tasks", "weekly", "study_log", "next_id",
                   "next_log_id", "archived_overrides"}
    dated_keys = {"courses", "tasks", "week_capacity", "study_log", "next_id",
                  "next_log_id", "archived_overrides"}
    new_keys = dated_keys | {"plan_drafts"}
    if not isinstance(raw, dict) or set(raw) not in (old_keys, middle_keys, dated_keys, new_keys):
        raise DataError("Data file has an invalid structure.")
    legacy_file = set(raw) == old_keys
    has_weekly_template = "weekly" in raw
    courses = _decode_courses(raw)
    week_capacity = _decode_week_capacity(raw, has_weekly_template)
    archived = _decode_archived_overrides(raw, legacy_file)
    tasks, ids = _decode_tasks(raw, courses)
    study_log, historical_task_ids = _decode_study_log(raw, legacy_file, tasks, ids)
    drafts = _decode_plan_drafts(raw, historical_task_ids)
    return {"courses": courses, "tasks": tasks, "week_capacity": week_capacity,
            "study_log": study_log, "next_id": raw["next_id"],
            "next_log_id": 1 if legacy_file else raw["next_log_id"],
            "archived_overrides": archived, "plan_drafts": drafts}


def load(path=DATA_PATH):
    """Missing file means a fresh start; a damaged file is never overwritten."""
    try:
        with open(path, encoding="utf-8") as file:
            raw = json.load(file)
    except FileNotFoundError:
        return empty_data()
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise DataError(f"Cannot read data file: {exc}") from exc
    return decode(raw)


def save(data, path=DATA_PATH):
    """Write beside the program, replacing the old file only after a full write."""
    raw = {**data, "tasks": [vars(task) for task in data["tasks"]],
           "study_log": [vars(entry) for entry in data["study_log"]]}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=Path(path).parent,
                                         prefix=".studyflow_", suffix=".tmp", delete=False) as file:
            temporary = file.name
            json.dump(raw, file, indent=2, ensure_ascii=False)
            file.write("\n")
        os.replace(temporary, path)
    except (OSError, UnicodeError) as exc:
        raise DataError(f"Could not save data: {exc}") from exc
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                # Preserve the original write error if cleanup also fails.
                pass
