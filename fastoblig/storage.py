from datetime import datetime
from enum import Enum
import os
from pathlib import Path
from sqlite3 import connect
from typing import Optional
from zoneinfo import ZoneInfo
import polars as pl

from pydantic import BaseModel 
from fastoblig.domain import Course, Exercise, Student, Submission, SubmissionState
import base64

_SET_UP_DDL = """\
CREATE TABLE settings (
	k text not null primary key,
	v text null
);
CREATE TABLE tokens(
	service text not null,
	value text null,
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
        assesment_folder text null,
        primary key (id, course),
        foreign key (course) references course(id)
);
create table submissions(
	id integer not null,
	exercise integer not null,
	repo_url text null,
	group_id integer null,
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
create table contributions (
	student_id integer not null,
	submission_id integer not null,
	primary key(student_id, submission_id),
	foreign key(student_id) references students(id),
	foreign key(submission_id) references submissions (id)
);
create table groups (
	group_id integer primary key,
	group_name text null,
	group_category_id integer null,
	group_category_name text null
);
create table memberships (
	student_id integer not null,
	group_id integer not null,
	primary key (student_id, group_id),
	foreign key(student_id) references students(id),
	foreign key(group_id) references groups(group_id)
);

CREATE TABLE config (
	id integer primary key,
	hostname text not null,
	current_course integer null,
	current_exercise integer null,
	current_submission integer null,
	foreign key (current_course) references courses(id),
	foreign key (current_exercise) references exercises(id),
	foreign key (current_submission) references submissions(id)
);
INSERT INTO settings (k) VALUES ('lms_backend');
INSERT INTO settings (k) VALUES ('default_text_editor');
INSERT INTO settings (k) VALUES ('default_grading_path');
INSERT INTO settings (k) VALUES ('current_course');
INSERT INTO settings (k) VALUES ('current_exercise');
INSERT INTO settings (k) VALUES ('current_submission');
"""

CANVAS_TOKEN = "canvas"
OPENAI_TOKEN = "openai"
GITHUB_TOKEN = "github"

class UpdateResult(Enum):
    UNCHANGED = 0
    NEW = 1
    MODIFIED = 2
    REMOVED = 3
    REJECTED = 4


