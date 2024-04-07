from __future__ import annotations
from zoneinfo import ZoneInfo
from datetime import datetime
import logging
from typing import Any, Literal
import re
import requests
from fastoblig.domain import Student, Exercise, Course, Submission, SubmissionState
from fastoblig.storage import CANVAS_TOKEN, Storage

# Base URL for Canvas LMS
BASE_URL = "https://hvl.instructure.com/api/v1"

UTC_TZ = ZoneInfo("UTC")
LOCAL_TZ = ZoneInfo("Europe/Oslo")

# Many Canvas endpoints are paginated
DEFAULT_PAGE_SIZE = 200


_course_regex = re.compile(r"(\w+\d+)(-.*)? (\d+)([VH]) (.*)")


def parse_course(json: dict[str, Any]) -> Course | None:
    semester: Literal["spring", "fall"] | None = None
    if "id" in json and "name" in json:
        match = _course_regex.fullmatch(json["name"])
        if match:
            code = match.group(1)
            year = int(match.group(3))
            semester = "spring" if match.group(4) == "V" else "fall"
            desc = match.group(5)
            return Course(
                id=json["id"],
                code=code,
                description=desc,
                year=(2000 + year),
                semester=semester,
            )
        else:
            return Course(
                id=json["id"],
                description=json["name"],
                year=None,
                code=None,
                semester=None,
            )
    else:
        logging.error("unexpected JSON for object 'course'")
        logging.debug(json)
        return None


_studno_regex = re.compile(r"(\d+)@hvl.no")


def parse_student(json: dict[str, Any]) -> Student | None:
    if "role" and "user" in json:
        if (
            json["role"] == "StudentEnrollment"
            and json["user"]["sortable_name"] != "Teststudent"
        ):
            user = json["user"]
            mail = user["login_id"]
            names = user["sortable_name"].split(",")
            id = int(user["id"])
            match = _studno_regex.fullmatch(mail)
            student_no = None
            if match:
                student_no = int(match.group(1))
            return Student(
                id=id,
                email=mail,
                student_no=student_no,
                firstname=names[1].strip(),
                lastname=names[0].strip(),
            )
    else:
        logging.error("unexpected json for object 'student'")
        logging.debug(json)
    return None


def parse_exercise(course: int, group: str, json: dict[str, Any]) -> Exercise | None:
    if "id" and "name" in json:
        id = json["id"]
        name = json["name"]
        content = str(json["description"])

        published = True
        if "published" in json:
            published = json["published"]

        grading = None
        if "grading_type" in json:
            grading = json["grading_type"]

        deadline = None
        if "due_at" in json and json["due_at"]:
            deadline = datetime.fromisoformat(json["due_at"][:-1])
            deadline = deadline.replace(tzinfo=UTC_TZ)
            deadline = deadline.astimezone(LOCAL_TZ)

        max_points = None
        if "points_possible" in json:
            max_points = json["points_possible"]

        submission_category_id = None
        if "group_category_id" in json:
            submission_category_id = json["group_category_id"]

        return Exercise(
            id=id,
            name=name,
            content=content,
            grading=grading,
            deadline=deadline,
            category=group,
            course=course,
            max_points=max_points,
            submission_category_id=submission_category_id,
            published=published,
        )
    else:
        logging.error("Unexpected JSON format for object 'exercise'")
        logging.debug(json)

    return None


_submission_group_regex = re.compile(r".*\s(\d+)")


def parse_submission(exercise: int, json: dict[str, Any]):
    if "id" in json and "workflow_state" in json and "submission_type" in json:
        id = json["id"]
        if json["submission_type"] == "online_url":
            content = json["url"]
        else:
            content = json["body"]

        state = SubmissionState.from_workflow_state(json["workflow_state"], json['grade'])
        submission_ts = None
        grade_ts = None
        score = None
        if state != SubmissionState.UNSUBMITTED:
            if json["submitted_at"]:
                submission_ts = datetime.fromisoformat(json["submitted_at"][:-1])
                submission_ts = submission_ts.replace(tzinfo=UTC_TZ)
                submission_ts = submission_ts.astimezone(LOCAL_TZ)
        if state in {SubmissionState.PASSED, SubmissionState.FAILED}:
            if json["graded_at"]:
                grade_ts = datetime.fromisoformat(json["graded_at"][:-1])
                grade_ts = grade_ts.replace(tzinfo=UTC_TZ)
                grade_ts = grade_ts.astimezone(LOCAL_TZ)
            score = json["score"]

        users = []
        submission_group_id = None
        submission_group_name: str | None = None
        submission_group_no: int | None = None
        if json["group"]["id"] is None:
            users.append(json["user_id"])
        else:
            group = json["group"]
            submission_group_id = group["id"]
            submission_group_name = group["name"]
            if submission_group_name:
                match = _submission_group_regex.fullmatch(submission_group_name)
                if match:
                    submission_group_no = int(match.group(1))

        extended_to = None
        if json['cached_due_date']:
            extended_to = datetime.fromisoformat(json['cached_due_date'][:-1])
            extended_to = extended_to.replace(tzinfo=UTC_TZ)
            extended_to = extended_to.astimezone(LOCAL_TZ)


        return Submission(
            id=id,
            content=content,
            submission_type=json['submission_type'],
            exercise=exercise,
            submitted_at=submission_ts,
            extended_to=extended_to,
            state=state,
            members=users,
            submission_group_id=submission_group_id,
            submission_group_name=submission_group_name,
            submission_group_no=submission_group_no,
            grade=score,
            graded_at=grade_ts,
        )

    else:
        logging.error("Unexpected JSON content for object 'submission'")
        logging.debug(json)

    return None


