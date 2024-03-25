from __future__ import annotations
import math
from zoneinfo import ZoneInfo
from datetime import datetime, tzinfo
import logging
from typing import Any, Literal
from pydantic import BaseModel
import os
import re
import requests
from requests.api import get

# Base URL for Canvas LMS
BASE_URL = "https://hvl.instructure.com/api/v1"

LOCAL_TZ = ZoneInfo("Europe/Oslo")

# Many Canvas endpoints are paginated
DEFAULT_PAGE_SIZE = 200


def _auth_header():
    if "CANVAS_TOKEN" in os.environ:
        return {
            'Authorization': f"Bearer {os.environ['CANVAS_TOKEN']}"
        }
    else:
        return {}


_course_regex = re.compile(r"(\w+\d+)(-.*)? (\d+)([VH]) (.*)")

class Course(BaseModel):
    id: int 
    code: str | None
    description: str | None
    semester : Literal["spring"] | Literal["fall"] | None
    year: int | None

    @staticmethod
    def from_json(json: dict[Any, Any]) -> Course | None:
        semester : Literal['spring', 'fall'] | None = None
        if "id" in json and 'name' in json:
            match =  _course_regex.fullmatch(json['name'])
            if match:
                code = match.group(1)
                year = int(match.group(3))
                semester = "spring" if match.group(4) == "V" else "fall"
                desc = match.group(5)
                return Course(id=json["id"], code=code, description=desc,
                              year=(2000+year), semester=semester) 
            else:
                return Course(id=json['id'], description=json['name'], year=None,
                              code=None, semester=None)
        else:
            logging.error("unexpected JSON for object 'course'")
            logging.debug(json)
            return None
    
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


_studno_regex = re.compile(r"(\d+)@hvl.no")

class Student(BaseModel):
    id: int
    student_no: str | None
    firstname: str 
    lastname: str 
    email: str

    @staticmethod
    def from_json(json: dict[str, Any]) -> Student | None:
        if "role" and "user" in json:
            if json["role"] == "StudentEnrollment" and json['user']['sortable_name'] != "Teststudent":
                user = json["user"]
                mail = user['login_id']
                names = user['sortable_name'].split(',')
                id = int(user['id'])
                match = _studno_regex.fullmatch(mail)
                student_no = None
                if match:
                    student_no = match.group(1)
                return Student(id=id, email=mail, student_no=student_no, firstname=names[1].trim(), lastname=names[0].trim())
        else:
            logging.error("unexpected json for object 'student'")
            logging.debug(json)
        return None

class Exercise(BaseModel):
    id : int 
    course: int
    name: str 
    content: str 
    grading : str | None 
    max_points: float | None
    deadline: datetime | None 
    category: str | None 
    published: bool = True
    # gruppesett in Canvas
    submission_category_id: int | None 

    @staticmethod
    def from_json(course: int, group: str, json: dict[str, Any]) -> Exercise | None:
        if "id" and "name" in json:
            id = json['id']
            name = json['name']
            content = str(json['description'])

            published = True
            if 'published' in json:
                published = json['published']

            grading = None 
            if 'grading_type' in json:
                grading = json['grading_type']

            deadline = None 
            if 'due_at' in json and json['due_at']:
                deadline = datetime.fromisoformat(json['due_at'][:-1])
                deadline = deadline.replace(tzinfo=LOCAL_TZ)

            max_points = None
            if 'points_possible' in json:
                max_points = json['points_possible']

            submission_category_id = None
            if 'group_category_id' in json:
                submission_category_id = json['group_category_id']

            return Exercise(id=id, name=name, content=content, grading=grading, deadline=deadline,
                            category=group, course=course, max_points=max_points,
                            submission_category_id=submission_category_id, published=published)
        else:
            logging.error("Unexpected JSON format for object 'exercise'")
            logging.debug(json)

        return None

    def __lt__(self, other: Any):
        if isinstance(other, Exercise):
            if self.deadline and other.deadline:
                return self.deadline < other.deadline
            elif self.deadline and other.deadline is None:
                return True 
            elif self.deadline is None:
                return False 
        return True


_submission_group_regex = re.compile(r".*\s(\d+)")

