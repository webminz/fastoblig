from datetime import datetime
from enum import Enum
import os
from pathlib import Path
from sqlite3 import connect 
from fastoblig.domain import Course, Exercise, Student, Submission, SubmissionState
import base64

_SET_UP_DDL = """\
CREATE TABLE tokens(
	service text not null,
	value text not null,
	primary key (service)
);
CREATE TABLE courses(
	id integer not null,
	code text null,
	description text null,
	semester text null,
	year integer null,
	primary key (id)
);
CREATE TABLE students(
	id integer not null,
	studentno integer null,
	email text null,
	firstname text null,
	lastname text null,
	primary key (id)
);
CREATE TABLE enrollment(
	course_id integer not null,
	student_id integer not null,
	primary key (course_id, student_id),
	foreign key (course_id) references course(id),
	foreign key (student_id) references student(id)
);
CREATE TABLE exercises(
	id integer not null,
	course integer not null,
	category text null,
    name text null,
    description_type text null,
    description text null,
	deadline text null,
	grading_type text null,
	max_points real null,
	state text null,
	submission_category_group_id integer null,
        grade_path text null,
    content blob null,
	assesment_folder text null,
	primary key (id, course),
	foreign key (course) references course(id)
);
create table submissions(
	id integer not null,
	exercise integer not null,
	repo_url text null,
        submission_type text null,
	group_id integer null,
	group_no integer null,
	group_name text null,
	state text null,
	grade real null,
	deadline text null,
	submitted_at text null,
	graded_at text null,
	comment_file text null,
	testresult_file text null,
	feedback_file text null,
	content blob null,
	primary key (id, exercise),
	foreign key (exercise) references exercises(id)
);
create table contribution(
	student_id integer not null,
	exercise_id integer not null,
	submission_id integer not null,
	primary key (student_id, exercise_id, submission_id),
	foreign key (student_id) references students(id),
	foreign key (exercise_id) references submissions(exercise),
	foreign key (submission_id) references submissions(id)
);
"""

CANVAS_TOKEN = "canvas"
OPENAI_TOKEN = "openai"
GITHUB_TOKEN = "github"

class UpdateResult(Enum):
    UNCHANGED = 0
    NEW = 1
    MODIFIED = 2
    REMOVED = 3

