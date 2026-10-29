"""StudyFlow terminal entry point. Run with: python main.py"""

from datetime import date, timedelta
from input_utils import hours_to_minutes

from models import add_study_entry, create_course, create_demo_data, create_task
from planner import (available_minutes, expected_minutes_for_task, format_minutes,
                     generate_plan, save_plan_snapshot, week_start)
from storage import DATA_PATH, DataError, load, save, valid_date


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
unsaved_changes = False


def ask_text(prompt, default=None):
    """Get a nonempty value; Enter can retain a value during editing."""
    while True:
        value = input(prompt).strip()
        if value:
            return value
        if default is not None:
            return default
        print("Please enter a nonempty value.")


def ask_date(prompt, default=None):
    while True:
        value = input(prompt).strip()
        if not value and default is not None:
            return default
        if valid_date(value):
            return value
        print("Enter a valid date in YYYY-MM-DD format.")


def ask_current_week_date():
    """Accept actual work only from this Monday through today."""
    today = date.today()
    monday = week_start(today)
    while True:
        value = ask_date(f"Study date [{today.isoformat()}]: ", today.isoformat())
        if monday <= date.fromisoformat(value) <= today:
            return date.fromisoformat(value)
        print(f"Choose a date from {monday} through {today}.")


def ask_hours(prompt, allow_zero=False, default=None, maximum=None):
    """Convert decimal hours to exact whole minutes and reject nonfinite input."""
    while True:
        value = input(prompt).strip()
        if not value and default is not None:
            return default
        try:
            return hours_to_minutes(value, allow_zero=allow_zero, maximum=maximum)
        except ValueError as exc:
            print(exc)


def ask_int(prompt, minimum=1, maximum=None, default=None):
    while True:
        value = input(prompt).strip()
        if not value and default is not None:
            return default
        try:
            number = int(value)
            if number < minimum or (maximum is not None and number > maximum):
                raise ValueError
            return number
        except ValueError:
            print(f"Enter an integer from {minimum}" + (f" to {maximum}." if maximum else "."))


def ask_choice(prompt, choices):
    while True:
        value = input(prompt).strip()
        if value in choices:
            return value
        print("Choose one of: " + ", ".join(choices))


def persist(data):
    global unsaved_changes
    try:
        save(data)
        unsaved_changes = False
        print(f"Saved to {DATA_PATH}.")
        return True
    except DataError as exc:
        unsaved_changes = True
        print(f"SAVE FAILED: {exc} Changes remain in memory; retry from the menu.")
        return False


def show_courses(data):
    if not data["courses"]:
        print("No courses yet.")
    for number, course in enumerate(data["courses"], 1):
        print(f"{number}. {course}")


def choose_course(data, default=None):
    if not data["courses"]:
        print("Add a course first.")
        return None
    show_courses(data)
    if default is not None:
        print(f"Press Enter to keep {default}.")
    while True:
        value = input("Course number: ").strip()
        if not value and default is not None:
            return default
        try:
            number = int(value)
            if 1 <= number <= len(data["courses"]):
                return data["courses"][number - 1]
        except ValueError:
            pass
        print("Choose an existing course number.")


def show_tasks(data):
    if not data["tasks"]:
        print("No tasks yet.")
    for task in sorted(data["tasks"], key=lambda item: (item.due, item.id)):
        state = "Complete" if task.complete else "Open"
        overrun = f" | OVER ESTIMATE by {format_minutes(task.overrun_minutes)}" if task.overrun_minutes else ""
        print(f"#{task.id} | {task.course} | {task.name} | due {task.due} | "
              f"remaining {format_minutes(task.remaining_minutes)} | "
              f"actual {format_minutes(task.spent_minutes)} / estimated {format_minutes(task.total_minutes)} | "
              f"{state}{overrun}")


def choose_task(data):
    if not data["tasks"]:
        print("No tasks yet.")
        return None
    show_tasks(data)
    while True:
        task_id = ask_int("Task ID (0 to cancel): ", minimum=0)
        if task_id == 0:
            return None
        for task in data["tasks"]:
            if task.id == task_id:
                return task
        print("That task ID does not exist.")


def add_course(data):
    while True:
        name = ask_text("Course name: ")
        if create_course(data, name):
            persist(data)
            return
        print("That course already exists.")


