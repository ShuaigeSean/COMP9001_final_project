# StudyFlow — Intelligent Study Planner

StudyFlow helps students manage coursework, deadlines, and study time across several courses. Set your daily availability, generate a weekly plan, and record what you actually studied. The planner uses deadline-based rules to suggest what to work on and identify tasks that may not fit before their due dates.

The app includes a Tkinter desktop interface and a terminal interface. It works locally using the Python standard library, with no internet connection, AI API, or third-party Python packages required.

## Features

- Add courses and create, edit, complete, or delete tasks.
- Track estimated total time, actual study time, and estimated remaining work separately.
- Set dated daily availability for the current week and next week.
- Generate a plan that prioritises earlier deadlines and respects daily capacity.
- Record task work and other activities, with planned-versus-actual comparisons.
- Keep a next-week draft and update it manually from actual progress.
- Browse previous weeks using date ranges.
- Save tasks, progress, plans, and history in a local JSON file.
- Load optional demo tasks with dates relative to the current day.

## Requirements

- Python **3.8 or newer**; development and testing used Python 3.10 on Windows.
- Tcl/Tk support for the desktop interface.

No `pip install` step is needed. To check whether Tkinter is available, run:

```bash
python -m tkinter
```

This should open a small example window. If Tcl/Tk is unavailable, the terminal interface can still be used.

## Getting started

Clone the repository and open its folder:

```bash
git clone https://github.com/ShuaigeSean/COMP9001_final_project.git
cd COMP9001_final_project
```

Start the desktop app:

```bash
python gui.py
```

Or start the terminal menu:

```bash
python main.py
```

On systems where Python is named `python3`, replace `python` in these commands with `python3`.

## Using the desktop app

### 1. Courses & Tasks

Click **Add Course**, then choose a course and enter a task name, due date, and total estimated hours. Click **Add Task** to save it. New tasks initially have the same estimated remaining time as their total estimate.

Select a task in the table to update its details, delete it, mark it complete, or use **Log Study** to open the study log with that task selected. When updating a task, remaining hours are a separate forecast; entering `0` marks the task complete.

Use `YYYY-MM-DD` for dates. Hours accept exact whole-minute values such as `1.5`, `0.25`, or `1:30`. A task's initial estimate must be positive.

### 2. Study Time

Enter the hours available on each dated weekday and click **Save Weekly Hours**. Each day can have between `0` and `24` hours. These settings apply to the displayed week; next week's hours are set separately.

Use **Daily Study Log** to record actual work:

1. Select a date from the current Monday through today.
2. Choose a task, or **Other activity** for work outside the task list.
3. Describe what you did and enter the actual hours.
4. Click **Save Activity**.

Task-linked entries update the task's actual and remaining time. Other activities contribute to daily totals and consume available study time without changing any task. Completed tasks can receive missing actual study records while remaining complete.

**Expected** comes from the saved task plan for that date. Generate the current week's plan before recording new work to establish this baseline. The planned amount is counted once per task/date, so several records for the same task cannot multiply its expected time. Other activities have an Expected value of `0`.

If actual study uses up the remaining estimate, the app asks how much work is still needed. Enter a positive value to keep the task open, or `0` if it is complete. Actual time beyond the total estimate produces an over-estimate message.

### 3. This Week Plan

Click **Generate This Week** to schedule the current week's remaining work and save the plan. Past dates show their configured capacity and recorded actual work; they are not scheduled again.

For example, a day with two hours of capacity and one hour already logged has one hour left for new planned work. Generating a plan does not count scheduled work as completed study.

### 4. Next Week Plan

Set next week's hours, click **Save Next Week Hours**, then click **Create Draft**. The draft is saved and stays unchanged while you record this week's actual work.

When reviewing the week, use **Update Draft from Actual Progress** to regenerate it from the latest task progress. Work merely scheduled for this week is not counted as completed. When the draft's week becomes current, it can be opened in **This Week Plan**.

### 5. Past Weeks

Select a date range to view previous activities, configured capacity, planned baseline, and actual time. Saved plan baselines include scheduled work even when no activity was recorded for it.

## Scheduling rules

1. Unfinished tasks are ordered by earliest deadline.
2. Equal deadlines use larger remaining work first, then lower task ID.
3. A task can span days, and a day can contain several tasks.
4. Actual work already logged for a date reduces that day's available capacity, down to a minimum of zero.
5. The deadline date is usable through the end of that day. On-time work is never assigned after its deadline.
6. Tasks already overdue when planning begins receive clearly labelled catch-up time after tasks that still have valid deadlines.
7. Deadline risk is assessed for tasks due within the displayed week. Later deadlines are left unevaluated because future availability may not be configured.

Saved Expected baselines remain fixed for past dates and dates already logged. Regeneration can update future dates that have no study records. Missing historical plans cannot be reconstructed from current task progress, so the app does not invent their Expected values.

This is a simple greedy scheduler. It does not claim to find every optimal schedule or create hour-by-hour appointments.

## Data and demo mode

The app automatically saves changes to **`studyflow_data.json` beside the Python files**, regardless of the terminal's working directory. It creates this file when needed; a missing file is a normal first start.

The file stores courses, task progress, dated weekly capacity, study logs, and saved plans. Writes use a temporary file before replacing the previous data. Invalid or unreadable saved data produces an error and is left untouched. If a save fails, changes remain in memory and **Retry Save** can be used.

**Load Demo replaces existing app data after confirmation**, including task and activity records. The built-in demo creates tasks and availability, with due dates relative to today; it does not create past-week history.

Local study data, backups, cached Python files, and old text exports are excluded from Git by `.gitignore`. A fresh clone therefore starts without the developer's personal records or manually added demo history.

## Project files

| File | Purpose |
| --- | --- |
| `gui.py` | Desktop entry point, event handling, and view updates |
| `gui_views.py` | Tkinter page layout and widget creation |
| `main.py` | Terminal entry point and menus |
| `models.py` | Task and activity models, shared creation and recording operations |
| `planner.py` | Scheduling, capacity calculations, saved baselines, and plan display text |
| `storage.py` | JSON validation, older-data compatibility, loading, and saving |
| `input_utils.py` | Shared exact conversion between hours and integer minutes |
| `test_planner.py` | Scheduling and persistence tests |
| `test_regressions.py` | Regression tests for capacity, progress, input, and data consistency |
| `test_gui.py` | Tkinter workflow, save-failure, and date-change tests |

## Tests

Run all tests from the project folder:

```bash
python -m unittest -v
```

The current suite contains **27 tests**, covering capacity limits, deadlines, task progress, stable Expected values, saved drafts, older data, invalid input, and desktop workflows. Tkinter tests skip if a usable window environment is unavailable.

To run the core tests without opening Tkinter windows:

```bash
python -m unittest -v test_planner test_regressions
```

## Current limitations

- Study-log entries cannot currently be edited or deleted.
- Use one app instance at a time; the terminal and desktop versions share the same data file.
- If the date changes while the desktop app is open, reopen it to refresh the dated controls.
- Editing a task's total estimate changes the reference used for its over-estimate comparison.

## COMP9001 context

StudyFlow was developed as a COMP9001 Python project. It applies file reading and writing to preserve real study progress, and exception handling to manage invalid input and file errors. Classes, lists, dictionaries, sorting, and date arithmetic support the task models and scheduling rules.
