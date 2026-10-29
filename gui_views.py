"""Build the StudyFlow desktop pages; callbacks remain in gui.py."""

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def build_tasks(app):
    """Create the course and task controls."""
    top = ttk.Frame(app.tasks_tab)
    top.pack(fill="x")
    ttk.Label(top, text="Courses").pack(side="left")
    app.course_list = tk.StringVar(value="None")
    ttk.Label(top, textvariable=app.course_list).pack(side="left", padx=10)
    ttk.Button(top, text="Add Course", command=app.add_course).pack(side="right")

    columns = ("id", "course", "name", "due", "remaining", "actual", "status")
    table_frame = ttk.Frame(app.tasks_tab)
    table_frame.pack(fill="both", expand=True, pady=10)
    app.task_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
    headings = {"id": "ID", "course": "Course", "name": "Task", "due": "Due date",
                "remaining": "Remaining", "actual": "Actual / Estimate", "status": "Status"}
    widths = {"id": 50, "course": 135, "name": 260, "due": 105,
              "remaining": 100, "actual": 150, "status": 130}
    for column in columns:
        app.task_tree.heading(column, text=headings[column])
        app.task_tree.column(column, width=widths[column], minwidth=50)
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=app.task_tree.yview)
    app.task_tree.configure(yscrollcommand=scrollbar.set)
    app.task_tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    app.task_tree.bind("<<TreeviewSelect>>", app.fill_task_fields)

    form = ttk.LabelFrame(app.tasks_tab, text="Task details", padding=10)
    form.pack(fill="x")
    for column in range(4):
        form.columnconfigure(column, weight=1)
    app.task_course = tk.StringVar()
    app.task_name = tk.StringVar()
    app.task_due = tk.StringVar(value=date.today().isoformat())
    app.task_hours = tk.StringVar()
    app.task_remaining = tk.StringVar()
    ttk.Label(form, text="Course").grid(row=0, column=0, sticky="w")
    ttk.Label(form, text="Task name").grid(row=0, column=1, sticky="w")
    ttk.Label(form, text="Due date (YYYY-MM-DD)").grid(row=0, column=2, sticky="w")
    ttk.Label(form, text="Total hours (1.5 or 1:30)").grid(row=0, column=3, sticky="w")
    app.course_box = ttk.Combobox(form, textvariable=app.task_course, state="readonly")
    app.course_box.grid(row=1, column=0, sticky="ew", padx=(0, 7))
    ttk.Entry(form, textvariable=app.task_name).grid(row=1, column=1, sticky="ew", padx=(0, 7))
    ttk.Entry(form, textvariable=app.task_due).grid(row=1, column=2, sticky="ew", padx=(0, 7))
    ttk.Entry(form, textvariable=app.task_hours).grid(row=1, column=3, sticky="ew")
    ttk.Label(form, text="Remaining hours (update; 0 = complete)").grid(row=2, column=3, sticky="w", pady=(7, 0))
    ttk.Entry(form, textvariable=app.task_remaining).grid(row=3, column=3, sticky="ew")
    buttons = ttk.Frame(app.tasks_tab)
    buttons.pack(fill="x", pady=(10, 0))
    for label, command in [("Add Task", app.add_task), ("Update Selected", app.update_task),
                           ("Log Study", app.open_study_log), ("Mark Complete", app.complete_task),
                           ("Delete Selected", app.delete_task), ("Clear Fields", app.clear_task_fields)]:
        ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 7))


def build_time(app):
    """Create weekly capacity controls and the daily study log."""
    ttk.Label(app.time_tab, text="This week's dated hours limit the automatic plan. "
              "Record actual work from this Monday through today below.").pack(anchor="w", pady=(0, 8))
    weekly = ttk.LabelFrame(app.time_tab, text=f"This week: {app.current_monday} to "
                            f"{app.current_monday + timedelta(days=6)}", padding=10)
    weekly.pack(fill="x")
    app.weekly_vars = []
    for index, weekday in enumerate(WEEKDAYS):
        day = app.current_monday + timedelta(days=index)
        ttk.Label(weekly, text=f"{weekday[:3]} {day:%m-%d}").grid(row=0, column=index, sticky="w", padx=5)
        variable = tk.StringVar()
        app.weekly_vars.append(variable)
        ttk.Entry(weekly, textvariable=variable, width=10).grid(row=1, column=index, sticky="w", padx=5)
    ttk.Button(weekly, text="Save Weekly Hours", command=app.save_weekly).grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Button(weekly, text="Plan Next Week →", command=lambda: app.tabs.select(app.next_tab)).grid(
        row=2, column=4, columnspan=3, sticky="e", pady=(10, 0))

    log = ttk.LabelFrame(app.time_tab, text="Daily Study Log", padding=10)
    log.pack(fill="both", expand=True, pady=(12, 0))
    app.log_date = tk.StringVar(value=date.today().isoformat())
    app.log_target = tk.StringVar(value="Other activity")
    app.log_activity = tk.StringVar()
    app.log_expected = tk.StringVar(value="0h 00m")
    app.log_actual = tk.StringVar()
    fields = [("Date (YYYY-MM-DD)", app.log_date, 15),
              ("Task or other work", app.log_target, 27),
              ("What did you do?", app.log_activity, 28),
              ("Expected from plan", app.log_expected, 16),
              ("Actual hours", app.log_actual, 12)]
    for column, (label, variable, width) in enumerate(fields):
        ttk.Label(log, text=label).grid(row=0, column=column, sticky="w", padx=4)
        if column == 1:
            app.log_target_box = ttk.Combobox(log, textvariable=variable, width=width, state="readonly")
            app.log_target_box.grid(row=1, column=column, sticky="ew", padx=4)
        elif column == 0:
            dates = [(app.current_monday + timedelta(days=offset)).isoformat()
                     for offset in range((date.today() - app.current_monday).days + 1)]
            ttk.Combobox(log, textvariable=variable, values=dates, width=width,
                         state="readonly").grid(row=1, column=column, sticky="ew", padx=4)
        elif column == 3:
            ttk.Label(log, textvariable=variable).grid(row=1, column=column, sticky="w", padx=4)
        else:
            ttk.Entry(log, textvariable=variable, width=width).grid(row=1, column=column, sticky="ew", padx=4)
        log.columnconfigure(column, weight=1 if column in (1, 2) else 0)
    ttk.Button(log, text="Save Activity", command=app.save_study_entry).grid(
        row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(10, 4))
    ttk.Label(log, text="Expected: saved plan once per task/date; no saved plan = 0.", wraplength=440).grid(
        row=2, column=2, columnspan=3, sticky="w", padx=4)
    app.log_summary = tk.StringVar()
    ttk.Label(log, textvariable=app.log_summary, wraplength=900).grid(
        row=3, column=0, columnspan=5, sticky="w", padx=4, pady=5)
    columns = ("date", "target", "activity", "expected", "actual", "difference")
    app.log_tree = ttk.Treeview(log, columns=columns, show="headings", height=9)
    headings = {"date": "Date", "target": "Task / Other", "activity": "What you did",
                "expected": "Expected", "actual": "Actual", "difference": "Actual - expected"}
    widths = {"date": 100, "target": 170, "activity": 250,
              "expected": 95, "actual": 95, "difference": 130}
    for column in columns:
        app.log_tree.heading(column, text=headings[column])
        app.log_tree.column(column, width=widths[column], minwidth=70)
    app.log_tree.grid(row=4, column=0, columnspan=5, sticky="nsew", pady=(5, 0))
    log.rowconfigure(4, weight=1)
    app.log_date.trace_add("write", lambda *_: app.refresh_log_display())
    app.log_target.trace_add("write", lambda *_: app.refresh_log_display())