def add_task(data):
    course = choose_course(data)
    if course is None:
        return
    name = ask_text("Task name: ")
    due = ask_date("Due date (YYYY-MM-DD): ")
    total = ask_hours("Estimated hours (e.g. 1.5): ")
    task = create_task(data, course, name, due, total)
    persist(data)
    print(f"Created task #{task.id}.")


def edit_task(data):
    task = choose_task(data)
    if task is None:
        return
    print("Press Enter to keep each current value.")
    course = choose_course(data, task.course)
    name = ask_text(f"Name [{task.name}]: ", task.name)
    due = ask_date(f"Due date [{task.due}]: ", task.due)
    print(f"Actual study recorded: {format_minutes(task.spent_minutes)}.")
    total = ask_hours(f"Total estimated hours [{format_minutes(task.total_minutes)}]: ",
                      default=task.total_minutes)
    remaining = ask_hours(f"Estimated remaining hours [{format_minutes(task.remaining_minutes)}] "
                          "(0 marks complete): ", allow_zero=True, default=task.remaining_minutes)
    task.course, task.name, task.due = course, name, due
    task.total_minutes = total
    task.remaining_minutes = remaining
    persist(data)


def delete_task(data):
    task = choose_task(data)
    if task and ask_choice(f"Delete task #{task.id}? (y/n): ", {"y", "n"}) == "y":
        data["tasks"].remove(task)
        persist(data)


def record_study(data):
    task = choose_task(data)
    if task is None:
        return
    day = ask_current_week_date()
    activity = ask_text(f"What did you do? [{task.name}]: ", task.name)
    expected = expected_minutes_for_task(data, day, task.id)
    print(f"Expected from this week's plan: {format_minutes(expected)}.")
    snapshot = data["plan_drafts"].get(week_start(day).isoformat(), {})
    if day.isoformat() not in snapshot.get("allocations", {}):
        print("No saved daily plan exists for this date; its missing Expected hours cannot be reconstructed.")
    minutes = ask_hours("Actual hours studied: ", maximum=1440)
    revised = None
    if not task.complete and minutes >= task.remaining_minutes:
        print("The current remaining estimate has been used up.")
        revised = ask_hours("Estimated hours still needed (0 if complete): ", allow_zero=True)
    try:
        add_study_entry(data, day, task, activity, expected, minutes, revised)
    except ValueError as exc:
        print(f"Activity was not saved: {exc}")
        return
    persist(data)
    print(f"Actual: {format_minutes(task.spent_minutes)}; remaining estimate: "
          f"{format_minutes(task.remaining_minutes)}.")
    if task.overrun_minutes:
        print(f"OVER ESTIMATE by {format_minutes(task.overrun_minutes)}.")


def complete_task(data):
    task = choose_task(data)
    if task and not task.complete:
        task.remaining_minutes = 0
        persist(data)
        print("Task marked complete.")


def show_availability(data):
    monday = week_start(date.today())
    print(f"This week's planning capacity: {monday} to {monday + timedelta(days=6)}")
    hours = data["week_capacity"].get(monday.isoformat(), [0] * 7)
    for index, minutes in enumerate(hours):
        print(f"{WEEKDAYS[index]} {monday + timedelta(days=index)}: {format_minutes(minutes)}")


def set_weekly(data):
    monday = week_start(date.today())
    hours = list(data["week_capacity"].get(monday.isoformat(), [0] * 7))
    print(f"Set planning capacity for {monday} to {monday + timedelta(days=6)}.")
    for index, day in enumerate(WEEKDAYS):
        hours[index] = ask_hours(f"{day} {monday + timedelta(days=index)} "
                                 f"[{format_minutes(hours[index])}]: ",
                                 allow_zero=True, default=hours[index], maximum=1440)
    data["week_capacity"][monday.isoformat()] = hours
    persist(data)


def plan_next_week(data):
    monday = week_start(date.today()) + timedelta(days=7)
    hours = list(data["week_capacity"].get(monday.isoformat(), [0] * 7))
    print(f"Set next-week capacity for {monday} to {monday + timedelta(days=6)}.")
    for index, day in enumerate(WEEKDAYS):
        hours[index] = ask_hours(f"{day} {monday + timedelta(days=index)} "
                                 f"[{format_minutes(hours[index])}]: ",
                                 allow_zero=True, default=hours[index], maximum=1440)
    data["week_capacity"][monday.isoformat()] = hours
    snapshot = save_plan_snapshot(data, generate_plan(data, monday, 7))
    if persist(data):
        print("Next-week draft saved. Run this option again when ready to align it with actual progress.")
    print(snapshot["text"])


