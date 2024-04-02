from datetime import datetime
import unittest
from pathlib import Path

from fastoblig.domain import Course, Exercise, Student, Submission, SubmissionState
from fastoblig.storage import OPENAI_TOKEN, Storage, UpdateResult

course = Course(
    id=1234,
    code="TEST101",
    description="Testkurs for høgskulelærere",
    semester="spring",
    year=2024
)
student1 = Student(
    id=1111,
    firstname="Ole",
    lastname="Nordmann",
    email="4242@hvl.no",
    student_no=4242
)
student2 = Student(
    id=2222,
    firstname="Marit",
    lastname="Bygdevik",
    email="6969@hvl.no",
    student_no=6969
)
exercise = Exercise(
    id=9876,
    name="Oblig 1: Be good",
    content="https://github.com/selabhvl/test101-oblig1-startcode:main:README.md",
    grading="pass_fail",
    max_points=100.0,
    category="obligs",
    description_type="git_repo",
    grading_path=None,
    course=course.id,
    deadline=datetime(2024, 5, 1, 23, 59),
    submission_category_id=7777
)
submission1 = Submission(
    id=212121,
    exercise=exercise.id,
    submission_type="online_url",
    submission_group_id=None,
    submission_group_name=None,
    submission_group_no=None,
    state=SubmissionState.UNSUBMITTED,
    submitted_at=None,
    graded_at=None,
    extended_to=None,
    feedback=None,
    testresult=None,
    content=None,
    members=[student1.id]
)
submission2 = Submission(
    id=343434,
    exercise=exercise.id,
    submission_type="online_url",
    submission_group_id=None,
    submission_group_name=None,
    submission_group_no=None,
    state=SubmissionState.UNSUBMITTED,
    submitted_at=None,
    graded_at=None,
    extended_to=None,
    feedback=None,
    testresult=None,
    content=None,
    members=[student2.id]
)
submission3 = Submission(
    id=565656,
    exercise=exercise.id,
    submission_type="online_url",
    submission_group_id=23,
    submission_group_name="Oblig 1 Gruppe 1",
    submission_group_no=1,
    state=SubmissionState.SUBMITTED,
    submitted_at=datetime(2024, 4, 1),
    graded_at=None,
    extended_to=exercise.deadline,
    feedback=None,
    testresult=None,
    content=None,
    members=[student1.id, student2.id]
)

class StorageTest(unittest.TestCase):

    PATH = Path.cwd() / ".temp" / "test-storage" 

    def setUp(self) -> None:
        super().setUp()
        StorageTest.PATH.mkdir(parents=True, exist_ok=True)

    def test_store_token(self):
        store = Storage(StorageTest.PATH)
        store.reset_db()

        store.set_token(OPENAI_TOKEN, "password123")
        actual = store.get_token(OPENAI_TOKEN)
        self.assertEqual(actual, "password123")

    def test_upsert_course(self):
        store = Storage(StorageTest.PATH)
        store.reset_db()

        store.upsert_course(course)
        result1 = store.upsert_enrollment(course.id, student1)
        self.assertEqual(result1, UpdateResult.NEW)
        store.upsert_course(course)
        result2 = store.upsert_enrollment(course.id, student1)
        result3 = store.upsert_enrollment(course.id, student2)
        self.assertEqual(result2, UpdateResult.UNCHANGED)
        self.assertEqual(result3, UpdateResult.NEW)
        # checking results 
        # TODO: better create store methods to access this information
        cursor = store.connection.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM courses")
            result_count = cursor.fetchone()
            self.assertEqual(1, result_count[0])
            cursor.execute("SELECT COUNT(*) FROM students")
            result_count = cursor.fetchone()
            self.assertEqual(2, result_count[0])
            cursor.execute("SELECT COUNT(*) FROM enrollment WHERE course_id=?", (course.id,))
            result_count = cursor.fetchone()
            self.assertEqual(2, result_count[0])
        finally:
            cursor.close()

    def test_upsert_exercise_with_submissions(self):
        store = Storage(StorageTest.PATH)
        store.reset_db()

        # preparations
        store.upsert_course(course)
        store.upsert_enrollment(course.id, student1)
        store.upsert_enrollment(course.id, student2)
        
        # set up
        store.upsert_exercise(exercise)
        inserted_subs = store.upsert_submissions(exercise.id, [submission1, submission2])
        expected_inserted_subs = {
            submission1.id : UpdateResult.NEW,
            submission2.id : UpdateResult.NEW
        }
        self.assertEqual(inserted_subs, expected_inserted_subs)

        stored_e = store.get_exercise(course.id, exercise.id)
        assert stored_e is not None
        self.assertEqual(stored_e.model_dump(), exercise.model_dump())

        stored_subs = store.get_submissions(exercise.id)
        self.assertEqual(2, len(stored_subs))

        inserted_subs = store.upsert_submissions(exercise.id, [submission3])
        expected_inserted_subs = {
            submission1.id : UpdateResult.REMOVED,
            submission2.id : UpdateResult.REMOVED,
            submission3.id : UpdateResult.NEW
        }
        self.assertEqual(inserted_subs, expected_inserted_subs)

        stored_subs = store.get_submissions(exercise.id)
        self.assertEqual(1, len(stored_subs))
        self.assertEqual(stored_subs[0].model_dump(), submission3.model_dump())

        s = submission3.model_copy()
        s.graded_at = datetime(2024, 4, 3, 13, 15, 8)
        s.state = SubmissionState.PASSED
        s.feedback = "/path/to/feedback"
        s.testresult = "/path/to/test"

        inserted_subs = store.upsert_submissions(exercise.id, [s])
        expected_inserted_subs = {
            submission3.id : UpdateResult.MODIFIED
        }
        self.assertEqual(inserted_subs, expected_inserted_subs)

        cursor = store.connection.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM contribution WHERE exercise_id = ?", (exercise.id,))
            result_row = cursor.fetchone()
            self.assertEqual(2, result_row[0])
        finally:
            cursor.close()


        


if __name__ == "__main__":
    unittest.main()



