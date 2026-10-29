"""Focused standard-library tests for the scheduling rules and persistence."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from models import StudyEntry, Task, add_study_entry, empty_data
from planner import available_minutes, expected_minutes_for_task, generate_plan, render_plan, week_start
from storage import DataError, load, save


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.start = date(2026, 10, 29)
        self.data = empty_data()
        self.data["courses"] = ["COMP9001"]
        self.data["week_capacity"][week_start(self.start).isoformat()] = [120] * 7

    def add(self, task_id, due_offset, minutes):
        self.data["tasks"].append(Task(task_id, "COMP9001", f"Task {task_id}",
                                       (self.start + timedelta(days=due_offset)).isoformat(),
                                       minutes, minutes))

    def test_capacity_conservation_and_deadline(self):
        self.add(1, 1, 180)
        self.add(2, 2, 210)
        plan = generate_plan(self.data, self.start, 3)
        totals = {1: 0, 2: 0}
        for day in plan["schedule"]:
            used = sum(minutes for _, minutes, _ in day["allocations"])
            self.assertLessEqual(used, day["capacity"])
            self.assertEqual(used + day["unused"], day["capacity"])
            for task_id, minutes, late in day["allocations"]:
                self.assertFalse(late)
                self.assertLessEqual(day["date"], self.data["tasks"][task_id - 1].due)
                totals[task_id] += minutes
        self.assertLessEqual(totals[1], 180)
        self.assertLessEqual(totals[2], 210)
        self.assertEqual([item["deadline_shortfall"] for item in plan["status"]], [0, 30])

    def test_short_window_is_not_deadline_risk(self):
        self.add(1, 10, 180)
        plan = generate_plan(self.data, self.start, 1)
        self.assertEqual(plan["status"][0]["window_unallocated"], 60)
        self.assertIsNone(plan["status"][0]["deadline_shortfall"])

    def test_progress_changes_next_plan_but_planning_does_not(self):
        self.add(1, 0, 180)
        first = generate_plan(self.data, self.start, 1)
        self.assertEqual(first["status"][0]["deadline_shortfall"], 60)
        self.assertEqual(self.data["tasks"][0].remaining_minutes, 180)
        self.data["tasks"][0].remaining_minutes -= 60
        second = generate_plan(self.data, self.start, 1)
        self.assertEqual(second["status"][0]["deadline_shortfall"], 0)

    def test_zero_capacity_and_overdue_catchup(self):
        self.data["week_capacity"][week_start(self.start).isoformat()] = [0] * 7
        self.add(1, -1, 60)
        plan = generate_plan(self.data, self.start, 2)
        self.assertTrue(plan["status"][0]["overdue"])
        self.assertEqual(plan["schedule"][0]["allocations"], [])
        self.data["week_capacity"][week_start(self.start).isoformat()][self.start.weekday()] = 60
        plan = generate_plan(self.data, self.start, 1)
        self.assertEqual(plan["schedule"][0]["allocations"], [(1, 60, True)])

    def test_no_open_tasks_and_invalid_saved_content(self):
        self.add(1, 0, 60)
        self.data["tasks"][0].remaining_minutes = 0
        plan = generate_plan(self.data, self.start, 1)
        self.assertEqual(plan["status"], [])
        self.assertEqual(plan["schedule"][0]["allocations"], [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text('{"courses": []}', encoding="utf-8")
            with self.assertRaises(DataError):
                load(path)

    def test_save_load_and_damaged_file(self):
        self.add(1, 1, 90)
        self.data["next_id"] = 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            save(self.data, path)
            self.assertEqual(load(path)["tasks"][0].remaining_minutes, 90)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(DataError):
                load(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_study_can_exceed_estimate_without_completing_task(self):
        task = Task(1, "COMP9001", "Project", self.start.isoformat(), 180, 180)
        with self.assertRaises(ValueError):
            task.record_study(240)
        self.assertEqual(task.spent_minutes, 0)
        task.record_study(240, revised_remaining=60)
        self.assertFalse(task.complete)
        self.assertEqual(task.spent_minutes, 240)
        self.assertEqual(task.overrun_minutes, 60)
        self.assertEqual(task.remaining_minutes, 60)
        self.data["tasks"] = [task]
        plan = generate_plan(self.data, self.start, 1)
        self.assertEqual(plan["schedule"][0]["allocations"], [(1, 60, False)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            self.data["next_id"] = 2
            save(self.data, path)
            restored = load(path)["tasks"][0]
            self.assertEqual((restored.spent_minutes, restored.remaining_minutes,
                              restored.overrun_minutes), (240, 60, 60))

    def test_legacy_task_file_still_loads(self):
        self.add(1, 1, 180)
        self.data["tasks"][0].remaining_minutes = 120
        self.data["next_id"] = 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            save(self.data, path)
            import json
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["weekly"] = [120] * 7
            del raw["week_capacity"]
            raw["overrides"] = {self.start.isoformat(): 60}
            del raw["study_log"]
            del raw["next_log_id"]
            del raw["archived_overrides"]
            del raw["plan_drafts"]
            del raw["tasks"][0]["spent_minutes"]
            path.write_text(json.dumps(raw), encoding="utf-8")
            migrated = load(path)
            restored = migrated["tasks"][0]
            self.assertEqual(restored.spent_minutes, 60)
            self.assertEqual(restored.remaining_minutes, 120)
            self.assertEqual(migrated["archived_overrides"], {self.start.isoformat(): 60})
            self.assertEqual(migrated["study_log"], [])
            self.assertEqual(available_minutes(migrated, date.today()), 120)

    def test_dated_data_without_drafts_still_loads(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            save(self.data, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            del raw["plan_drafts"]
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(load(path)["plan_drafts"], {})

    def test_daily_log_updates_only_linked_task_and_persists(self):
        today = date.today()
        task = Task(1, "COMP9001", "Project", today.isoformat(), 180, 180)
        self.data["tasks"] = [task]
        self.data["next_id"] = 2
        add_study_entry(self.data, today, task, "Wrote introduction", 120, 90)
        self.assertEqual((task.spent_minutes, task.remaining_minutes), (90, 90))
        add_study_entry(self.data, today, None, "Read an unrelated book", 0, 60)
        self.assertEqual((task.spent_minutes, task.remaining_minutes), (90, 90))
        self.assertEqual([entry.actual_minutes - entry.expected_minutes
                          for entry in self.data["study_log"]], [-30, 60])
        with self.assertRaises(ValueError):
            add_study_entry(self.data, today + timedelta(days=1), task, "Future work", 30, 30)
        with self.assertRaises(ValueError):
            add_study_entry(self.data, week_start(today) - timedelta(days=1), task,
                            "Previous week", 30, 30)
        with self.assertRaises(ValueError):
            add_study_entry(self.data, today, None, "Impossible day", 0, 1440)
        self.assertEqual(len(self.data["study_log"]), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            save(self.data, path)
            restored = load(path)
            self.assertEqual(len(restored["study_log"]), 2)
            self.assertEqual(restored["tasks"][0].remaining_minutes, 90)

    def test_dated_weeks_and_past_days(self):
        today = date.today()
        monday = week_start(today)
        next_monday = monday + timedelta(days=7)
        data = empty_data()
        data["courses"] = ["COMP9001"]
        data["week_capacity"][monday.isoformat()] = [60] * 7
        data["week_capacity"][next_monday.isoformat()] = [120] * 7
        data["tasks"] = [Task(1, "COMP9001", "Future task",
                              (next_monday + timedelta(days=2)).isoformat(), 240, 240)]
        self.assertEqual(available_minutes(data, today), 60)
        self.assertEqual(available_minutes(data, next_monday), 120)
        current = generate_plan(data, monday, 7, earliest_day=today)
        self.assertTrue(all(day["capacity"] == 60 and day["past"] and not day["allocations"]
                            for day in current["schedule"] if day["date"] < today.isoformat()))
        self.assertIsNone(current["status"][0]["deadline_shortfall"])
        following = generate_plan(data, next_monday, 7)
        self.assertEqual(following["status"][0]["deadline_shortfall"], 0)

    def test_past_day_shows_configured_capacity_and_logged_actual(self):
        monday = date(2026, 10, 26)
        data = empty_data()
        data["week_capacity"][monday.isoformat()] = [540] * 7
        data["study_log"].append(StudyEntry(1, "2026-10-27", None, "Reading", 0, 45))
        plan = generate_plan(data, monday, 7, earliest_day=date(2026, 10, 29))
        text = render_plan(plan, data)
        self.assertIn("2026-10-27 | configured capacity 9h 00m | past day, no new plan "
                      "| actual logged 0h 45m", text)
        self.assertNotIn("2026-10-27 | available 0h 00m | planned 0h 00m", text)


if __name__ == "__main__":
    unittest.main()