def log_other_activity(data):
    day = ask_current_week_date()
    activity = ask_text("What did you do? ")
    expected = 0
    print("Expected from plan: 0h 00m (other activity).")
    actual = ask_hours("Actual hours: ", maximum=1440)
    try:
        add_study_entry(data, day, None, activity, expected, actual)
    except ValueError as exc:
        print(f"Activity was not saved: {exc}")
        return
    persist(data)
    print("Other activity saved; task progress was not changed.")


def show_study_log(data):
    if not data["study_log"]:
        print("No daily activities recorded yet.")
        return
    for entry in sorted(data["study_log"], key=lambda item: (item.date, item.id), reverse=True):
        target = "Other" if entry.task_id is None else f"Task #{entry.task_id}"
        difference = entry.actual_minutes - entry.expected_minutes
        sign = "+" if difference >= 0 else "-"
        print(f"{entry.date} | {target} | {entry.activity} | expected "
              f"{format_minutes(entry.expected_minutes)} | actual {format_minutes(entry.actual_minutes)} "
              f"| difference {sign}{format_minutes(abs(difference))}")
    today = date.today()
    actual_today = sum(entry.actual_minutes for entry in data["study_log"] if entry.date == today.isoformat())
    print(f"Today: actual {format_minutes(actual_today)} / planning capacity "
          f"{format_minutes(available_minutes(data, today))}.")


def make_plan(data):
    monday = week_start(date.today())
    try:
        plan = generate_plan(data, monday, 7, earliest_day=date.today())
    except (ValueError, OverflowError) as exc:
        print(f"Cannot generate plan: {exc}")
        return
    snapshot = save_plan_snapshot(data, plan)
    persist(data)
    print("\n" + snapshot["text"])


def load_demo(data):
    if (data["courses"] or data["tasks"] or data["week_capacity"] or
            data["study_log"] or data["archived_overrides"] or data["plan_drafts"]):
        print("Demo data will replace all existing courses, tasks, daily logs and availability.")
        if ask_choice("Type REPLACE to continue, or n to cancel: ", {"REPLACE", "n"}) != "REPLACE":
            return data
    demo = create_demo_data(date.today())
    persist(demo)
    print("Demo loaded. Generate a 7-day plan to see deadline pressure and a later task.")
    return demo


def run():
    global unsaved_changes
    unsaved_changes = False
    try:
        data = load()
    except DataError as exc:
        print(f"DATA ERROR: {exc}")
        print(f"Original file left untouched: {DATA_PATH}")
        print("Repair or move the file, then restart StudyFlow.")
        return
    print("StudyFlow - Intelligent Study Planner")
    print(f"Data file: {DATA_PATH}")
    if data["archived_overrides"]:
        print("Previous date overrides were archived in JSON and no longer affect plans.")
    actions = {
        "1": lambda: add_course(data), "2": lambda: show_courses(data),
        "3": lambda: add_task(data), "4": lambda: show_tasks(data),
        "5": lambda: edit_task(data), "6": lambda: delete_task(data),
        "7": lambda: record_study(data), "8": lambda: complete_task(data),
        "9": lambda: show_availability(data), "10": lambda: set_weekly(data),
        "11": lambda: show_study_log(data), "12": lambda: log_other_activity(data),
        "13": lambda: make_plan(data), "14": lambda: persist(data),
        "16": lambda: plan_next_week(data),
    }
    while True:
        print("\n1 Add course  2 View courses  3 Add task  4 View tasks")
        print("5 Edit task   6 Delete task   7 Log task study   8 Mark complete")
        print("9 View weekly capacity  10 Set weekly hours  11 View daily log  12 Log other activity")
        print("13 This-week plan  14 Retry save  15 Load demo data  16 Next-week plan  0 Exit")
        choice = ask_choice("Choice: ", set(actions) | {"0", "15"})
        if choice == "0":
            if unsaved_changes:
                action = ask_choice("Unsaved changes: retry save (r), discard and exit (d), or cancel (c): ",
                                    {"r", "d", "c"})
                if action == "c" or (action == "r" and not persist(data)):
                    continue
            print("Goodbye.")
            return
        if choice == "15":
            data = load_demo(data)
        else:
            actions[choice]()


if __name__ == "__main__":
    try:
        run()
    except (EOFError, KeyboardInterrupt):
        if unsaved_changes:
            print("\nWarning: the last save failed; changes in memory have not been saved.")
        print("\nGoodbye.")
