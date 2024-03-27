from enum import Enum
import os
from pathlib import Path
from sqlite3 import connect 
from domain import Course, Exercise, Student
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

    def init_db(self) -> None:
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
        self.connection.close()
        os.remove(self.db_file)
        self.connection = connect(str(self.db_file.absolute()))
        self.init_db()

            
    def __del__(self) -> None:
        if self.connection:
            self.connection.close()

    def get_token(self, token: str) -> str | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT value FROM tokens WHERE service = ?", (token,))
        result = cursor.fetchone()
        cursor.close()
        if result and result[0]:
            return base64.b64decode(result[0].encode()).decode()
        else:
            return None


    def set_token(self, token: str, value: str) -> None:
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

    
    def upsert_exercise(self, exercise: Exercise):
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM exercises WHERE id = ? AND course = ?", (exercise.id,exercise.course))
        if cursor.fetchone():
            cursor.execute("""UPDATE exercises SET\
category = ?,
name = ?, 
description_type = ?,
description = ?, 
deadline = ?,
grading_type = ?,
max_points = ?,
state = ?, 
submission_category_group_id = ?
WHERE id = ? and course = ?\
            """)
            
        pass

	# id integer not null,
	# course integer not null,
	# category text null,
 #    name text null,
 #    description_type text null,
 #    description_file text null,
	# deadline text null,
	# grading_type text null,
	# max_points real null,
	# state text null,
	# submission_category_group_id integer null,
 #    content blob null,
	# assesment_folder text null,
