from pathlib import Path
from rich.console import Console
from rich.prompt import Confirm, Prompt
from typer import prompt
from fastoblig.canvas import CanvasClient
from fastoblig.storage import Storage, SubmissionResult, UpdateResult
from rich.table import Table
from fastoblig.domain import Submission
from fastoblig.utils import GitProgressbar
import pygit2

def list_course(client: CanvasClient, storage: Storage, console: Console, offline: bool):
    if not offline:
        courses = client.get_courses()
        if courses and len(courses) > 0:
            table = Table("id", "code", "year", "semester", "title", "state")
            for c in courses:
                state = None
                if storage.get_course(c.id):
                    state = "WATCHING"
                table.add_row(str(c.id), c.code, str(c.year), c.semester, c.description, state)
            console.print(table)
        else:
            console.print("[orange]Cannot find any courses for your user in the LMS ?!")
    else:
        courses = storage.get_courses()
        if courses and len(courses) > 0:
            table = Table("id", "code", "year", "semester", "title", "state")
            for c in courses:
                state = "WATCHING"
                table.add_row(str(c.id), c.code, str(c.year), c.semester, c.description, state)
            console.print(table)
        else:
            console.print("Cannot find any locally stored course data! You are not watching any couse a.t.m. ?")


def watch_course(client: CanvasClient, storage: Storage, console: Console, course: int, transient: bool):
    courses = client.get_courses()
    matches = [c for c in courses if c.id == course]
    if len(matches) > 0:
        if not transient:
            storage.upsert_course(matches[0])
        students = client.get_enrollments(course)
        if students and len(students) > 0:
            # file = None
            # TODO: remove write_csv option and replace with a dedicated statistic method
            # if write_csv:
            #     file = open(write_csv, "w")
            #     file.write("id,student_no,firstname,lastname,email\n")
            table = Table("id", "student_no", "firstname", "lastname", "email")
            for s in students:
                style = None
                if not transient:
                    result = storage.upsert_enrollment(course, s)
                    if result == UpdateResult.NEW:
                        style = 'green'

                table.add_row(str(s.id), str(s.student_no), s.firstname, s.lastname, s.email, style=style)
            console.print(table)
    else:
        console.print(f"Course with id '{course}' not found :exclamation:")

def print_submission_table(console: Console, update_map: SubmissionResult):
    table = Table("id", "state", "group", "students", "repo" , "delivered")
    counter = 0
    for s in sorted(update_map, key=lambda x: x.submission_group_name if x.submission_group_name is not None else "ZZZ"):
        sid = s.id
        id_print = str(sid)
        style = None
        if update_map[sid] == UpdateResult.NEW:
            style = "green"
            id_print = f"+ {id_print}"
        elif update_map[sid] == UpdateResult.MODIFIED:
            style = "yellow"
            id_print = f"~ {id_print}"
        elif update_map[sid] == UpdateResult.REMOVED:
            style = "red"
            id_print = f"- {id_print}"

        table.add_row(
            id_print,
            s.state.name,
            str(s.submission_group_name), 
            str(s.contributions), 
            s.content, 
            s.submitted_at.isoformat() if s.submitted_at is not None else None, 
            style=style)
        counter += 1
    console.print(table)
    console.print(f"[bold]{counter}[/bold] Entries")


def list_exercises(client: CanvasClient, storage: Storage, console: Console, course: int, offline: bool):
    """
    Prints a table with all the exercises in the given course (by id).
    If offline option is specified, the LMS will not be contacted, i.e. only locally stored 
    exercises will be shown.
    """
    if offline:
        exercises = storage.get_exercises()
    else:
        exercises = client.get_exercises(course)
    table = Table("id", "name", "group", "deadline", "state" , "grading", "points")
    for e in sorted(exercises):
        if not offline:
            stored_e = storage.get_exercise(e.id)
            if stored_e is not None:
                e = stored_e
        table.add_row(str(e.id),
                      e.name, e.category,
                      e.deadline.isoformat() if e.deadline is not None else None,
                      e.print_state(),
                      e.grading_type,
                      str(e.max_points))

    console.print(table)