def build_plan(app):
    """Create the current week's plan display."""
    options = ttk.Frame(app.plan_tab)
    options.pack(fill="x")
    ttk.Label(options, text=f"{app.current_monday} to {app.current_monday + timedelta(days=6)}").pack(side="left")
    ttk.Button(options, text="Generate This Week", command=app.generate).pack(side="left", padx=10)
    ttk.Button(options, text="Go to Next Week →", command=lambda: app.tabs.select(app.next_tab)).pack(side="right")
    ttk.Label(app.plan_tab, text="Past days are not scheduled again. Deadline day is included.").pack(
        anchor="w", pady=8)
    app.plan_view = ScrolledText(app.plan_tab, wrap="word", font=("Consolas", 10), state="disabled")
    app.plan_view.pack(fill="both", expand=True)


def build_next(app):
    """Create the next week's capacity and draft controls."""
    ttk.Label(app.next_tab, text=f"Next week: {app.next_monday} to "
              f"{app.next_monday + timedelta(days=6)}").pack(anchor="w", pady=(0, 8))
    weekly = ttk.LabelFrame(app.next_tab, text="Set next week's daily capacity", padding=10)
    weekly.pack(fill="x")
    app.next_week_vars = []
    for index, weekday in enumerate(WEEKDAYS):
        day = app.next_monday + timedelta(days=index)
        ttk.Label(weekly, text=f"{weekday[:3]} {day:%m-%d}").grid(row=0, column=index, padx=5, sticky="w")
        variable = tk.StringVar()
        app.next_week_vars.append(variable)
        ttk.Entry(weekly, textvariable=variable, width=10).grid(row=1, column=index, padx=5, sticky="w")
    ttk.Button(weekly, text="Save Next Week Hours", command=app.save_next_week).grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
    row = ttk.Frame(app.next_tab)
    row.pack(fill="x", pady=10)
    app.next_generate_button = ttk.Button(row, text="Create Draft", command=app.generate_next)
    app.next_generate_button.pack(side="left")
    ttk.Label(row, text="Update the draft from actual progress when you review this week.").pack(
        side="left", padx=8)
    app.next_draft_info = tk.StringVar()
    ttk.Label(app.next_tab, textvariable=app.next_draft_info).pack(anchor="w", pady=(0, 6))
    app.next_plan_view = ScrolledText(app.next_tab, wrap="word", font=("Consolas", 10), state="disabled")
    app.next_plan_view.pack(fill="both", expand=True)


def build_history(app):
    """Create the past-week selector and activity table."""
    row = ttk.Frame(app.history_tab)
    row.pack(fill="x")
    ttk.Label(row, text="Past week").pack(side="left")
    app.history_week = tk.StringVar()
    app.history_box = ttk.Combobox(row, textvariable=app.history_week, state="readonly", width=30)
    app.history_box.pack(side="left", padx=8)
    app.history_box.bind("<<ComboboxSelected>>", lambda _event: app.refresh_history())
    app.history_summary = tk.StringVar()
    ttk.Label(app.history_tab, textvariable=app.history_summary, wraplength=900).pack(anchor="w", pady=12)
    columns = ("date", "target", "activity", "expected", "actual", "difference")
    app.history_tree = ttk.Treeview(app.history_tab, columns=columns, show="headings")
    for column, title, width in [("date", "Date", 100), ("target", "Task / Other", 130),
                                 ("activity", "What you did", 260), ("expected", "Expected", 95),
                                 ("actual", "Actual", 95), ("difference", "Difference", 130)]:
        app.history_tree.heading(column, text=title)
        app.history_tree.column(column, width=width, minwidth=70)
    app.history_tree.pack(fill="both", expand=True)


