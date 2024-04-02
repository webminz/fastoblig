from pathlib import Path
from fastoblig.storage import Storage, CANVAS_TOKEN, OPENAI_TOKEN, UpdateResult
from typing import Optional
from typer import Typer, get_app_dir, confirm, progressbar
from rich.console import Console
from rich.table import Table
import os
from fastoblig.canvas import CanvasClient
import pygit2


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
def configure(set_canvas_token: Optional[str] = None, 
          set_openai_token: Optional[str] = None,
          config_reset: bool = False):
    """
    Set/unset central config parameters.
    """
    if set_canvas_token is None and set_openai_token is None and not config_reset:
        console.print(f"FastOBLIG configuration :house: stored at: '{storage.db_file}'")
        console.print("[grey]You may change this by setting the '$FASTOBLIG_HOME' environment variable[/grey]")

    if set_canvas_token:
        storage.set_token(CANVAS_TOKEN, set_canvas_token)
        console.print("Canvas access token updated!")

    if set_openai_token:
        storage.set_token(OPENAI_TOKEN, set_openai_token)
        console.print("OpenAI access token updated!")

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
        table = Table("id", "code", "year", "semester", "title")
        for c in courses:
            table.add_row(str(c.id), c.code, str(c.year), c.semester, c.description)
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
                result = storage.upsert_enrollment(course, s)
                if result == UpdateResult.NEW:
                    style = 'green'

                table.add_row(str(s.id), s.student_no, s.firstname, s.lastname, s.email, style=style)

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



class GitProgrssbar(pygit2.RemoteCallbacks):

    def __init__(self):
        super().__init__(None, None)
        self.bar = progressbar(length=100)
        self.bar.__enter__()

    def fin(self):
        self.bar.update(100)
        self.bar.__exit__(None, None, None)

    def transfer_progress(self, stats):
        self.bar.update(int(stats.indexed_objects/stats.total_objects * 100))

@exercises_app.command("list")
def get_exercises(course: int):
    """
    Shows all exercises that are registered for the course in the LMS backend.
    """
    exercises = client.get_exercises(course)
    table = Table("id", "name", "group", "deadline", "published" , "grading", "points")
    for e in sorted(exercises):
        table.add_row(str(e.id), e.name, e.category, e.deadline.isoformat() if e.deadline is not None else None,
                      str(e.published), e.grading, str(e.max_points))
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

        if work_dir is None:
            work_dir = Path.cwd() / str(course)
        work_dir.mkdir(parents=True, exist_ok=True)
        e.grading_path = work_dir

        if description_repo:
            e.description_type = "git_repo"
            e.content = f"{description_repo};{repo_branch};{repo_file}"
            description_folder = work_dir / "exercise"
            if not description_folder.exists():
                console.print(f":arrow_down: Downloading '{description_repo}'@{repo_branch} into '{description_folder.absolute()}'")
                progress = GitProgrssbar()
                pygit2.clone_repository(description_repo,
                                        str(description_folder.absolute()),
                                        checkout_branch=repo_branch)
                progress.fin()
        # TODO: update database
    else:
        console.print(f"Exercise with id {exercise} is not found!")
            

@submissions_app.command("list")
def get_submissions(course: int, exercise: int):
    """
    Shows all submissions for the given exercise.
    """
    submissions = client.get_submissions(course, exercise)
    table = Table("id", "state", "group", "students", "repo" , "delivered")
    for s in submissions:
        table.add_row(str(s.id), s.state.name, str(s.submission_group_no), str(s.members), s.content, 
                      s.submitted_at.isoformat() if s.submitted_at is not None else None)
    console.print(table)

    
if __name__ == "__main__":
    app()