class CanvasClient:

    def __init__(self, storage: Storage, base_url=BASE_URL, default_page_size=DEFAULT_PAGE_SIZE) -> None:
        self.storage = storage
        self.base_url = base_url
        self.default_page_size = default_page_size

    def _auth_header(self):
        token = self.storage.get_token(CANVAS_TOKEN)
        if token is not None:
            return {"Authorization": f"Bearer {token}"}
        else:
            return {}

    def get_courses(self) -> list[Course]:
        query = f"per_page={self.default_page_size}"
        url = self.base_url + "/courses" + "?" + query
        response = requests.get(url, headers=self._auth_header())
        if response.status_code == 200:
            data = response.json()
            courses = [parse_course(c) for c in data]
            result: list[Course] = sorted(
                [c for c in courses if c is not None], reverse=True
            )
            return result
        else:
            logging.error(
                f"Error: got unexpected Canvas response when retrieving courses: {response.status_code}"
            )
            logging.debug(response.content)
            return []

    def get_enrollments(self, course_id: int) -> list[Student]:
        query = f"per_page={self.default_page_size}"
        url = self.base_url + f"/courses/{course_id}/enrollments" + "?" + query
        response = requests.get(url, headers=self._auth_header())
        if response.status_code == 200:
            data = response.json()
            students = [parse_student(c) for c in data]
            result: list[Student] = [s for s in students if s is not None]
            return result
        else:
            logging.error(
                f"Got unexpected Canvas response when retrieving enrollments: {response.status_code}"
            )
            logging.debug(response.content)
            return []

    def get_exercises(self, course_id: int) -> list[Exercise]:
        query = f"per_page={self.default_page_size}"
        # first get all groups
        ass_groups_url = (
            self.base_url + f"/courses/{course_id}/assignment_groups" + "?" + query
        )
        ass_groups_response = requests.get(ass_groups_url, headers=self._auth_header())
        result = []
        if ass_groups_response.status_code == 200:
            ass_groups = [(o["id"], o["name"]) for o in ass_groups_response.json()]
            for gid, gname in ass_groups:
                ass_url = (
                    self.base_url
                    + f"/courses/{course_id}/assignment_groups/{gid}/assignments"
                )
                ass_response = requests.get(ass_url, headers=self._auth_header())
                if ass_response.status_code == 200:
                    to_add = [
                        parse_exercise(course_id, gname, o) for o in ass_response.json()
                    ]
                    for e in to_add:
                        if e is not None:
                            result.append(e)
                else:
                    logging.error(
                        f"Got unexpected Canvas result when retrieving assignments: {ass_response.status_code}"
                    )
                    logging.debug(ass_response.content)
        else:
            logging.error(
                f"Got unexpected Canvas result when retrieving assignment groups: {ass_groups_response.status_code}"
            )
            logging.debug(ass_groups_response.content)
        return result

    def get_submissions(self, course_id: int, exercise_id: int) -> list[Submission]:
        result = []
        query = f"per_page={self.default_page_size}&grouped=true&include=group"
        url = (
            self.base_url
            + f"/courses/{course_id}/assignments/{exercise_id}/submissions?"
            + query
        )
        response = requests.get(url, headers=self._auth_header())
        if response.status_code == 200:
            subs = [parse_submission(exercise_id, o) for o in response.json()]
            for s in subs:
                if s is not None:
                    if s.submission_group_id:
                        group_member_url = (
                            self.base_url + f"/groups/{s.submission_group_id}/users"
                        )
                        group_member_response = requests.get(
                            group_member_url, headers=self._auth_header()
                        )
                        if group_member_response.status_code == 200:
                            for m in group_member_response.json():
                                s.members.append(m["id"])
                        else:
                            logging.error(
                                f"Unexpected Canvas response when retrieving group members: {group_member_response.status_code}"
                            )
                            logging.debug(group_member_response.content)
                    result.append(s)
        else:
            logging.error("Unexpected Canvas response when retrieving submissions")
            logging.debug(response.content)

        return result


    def update_submission(self,
                          course_id: int,
                          assignment_id: int,
                          student_id: int,
                          is_group: bool = True,
                          comment: str | None = None,
                          grading: str | None = None):
        url = f"{self.base_url}/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
        data = {}
        if is_group:
            data['comment[group_comment]'] = "true"
        if comment:
            data['comment[text_comment]'] = comment
        if grading:
            data['submission[posted_grade]'] = grading
        requests.put(url, headers=self._auth_header(), data=data)