def download_exercise(
    client: CanvasClient,
    storage: Storage,
    console: Console,
    course: int, 
    exercise: int,
    work_dir: Path ,
    description_repo: str | None,
    repo_branch: str = "main",
    repo_file: str = "README.MD"
):
    # Step 1: Retrieve from LMS
    exercises = client.get_exercises(course)

    # Step 2: Finding the exercise with given ID
    match = [e for e in exercises if e.id == exercise]
    if len(match) > 0:
        e = match[0]
        console.print(f"Preparing to grade exercise: {e.id} (\"{e.name}\") :pencil:")

        # Step 3: Setting up grading directories locally
        console.print(f"Grading directory is '{work_dir}':", end=" ")
        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)
            console.print("[green]CREATED[/green]")
        else:
            console.print("[yellow]EXISTED[/yellow]")
        e.grading_path = work_dir.resolve().absolute()

        # Step 4: If repo description provided, set it up
        if description_repo:
            e.description_type = "git_repo"
            e.content = f"{description_repo};{repo_branch};{repo_file}"
            description_folder = work_dir / "exercise"
            if not description_folder.exists():
                console.print(f":arrow_down: Downloading <{description_repo}> at '{repo_branch}' into '{description_folder.absolute()}'")
                progress = GitProgressbar()
                pygit2.clone_repository(description_repo,
                                        str(description_folder.resolve()),
                                        checkout_branch=repo_branch,
                                        callbacks=progress)
                progress.fin()
                console.print("You may want to inspect and update the exercise description here before starting to assess submissions :wink:")
        # FEATURE: in the future one may want to support different types of exercise descriptions here

        # Step 5: check for submission group
        group_categories = client.get_group_categories_in_course(e.course)
        group_set_needs_attention = False
        if e.submission_category_id is None:
            console.print("[orange]Attention: This exercise does not have a [it]submission group category[/it] configured![/orange] ")
            group_set_needs_attention = True
        elif e.submission_category_id not in group_categories.select('group_category_id').to_series().to_list():
            console.print(f"[orange]Attention: The specified [it]submission group category[/it] does not exist in this course context![/orange] ")
            e.submission_category_id = None
            group_set_needs_attention = True

            
        if group_set_needs_attention:
            group_set_needs_attention = Confirm.ask("Do you want to specify another [it]submission group category[/it] manually?", default=True)

        if group_set_needs_attention:
            cat_table = Table("ID", "Group Category")
            for row in group_categories.iter_rows():
                cat_table.add_row(str(row[0]), row[1])
            console.print(cat_table)
            group_category = Prompt.ask("Enter group category ID")
            e.submission_category_id = int(group_category)

        if e.submission_category_id is not None:
            console.print("Downloading student group memberships...")
            students_in_groups = client.get_student_in_groups(e.course, e.submission_category_id)
            storage.insert_group_memberships(students_in_groups)
        
        storage.upsert_exercise(e)
        storage.set_current_exercise(e.id)

        console.print("You may now use the 'submissions' subcommand to start grading individual submissions")
    else:
        console.print(f"Exercise with id '{exercise}' not found in course '{course}'!")




def grade_submission():
    # TODO: make work again
    # all_subs = storage.get_submissions(exercise)
    # exercs = storage.get_exercise(course, exercise)
    # relevant_subs = [s for s in all_subs if s.id == submission]
    # if len(relevant_subs) == 1 and exercs:
    #     sub = relevant_subs[0]
    #
    #     if reset and sub.state != SubmissionState.UNSUBMITTED:
    #         do_reset(exercs, sub, reset)
    #         return
    #
    #
    #     if sub.state == SubmissionState.UNSUBMITTED:
    #         console.print(":thumbsdown: Sorry! But the submision is not submitted and can therefore not be assessed!")
    #     
    #
    #     elif sub.state == SubmissionState.SUBMITTED:
    #         if sub.extended_to is not None and sub.submitted_at is not None:
    #             if sub.submitted_at < sub.extended_to:
    #                 timeliness = "[green]on time[/green]"
    #             else:
    #                 timeliness = f"[red]late[/red] submitted: '{sub.submitted_at.isoformat()}', due: '{sub.extended_to.isoformat()}'"
    #             console.print(f":nine_o’clock: Submission was {timeliness}!")
    #
    #         do_checkout(exercs, sub)
    #
    #     elif proceed and sub.state not in {SubmissionState.PASSED, SubmissionState.FAILED}:
    #         lang_arg : Literal['EN', 'NO', 'DE'] = "NO"
    #         if lang:
    #             if lang == "NO":
    #                 lang_arg = "NO"
    #             elif lang == 'EN':
    #                 lang_arg = "EN"
    #             elif lang == "DE":
    #                 lang_arg = "DE"
    #             else:
    #                 console.print(f"[red] Unknown/unsupported language: {lang}")
    #                 return
    #
    #         do_next_step(
    #             exercs,
    #             sub,
    #             lang=lang_arg,
    #             test_pytest=test_pytest,
    #             test_shell=test_shell,
    #             test_deamon=test_deamon,
    #             baseline_ts=baseline_ts,
    #             ignore_file_pattern=ignore_file_pattern,
    #             comment=comment
    #         )
    #
    #     else:
    #         console.print(f"Submission is currently in state {sub.state}. Did you maybe forget to provide the '--proceed' option?")
    # else:
    #     console.print(f":boom: Submission with id={submission} is not found for exercise={exercise}!")
    pass
