"""Small Tkinter smoke test; skips automatically when no display is available."""

import tempfile
import tkinter as tk
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import gui
from models import StudyEntry, empty_data
from planner import week_start
from storage import DataError, load, save


class GUITests(unittest.TestCase):
    def test_failed_save_can_be_cancelled_on_close(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk window unavailable: {exc}")
        root.withdraw()
        try:
            app = gui.StudyFlowGUI(root, empty_data())
            with patch.object(gui, "save", side_effect=DataError("Disk unavailable")), \
                 patch.object(gui.messagebox, "showerror"), \
                 patch.object(gui.messagebox, "askyesnocancel", return_value=None):
                self.assertFalse(app.persist())
                self.assertTrue(app.unsaved_changes)
                app.close()
                self.assertTrue(root.winfo_exists())
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "data.json"
                with patch.object(gui, "save", side_effect=lambda data: save(data, path)):
                    self.assertTrue(app.persist())
                    self.assertFalse(app.unsaved_changes)
        finally:
            root.destroy()

    def test_date_rollover_blocks_writing_to_stale_week(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk window unavailable: {exc}")
        root.withdraw()
        try:
            app = gui.StudyFlowGUI(root, empty_data())
            app.opened_on = date.today() - timedelta(days=1)
            for variable in app.weekly_vars:
                variable.set("2")
            with patch.object(gui.messagebox, "showinfo") as notice, patch.object(gui, "save") as save_mock:
                app.save_weekly()
                app.generate_next()
            self.assertTrue(notice.called)
            save_mock.assert_not_called()
            self.assertEqual(app.data["week_capacity"], {})
            self.assertEqual(app.data["plan_drafts"], {})
        finally:
            root.destroy()

    def test_main_workflow(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk window unavailable: {exc}")
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as directory:
                data_path = Path(directory) / "data.json"
                with patch.object(gui, "save", side_effect=lambda data: save(data, data_path)):
                    app = gui.StudyFlowGUI(root, empty_data())
                    with patch.object(gui.simpledialog, "askstring", return_value="COMP9001"):
                        app.add_course()
                    self.assertEqual(app.data["courses"], ["COMP9001"])
                    app.next_week_vars[0].set("3")
                    app.task_name.set("Project")
                    app.task_due.set((date.today() + timedelta(days=1)).isoformat())
                    app.task_hours.set("3")
                    app.add_task()
                    self.assertEqual(app.next_week_vars[0].get(), "3")
                    self.assertEqual(load(data_path)["tasks"][0].remaining_minutes, 180)
                    for variable in app.weekly_vars:
                        variable.set("2")
                    app.save_weekly()
                    app.generate()
                    self.assertIn("StudyFlow plan:", app.plan_text)
                    self.assertEqual(app.data["tasks"][0].remaining_minutes, 180)
                    app.log_target.set("#1 COMP9001: Project")
                    self.assertEqual(app.log_expected.get(), "2h 00m")
                    app.log_activity.set("Drafted the introduction")
                    app.log_actual.set("1")
                    app.save_study_entry()
                    self.assertEqual(load(data_path)["tasks"][0].remaining_minutes, 120)
                    self.assertEqual(load(data_path)["study_log"][0].activity,
                                     "Drafted the introduction")
                    self.assertEqual(load(data_path)["study_log"][0].expected_minutes, 120)
                    self.assertIsNone(app.plan_text)
                    app.generate()
                    self.assertIn("available now 1h 00m | planned 1h 00m", app.plan_text)
                    app.log_target.set("#1 COMP9001: Project")
                    app.log_activity.set("Finished the draft")
                    app.log_actual.set("3")
                    with patch.object(gui.simpledialog, "askstring", return_value="1"), \
                         patch.object(gui.messagebox, "showinfo") as notice:
                        app.save_study_entry()
                    task = load(data_path)["tasks"][0]
                    self.assertEqual((task.spent_minutes, task.remaining_minutes,
                                      task.overrun_minutes), (240, 60, 60))
                    self.assertFalse(task.complete)
                    self.assertIn("1h 00m over", notice.call_args.args[1])
                    app.generate()
                    self.assertIn("actual logged 4h 00m | available now 0h 00m | planned 0h 00m", app.plan_text)
                    self.assertIn("Actual study is 1h 00m over the estimate", app.plan_text)
                    app.log_target.set("Other activity")
                    app.log_activity.set("Read an unrelated article")
                    self.assertEqual(app.log_expected.get(), "0h 00m")
                    app.log_actual.set("0.5")
                    app.save_study_entry()
                    restored = load(data_path)
                    self.assertEqual(restored["tasks"][0].spent_minutes, 240)
                    self.assertEqual(restored["study_log"][-1].task_id, None)
                    self.assertIn("actual 4h 30m", app.log_summary.get())
                    self.assertFalse(hasattr(app, "override_tree"))
                    for variable in app.next_week_vars:
                        variable.set("1")
                    app.save_next_week()
                    app.generate_next()
                    self.assertIn(str(app.next_monday), app.next_plan_text)
                    self.assertEqual(load(data_path)["week_capacity"][app.next_monday.isoformat()], [60] * 7)
                    saved_draft = app.next_plan_text
                    self.assertEqual(load(data_path)["plan_drafts"][app.next_monday.isoformat()]["text"], saved_draft)
                    app.log_target.set("#1 COMP9001: Project")
                    app.log_activity.set("Reviewed the draft")
                    app.log_actual.set("0.5")
                    with patch.object(gui.messagebox, "showinfo"):
                        app.save_study_entry()
                    self.assertEqual(app.next_plan_text, saved_draft)
                    self.assertEqual(load(data_path)["plan_drafts"][app.next_monday.isoformat()]["text"], saved_draft)
                    app.generate_next()
                    self.assertNotEqual(app.next_plan_text, saved_draft)
                    updated_draft = app.next_plan_text
                    app.data["plan_drafts"][app.current_monday.isoformat()] = {
                        "saved_on": date.today().isoformat(), "text": "Saved current-week draft"}
                    app.persist()
                    second_window = tk.Toplevel(root)
                    try:
                        reopened = gui.StudyFlowGUI(second_window, load(data_path))
                        self.assertEqual(reopened.next_plan_text, updated_draft)
                        self.assertEqual(reopened.plan_text, "Saved current-week draft")
                    finally:
                        second_window.destroy()
                    before = len(app.data["study_log"])
                    app.log_date.set((week_start(date.today()) - timedelta(days=1)).isoformat())
                    app.log_activity.set("Too old")
                    app.log_actual.set("1")
                    with patch.object(gui.messagebox, "showerror") as error:
                        app.save_study_entry()
                    self.assertTrue(error.called)
                    self.assertEqual(len(app.data["study_log"]), before)
                    last_week = week_start(date.today()) - timedelta(days=7)
                    app.data["study_log"].append(StudyEntry(
                        app.data["next_log_id"], last_week.isoformat(), None,
                        "Last week's reading", 0, 45))
                    app.data["next_log_id"] += 1
                    app.persist()
                    app.refresh_all()
                    week_label = f"{last_week} to {last_week + timedelta(days=6)}"
                    self.assertIn(week_label, app.history_box["values"])
                    app.history_week.set(week_label)
                    app.refresh_history()
                    self.assertIn("actual 0h 45m", app.history_summary.get())
                    self.assertEqual(load(data_path)["study_log"][-1].activity, "Last week's reading")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
