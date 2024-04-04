from datetime import datetime
from enum import Enum
from typing import Literal, Any
from pydantic import BaseModel
from pathlib import Path

class Student(BaseModel):
    id: int
    student_no: int | None
    firstname: str 
    lastname: str 
    email: str

class Course(BaseModel):
    id: int 
    code: str | None
    description: str 
    semester : Literal["spring"] | Literal["fall"] | None
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

class Exercise(BaseModel):
    id : int 
    course: int
    name: str 
    content: str | None
    grading : str | None 
    max_points: float | None
    description_type : str = "canvas"
    deadline: datetime | None 
    category: str | None 
    published: bool = True
    # gruppesett in Canvas
    submission_category_id: int | None 
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
    FAILED = 2 
    PASSED = 3 
    CHECKED_OUT = 4 
    TESTED = 5 
    FEEDBACK_GENERATED = 6 
    FEEDBACK_PUBLISHED = 7

    @staticmethod
    def from_workflow_state(state: str, grade: str | float | None):
        if state == "submitted":
            return SubmissionState.SUBMITTED
        elif state == "graded" and grade == "complete":
            return SubmissionState.PASSED # externally graded
        elif state == "graded":
            return SubmissionState.FAILED
        else:
            return SubmissionState.UNSUBMITTED


class Submission(BaseModel):
    id: int 
    exercise: int 
    content: str | None
    submission_type: str | None
    submission_group_id: int | None
    submission_group_name: str | None
    submission_group_no: int | None 
    members : list[int]
    state : SubmissionState = SubmissionState.UNSUBMITTED
    submitted_at: datetime | None  
    graded_at: datetime | None  
    extended_to: datetime | None = None
    grade: float | None = None
    testresult: str | None = None
    comment: str | None = None
    feedback: str | None = None
