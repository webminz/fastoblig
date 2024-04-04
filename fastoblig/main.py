from pathlib import Path
import re
import shutil
from fastoblig.domain import Exercise, Submission, SubmissionState
from fastoblig.storage import GITHUB_TOKEN, Storage, CANVAS_TOKEN, OPENAI_TOKEN, UpdateResult
from typing import Optional
from typer import Typer, get_app_dir, confirm, prompt
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown
from rich.panel import Panel
import os
from fastoblig.canvas import CanvasClient
import pygit2
from fastoblig.utils import GitProgressbar, run_pytest
from fastoblig.feedback import create_system_prompt, collect_submission_files, contact_openai
import xml.etree.ElementTree as ET
from fastoblig.github import upload_issue
import git

APP_NAME = "fastoblig"
console = Console()

def startup():
    if "FASTOBLIG_HOME" in os.environ:
        app_dir = Path(os.environ['FASTOBLIG_HOME'])
    else:
        app_dir = Path(get_app_dir(APP_NAME))
    if not app_dir.exists():
        console.print("This seems to be the first time :tada: for you running FastOBLIG on this system?")
        console.print(f"We will now create the storage home :house: at the following path: '{app_dir.absolute()}'")
        console.print("You may want to set the environment variable '$FASTOBLIG_HOME' if you want to change this location!")
        app_dir.mkdir(parents=True)
    storage = Storage(app_dir)
    return storage


# Domain objects
storage = startup()
client = CanvasClient(storage)

# Typer
app = Typer(no_args_is_help=True)
courses_app = Typer(no_args_is_help=True)
exercises_app = Typer(no_args_is_help=True)
submissions_app = Typer(no_args_is_help=True)
app.add_typer(courses_app, name="courses", help="Show and track your courses in the LMS")
app.add_typer(exercises_app, name="exercises", help="Administer exercises")
app.add_typer(submissions_app, name="submissions", help="Explore and grade exercise submissions")


@app.command("config")
def configure(
    set_canvas_token: Optional[str] = None, 
    set_openai_token: Optional[str] = None,
    set_github_token: Optional[str] = None,
    config_reset: bool = False):
    """
    Set/unset central config parameters.
    """
    if set_canvas_token is None and set_openai_token is None and set_github_token is None and not config_reset:
        console.print(f"FastOBLIG configuration :house: stored at: '{storage.db_file}'")
        console.print("[grey]You may change this by setting the '$FASTOBLIG_HOME' environment variable[/grey]")

    if set_canvas_token:
        storage.set_token(CANVAS_TOKEN, set_canvas_token)
        console.print("Canvas access token updated!")

    if set_openai_token:
        storage.set_token(OPENAI_TOKEN, set_openai_token)
        console.print("OpenAI access token updated!")

    if set_github_token:
        storage.set_token(GITHUB_TOKEN, set_github_token)
        console.print("GitHub access token updated!")

    if config_reset:
        really = confirm("Do you really want to reset the cofiguration? All data will be lost!", abort=True)
        if really:
            storage.reset_db()




@courses_app.command(name="list")
def list_courses():
    """
    Shows all courses registered for the current user in the LMS backend.
    """
    courses = client.get_courses()
    if courses and len(courses) > 0:
        table = Table("id", "code", "year", "semester", "title", "state")
        for c in courses:
            state = None
            if storage.get_course(c.id):
                state = "TRACKING"
            table.add_row(str(c.id), c.code, str(c.year), c.semester, c.description, state)
        console.print(table)


