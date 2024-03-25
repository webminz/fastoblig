from pathlib import Path
from typing import Optional
from typer import Typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
import canvas

load_dotenv()

app = Typer(no_args_is_help=True)
console = Console()

@app.command(name="courses")
def list_courses():
    """
    Shows all courses registered for the current user in the LMS backend.
    """
    courses = canvas.get_courses()
    if courses and len(courses) > 0:
        table = Table("id", "code", "year", "semester", "title")
        for c in courses:
            table.add_row(str(c.id), c.code, str(c.year), c.semester, c.description)
        console.print(table)


@app.command(name="students")
def list_students(course: int, write_csv: Optional[str] = None):
    """
    Shows all students that are enrolled in the given course from LMS backedn.
    """
    students = canvas.get_enrollments(course)
    if students and len(students) > 0:
        file = None
        if write_csv:
            file = open(write_csv, "w")
            file.write("id,student_no,firstname,lastname,email\n")
        table = Table("id", "student_no", "firstname", "lastname", "email")
        for s in students:
            table.add_row(str(s.id), s.student_no, s.firstname, s.lastname, s.email)
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

@app.command("exercises")
def get_exercises(course: int):
    """
    Shows all exercises that are registered for the course in the LMS backend.
    """
    exercises = canvas.get_exercises(course)
    table = Table("id", "name", "group", "deadline", "published" , "grading", "points")
    for e in sorted(exercises):
        table.add_row(str(e.id), e.name, e.category, e.deadline.isoformat() if e.deadline is not None else None,
                      str(e.published), e.grading, str(e.max_points))
    console.print(table)


@app.command("submissions")
def get_submissions(course: int, exercise: int):
    """
    Shows all submissions for the given exercise.
    """
    submissions = canvas.get_submissions(course, exercise)
    table = Table("id", "state", "group", "students", "repo" , "delivered")
    for s in submissions:
        table.add_row(str(s.id), s.state, str(s.submission_group_no), str(s.members), s.content, 
                      s.submitted_at.isoformat() if s.submitted_at is not None else None)
    console.print(table)

    
if __name__ == "__main__":
    app()