class Storage:
    """
    Provides an API for persistent storage of courses, enrollments, exercises and submissions 
    including other application data such as secret tokens etc.
    The backend technology is provided by `sqlite`.
    """

    def init_db(self) -> None:
        """
        Initializes the database structure.
        """
        self.connection.executescript(_SET_UP_DDL)
        self.connection.commit()

    def __init__(self, home_path: Path) -> None:
        self.db_file = home_path / "store.sqlite"
        if self.db_file.exists():
            self.connection = connect(str(self.db_file.absolute()))
        else:
            db_file = str(self.db_file.absolute())
            print("Initializing database on first start ...", end="")
            self.connection = connect(db_file)
            self.init_db()
            print("OK")


    def reset_db(self) -> None:
        """
        Deletes the whole database to start afresh.
        """
        self.connection.close()
        os.remove(self.db_file)
        self.connection = connect(str(self.db_file.absolute()))
        self.init_db()

            
    def __del__(self) -> None:
        if self.connection:
            self.connection.close()

    def get_token(self, token: str) -> str | None:
        """
        Retrieves the application secret token of the given type.
        """
        cursor = self.connection.cursor()
        cursor.execute("SELECT value FROM tokens WHERE service = ?", (token,))
        result = cursor.fetchone()
        cursor.close()
        if result and result[0]:
            return base64.b64decode(result[0].encode()).decode()
        else:
            return None


    def set_token(self, token: str, value: str) -> None:
        """
        Stores an application secret token of the given type in the database.
        """
        cursor = self.connection.cursor()
        if self.get_token(token):
            cursor.execute("UPDATE tokens SET value=? WHERE service = ?", 
                           (base64.b64encode(value.encode()).decode(), token))
        else:
            cursor.execute("INSERT INTO tokens (service, value) VALUES (?, ?)", 
                           (token, base64.b64encode(value.encode()).decode()))
        self.connection.commit()
        cursor.close()


    def upsert_course(self, course: Course):
        """
        Inserts or updates the given course object into the database.
        """
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM courses WHERE id = ?", (course.id,))
        result = cursor.fetchall()
        if len(result) > 0:
            cursor.execute("""\
UPDATE courses SET 
code=?,
description=?,
semester=?,
year=?
WHERE id=?\
            """, (course.code, course.description, course.semester, course.year, course.id))
        else:
            cursor.execute("INSERT INTO courses (id, code, description, semester, year) VALUES (?, ?, ?, ?, ?)",
                           (course.id, course.code, course.description, course.semester, course.year))
        self.connection.commit()
        cursor.close()

    

    def upsert_enrollment(self, course_id: int, student: Student) -> UpdateResult:
        """
        Inserts or updates a course enrollment for the given student in the given course.
        """
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM enrollment WHERE course_id = ? AND student_id = ?", (course_id, student.id))
        if cursor.fetchone():
            cursor.close()
            return UpdateResult.UNCHANGED
        else:
            cursor.execute("SELECT * FROM students WHERE id = ?", (student.id,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO students (id, studentno, email, firstname, lastname) VALUES (?,?,?,?,?)",
                               (student.id, student.student_no, student.email, student.firstname, student.lastname))
            cursor.execute("INSERT INTO enrollment(course_id, student_id) VALUES (?,?)", (course_id, student.id))
            self.connection.commit()
            cursor.close()
            return UpdateResult.NEW

    
    def get_exercise(self, course_id: int, exercise_id: int) -> Exercise | None:
        """
        Retrieves the exercise object with the given id in the given course.
        """
        cursor = self.connection.cursor()
        cursor.execute("""\
SELECT 
id, 
course,
category,
name,
description_type,
description,
deadline,
grading_type,
max_points,
state,
grade_path,
submission_category_group_id FROM exercises WHERE id = ? AND course = ?
        """, (exercise_id, course_id))
        result_row = cursor.fetchone()
        result = None
        if result_row:
            result = Exercise(
                id=exercise_id,
                course=course_id,
                category=result_row[2],
                name=result_row[3],
                description_type=result_row[4],
                content=str(result_row[5]) if result_row[4] == 'git_repo' else None,
                deadline=datetime.fromisoformat(result_row[6]),
                grading=result_row[7],
                max_points=result_row[8],
                published=False if result_row[9] == "unpublished" else True, 
                grading_path=result_row[10],
                submission_category_id=result_row[11]
            )
        cursor.close()
        return result


    def upsert_exercise(self, exercise: Exercise) -> UpdateResult:
        """
        Inserts or updates the given Exercise object into the database.
        """
        old = self.get_exercise(exercise.course, exercise.id)
        if old and old.model_dump() == exercise.model_dump():
            return UpdateResult.UNCHANGED
        cursor = self.connection.cursor()
        if old:
            cursor.execute("""UPDATE exercises SET\
category = ?,
name = ?, 
description_type = ?,
description = ?, 
deadline = ?,
grading_type = ?,
max_points = ?,
state = ?, 
grade_path = ?,
submission_category_group_id = ?
WHERE id = ? and course = ?\
            """, (exercise.category,
                  exercise.name,
                  exercise.description_type,
                  exercise.content if exercise.description_type == 'git_repo' else None,
                  exercise.deadline.isoformat() if exercise.deadline is not None else None,
                  exercise.grading,
                  exercise.max_points,
                  "published" if exercise.published else "unpublished",
                  exercise.submission_category_id,
                  exercise.grading_path,
                  exercise.id, exercise.course))
            result = UpdateResult.MODIFIED
        else:
            cursor.execute("""\
INSERT INTO exercises (
id, 
course,
category,
name,
description_type,
description,
deadline,
grading_type,
max_points,
state,
grade_path,
submission_category_group_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\
            """, (exercise.id,
                  exercise.course,
                  exercise.category,
                  exercise.name,
                  exercise.description_type,
                  exercise.content if exercise.description_type == 'git_repo' else None,
                  exercise.deadline.isoformat() if exercise.deadline is not None else None,
                  exercise.grading,
                  exercise.max_points,
                  "published" if exercise.published else "unpublished",
                  exercise.grading_path,
                  exercise.submission_category_id,
                  ))
            result = UpdateResult.NEW
        self.connection.commit()
        cursor.close()
        return result


    def get_submissions(self, exercise_id: int) -> list[Submission]:
        """
        Retrieves a list of all saved submissions for the given exercise.
        """
        result = []
        cursor = self.connection.cursor()
        cursor.execute("""\
SELECT 
id,
exercise,
repo_url,
submission_type,
group_id,
group_no,
group_name,
state,
grade,
deadline,
submitted_at,
graded_at,
comment_file,
testresult_file,
feedback_file FROM submissions WHERE exercise = ?\
        """, (exercise_id,))
        result_rows = cursor.fetchall()
        for result_row in result_rows:
            members = []
            cursor.execute("SELECT student_id FROM contribution WHERE exercise_id=? AND submission_id=?", 
                           (exercise_id, result_row[0]))
            for member in cursor.fetchall():
                members.append(member[0])
            result.append(Submission(
                members=members,
                id=result_row[0],
                exercise=result_row[1],
                content=result_row[2],
                submission_type=result_row[3],
                submission_group_id=result_row[4],
                submission_group_no=result_row[5],
                submission_group_name=result_row[6],
                state=SubmissionState[result_row[7]],
                grade=result_row[8],
                extended_to=datetime.fromisoformat(result_row[9]) if result_row[9] else None,
                submitted_at=datetime.fromisoformat(result_row[10]) if result_row[10] else None,
                graded_at=datetime.fromisoformat(result_row[11]) if result_row[11] else None,
                comment=result_row[12],
                testresult=result_row[13],
                feedback=result_row[14]
            ))
        return result

    def upsert_submissions(self, exercise_id: int,  submissions: list[Submission]) -> dict[int, UpdateResult]:
        """
        This method compares the given list of submission with the stored submissions 
        and updates them accordingly or inserts new submissions if they are not stored.
        Also it checks the student group members of each given submission and deletes previously 
        stored submissions with state "unsubmitted" if those were associated with that member.
        It returns a dictionary that shows which submissions were added, modified, or deleted.
        """
        result  = {}
        old = self.get_submissions(exercise_id)
        old_indexed = { s.id: s for s in old }
        single_unsubmitted = { s.members[0]: s for s in old 
            if len(s.members) == 1 and s.state == SubmissionState.UNSUBMITTED }
        cursor = self.connection.cursor()
        for new in submissions:
            if new.id in old_indexed:
                old_submission = old_indexed[new.id]
                if new.model_dump() == old_submission.model_dump():
                    result[new.id] = UpdateResult.UNCHANGED
                else:
                    cursor.execute("""\
UPDATE submissions SET
repo_url=?,
submission_type=?,
group_id=?,
group_no=?,
group_name=?,
state=?,
grade=?,
deadline=?,
submitted_at=?,
graded_at=?,
comment_file=?,
testresult_file=?,
feedback_file=?
WHERE
id=? AND
exercise=?\
                    """, (new.content if new.submission_type == "repo_url" else None,
                          new.submission_type,
                          new.submission_group_id,
                          new.submission_group_no,
                          new.submission_group_name,
                          new.state.name,
                          new.grade,
                          new.extended_to.isoformat() if new.extended_to else None, 
                          new.submitted_at.isoformat() if new.submitted_at else None,
                          new.graded_at.isoformat() if new.graded_at else None,
                          new.content,
                          new.testresult,
                          new.feedback,
                          new.id,
                          new.exercise
                        ))
                    result[new.id] = UpdateResult.MODIFIED
            else:
                result[new.id] = UpdateResult.NEW
                cursor.execute("""\
INSERT INTO submissions(
id, 
exercise,
repo_url,
submission_type,
group_id,
group_no,
group_name,
state,
grade,
deadline,
submitted_at,
graded_at,
comment_file,
testresult_file,
feedback_file
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                       new.id,
                       new.exercise,
                       new.content if new.submission_type == "repo_url" else None,
                       new.submission_type,
                       new.submission_group_id,
                       new.submission_group_no,
                       new.submission_group_name,
                       new.state.name,
                       new.grade,
                       new.extended_to.isoformat() if new.extended_to else None, 
                       new.submitted_at.isoformat() if new.submitted_at else None,
                       new.graded_at.isoformat() if new.graded_at else None,
                       new.content,
                       new.testresult,
                       new.feedback,
                        ))
            for member in new.members:
                if member in single_unsubmitted:
                    single_unsubmitted_submission = single_unsubmitted[member]
                    if single_unsubmitted_submission.id != new.id:
                        result[single_unsubmitted_submission.id] = UpdateResult.REMOVED
                        cursor.execute("DELETE FROM contribution WHERE exercise_id=? AND student_id=? AND submission_id=?", (
                            single_unsubmitted_submission.exercise,
                            member,
                            single_unsubmitted_submission.id
                        ))
                        cursor.execute("DELETE FROM submissions WHERE exercise=? AND id = ?", 
                                       (single_unsubmitted_submission.exercise, single_unsubmitted_submission.id))
                cursor.execute("""\
SELECT * FROM contribution WHERE exercise_id=? AND student_id=? AND submission_id=?\
                               """, (
                            new.exercise,
                            member,
                            new.id
                    ))
                if cursor.fetchone() is None:
                    cursor.execute("""\
INSERT INTO contribution (exercise_id, student_id, submission_id) VALUES (?, ?, ?)\
                                   """, (
                        new.exercise, 
                        member,
                        new.id
                    ))
        self.connection.commit()
        cursor.close()
        return result


