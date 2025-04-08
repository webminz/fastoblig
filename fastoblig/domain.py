from datetime import datetime
from enum import Enum
from typing import Literal, Any
from pydantic import BaseModel
from pathlib import Path

class Student(BaseModel):
    """
    Students are uniquely identified by a numeric id, given by the LMS.
    Also, the student email may be used as a secondary identifier as 
    it generally contains some form of student id.
    """
    id: int
    student_no: int | None
    firstname: str 
    lastname: str 
    email: str

class Course(BaseModel):
    """
    Represents a course _instance_!
    Each course instance has a unique id.
    Each course instance has course code.
    The combination of couse code, year, and semester should be unique.
    """
    id: int 
    code: str | None
    description: str 
    semester : Literal["spring", "fall"] | None
    year: int | None

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, Course):
            if self.year and self.semester:
                if other.year and other.semester:
                    if self.year == other.year:
                        s1 = 0 if self.semester == "spring" else 1
                        s2 = 0 if other.semester == "spring" else 1
                        return s1 < s2 
                    else:
                        return self.year < other.year
                return False 
        return True

ExerciseDescriptionType = Literal['git_repo', 'canvas_quiz', 'canvas_html', 'plaintext']

GradingType = Literal['pass_fail', 'points']

SubissionType = Literal['online_upload', 'online_text_entry', 'online_quiz', 'online_url']

class Exercise(BaseModel):
    """
    A course exercise that is graded, which comprises the following fields.

    :id: int (numeric id of the exercise, is assigned by the LMS, global uniqueness is assumed)
    :course: int (reference to the associated course)
    :name: str (a short title of the exercise)
    :content: str (detailed description of the exercise, internal structure depends on the type of exercise)
    """
    id : int  
    course: int
    name: str 
    content: str | None
    grading_type : GradingType = "points" 
    max_points: float | None
    description_type : ExerciseDescriptionType = "canvas_html"
    deadline: datetime | None 
    category: str | None 
    published: bool = True
    # gruppesett in Canvas
    submission_category_id: int | None 
    # The location, where the grading data is stored on the local filesystem
    grading_path: Path | None = None

    def __lt__(self, other: Any):
        if isinstance(other, Exercise):
            if self.deadline and other.deadline:
                return self.deadline < other.deadline
            elif self.deadline and other.deadline is None:
                return True 
            elif self.deadline is None:
                return False 
        return True

    def print_state(self) -> str:
        if self.grading_path is not None:
            return "GRADING"
        elif self.published:
            return "PUBLISHED"
        else: 
            return "UNPUBLISHED"


class SubmissionState(Enum):
    UNSUBMITTED = 0
    SUBMITTED = 1
    FAILED_IMPORTED = 2 
    PASSED_IMPORTED = 3 
    CHECKED_OUT = 4 
    TESTED = 5 
    FEEDBACK_GENERATED = 6 
    FEEDBACK_PUBLISHED = 7
    FAILED = 8
    PASSED = 9

    @staticmethod
    def from_workflow_state(state: str, grade: str | float | None):
        if state == "submitted":
            return SubmissionState.SUBMITTED
        elif state == "graded" and (grade == "complete" or (isinstance(grade, float) and grade > 0.0)):
            return SubmissionState.PASSED_IMPORTED # externally graded
        elif state == "graded":
            return SubmissionState.FAILED_IMPORTED
        else:
            return SubmissionState.UNSUBMITTED

    # TODO: succesor states and custom compare

    def __lt__(self, other):
        if isinstance(other, SubmissionState):
            return self.value < other.value
        else:
            return False

    
    def __eq__(self, other):
        if isinstance(other, SubmissionState):
            return self.value == other.value
        else:
            return False


class Submission(BaseModel):
    """
    Represent the submission for an exercise made by a group of students.
    This group of students might as well consist of a single student.
    """

    # TODO: custom compare

    id: int 
    exercise: int 
    content: str | None
    state : SubmissionState 
    contributions: list[int]
    submission_type: str | None
    submission_group_id: int | None
    submission_group_name: str | None
    submitted_at: datetime | None  = None
    graded_at: datetime | None = None
    extended_to: datetime | None = None
    grade: float | None = None
    testresult_file: Path | None = None
    comment_file: Path | None = None
    feedback_file: Path | None = None