class SubmissionResult(BaseModel):
    submissions : dict[int, Submission]
    states: dict[int, UpdateResult]

    def __iter__(self): # type: ignore
        return self.submissions.values().__iter__()

    def __getitem__(self, k):
        return self.states[k]

    def __contains__(self, k):
        return k in self.states



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
        self.current_course = None

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

    def set_current_course(self, course: int):
        cursor = self.connection.cursor()
        cursor.execute("UPDATE config SET current_course = ? WHERE id = 0", (course,))
        self.connection.commit()
        cursor.close()
    
    def get_current_course(self) -> int | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT current_course FROM config  WHERE id = 0", )
        result = None
        result_row = cursor.fetchone()
        if result_row:
            result = result_row[0]
        self.connection.rollback()
        cursor.close()
        return result


    def set_current_exercise(self, exercise: int):
        cursor = self.connection.cursor()
        cursor.execute("UPDATE config SET current_exercise = ? WHERE id = 0", (exercise,))
        self.connection.commit()
        cursor.close()
    
    def get_current_exercise(self) -> int | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT current_exercise FROM config WHERE id = 0", )
        result = None
        result_row = cursor.fetchone()
        if result_row is not None:
            result = result_row[0]
        cursor.close()
        return result

    def set_current_submission(self, submission: int):
        cursor = self.connection.cursor()
        cursor.execute("UPDATE config SET current_submission = ? WHERE id = 0", (submission,))
        self.connection.commit()
        cursor.close()
    
    def get_current_submission(self) -> int | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT current_submission FROM config WHERE id = 0", )
        result = None
        result_row = cursor.fetchone()
        if result_row is not None:
            result = result_row[0]
        cursor.close()
        return result

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

    def get_course(self, course_id: int) -> Course | None:
        """
        Retrieves a stored course information object if exists.
        """
        cursor = self.connection.cursor()
        cursor.execute("SELECT code, description, semester, year FROM courses WHERE id = ?", (course_id,))
        result_row = cursor.fetchone()
        result = None
        if result_row:
            result = Course(id=course_id, code=result_row[0], description=result_row[1], semester=result_row[2], year=result_row[3])
        cursor.close()
        return result

    def get_courses(self) -> list[Course]:
        """
        Retrieves a list of all actively watched courses.
        """
        cursor = self.connection.cursor()
        cursor.execute("SELECT id, code, description, semester, year FROM courses")
        result_row = cursor.fetchall()
        result = []
        if result_row:
            result.append(Course(id=result_row[0], code=result_row[1], description=result_row[2], semester=result_row[3], year=result_row[4]))
        cursor.close()
        return result



    def get_student(self, student_id: int) -> Student | None:
        """
        Retrieves the student with given id if exists.
        """
        cursor = self.connection.cursor()
        cursor.execute("SELECT email, firstname, lastname, studentno FROM students WHERE id=?", (student_id,))
        result_row = cursor.fetchone()
        result = None
        if result_row:
            result = Student(id=student_id, student_no=result_row[3], email=result_row[0], firstname=result_row[1], lastname=result_row[2])
        cursor.close()
        return result


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

    
    def get_exercise(self, exercise_id: int) -> Exercise | None:
        """
        Retrieves the exercise object with the given id.
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
submission_category_group_id
FROM exercises WHERE id = ?
        """, (exercise_id, ))
        result_row = cursor.fetchone()
        result = None
        if result_row:
            result = Exercise(
                id=exercise_id,
                course=result_row[1],
                category=result_row[2],
                name=result_row[3],
                description_type=result_row[4],
                content=result_row[5],
                deadline=datetime.fromisoformat(result_row[6]),
                grading_type=result_row[7],
                max_points=result_row[8],
                published=True if result_row[9] == "published" else False, 
                grading_path=result_row[10],
                submission_category_id=result_row[11]
            )
        cursor.close()
        return result


    def get_exercises(self, course_id: int | None = None) -> list[Exercise]:
        """
        Retrieves all locally stored exercises.
        One may provide an optional course_id to filter for exercises in the specified course.
        """
        cursor = self.connection.cursor()
        if course_id:
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
    submission_category_group_id
    FROM exercises WHERE course = ?
            """, (course_id, ))
        else:
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
    submission_category_group_id
    FROM exercises""")
        result_rows= cursor.fetchall()
        return [Exercise(
                    id=result_row[0],
                    course=result_row[1],
                    category=result_row[2],
                    name=result_row[3],
                    description_type=result_row[4],
                    content=result_row[5],
                    deadline=datetime.fromisoformat(result_row[6]),
                    grading_type=result_row[7],
                    max_points=result_row[8],
                    published=True if result_row[9] == "published" else False, 
                    grading_path=result_row[10],
                    submission_category_id=result_row[11]
            ) for result_row in result_rows]

    def upsert_exercise(self, exercise: Exercise) -> UpdateResult:
        """
        Inserts or updates the given Exercise object into the database.
        """
        old = self.get_exercise(exercise.id)
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
                  exercise.grading_type,
                  exercise.max_points,
                  "published" if exercise.published else "unpublished",
                  exercise.submission_category_id,
                  str(exercise.grading_path),
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
                  exercise.grading_type,
                  exercise.max_points,
                  "published" if exercise.published else "unpublished",
                  str(exercise.grading_path),
                  exercise.submission_category_id,
                  ))
            result = UpdateResult.NEW
        self.connection.commit()
        cursor.close()
        return result


    def insert_group_memberships(self, students_in_group_df: pl.DataFrame):
        cursor = self.connection.cursor()
        for row in students_in_group_df.select("group_id", "group_name", "group_category_id", "group_category_name").unique().iter_rows():
            cursor.execute("INSERT INTO groups (group_id,  group_name, group_category_id, group_category_name) VALUES (?, ?, ?, ?)", (row[0], row[1], row[2], row[3]))
        for row in students_in_group_df.iter_rows():
            cursor.execute("INSERT INTO memberships (student_id, group_id) VALUES (?, ?)", (row[0], row[1]))
        self.connection.commit()
        cursor.close()


    def get_submissions(self, exercise_id: int) -> list[Submission]:
        """
        Retrieves a list of all saved submissions for the given exercise.
        """
        exe = self.get_exercise(exercise_id)
        if not exe:
            return []
        result = []
        cursor = self.connection.cursor()
        cursor.execute("""\
SELECT 
id, --0
exercise, --1
repo_url, --2
submission_type, --3
group_id, --4
group_name, --5
state, --6
grade, --7
deadline, --8
submitted_at, --9
graded_at, --10
comment_file, --11
testresult_file, --12
feedback_file --13
content --14
FROM submissions WHERE exercise = ?\
        """, (exercise_id,))
        result_rows = cursor.fetchall()
        for result_row in result_rows:
            contributions = []
            cursor.execute("SELECT student_id FROM contributions WHERE submission_id=?", 
                           (result_row[0],))
            for r in cursor.fetchall():
                contributions.append(r[0])
            result.append(Submission(
                contributions=contributions,
                id=result_row[0],
                exercise=result_row[1],
                content=result_row[2], # TODO: depents on the exercise otherwise r[14]
                submission_type=result_row[3],
                submission_group_id=result_row[4],
                submission_group_name=result_row[5],
                state=SubmissionState[result_row[6]],
                grade=result_row[7],
                extended_to=datetime.fromisoformat(result_row[8]).replace(tzinfo=ZoneInfo("UTC")) if result_row[8] else None,
                submitted_at=datetime.fromisoformat(result_row[9]).replace(tzinfo=ZoneInfo("UTC")) if result_row[9] else None,
                graded_at=datetime.fromisoformat(result_row[10]).replace(tzinfo=ZoneInfo("UTC")) if result_row[10] else None,
                comment_file=result_row[11],
                testresult_file=result_row[12],
                feedback_file=result_row[13]
            ))
        return result


    def get_submission(self, submission_id: int) -> Optional[Submission]:
        """
        Retrieves a submission with the given ID if exists
        """
        cursor = self.connection.cursor()
        cursor.execute("""\
SELECT 
id, --0
exercise, --1
repo_url, --2
submission_type, --3
group_id, --4
group_name, --5
state, --6
grade, --7
deadline, --8
submitted_at, --9
graded_at, --10
comment_file, --11
testresult_file, --12
feedback_file --13
content --14
FROM submissions WHERE id = ?\
        """, (submission_id,))
        result_row = cursor.fetchone()
        result = None
        if result_row:
            contributions = []
            cursor.execute("""
SELECT student_id FROM contributions WHERE submission_id = ? 
            """, (submission_id,))
            contribs_rows = cursor.fetchall()
            for contrib_row in contribs_rows:
                contributions.append(contrib_row[0])
            result =  Submission(
                contributions=contributions,
                id=result_row[0],
                exercise=result_row[1],
                content=result_row[2], # TODO: depents on the exercise otherwise r[14]
                submission_type=result_row[3],
                submission_group_id=result_row[4],
                submission_group_name=result_row[5],
                state=SubmissionState[result_row[6]],
                grade=result_row[7],
                extended_to=datetime.fromisoformat(result_row[8]).replace(tzinfo=ZoneInfo("UTC")) if result_row[8] else None,
                submitted_at=datetime.fromisoformat(result_row[9]).replace(tzinfo=ZoneInfo("UTC")) if result_row[9] else None,
                graded_at=datetime.fromisoformat(result_row[10]).replace(tzinfo=ZoneInfo("UTC")) if result_row[10] else None,
                comment_file=result_row[11],
                testresult_file=result_row[12],
                feedback_file=result_row[13]
            )
        cursor.close()
        return result
        

    def load_submissions(self, exercise_id: int, submissions: list[Submission]) -> SubmissionResult:
        """
        This method is called upon the initial loading of submissions into the database when they come from the LMS.
        """
        cursor = self.connection.cursor()

        result_state = {}
        result_objs = {}
        
        current_submissions = { s.id: s for s in self.get_submissions(exercise_id)}
        exercise = self.get_exercise(exercise_id)
        assert exercise is not None
        
        for new_submission in submissions:
            if new_submission.id in current_submissions:
                old_submission = current_submissions[new_submission.id]
                assert old_submission.submitted_at is not None
                assert new_submission.submitted_at is not None
                if old_submission.submitted_at < new_submission.submitted_at:
                    result_state[new_submission.id] = UpdateResult.MODIFIED
                    result_objs[new_submission.id] = new_submission
                elif old_submission.state > new_submission.state:
                    result_state[new_submission.id] = UpdateResult.REJECTED
                    result_objs[new_submission.id] = old_submission
                else:
                    result_state[new_submission.id] = UpdateResult.UNCHANGED
                    result_objs[new_submission.id] = old_submission
            else:
                result_state[new_submission.id] = UpdateResult.NEW 

                if new_submission.submission_group_id is None and exercise.submission_category_id is not None:
                    student = new_submission.contributions[0]
                    cursor.execute("select g.group_id, g.group_name from memberships m inner join groups g on m.group_id = g.group_id  where student_id = ? and g.group_category_id = ?", (student, exercise.submission_category_id))
                    result_row = cursor.fetchone()
                    if result_row:
                        new_submission.submission_group_id = result_row[0]
                        new_submission.submission_group_name = result_row[1]

                if new_submission.submission_group_id is not None:
                    cursor.execute("""\
insert into contributions (student_id , submission_id) \
select student_id, ? as submission \
from memberships where group_id = ? \
returning student_id""", (new_submission.id, new_submission.submission_group_id))
                    contributions_rows = cursor.fetchall()
                    new_submission.contributions = [int(r[0]) for r in contributions_rows]

                self._insert_submission(cursor, new_submission)

                result_objs[new_submission.id] = new_submission

        preexisitng = set(current_submissions.keys()).difference(result_state.keys())
        for id in preexisitng:
            result_objs[id] = current_submissions[id]
            result_state[id] = UpdateResult.UNCHANGED

        self.connection.commit()

        return SubmissionResult(submissions=result_objs, states=result_state)

    def _insert_submission(self, cursor, new: Submission):
        cursor.execute("""\
INSERT INTO submissions(
id, -- 0
exercise, -- 1
repo_url, -- 2
submission_type, -- 3
group_id, -- 4
group_name, -- 5
state, -- 6
grade, -- 7
deadline, -- 8
submitted_at, -- 9
graded_at, -- 10
comment_file, -- 11
testresult_file, -- 12
feedback_file -- 13
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                       new.id, # 0
                       new.exercise, # 1
                       new.content, # 2
                       new.submission_type, # 3
                       new.submission_group_id, # 4
                       new.submission_group_name, # 5
                       new.state.name, # 6
                       new.grade, # 7
                       new.extended_to.isoformat() if new.extended_to else None, # 8
                       new.submitted_at.isoformat() if new.submitted_at else None, # 9
                       new.graded_at.isoformat() if new.graded_at else None, # 10
                       str(new.comment_file.absolute()) if new.comment_file else None, # 11
                       str(new.testresult_file.absolute()) if new.testresult_file else None, # 12
                       str(new.feedback_file.absolute() if new.feedback_file else None), #13
                    ))



    def update_submission(self, submission: Submission):
        cursor = self.connection.cursor()
        cursor.execute("""\
UPDATE submissions SET
repo_url=?,
submission_type=?,
group_id=?,
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
        """, (submission.content if submission.submission_type == "online_url" else None,
              submission.submission_type,
              submission.submission_group_id,
              submission.submission_group_name,
              submission.state.name,
              submission.grade,
              submission.extended_to.isoformat() if submission.extended_to else None, 
              submission.submitted_at.isoformat() if submission.submitted_at else None,
              submission.graded_at.isoformat() if submission.graded_at else None,
              str(submission.comment_file.absolute()) if submission.comment_file else None,
              str(submission.testresult_file.absolute()) if submission.testresult_file else None,
              str(submission.feedback_file.absolute()) if submission.feedback_file else None,
              submission.id,
              submission.exercise
            ))
        self.connection.commit()
        cursor.close()


    def upsert_submissions(self, exercise_id: int, submissions: list[Submission], force: bool = False) -> SubmissionResult:
        """
        This method compares the given list of submission with the stored submissions 
        and updates them accordingly or inserts new submissions if they are not stored.
        Also it checks the student group members of each given submission and deletes previously 
        stored submissions with state "unsubmitted" if those were associated with that member.
        It returns a dictionary that shows which submissions were added, modified, or deleted.
        """


        def is_resubmit(old_s: Submission, new_s: Submission) -> bool:
            return old_s.state in {
                SubmissionState.FAILED,
                SubmissionState.FAILED_IMPORTED
            } and new_s.state == SubmissionState.SUBMITTED

        result  = {}
        result_subs = {}

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
                    result_subs[new.id] = new
                elif not force and new.state.value < old_submission.state.value and not is_resubmit(old_submission, new):
                    result[new.id] = UpdateResult.REJECTED
                    result_subs[new.id] = old_submission
                else:
                    cursor.execute("""\
UPDATE submissions SET
repo_url=?,
submission_type=?,
group_id=?,
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
                    """, (new.content if new.submission_type == "online_url" else None,
                          new.submission_type,
                          new.submission_group_id,
                          new.submission_group_name,
                          new.state.name,
                          new.grade,
                          new.extended_to.isoformat() if new.extended_to else None, 
                          new.submitted_at.isoformat() if new.submitted_at else None,
                          new.graded_at.isoformat() if new.graded_at else None,
                          str(new.comment_file.absolute()) if new.comment_file else None,
                          str(new.testresult_file.absolute()) if new.testresult_file else None,
                          str(new.feedback_file.absolute()) if new.feedback_file else None,
                          new.id,
                          new.exercise
                        ))
                    result[new.id] = UpdateResult.MODIFIED
                    result_subs[new.id] = new
            else:
                result[new.id] = UpdateResult.NEW
                result_subs[new.id] = new
                cursor.execute("""\
INSERT INTO submissions(
id, -- 0
exercise, -- 1
repo_url, -- 2
submission_type, -- 3
group_id, -- 4
group_name, -- 5
state, -- 6
grade, -- 7
deadline, -- 8
submitted_at, -- 9
graded_at, -- 10
comment_file, -- 11
testresult_file, -- 12
feedback_file -- 13
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                       new.id, # 0
                       new.exercise, # 1
                       new.content if new.submission_type == "online_url" else None, # 2
                       new.submission_type, # 3
                       new.submission_group_id, # 4
                       new.submission_group_name, # 5
                       new.state.name, # 6
                       new.grade, # 7
                       new.extended_to.isoformat() if new.extended_to else None, # 8
                       new.submitted_at.isoformat() if new.submitted_at else None, # 9
                       new.graded_at.isoformat() if new.graded_at else None, # 10
                       str(new.comment_file.absolute()) if new.comment_file else None, # 11
                       str(new.testresult_file.absolute()) if new.testresult_file else None, # 12
                       str(new.feedback_file.absolute() if new.feedback_file else None), #13
                    ))
            for member, contribution in zip(new.members, new.contributions):
                if member in single_unsubmitted:
                    single_unsubmitted_submission = single_unsubmitted[member]
                    if single_unsubmitted_submission.id != new.id:
                        result[single_unsubmitted_submission.id] = UpdateResult.REMOVED
                        cursor.execute("DELETE FROM contributions WHERE student_id=? AND submission_id=?", (
                            member,
                            single_unsubmitted_submission.id
                        ))
                        cursor.execute("DELETE FROM submissions WHERE exercise=? AND id = ?", 
                                       (single_unsubmitted_submission.exercise, single_unsubmitted_submission.id))
                cursor.execute("""\
SELECT * FROM contributions WHERE student_id=? AND submission_id=?\
                               """, (
                            member,
                            new.id
                    ))
                if cursor.fetchone() is None:
                    cursor.execute("""\
INSERT INTO contributions (id, student_id, submission_id) VALUES (?, ?, ?)\
                                   """, (
                        contribution,
                        member,
                        new.id
                    ))
        self.connection.commit()
        cursor.close()
        return SubmissionResult(submissions=result_subs, states=result)