@courses_app.command(name="track")
def track_course(course: int, write_csv: Optional[Path] = None):
    """
    Starts tracking this course, i.e. downloads the list of student enrollments and stores course information.
    """
    courses = client.get_courses()
    matches = [c for c in courses if c.id == course]
    if len(matches) > 0:
        storage.upsert_course(matches[0])
        students = client.get_enrollments(course)
        if students and len(students) > 0:
            file = None
            if write_csv:
                file = open(write_csv, "w")
                file.write("id,student_no,firstname,lastname,email\n")
            table = Table("id", "student_no", "firstname", "lastname", "email")
            for s in students:
                style = None
                # TODO: the tracking of enrollment should better be done similar to submissions
                result = storage.upsert_enrollment(course, s)
                if result == UpdateResult.NEW:
                    style = 'green'

                table.add_row(str(s.id), str(s.student_no), s.firstname, s.lastname, s.email, style=style)

                if file:
                    file.write(str(s.id))
                    file.write(",")
                    file.write(str(s.student_no))
                    file.write(',"')
                    file.write(s.firstname)
                    file.write('","')
                    file.write(s.lastname)
                    file.write('",')
                    file.write(s.email)
                    file.write("\n")
            if file:
                file.close()
            console.print(table)
    else:
        console.print(f"Course with id '{course}' not found :exclamation:")




@exercises_app.command("list")
def get_exercises(course: int):
    """
    Shows all exercises that are registered for the course in the LMS backend.
    """
    exercises = client.get_exercises(course)
    table = Table("id", "name", "group", "deadline", "state" , "grading", "points")
    for e in sorted(exercises):
        stored_e = storage.get_exercise(e.course, e.id)
        if stored_e is not None:
            e = stored_e
        table.add_row(str(e.id),
                      e.name, e.category,
                      e.deadline.isoformat() if e.deadline is not None else None,
                      e.print_state(),
                      e.grading,
                      str(e.max_points))

    console.print(table)


@exercises_app.command("grade")
def grade_exercise(course: int, 
                   exercise: int,
                   work_dir: Optional[Path] = None,
                   description_repo: Optional[str] = None,
                   repo_file: str = "README.md",
                   repo_branch: str = "main"):
    """
    Begins with the preparations to grade an exercise. i.e. downloads the instructions and submissions.
    """
    exercises = client.get_exercises(course)
    match = [e for e in exercises if e.id == exercise]
    if len(match) > 0:
        e = match[0]
        console.print(f"Preparing to grade exercise: {e.id} (\"{e.name}\") :pencil:")

        if work_dir is None:
            work_dir = Path.cwd() / str(course)
        console.print(f"Grading directory is '{work_dir}':", end=" ")
        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)
            console.print("[green]CREATED[/green]")
        else:
            console.print("[yellow]EXISTED[/yellow]")
        e.grading_path = work_dir.resolve()

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
        
        storage.upsert_exercise(e)
        console.print("Retrieving student submissions from the LMS")
        submissions = client.get_submissions(course, exercise)
        update_map = storage.upsert_submissions(exercise, submissions)
        print_submission_table(update_map, submissions)
        console.print("You may now use the 'submissions' subcommand to start grading individual submissions")
    else:
        console.print(f"Exercise with id '{exercise}' not found in course '{course}'!")

    
def print_submission_table(update_map: dict[int, UpdateResult], submissions: list[Submission]):
    # TODO: show the id column, right aligned
    table = Table("id", "state", "group", "students", "repo" , "delivered")
    submission_map = { s.id: s for s in submissions}
    for sid in update_map.keys():
        id_print = str(sid)
        s = submission_map[sid]
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
        elif update_map[sid] == UpdateResult.REJECTED:
            # TODO: ineffective: use dedidated get_by_id method
            s = [ ss for ss in storage.get_submissions(s.exercise) if ss.id == s.id][0]

        table.add_row(
            id_print,
            s.state.name,
            str(s.submission_group_no), 
            str(s.members), 
            s.content, 
            s.submitted_at.isoformat() if s.submitted_at is not None else None, 
            style=style)
    console.print(table)

            

@submissions_app.command("list")
def get_submissions(course: int, exercise: int):
    """
    Shows all submissions for the given exercise and updates the database of previously stored submissions.
    """
    # TODO: offline option
    result = storage.get_exercise(course, exercise)

    if result is not None:
        console.print(f"Exercise: {result.id} (\"{result.name}\"):")
        submissions = client.get_submissions(course, exercise)
        update_map = storage.upsert_submissions(exercise, submissions)
        print_submission_table(update_map, submissions)
    else: 
        console.print(f"Cannot find exercise with id='{exercise}' in course with id='{course}'!")
        console.print("Remember that you have to start grading an exercise with the subcommand 'exercises grade' before you can see submissions here!")


