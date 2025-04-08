from __future__ import annotations
from zoneinfo import ZoneInfo
from datetime import datetime, tzinfo
from rich.progress import track
import logging
from typing import Any, Literal
import re
from pydantic_core.core_schema import is_instance_schema
import requests
from requests.models import parse_header_links
from fastoblig.domain import Student, Exercise, Course, Submission, SubmissionState
from fastoblig.storage import CANVAS_TOKEN, Storage
import polars as pl

logger = logging.getLogger("rich")

# Base URL for Canvas LMS
BASE_URL = "https://hvl.instructure.com/api/v1"

UTC_TZ = ZoneInfo("UTC")
LOCAL_TZ = ZoneInfo("Europe/Oslo")

# Many Canvas endpoints are paginated
DEFAULT_PAGE_SIZE = 200


_course_regex = re.compile(r"(\w+\d+)(-.*)? (\d+)([VH]) (.*)")

class CanvasHttpException(Exception):
    pass


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
        logger.error("unexpected JSON for object 'course'")
        logger.debug(json)
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
        logger.error("unexpected json for object 'student'")
        logger.debug(json)
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


    def _get_request(self, p: str, q: list[tuple[str, str]] = []) -> Any:
        if len(q) > 0:
            query = "?" + "&".join([f"{k}={v}" for k,v in q])
        else:
            query = ""
        url = f"{self.base_url}{p}{query}"
        response = requests.get(url, headers=self._auth_header())
        if response.status_code == 200:
            return response.json()
        else:
            logger.error("Unexpected response (%d) when requesting path '%s'. \nResponse: %s", response.status_code, url, response.content)
            raise CanvasHttpException()

    def _get_request_df(self, p: str,q: list[tuple[str, str]] = []) -> pl.DataFrame:
        data = self._get_request(p, q)
        if isinstance(data, dict):
            return pl.from_dicts([data])
        if isinstance(data, list) and len(data) == 0:
            return pl.DataFrame()
        return pl.from_dicts(data)


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
            logger.error(
                f"Error: got unexpected Canvas response when retrieving courses: {response.status_code}"
            )
            logger.debug(response.content)
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
            logger.error(
                f"Got unexpected Canvas response when retrieving enrollments: {response.status_code}"
            )
            logger.debug(response.content)
            return []
    

    def get_group_categories_in_course(self, course_id: int) -> pl.DataFrame:
        url =  f"/courses/{course_id}/group_categories?per_page=50" 
        q = [("per_page", "500")]
        df = self._get_request_df(url, q)
        return df.select(
            pl.col('id').alias('group_category_id'),
            pl.col('name').alias('group_category_name'),
            'allows_multiple_memberships'
        )
    
    def get_groups_in_course(self, course_id: int) -> pl.DataFrame:
        url = f"/courses/{course_id}/groups" 
        q = [("per_page", "500")]
        df = self._get_request_df(url, q)
        groups = self.get_group_categories_in_course(course_id)
        return df.select(
            pl.col('id').alias('group_id'),
            'name',
            'group_category_id',
        ).join(groups, on='group_category_id')


    def group_members(self, group_id: int, group_name: str, group_cat_id: int, group_cat_name: str) -> pl.DataFrame:
        url = f"/groups/{group_id}/users"
        df = self._get_request_df(url, [("per_page", "500")])
        if len(df) > 0:
            return df.select(
                pl.col('id').alias('user_id'),
                pl.lit(group_id).cast(pl.Int64).alias('group_id'),
                pl.lit(group_name).cast(pl.String).alias('group_name'),
                pl.lit(group_cat_id).cast(pl.Int64).alias('group_category_id'),
                pl.lit(group_cat_name).cast(pl.String).alias('group_category_name'),
            )
        else: 
            return pl.DataFrame()

    def get_student_in_groups(self, course_id: int, group_category_id: int) -> pl.DataFrame:
        # TODO: run in parallel?
        groups = self.get_groups_in_course(course_id)
        group_memberships = []
        relevant_groups = groups.filter(pl.col('group_category_id') == group_category_id)
        for row in track(relevant_groups.iter_rows()):
            group_id = row[0]
            group_name = row[1]
            group_cat_id = row[2]
            group_cat_name = row[3]
            members = self.group_members(group_id, group_name, group_cat_id, group_cat_name)
            if len(members) > 0:
                group_memberships.append(members)
        group_memberships_df = pl.concat(group_memberships)
        return group_memberships_df
    


    def get_exercise_groups(self, course_id: int):
        url = f"/courses/{course_id}/assignment_groups"
        assigs = self._get_request_df(url).select(pl.col('id').alias('assignment_group_id'), pl.col('name').alias('exercise_category'))
        return assigs

    def get_exercises(self, course_id: int) -> list[Exercise]:
        exercise_cats = self.get_exercise_groups(course_id)
        q = [("per_page", "500"), ("include", "group")]
        url = f"/courses/{course_id}/assignments"
        df = self._get_request_df(url, q)
        assignments =  df.join(exercise_cats, on='assignment_group_id', how='left', coalesce=True).sort('exercise_category','position').select(
            pl.col('id').alias('exercise_id'), # 0
            pl.col('name').alias('exercise_name'), # 1
            pl.col('description').alias('content'), # 2
            pl.col('due_at').str.to_datetime("%Y-%m-%dT%H:%M:%SZ", strict=False).dt.replace_time_zone('UTC'), # 3
            pl.col('points_possible'), # 4
            pl.col('exercise_category'), # 5
            pl.col('grading_type'), # 6
            pl.col('created_at').str.to_datetime("%Y-%m-%dT%H:%M:%SZ", strict=False).dt.replace_time_zone('UTC'), # 7
            pl.col('updated_at').str.to_datetime("%Y-%m-%dT%H:%M:%SZ", strict=False).dt.replace_time_zone('UTC').alias('last_changed'), # 8
            pl.col('group_category_id'), # 9
            pl.col('submission_types'), # 10
            pl.col('workflow_state'), # 11
            pl.col('allowed_extensions'), # 12
        )
        result = []
        for row in assignments.iter_rows():
            result.append(Exercise(
                id=row[0],
                course=course_id,
                name=row[1],
                content=row[2],
                deadline=row[3],
                grading_type=row[6],
                max_points=row[4],
                description_type="canvas_quiz" if "online_quiz" in row[10] else "canvas_html",
                category=row[5],
                grading_path=None,
                submission_category_id=row[9]
            ))

        return result 
            # first get all groups


    def get_submissions(self, course_id: int, exercise_id: int, default_filter: str = "submitted") -> list[Submission]:
        path = f"/courses/{course_id}/assignments/{exercise_id}/submissions"
        quer = [("per_page", "500"), ("include[]", "group"), ("grouped", "true"), ("include[]", "submission_history")]
        df = self._get_request_df(path, quer)
        subs = df.select(
            pl.col('id').alias('submission_id'), #0
            pl.col('body').alias('text_content'),#1
            pl.col('url').alias('url_content'),#2
            'score',#3
            pl.col('submitted_at').str.to_datetime("%Y-%m-%dT%H:%M:%SZ", strict=False).dt.replace_time_zone('UTC'),#4
            'submission_type',#5
            'workflow_state',#6
            pl.col('graded_at').cast(pl.String).str.to_datetime("%Y-%m-%dT%H:%M:%SZ", strict=False).dt.replace_time_zone('UTC'),#7
            'grade_matches_current_submission',#8
            'attempt',#9
            pl.col('group').struct.field('id').alias('group_id'),#10
            pl.col('group').struct.field('name').alias('group_name'),#11
            pl.col('user_id'), # 12
        ).filter(pl.col('workflow_state') == default_filter)
        result = []
        for row in subs.iter_rows():
            result.append(Submission(
                id=row[0],
                exercise=exercise_id, 
                submission_group_id=row[10],
                submission_group_name=row[11],
                contributions=[row[12]],
                content=row[2] if row[5] == "online_url" else row[1],
                state=SubmissionState.from_workflow_state(row[6], row[3]),
                submitted_at=row[4].replace(tzinfo=ZoneInfo("UTC")) if row[4] is not None else None,
                graded_at=row[7].replace(tzinfo=ZoneInfo("UTC")) if row[7] is not None else None,
                submission_type=row[5]
            ))
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
