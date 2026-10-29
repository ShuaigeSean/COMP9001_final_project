"""Optional Tkinter desktop interface for StudyFlow. Run: python gui.py"""

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, simpledialog, ttk

from gui_views import build_history, build_next, build_plan, build_tasks, build_time
from input_utils import hours_to_minutes, minutes_to_hours
from models import add_study_entry, create_course, create_demo_data, create_task
from planner import (available_minutes, expected_minutes_for_task, format_minutes,
                     generate_plan, planned_minutes_on, save_plan_snapshot, week_start)
from storage import DATA_PATH, DataError, load, save, valid_date


class StudyFlowGUI:
    """Small desktop view over the same data and scheduler as the CLI."""

    def __init__(self, root, data):
        self.root = root
        self.data = data
        self.plan_text = None
        self.next_plan_text = None
        self.unsaved_changes = False
        self.opened_on = date.today()
        self.current_monday = week_start(date.today())
        self.next_monday = self.current_monday + timedelta(days=7)
        self.root.title("StudyFlow - Intelligent Study Planner")
        self.root.geometry("1020x720")
        self.root.minsize(800, 580)
        self._build()
        self.refresh_all(refresh_hours=True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Treeview", rowheight=26)
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="StudyFlow", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Plan your study around real deadlines and available time.").pack(anchor="w", pady=(0, 10))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.tasks_tab = ttk.Frame(self.tabs, padding=10)
        self.time_tab = ttk.Frame(self.tabs, padding=10)
        self.plan_tab = ttk.Frame(self.tabs, padding=10)
        self.next_tab = ttk.Frame(self.tabs, padding=10)
        self.history_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.tasks_tab, text="Courses & Tasks")
        self.tabs.add(self.time_tab, text="Study Time")
        self.tabs.add(self.plan_tab, text="This Week Plan")
        self.tabs.add(self.next_tab, text="Next Week Plan")
        self.tabs.add(self.history_tab, text="Past Weeks")
        build_tasks(self)
        build_time(self)
        build_plan(self)
        build_next(self)
        build_history(self)
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        self.status = tk.StringVar(value=f"Data: {DATA_PATH}")
        ttk.Label(footer, textvariable=self.status, wraplength=720).pack(side="left")
        ttk.Button(footer, text="Retry Save", command=self.persist).pack(side="right")
        ttk.Button(footer, text="Load Demo", command=self.load_demo).pack(side="right", padx=8)
        self._restore_current_draft()

    def refresh_all(self, refresh_hours=False):
        self.course_list.set(", ".join(self.data["courses"]) or "None")
        self.course_box["values"] = self.data["courses"]
        if self.data["courses"] and self.task_course.get() not in self.data["courses"]:
            self.task_course.set(self.data["courses"][0])
        self.task_tree.delete(*self.task_tree.get_children())
        for task in sorted(self.data["tasks"], key=lambda item: (item.due, item.id)):
            state = ("Complete" if task.complete else
                     f"Over by {format_minutes(task.overrun_minutes)}" if task.overrun_minutes else "Open")
            self.task_tree.insert("", "end", iid=str(task.id), values=(
                task.id, task.course, task.name, task.due,
                format_minutes(task.remaining_minutes),
                f"{format_minutes(task.spent_minutes)} / {format_minutes(task.total_minutes)}",
                state))
        if refresh_hours:
            current_hours = self.data["week_capacity"].get(self.current_monday.isoformat(), [0] * 7)
            next_hours = self.data["week_capacity"].get(self.next_monday.isoformat(), [0] * 7)
            for variable, minutes in zip(self.weekly_vars, current_hours):
                variable.set(minutes_to_hours(minutes))
            for variable, minutes in zip(self.next_week_vars, next_hours):
                variable.set(minutes_to_hours(minutes))
        targets = ["Other activity"] + [
            f"#{task.id} {task.course}: {task.name}" for task in self.data["tasks"]]
        self.log_target_box["values"] = targets
        if self.log_target.get() not in targets:
            self.log_target.set("Other activity")
        self.log_tree.delete(*self.log_tree.get_children())
        for entry in sorted(self.data["study_log"], key=lambda item: (item.date, item.id), reverse=True):
            if not self.current_monday.isoformat() <= entry.date <= date.today().isoformat():
                continue
            difference = entry.actual_minutes - entry.expected_minutes
            comparison = ("+" if difference >= 0 else "-") + format_minutes(abs(difference))
            target = "Other" if entry.task_id is None else f"Task #{entry.task_id}"
            self.log_tree.insert("", "end", iid=str(entry.id), values=(
                entry.date, target, entry.activity, format_minutes(entry.expected_minutes),
                format_minutes(entry.actual_minutes), comparison))
        past_weeks = {week_start(date.fromisoformat(entry.date)).isoformat()
                      for entry in self.data["study_log"]
                      if entry.date < self.current_monday.isoformat()}
        past_weeks.update(key for key in self.data["week_capacity"]
                          if key < self.current_monday.isoformat())
        self.history_week_dates = {
            f"{monday} to {date.fromisoformat(monday) + timedelta(days=6)}": monday
            for monday in sorted(past_weeks, reverse=True)
        }
        choices = list(self.history_week_dates)
        self.history_box["values"] = choices
        if self.history_week.get() not in choices:
            self.history_week.set(choices[0] if choices else "")
        self.refresh_history()
        self.refresh_log_display()
        self.show_next_draft()

    def show_next_draft(self):
        """Display the saved next-week snapshot without changing real progress."""
        draft = self.data["plan_drafts"].get(self.next_monday.isoformat())
        self.next_plan_text = None if draft is None else draft["text"]
        if draft is None:
            self.next_draft_info.set("No draft saved yet. Create one, then update it from actual progress later.")
            self.next_generate_button.configure(text="Create Draft")
        else:
            self.next_draft_info.set(
                f"Draft saved on {draft['saved_on']}. It stays unchanged until you update it.")
            self.next_generate_button.configure(text="Update Draft from Actual Progress")
        self.next_plan_view.configure(state="normal")
        self.next_plan_view.delete("1.0", "end")
        if self.next_plan_text is not None:
            self.next_plan_view.insert("1.0", self.next_plan_text)
        self.next_plan_view.configure(state="disabled")

    def _restore_current_draft(self):
        """Show a draft made last week when that week becomes current."""
        draft = self.data["plan_drafts"].get(self.current_monday.isoformat())
        if draft is None:
            return
        self.plan_text = draft["text"]
        self.plan_view.configure(state="normal")
        self.plan_view.delete("1.0", "end")
        self.plan_view.insert("1.0", self.plan_text)
        self.plan_view.configure(state="disabled")
        self.status.set(f"Showing a saved draft from {draft['saved_on']}; Generate This Week to refresh it.")

    def refresh_log_display(self):
        self.refresh_log_summary()
        day_text = self.log_date.get().strip()
        target = self.log_target.get()
        expected = 0
        if valid_date(day_text) and target.startswith("#"):
            try:
                task_id = int(target.split(" ", 1)[0][1:])
                expected = expected_minutes_for_task(self.data, date.fromisoformat(day_text), task_id)
            except (ValueError, OverflowError):
                pass
        self.log_expected.set(format_minutes(expected))

    def refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        monday_text = self.history_week_dates.get(self.history_week.get(), "")
        if not valid_date(monday_text):
            self.history_summary.set("No past weeks recorded yet.")
            return
        monday = date.fromisoformat(monday_text)
        sunday = monday + timedelta(days=6)
        entries = [entry for entry in self.data["study_log"]
                   if monday_text <= entry.date <= sunday.isoformat()]
        capacity = sum(self.data["week_capacity"].get(monday_text, [0] * 7))
        expected = sum(planned_minutes_on(self.data, monday + timedelta(days=offset)) for offset in range(7))
        actual = sum(entry.actual_minutes for entry in entries)
        legacy_note = (" | No saved daily plan: expected totals use logs only."
                       if not self.data["plan_drafts"].get(monday_text, {}).get("allocations") else "")
        self.history_summary.set(
            f"{monday} to {sunday} | planning capacity {format_minutes(capacity)} | "
            f"planned baseline {format_minutes(expected)} | actual {format_minutes(actual)}{legacy_note}")
        for entry in sorted(entries, key=lambda item: (item.date, item.id)):
            difference = entry.actual_minutes - entry.expected_minutes
            comparison = ("+" if difference >= 0 else "-") + format_minutes(abs(difference))
            target = "Other" if entry.task_id is None else f"Task #{entry.task_id}"
            self.history_tree.insert("", "end", iid=str(entry.id), values=(
                entry.date, target, entry.activity, format_minutes(entry.expected_minutes),
                format_minutes(entry.actual_minutes), comparison))

    def refresh_log_summary(self):
        day_text = self.log_date.get().strip()
        if not valid_date(day_text):
            self.log_summary.set("Enter a valid date to view that day's totals.")
            return
        if not self.current_monday.isoformat() <= day_text <= date.today().isoformat():
            self.log_summary.set("Choose a date from this Monday through today.")
            return
        entries = [entry for entry in self.data["study_log"] if entry.date == day_text]
        expected = planned_minutes_on(self.data, date.fromisoformat(day_text))
        actual = sum(entry.actual_minutes for entry in entries)
        available = available_minutes(self.data, date.fromisoformat(day_text))
        difference = actual - available
        comparison = ("+" if difference >= 0 else "-") + format_minutes(abs(difference))
        snapshot = self.data["plan_drafts"].get(week_start(date.fromisoformat(day_text)).isoformat(), {})
        note = " | No saved daily plan for this date." if day_text not in snapshot.get("allocations", {}) else ""
        self.log_summary.set(
            f"{day_text}: planning capacity {format_minutes(available)} | "
            f"planned baseline {format_minutes(expected)} | actual {format_minutes(actual)} | "
            f"actual vs capacity {comparison}{note}")

    def persist(self):
        try:
            save(self.data)
            self.unsaved_changes = False
            self.status.set("Saved to " + str(DATA_PATH))
            return True
        except DataError as exc:
            self.unsaved_changes = True
            self.status.set("SAVE FAILED: changes remain in memory")
            messagebox.showerror("Save failed", str(exc) + "\nChanges remain in memory; use Retry Save.", parent=self.root)
            return False

    def close(self):
        """Do not silently discard changes after a failed disk write."""
        if self.unsaved_changes:
            answer = messagebox.askyesnocancel("Unsaved changes", "Retry saving before closing?\n"
                                               "Yes: save; No: discard changes; Cancel: keep working.",
                                               parent=self.root)
            if answer is None or (answer and not self.persist()):
                return
        self.root.destroy()

    def ensure_current_date(self):
        """Prevent stale weekday fields from writing to the wrong week."""
        if date.today() == self.opened_on:
            return True
        messagebox.showinfo("Date changed", "Reopen StudyFlow to refresh this week's dates.\n"
                            "Save any unsaved changes before closing.", parent=self.root)
        return False

    def changed(self):
        self.refresh_all()
        self.plan_text = None
        self.plan_view.configure(state="normal")
        self.plan_view.delete("1.0", "end")
        self.plan_view.configure(state="disabled")
        self.persist()

    def selected_task(self):
        selection = self.task_tree.selection()
        if not selection:
            messagebox.showwarning("Select a task", "Select a task in the table first.", parent=self.root)
            return None
        task_id = int(selection[0])
        return next(task for task in self.data["tasks"] if task.id == task_id)

    def fill_task_fields(self, _event=None):
        selection = self.task_tree.selection()
        if not selection:
            return
        task = next(task for task in self.data["tasks"] if task.id == int(selection[0]))
        self.task_course.set(task.course)
        self.task_name.set(task.name)
        self.task_due.set(task.due)
        self.task_hours.set(minutes_to_hours(task.total_minutes))
        self.task_remaining.set(minutes_to_hours(task.remaining_minutes))

    def clear_task_fields(self):
        for item in self.task_tree.selection():
            self.task_tree.selection_remove(item)
        self.task_name.set("")
        self.task_due.set(date.today().isoformat())
        self.task_hours.set("")
        self.task_remaining.set("")

    def add_course(self):
        name = simpledialog.askstring("Add course", "Course name:", parent=self.root)
        if name is None:
            return
        name = name.strip()
        if not create_course(self.data, name):
            messagebox.showerror("Invalid course", "Enter a unique, nonempty course name.", parent=self.root)
            return
        self.changed()
        self.task_course.set(name)

    def task_fields(self):
        course = self.task_course.get()
        name = self.task_name.get().strip()
        due = self.task_due.get().strip()
        if course not in self.data["courses"]:
            raise ValueError("Choose an existing course first.")
        if not name:
            raise ValueError("Enter a task name.")
        if not valid_date(due):
            raise ValueError("Enter a valid due date in YYYY-MM-DD format.")
        return course, name, due, hours_to_minutes(self.task_hours.get())

    def add_task(self):
        try:
            course, name, due, minutes = self.task_fields()
        except ValueError as exc:
            messagebox.showerror("Invalid task", str(exc), parent=self.root)
            return
        create_task(self.data, course, name, due, minutes)
        self.changed()
        self.clear_task_fields()

    def update_task(self):
        task = self.selected_task()
        if task is None:
            return
        try:
            course, name, due, minutes = self.task_fields()
            remaining = hours_to_minutes(self.task_remaining.get(), allow_zero=True)
        except ValueError as exc:
            messagebox.showerror("Invalid task", str(exc), parent=self.root)
            return
        task.course, task.name, task.due = course, name, due
        task.total_minutes = minutes
        task.remaining_minutes = remaining
        self.changed()

    def delete_task(self):
        task = self.selected_task()
        if task and messagebox.askyesno("Delete task", f"Delete task #{task.id}: {task.name}?", parent=self.root):
            self.data["tasks"].remove(task)
            self.changed()
            self.clear_task_fields()

    def open_study_log(self):
        task = self.selected_task()
        if task is None:
            return
        self.log_target.set(f"#{task.id} {task.course}: {task.name}")
        self.log_activity.set(task.name)
        self.tabs.select(self.time_tab)

    def complete_task(self):
        task = self.selected_task()
        if task and not task.complete:
            task.remaining_minutes = 0
            self.changed()

    def save_weekly(self):
        if not self.ensure_current_date():
            return
        try:
            weekly = [hours_to_minutes(variable.get(), allow_zero=True, maximum=1440)
                      for variable in self.weekly_vars]
        except ValueError as exc:
            messagebox.showerror("Invalid weekly hours", str(exc), parent=self.root)
            return
        self.data["week_capacity"][self.current_monday.isoformat()] = weekly
        self.changed()

    def save_next_week(self):
        if not self.ensure_current_date():
            return
        try:
            weekly = [hours_to_minutes(variable.get(), allow_zero=True, maximum=1440)
                      for variable in self.next_week_vars]
        except ValueError as exc:
            messagebox.showerror("Invalid next-week hours", str(exc), parent=self.root)
            return
        self.data["week_capacity"][self.next_monday.isoformat()] = weekly
        self.changed()
        if self.next_plan_text is not None and not self.unsaved_changes:
            self.status.set("Next-week hours saved. Update the draft to use the new hours.")

    def save_study_entry(self):
        if not self.ensure_current_date():
            return
        day_text = self.log_date.get().strip()
        if (not valid_date(day_text) or
                not self.current_monday.isoformat() <= day_text <= date.today().isoformat()):
            messagebox.showerror("Invalid date", "Choose a date from this Monday through today.",
                                 parent=self.root)
            return
        target = self.log_target.get()
        task = None
        if target != "Other activity":
            try:
                task_id = int(target.split(" ", 1)[0][1:])
                task = next(item for item in self.data["tasks"] if item.id == task_id)
            except (ValueError, StopIteration):
                messagebox.showerror("Invalid task", "Choose an existing task or Other activity.", parent=self.root)
                return
        activity = self.log_activity.get().strip() or (task.name if task else "")
        if not activity:
            messagebox.showerror("Invalid activity", "Describe what you did.", parent=self.root)
            return
        try:
            expected = (expected_minutes_for_task(self.data, date.fromisoformat(day_text), task.id)
                        if task is not None else 0)
            actual = hours_to_minutes(self.log_actual.get(), maximum=1440)
        except ValueError as exc:
            messagebox.showerror("Invalid study hours", str(exc), parent=self.root)
            return
        revised = None
        if task is not None and not task.complete and actual >= task.remaining_minutes:
            answer = simpledialog.askstring(
                "Update remaining estimate",
                f"Actual work uses up the current remaining estimate for {task.name}.\n"
                "How many more hours are needed? Enter 0 if complete.", parent=self.root)
            if answer is None:
                return
            try:
                revised = hours_to_minutes(answer, allow_zero=True)
            except ValueError as exc:
                messagebox.showerror("Invalid remaining time", str(exc), parent=self.root)
                return
        try:
            add_study_entry(self.data, date.fromisoformat(day_text), task, activity, expected, actual, revised)
        except ValueError as exc:
            messagebox.showerror("Invalid activity", str(exc), parent=self.root)
            return
        self.changed()
        self.log_activity.set("")
        self.log_actual.set("")
        if task is not None and task.overrun_minutes:
            messagebox.showinfo("Over estimate",
                                f"Actual study is {format_minutes(task.overrun_minutes)} over the "
                                f"{format_minutes(task.total_minutes)} estimate.\n"
                                f"Remaining work: {format_minutes(task.remaining_minutes)}.", parent=self.root)

    def generate(self):
        if not self.ensure_current_date():
            return
        try:
            plan = generate_plan(self.data, self.current_monday, 7, earliest_day=date.today())
        except (ValueError, OverflowError) as exc:
            messagebox.showerror("Cannot generate plan", str(exc), parent=self.root)
            return
        self.plan_text = save_plan_snapshot(self.data, plan)["text"]
        self.plan_view.configure(state="normal")
        self.plan_view.delete("1.0", "end")
        self.plan_view.insert("1.0", self.plan_text)
        self.plan_view.configure(state="disabled")
        self.refresh_log_display()
        if self.persist():
            self.status.set("Plan saved. Expected is fixed for dates already logged; future unlogged dates can be replanned.")

    def generate_next(self):
        if not self.ensure_current_date():
            return
        try:
            plan = generate_plan(self.data, self.next_monday, 7)
        except (ValueError, OverflowError) as exc:
            messagebox.showerror("Cannot generate next-week plan", str(exc), parent=self.root)
            return
        save_plan_snapshot(self.data, plan)
        self.show_next_draft()
        if self.persist():
            self.status.set("Next-week draft saved from current actual progress. Update it again when ready.")

    def load_demo(self):
        if not self.ensure_current_date():
            return
        has_data = (self.data["courses"] or self.data["tasks"] or
                    self.data["week_capacity"] or self.data["study_log"] or
                    self.data["archived_overrides"] or self.data["plan_drafts"])
        if has_data and not messagebox.askyesno("Replace existing data",
                                                "Demo data will replace all courses, tasks and study time. Continue?",
                                                parent=self.root):
            return
        self.data = create_demo_data(date.today())
        self.clear_task_fields()
        self.changed()
        self.refresh_all(refresh_hours=True)
        if not self.unsaved_changes:
            self.status.set("Demo loaded. Open This Week Plan and click Generate This Week.")


def main():
    try:
        data = load()
    except DataError as exc:
        print(f"DATA ERROR: {exc}\nOriginal file left untouched: {DATA_PATH}")
        return
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print("Cannot open Tkinter window. Check that Tcl/Tk is installed with your Python.")
        print(f"Details: {exc}")
        return
    app = StudyFlowGUI(root, data)
    if data["archived_overrides"]:
        app.status.set("Old date overrides were archived in JSON and no longer affect plans.")
    root.mainloop()


if __name__ == "__main__":
    main()
