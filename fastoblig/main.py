import os
from pathlib import Path
import sys
from typing import Annotated, Optional
import logging
from rich.logging import RichHandler

from typer import Argument, Typer, get_app_dir, confirm, prompt
from rich.console import Console
from typer.params import Option

from fastoblig.assessment import Assessor
from fastoblig.canvas import CanvasClient
from fastoblig.completions import AutoCompleter
import fastoblig.commands as cmd

from fastoblig.domain import SubmissionState
from fastoblig.storage import GITHUB_TOKEN, Storage, CANVAS_TOKEN, OPENAI_TOKEN, SubmissionResult, UpdateResult


# global variables
APP_NAME = "fastoblig"
console = Console()


def logger_startup():
    logging.basicConfig(
        level="NOTSET", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
    )
    if "FASTOBLIG_LOG" in os.environ:
        log_level = os.environ["FASTOBLIG_LOG"]
    else:
        log_level = "ERROR"
    logging.getLogger().setLevel(log_level)
    logger = logging.getLogger("rich")
    logging.getLogger("requests").setLevel(log_level)
    logging.getLogger("urllib3").setLevel(log_level)
    logging.getLogger("git").setLevel(log_level)
    logging.getLogger("xml.etree").setLevel(log_level)
    logger.setLevel(log_level)
    return logger

logger = logger_startup()

# FEATURE: statistic functions
# FEATURE: add submission manually

def startup(with_logger: bool = True):
    if "FASTOBLIG_HOME" in os.environ:
        app_dir = Path(os.environ['FASTOBLIG_HOME'])
    else:
        app_dir = Path(get_app_dir(APP_NAME, roaming=True, force_posix=True))
    if not app_dir.exists():
        console.print("This seems to be the first time :tada: for you running FastOBLIG on this system")
        console.print(f"We will now create the storage home :house: at the following path: '{app_dir.absolute()}'")
        console.print("You may want to set the environment variable '$FASTOBLIG_HOME' if you want to change this location!")
        app_dir.mkdir(parents=True)
    if with_logger:
        logger.info("Using storage location at '%s' for fastoblig.", app_dir.absolute())
    storage = Storage(app_dir)
    return storage


# Domain objects
storage = startup()
client = CanvasClient(storage)
autocompleter = AutoCompleter(storage, client)

# Typer
app = Typer(no_args_is_help=True)
courses_app = Typer(no_args_is_help=True)
exercises_app = Typer(no_args_is_help=True)
submissions_app = Typer(no_args_is_help=True)
app.add_typer(courses_app, name="course", help="Manage courses in the LMS")
app.add_typer(exercises_app, name="exercise", help="Manage exercises in the LMS")
app.add_typer(submissions_app, name="submission", help="Manage submissions in the LMS")


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


# courses group

@courses_app.command(name="list")
def list_courses(
    offline: Annotated[bool, Option(help="""
Does not contact the LMS. Retrieves only locally stored watched courses
    """)] = False
):
    """
    Shows all courses registered for the current user in the LMS backend.
    """
    cmd.list_course(client, storage, console, offline)
    


@courses_app.command(name="watch")
def track_course(course: int, preview: bool = False):
    """
    Starts watching this course, i.e. downloads the list of student enrollments and stores course information.
    """
    # TODO: auto complete via Canvas API call
    cmd.watch_course(client, storage, console, course, preview)




@courses_app.command("set")
def set_current_course(
    course: Annotated[int, Argument(help="The course id (from LMS)", autocompletion=autocompleter.watched_courses)]
):
    """
    Sets the current course 
    """
    storage.set_current_course(course)


# TODO: show overview of students in course


# Exercises group

@exercises_app.command("list")
def get_exercises(
    course: Annotated[int, Argument(help="Course (ID) containing the exercises", default_factory=storage.get_current_course)],
    offline: Annotated[bool, Option(help="do not connect the Canvas API but only used locally stored information")] = False
):
    """
    Shows all exercises that are registered for the course in the LMS backend.
    """
    if course is None:
        console.print("[red]Course ID was not specified!!![/red]")
        sys.exit(1)
    cmd.list_exercises(client, storage, console, course, offline)


@exercises_app.command("grade")
def grade_exercise(course: int, # TODO: make optional if current course is set
                   exercise: int, # TODO: autocomplete from web request
                   work_dir: Optional[Path] = None,
                   repo_url: Optional[str] = None,
                   repo_file: str = "README.md",
                   repo_branch: str = "main"):
    """
    Begins with the preparations to grade an exercise. i.e. downloads the instructions and submissions.
    """
    if work_dir is None:
        base_dir = Path(get_app_dir(APP_NAME, roaming=True, force_posix=True)) / "_grading"
        if not base_dir.exists():
            base_dir.mkdir(parents=True, exist_ok=True)
        work_dir = base_dir / str(exercise)

    cmd.download_exercise(client, storage, console, course, exercise, work_dir, repo_url, repo_branch, repo_file)
    