def do_checkout(exercise: Exercise, submission: Submission):
    if exercise.description_type == "git_repo" and exercise.grading_path is not None and submission.content is not None:
        base_path = exercise.grading_path
        if submission.submission_group_no is not None:
            submission_path = base_path / f"group_{submission.submission_group_no}"
        else:
            submission_path = base_path / str(submission.id)

        console.print(f":file_folder: Working Directory (i.e. local storage) for this submission is: '{submission_path.resolve()}'")
        if submission_path.exists():
            console.print("""Warning: The aforementioned directory exists already!
            Please backup the contents of the folder and delete it so that we can proceed afresh.""")
        else:
            console.print(f":arrow_down: Cloning <{submission.content}> into the above directory")
            try:
                git.Repo.clone_from(submission.content, submission_path)
                submission.state = SubmissionState.CHECKED_OUT
                storage.upsert_submissions(exercise.id, [submission])
                console.print(":wrench: You may now wish to inspect the repository content and make sure that all dependencies are resolved before running tests.")
                console.print(":arrow_forward: You continue the evaluation of the submission by calling 'eval' with same parameters and providing the \"--continue\" option.")
            except git.GitCommandError as e:
                console.print(e, style="red")
            # TODO: copy the logic from sorting towards the relevant commit

    else:
        console.print(f"Exercise is of type: '{exercise.description_type}'! This type of exercise is currently not supported in FastOblig!")


def read_feedback_xml(file_path: str) -> tuple[str | None, str | None]:
    text = None
    assesment = None
    document = ET.parse(file_path)
    root = document.getroot()
    review = root.find("review")
    if review is not None and review.text is not None:
        text = review.text
    ass = root.find("assessment")
    if ass is not None and ass.text is not None:
        assesment = ass.text
    return (text, assesment)


def do_reset(exercise: Exercise, submission: Submission):
    """
    This method resets a submission to the "SUBMITTED"-state.
    It also includes to remove the potentially checked out repository from disk.
    """
    console.print("[orange] --reset was chosen: thus resetting the state of this submission[/orange]")
    if exercise.grading_path:
        base_path = exercise.grading_path
        if submission.submission_group_no is not None:
            submission_path = base_path / f"group_{submission.submission_group_no}"
        else:
            submission_path = base_path / str(submission.id)
        if submission_path.exists():
            shutil.rmtree(submission_path)
            console.print(f"Removed directory: '{submission_path.resolve()}")
    submission.state = SubmissionState.SUBMITTED
    submission.graded_at = None 
    submission.grade = None 
    submission.testresult = None 
    submission.comment = None
    submission.feedback = None
    storage.upsert_submissions(exercise.id, [submission], force=True)
    console.print(f"Submission {submission.id} is back in state: SUBMITTED")