class Submission(BaseModel):
    id: int 
    exercise: int 
    content: str | None
    submission_group_id: int | None
    submission_group_name: str | None
    submission_group_no: int | None 
    members : list[int]
    state : str = "unsubmitted"
    submitted_at: datetime | None  
    graded_at: datetime | None  
    grade: float | None = None
    extended_to: datetime | None = None
    testresult: str | None = None
    comment: str | None = None
    feedback: str | None = None


    @staticmethod
    def from_json(exercise: int, json: dict[str, Any]):
    # submission  objects have 
    # - id 
    # - url if submission_type == "online_url" else look in body
    # - grade can contain complete if workflow_state="graded"
    # - score -> similar to grade 
    # - submitted_at 
    # - user_id -> relevant if single group
    # - graded_at 
    # group.id 
    # group.name
        if 'id' in json and 'workflow_state' in json and 'submission_type' in json:
            id = json['id']
            if json['submission_type'] == 'online_url':
                content = json['url']
            else:
                content = json['body']

            submission_ts = None
            state = json['workflow_state']
            if state != "unsubmitted":
                if json['submitted_at']:
                    submission_ts = datetime.fromisoformat(json['submitted_at'][:-1])
                    submission_ts =  submission_ts.replace(tzinfo=LOCAL_TZ)

            grade_ts = None
            score = None
            if state == "graded":
                if json['graded_at']:
                    grade_ts = datetime.fromisoformat(json['graded_at'][:-1])
                    grade_ts = grade_ts.replace(tzinfo=LOCAL_TZ)
                state = json['grade']
                score = json['score']


            users = []
            submission_group_id = None 
            submission_group_name : str | None = None
            submission_group_no :int | None = None
            if json['group']['id'] is None:
                users.append(json['user_id'])
            else:
                group = json['group']
                submission_group_id = group['id']
                submission_group_name = group['name']
                if submission_group_name:
                    match = _submission_group_regex.fullmatch(submission_group_name)
                    if match:
                        submission_group_no = int(match.group(1))

            return Submission(id=id,
                              content=content, 
                              exercise=exercise,
                              submitted_at=submission_ts, 
                              state=state,
                              members=users,
                              submission_group_id=submission_group_id, 
                              submission_group_name=submission_group_name,
                              submission_group_no=submission_group_no,
                              grade=score,
                              graded_at=grade_ts)

        else:
            logging.error("Unexpected JSON content for object 'submission'")
            logging.debug(json)

        return None


def get_courses() -> list[Course]:
    query = f"per_page={DEFAULT_PAGE_SIZE}"
    url = BASE_URL + "/courses" + "?" + query
    response = requests.get(url, headers=_auth_header())
    if response.status_code == 200:
        data = response.json()
        courses = [Course.from_json(c) for c in data]
        result : list[Course] = sorted([c for c in courses if c is not None], reverse=True)
        return result
    else:
        logging.error(f"Error: got unexpected Canvas response when retrieving courses: {response.status_code}")
        logging.debug(response.content)
        return []


def get_enrollments(course_id: int) -> list[Student]:
    query = f"per_page={DEFAULT_PAGE_SIZE}"
    url = BASE_URL + f"/courses/{course_id}/enrollments"  + "?" + query
    response = requests.get(url, headers=_auth_header())
    if response.status_code == 200:
        data = response.json()
        students = [Student.from_json(c) for c in data]
        result : list[Student] = [s for s in students if s is not None]
        return result
    else:
        logging.error(f"Got unexpected Canvas response when retrieving enrollments: {response.status_code}")
        logging.debug(response.content)
        return []


def get_exercises(course_id: int) -> list[Exercise]:
    query = f"per_page={DEFAULT_PAGE_SIZE}"
    # first get all groups
    ass_groups_url = BASE_URL + f"/courses/{course_id}/assignment_groups"  + "?" + query
    ass_groups_response = requests.get(ass_groups_url, headers=_auth_header())
    result = []
    if ass_groups_response.status_code == 200:
        ass_groups = [(o['id'], o['name']) for o in ass_groups_response.json() ]
        for (gid, gname) in ass_groups:
            ass_url = BASE_URL + f"/courses/{course_id}/assignment_groups/{gid}/assignments"
            ass_response = requests.get(ass_url, headers=_auth_header())
            if ass_response.status_code == 200:
                to_add = [Exercise.from_json(course_id, gname, o) for o in ass_response.json()]
                for e in to_add:
                    if e is not None:
                        result.append(e)
            else:
                logging.error(f"Got unexpected Canvas result when retrieving assignments: {ass_response.status_code}")
                logging.debug(ass_response.content)
    else:
        logging.error(f"Got unexpected Canvas result when retrieving assignment groups: {ass_groups_response.status_code}")
        logging.debug(ass_groups_response.content)
    return result


def get_submissions(course_id: int, exercise_id: int) -> list[Submission]:
    result = []
    query = f"per_page={DEFAULT_PAGE_SIZE}&grouped=true&include=group"
    url = BASE_URL + f"/courses/{course_id}/assignments/{exercise_id}/submissions?" + query
    response = requests.get(url, headers=_auth_header())
    if response.status_code == 200:
        subs = [Submission.from_json(exercise_id, o) for o in response.json()]
        for s in subs:
            if s is not None:
                if s.submission_group_id:
                    group_member_url = BASE_URL + f"/groups/{s.submission_group_id}/users"
                    group_member_response = requests.get(group_member_url, headers=_auth_header())
                    if group_member_response.status_code == 200:
                        for m in group_member_response.json():
                            s.members.append(m['id'])
                    else:
                        logging.error(f"Unexpected Canvas response when retrieving group members: {group_member_response.status_code}")
                        logging.debug(group_member_response.content)
                result.append(s)
    else: 
        logging.error("Unexpected Canvas response when retrieving submissions")
        logging.debug(response.content)


    return result