############################
# `submissions` subcommand #
############################
            

@submissions_app.command("list")
def get_submissions(
    exercise: Annotated[Optional[int], Option(
        help="The id of the exercise to get submission for",
        default_factory=storage.get_current_exercise,
        autocompletion=autocompleter.watched_exercises
    )],
    offline: Annotated[bool, Option(
        help="Flag to not contact the LMS and only retrieve from the locally stored submissions"
    )] = False,
    persist: Annotated[bool, Option(
        help="Flag to perform an update of the locally stored submission with the result from the LMS"
    )] = True
):
    """
    Shows all submissions for the given exercise and updates the database of previously stored submissions.
    """

    if exercise is None:
        console.print("[red]No `exercise` specified [/red]")
        sys.exit(1)

    e = storage.get_exercise(exercise)
    if e is None:
        console.print(f"[red]Cannot find exercise with id='{exercise}'![/red]")
        console.print("Remember that you have to start grading an exercise with the subcommand 'exercise grade' before you can see submissions here!")
        sys.exit(1)

    console.print(f"Exercise: {e.id} (\"{e.name}\"):")
    locally = storage.get_submissions(exercise)
    if offline:
        sub_map = {x.id: x for x in locally}
        update_map = { x.id: UpdateResult.UNCHANGED for x in locally }
        cmd.print_submission_table(console, SubmissionResult(submissions=sub_map, states=update_map))
    else:
        submissions = client.get_submissions(e.course, exercise)
        if persist:
            subs = storage.load_submissions(exercise, submissions)
            cmd.print_submission_table(console, subs)
        else:
            update_map = { x.id: UpdateResult.NEW for x in submissions }
            sub_map = {x.id: x for x in submissions}
            cmd.print_submission_table(console, SubmissionResult(submissions=sub_map, states=update_map))

        

@submissions_app.command("grade")
def grade_submission(
        submission: Annotated[int, Argument(
        help="The ID of the submission to grade",
        default_factory=storage.get_current_submission
    )]
    ):
    """
    Starts or continues the evaluation of the given SUBMISSION for the given EXERCISE.
    The evaluation has several phases, which are encoded in a state machine:

    0. [SUBMITTED]: The student (group) has submitted their work in the LMS. If it is a git-repo submission it will start by downloading into the `grading_directory`.
    1. [CHECKED_OUT]: The student repo submission has been cloned locally. The next step is to run automated tests if there are any. 
    2. [TESTED]: The student submission has been tested. In the next step GPT-4 will be consulted to generate a feedback.
    3. [FEEDBACK_RECEIVED]: The automatic feeback has been generated. In the next step feedback will be posted in the GitHub repo and the LMS get updated.
    4. [GRADED]: The LMS has marked the exercise as graded. No further actions are required/possible. However, the grading can be reset using "--reset"
    """
    sub = storage.get_submission(submission)
    if sub is None:
        console.print(f"[red]Cannot find a submission with id = '{submission}'![/red]")
        sys.exit(1)
    storage.set_current_submission(submission)
    exe = storage.get_exercise(sub.exercise)
    assert exe is not None
    assessor = Assessor(console, storage, exe, sub)
    assessor.assess()


# TODO: params for 'copy-to-clipboard' and 'open in file explorer'
@submissions_app.command("files")
def submission_files(
        submission: Annotated[int, Argument(
        help="The ID of the submission",
        default_factory=storage.get_current_submission
    )]
    ):
    """
    Opens the local file system location of the submission.
    """
    sub = storage.get_submission(submission)
    if sub is None:
        console.print(f"[red]Cannot find a submission with id = '{submission}'![/red]")
        sys.exit(1)
    exe = storage.get_exercise(sub.exercise)
    assert exe is not None
    assessor = Assessor(console, storage, exe, sub)
    assessor.files()


@submissions_app.command("reset")
def submission_reset(
        submission: Annotated[int, Argument(
            help="The ID of the submission",
        )],
        state: Annotated[str, Argument(
            help="The state to reset to",
            autocompletion=autocompleter.submission_states
        )]
    ):
    """
    Resets the provided submission to the given state
    """
    sub = storage.get_submission(submission)
    if sub is None:
        console.print(f"[red]Cannot find a submission with id = '{submission}'![/red]")
        sys.exit(1)
    exe = storage.get_exercise(sub.exercise)
    assert exe is not None
    assessor = Assessor(console, storage, exe, sub)
    assessor.reset(SubmissionState[state])

    



    
if __name__ == "__main__":
    app()

