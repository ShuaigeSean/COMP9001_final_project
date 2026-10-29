"""Regression cases found during the StudyFlow logic review."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

import main
from input_utils import hours_to_minutes, minutes_to_hours
from models import StudyEntry, Task, add_study_entry, create_demo_data, empty_data
from planner import (expected_minutes_for_task, generate_plan, planned_minutes_on,
                     save_plan_snapshot, week_start)
from storage import DataError, decode, load, save


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.today = date.today()
        self.monday = week_start(self.today)
        self.data = empty_data()
        self.data["courses"] = ["COMP9001"]
        self.data["week_capacity"][self.monday.isoformat()] = [120] * 7
        self.task = Task(1, "COMP9001", "Project", self.today.isoformat(), 180, 180)
        self.data["tasks"] = [self.task]
        self.data["next_id"] = 2

    def test_demo_data_uses_relative_dates_and_independent_values(self):
        start = date(2026, 12, 29)
        demo = create_demo_data(start)
        self.assertEqual([task.id for task in demo["tasks"]], [1, 2, 3, 4])
        self.assertEqual(demo["next_id"], 5)
        self.assertEqual(demo["tasks"][-1].due, "2027-01-12")
        self.assertEqual(demo["week_capacity"]["2026-12-28"], [120] * 7)
        demo["courses"].append("Extra")
        self.assertNotIn("Extra", create_demo_data(start)["courses"])

    def test_logged_other_work_consumes_capacity_and_affects_risk(self):
        add_study_entry(self.data, self.today, None, "Other reading", 0, 120)
        plan = generate_plan(self.data, self.today, 1)
        self.assertEqual(plan["schedule"][0]["remaining_capacity"], 0)
        self.assertEqual(plan["schedule"][0]["allocations"], [])
        self.assertEqual(plan["status"][0]["deadline_shortfall"], 180)

    def test_logged_task_work_is_not_given_a_fresh_daily_budget(self):
        add_study_entry(self.data, self.today, self.task, "Writing", 0, 90)
        plan = generate_plan(self.data, self.today, 1)
        day = plan["schedule"][0]
        self.assertEqual(day["allocations"], [(1, 30, False)])
        self.assertEqual(day["actual"] + sum(item[1] for item in day["allocations"]), 120)
        self.assertEqual(plan["status"][0]["deadline_shortfall"], 60)

    def test_expected_uses_saved_plan_despite_task_reordering_and_restart(self):
        second = Task(2, "COMP9001", "Exercises", self.today.isoformat(), 60, 60)
        self.data["tasks"].append(second)
        self.data["next_id"] = 3
        plan = generate_plan(self.data, self.monday, 7, earliest_day=self.today)
        save_plan_snapshot(self.data, plan)
        self.assertEqual(expected_minutes_for_task(self.data, self.today, 1), 120)
        self.assertEqual(expected_minutes_for_task(self.data, self.today, 2), 0)
        add_study_entry(self.data, self.today, self.task, "Writing", 120, 150)
        # The remaining-work tie-break order has changed, but the saved budget has not.
        self.assertLess(self.task.remaining_minutes, second.remaining_minutes)
        save_plan_snapshot(self.data, generate_plan(self.data, self.monday, 7, earliest_day=self.today))
        self.assertEqual(expected_minutes_for_task(self.data, self.today, 2), 0)
        self.assertEqual(expected_minutes_for_task(self.data, self.today, 1), 0)
        self.assertEqual(planned_minutes_on(self.data, self.today), 120)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            save(self.data, path)
            restored = load(path)
            self.assertEqual(planned_minutes_on(restored, self.today), 120)
            self.assertEqual(expected_minutes_for_task(restored, self.today, 2), 0)

    def test_missing_plan_does_not_invent_expected_for_a_date(self):
        self.assertEqual(expected_minutes_for_task(self.data, self.today, 1), 0)

    def test_unlogged_planned_work_is_included_in_history_total(self):
        save_plan_snapshot(self.data, generate_plan(self.data, self.monday, 7, earliest_day=self.today))
        self.assertEqual(self.data["study_log"], [])
        self.assertEqual(planned_minutes_on(self.data, self.today), 120)

    def test_completed_task_accepts_missing_actual_log_without_reopening(self):
        self.task.remaining_minutes = 0
        add_study_entry(self.data, self.today, self.task, "Backfilled final review", 0, 60)
        self.assertTrue(self.task.complete)
        self.assertEqual(self.task.spent_minutes, 60)

    def test_cli_daily_limit_does_not_crash_or_change_task(self):
        add_study_entry(self.data, self.today, None, "Full day", 0, 1440)
        with patch("builtins.input", side_effect=["", "Extra work", "1"]), \
             patch.object(main, "persist") as persist, redirect_stdout(io.StringIO()) as output:
            main.log_other_activity(self.data)
        self.assertIn("Activity was not saved", output.getvalue())
        persist.assert_not_called()
        with patch.object(main, "choose_task", return_value=self.task), \
             patch("builtins.input", side_effect=["", "Writing", "1"]), \
             patch.object(main, "persist") as persist, redirect_stdout(io.StringIO()):
            main.record_study(self.data)
        persist.assert_not_called()
        self.assertEqual(self.task.remaining_minutes, 180)
        self.assertEqual(self.task.spent_minutes, 0)

    def test_numeric_inputs_reject_nonfinite_extreme_and_fractional_minutes(self):
        for value in ("NaN", "Infinity", "-1", "1e1000000", "1e-1000000", "0.001", "1:60", "0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hours_to_minutes(value)
        self.assertEqual(hours_to_minutes("0:01"), 1)
        self.assertEqual(hours_to_minutes("1.5"), 90)
        self.assertTrue(all(hours_to_minutes(minutes_to_hours(n), allow_zero=True) == n for n in range(1441)))

    def test_inconsistent_log_totals_are_rejected_on_load(self):
        raw = {**self.data, "tasks": [vars(self.task)], "study_log": [
            vars(StudyEntry(1, self.today.isoformat(), 1, "Writing", 0, 60))], "next_log_id": 2}
        with self.assertRaises(DataError):
            decode(raw)  # A saved task cannot have less actual time than its own logs.
        raw["study_log"] = [vars(StudyEntry(1, self.today.isoformat(), None, "Day", 0, 1440)),
                            vars(StudyEntry(2, self.today.isoformat(), None, "Extra", 0, 1))]
        raw["next_log_id"] = 3
        with self.assertRaises(DataError):
            decode(raw)

    def test_historical_task_ids_cannot_be_reused(self):
        raw = {**self.data, "tasks": [], "study_log": [
            vars(StudyEntry(1, self.today.isoformat(), 9, "Deleted task's work", 0, 60))],
            "next_log_id": 2}
        with self.assertRaises(DataError):
            decode(raw)

    def test_write_cleanup_failure_preserves_data_error_and_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text("original", encoding="utf-8")
            with patch("storage.os.replace", side_effect=PermissionError("replace denied")), \
                 patch("storage.os.unlink", side_effect=PermissionError("cleanup denied")):
                with self.assertRaisesRegex(DataError, "replace denied"):
                    save(self.data, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