def do_next_step(exercise: Exercise, submission: Submission):
    """
    This method, depending on the current state of the submission in the evaluation procedure, for 
    a submission that already has been downloaded.
    """
    if exercise.grading_path is None:
        console.print("ShouldNotError: exercise has no working directory!")
        return

    base_path = exercise.grading_path
    if submission.submission_group_no is not None:
        submission_path = base_path / f"group_{submission.submission_group_no}"
    else:
        submission_path = base_path / str(submission.id)

    if submission.state == SubmissionState.CHECKED_OUT:
        console.print(":microscope: Running tests with backend: pytest:", end=" ")
        return_code, result = run_pytest(str((submission_path).resolve()))
        result_regex = re.compile(r"=* (.+) =*")
        match = result_regex.match(result.splitlines()[-1])
        if match: 
            console.print(match.group(1))
        else:
            console.print(f"Return code: {return_code}")
        output_file_dir = submission_path / "_fastoblig" 
        output_file_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_file_dir / "testrestult.txt"
        with open(output_file, mode="wt") as f:
            f.write(result)
        console.print(f":floppy_disk: Testresult written to '{output_file}'.")
        submission.state = SubmissionState.TESTED
        submission.testresult = str(output_file.resolve())
        storage.upsert_submissions(submission.exercise, [submission], force=True)
        console.print(":arrow_forward: You may now wish to inspect the test results before proceeding by sending it to GPT.")

    if submission.state == SubmissionState.TESTED:
        course = storage.get_course(exercise.course)
        assert course is not None
        system_prompt = create_system_prompt(exercise.grading_path / "exercise",
                                             "README.md", 
                                             course.description,
                                             exercise.name,
                                             "Norwegian")
        user_prompt = collect_submission_files(submission_path, 
                                               submission.submission_group_no if submission.submission_group_no else submission.id, 
                                               submission.testresult, 
                                               submission.comment)
        access_token = storage.get_token(OPENAI_TOKEN)
        if access_token is None:
            console.print("Sorry! Cannot contact GPT because the OpenAI API token was not set! Use `fastoblig config`!")
            return

        console.print("Asking GPT for a feedback on the submission")
        response = contact_openai(access_token, user_prompt, system_prompt) 
        console.print("Feedback received:")

        # fixing the sometimes weird formatting coming from GPT
        if response.startswith("```xml"):
            response = response[7:-3]
        response_lines = [l.strip() for l in response.splitlines()]
        response = "\n".join(response_lines)
            
        feedback_file = submission_path / "_fastoblig" / "feedback.xml"
        with open(feedback_file, mode="wt") as f:
            f.write(response)

        feedback, score = read_feedback_xml(str(feedback_file.resolve()))

        submission.feedback = str(feedback_file.resolve())
        submission.state = SubmissionState.FEEDBACK_GENERATED
        storage.upsert_submissions(submission.exercise, [submission])

        if feedback is not None:
            console.print(Panel(Markdown(feedback)))
        console.print(f"First initial assesment: {score} ")
        console.print(f"You may now want to inspect the feedback at '{feedback_file.resolve()}' and modify it before sending it" + 
                      "back to the students in the next step")
        return


    if submission.state == SubmissionState.FEEDBACK_GENERATED:
        console.print(f"current state is {submission.state}")
        assert submission.feedback is not None
        feedback, _ = read_feedback_xml(submission.feedback)
        if feedback is not None:
            console.print("Current feedback is:")
            console.print(Panel(Markdown(feedback)))
            assert submission.content is not None
            posted_feedback = False
            if submission.content.startswith("https://github.com"):
                is_confirmed = confirm(f"Do you want to upload this feedback to {submission.content}?")
                if is_confirmed:
                    issue_url = upload_issue(storage.get_token(GITHUB_TOKEN),
                                             submission.content, 
                                             f"Feedback: {exercise.name}",
                                             feedback)
                    posted_feedback = True
                    console.print(f"Feedback posted at: {issue_url}")
                    is_confirmed = confirm(f"Do you want to link to this issue on the LMS submission page?", default=True)
                    if is_confirmed:
                        client = CanvasClient(storage)
                        client.update_submission(exercise.course, exercise.id, submission.members[0], 
                                                 comment=f"Se more details at: {issue_url}")
            else:
                is_confirmed = confirm("Do you want to upload this feedback to the LMS submission page?")
                if is_confirmed:
                    client = CanvasClient(storage)
                    client.update_submission(exercise.course, exercise.id, submission.members[0], 
                                             comment=feedback)
                    posted_feedback = True

            if not posted_feedback:
                is_confirmed = confirm("You did not post the feedback somewhere? Do you want to conclude this step anyways and proceed to the final grading?")
            if posted_feedback or is_confirmed:
                submission.state = SubmissionState.FEEDBACK_PUBLISHED
                storage.upsert_submissions(exercise.id, [submission])
        else:
            console.print(f"Weird... The Feedback content is empty! Please check '{submission.feedback}'")
        return

    if submission.state == SubmissionState.FEEDBACK_PUBLISHED:
        console.print("Entering final stage: ASSESMENT")
        if submission.testresult is not None:
            with open(submission.testresult, mode="rt") as f:
                lines = f.readlines()
                if len(lines) > 0:
                    result_regex = re.compile(r"=* (.+) =*")
                    match = result_regex.match(lines[-1])
                    if match:
                        console.print(f"Testresult was: {match.group(1)}")
        if submission.feedback is not None:
            _, score = read_feedback_xml(submission.feedback)
            if score:
                console.print(f"GPT suggested character grade: {score}")
        client = CanvasClient(storage)
        if exercise.grading == "pass_fail":
            score_input = prompt("Enter grade (pass/complete/fail/incomplete)")
            comment_input = prompt("Comment (optional)", default="")
            client.update_submission(exercise.course, exercise.id, submission.members[0],
                                     comment=comment_input if len(comment_input) > 0 else None,
                                     grading=score_input)
            if score_input in {'complete', 'pass'}:
                submission.state = SubmissionState.PASSED
            else:
                submission.state = SubmissionState.FAILED
        elif exercise.grading == "points":
            score_input = prompt("Enter point score (e.g. 42.0)")
            comment_input = prompt("Comment (optional)", default="")
            client.update_submission(exercise.course, exercise.id, submission.members[0],
                                     comment=comment_input if len(comment_input) > 0 else None,
                                     grading=score_input)
            if float(score_input) > 0:
                submission.state = SubmissionState.PASSED
            else: 
                submission.state = SubmissionState.FAILED

        storage.upsert_submissions(exercise.id, [submission])
        console.print(f":tada: Assessment of submission {submission.id} is now completed!")

        

