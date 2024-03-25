from __future__ import annotations
import logging
from typing import Any, Literal
from pydantic import BaseModel
import os
import re
import requests

# Base URL for Canvas LMS
BASE_URL = "https://hvl.instructure.com/api/v1"

# Many Canvas endpoints are paginated
DEFAULT_PAGE_SIZE = 200

_token = None
if "CANVAS_TOKEN" in os.environ:
    _token = os.environ["CANVAS_TOKEN"]


_course_regex = re.compile(r"(\w+\d+)(-.*)? (\d+)([VH]) (.*)")

class Course(BaseModel):
    id: str 
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
                return Course(id=str(json["id"]), code=code, description=desc,
                              year=(2000+year), semester=semester) 
            else:
                return Course(id=str(json['id']), description=json['name'], year=None,
                              code=None, semester=None)
        else:
            logging.error("got unexpected json:")
            logging.error(json)
            return None


def get_courses() -> list[Course]:
    query = f"per_page={DEFAULT_PAGE_SIZE}"
    url = BASE_URL + "/courses" + "?" + query
    headers = {
        'Authorization': f"Bearer {_token}"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        courses = [Course.from_json(c) for c in data]
        result : list[Course] = [c for c in courses if c is not None]
        return result
    else:
        logging.error(f"Error: got unexpected canvas response: {response.status_code}")
        logging.error(response.content)
        return []