@submissions_app.command("eval")
def grade_submission(
        course: int,
        exercise: int,
        submission: int,
        reset: bool = False,
        proceed: bool = False):
    # TODO: add option for test-backend, option for adding a potential comment
    """
    Starts or continues the evaluation of the given SUBMISSION for the given EXERCISE.
    The evaluation has several phases, which are encoded in a state machine:

    0. [SUBMITTED]: The student (group) has submitted their work in the LMS. If it is a git-repo submission it will start by downloading into the `grading_directory`.
    1. [CHECKED_OUT]: The student repo submission has been cloned locally. The next step is to run automated tests if there are any. 
    2. [TESTED]: The student submission has been tested. In the next step GPT-4 will be consulted to generate a feedback.
    3. [FEEDBACK_RECEIVED]: The automatic feeback has been generated. In the next step feedback will be posted in the GitHub repo and the LMS get updated.
    4. [GRADED]: The LMS has marked the exercise as graded. No further actions are required/possible. However, the grading can be reset using "--reset"
    """
    all_subs = storage.get_submissions(exercise)
    exercs = storage.get_exercise(course, exercise)
    relevant_subs = [s for s in all_subs if s.id == submission]
    if len(relevant_subs) == 1 and exercs:
        sub = relevant_subs[0]

        if reset and sub.state != SubmissionState.UNSUBMITTED:
            do_reset(exercs, sub)

        console.print(f"Starting Evalution of submission {submission} for group {sub.submission_group_no}...")
        console.print("Group members:", end="\n\n")
        for stud_id in sub.members:
            student = storage.get_student(stud_id)
            if student:
                console.print(f"  - {student.id}: {student.firstname} {student.lastname} ({student.email})")
        console.print()

        if sub.state == SubmissionState.UNSUBMITTED:
            console.print(":thumbsdown: Sorry! But the submision is not submitted and can therefore not be assessed!")
        

        elif sub.state == SubmissionState.SUBMITTED:
            if sub.extended_to is not None and sub.submitted_at is not None:
                if sub.submitted_at < sub.extended_to:
                    timeliness = "[green]on time[/green]"
                else:
                    timeliness = f"[red]late[/red] submitted: '{sub.submitted_at.isoformat()}', due: '{sub.extended_to.isoformat()}'"
                console.print(f":hourglass: Submission was {timeliness}!")

            do_checkout(exercs, sub)

        elif proceed and sub.state not in {SubmissionState.PASSED, SubmissionState.FAILED}:
            do_next_step(exercs, sub)
        else:
            console.print(f"Submission is currently in state {sub.state}. Did you maybe forget to provide the '--proceed' option?")
    else:
        console.print(f"Submission with id={submission} is not found for exercise={exercise}!")




    
if __name__ == "__main__":
    app()

