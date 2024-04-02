import json
from unittest.mock import MagicMock, patch
from typing import Any
from fastoblig.canvas import CanvasClient
import unittest

from fastoblig.domain import Course
from fastoblig.storage import CANVAS_TOKEN 



COURSES_JSON = """\
[
    {
        "id": 50001,
        "name": "ING301-1 23V Datateknologi og videregående programmering for ingeniører",
        "account_id": 60001,
        "uuid": "95ddb0ba-7cdb-4331-bcd5-22fb8adca751",
        "start_at": null,
        "grading_standard_id": null,
        "is_public": false,
        "created_at": "2022-05-01T06:15:00Z",
        "course_code": "ING301-1 23V",
        "default_view": "modules",
        "root_account_id": 1,
        "enrollment_term_id": 333,
        "license": "private",
        "grade_passback_setting": null,
        "end_at": null,
        "public_syllabus": false,
        "public_syllabus_to_auth": false,
        "storage_quota_mb": 500,
        "is_public_to_auth_users": false,
        "homeroom_course": false,
        "course_color": null,
        "friendly_name": null,
        "apply_assignment_group_weights": false,
        "calendar": {
          "ics": "https://test.instructure.com/feeds/calendars/course_28937y478y923742894289.ics"
        },
        "time_zone": "Europe/Copenhagen",
        "blueprint": false,
        "template": false,
        "sis_course_id": "UE_203_ING301_1_2023_VÅR_1",
        "integration_id": null,
        "enrollments": [
          {
            "type": "teacher",
            "role": "TeacherEnrollment",
            "role_id": 4,
            "user_id": 80000000001,
            "enrollment_state": "active",
            "limit_privileges_to_course_section": false
          }
        ],
        "hide_final_grades": false,
        "workflow_state": "available",
        "restrict_enrollments_to_course_dates": false
    },
    {
        "id": 500002,
        "name": "Testemne for Ole Nordmann",
        "account_id": 60001,
        "uuid": "d05cfa41b34d435f8a965ea073426bc6",
        "start_at": null,
        "grading_standard_id": null,
        "is_public": null,
        "created_at": "2022-03-15T11:43:02Z",
        "course_code": "Testemne for Ole Nordmann",
        "default_view": "modules",
        "root_account_id": 1,
        "enrollment_term_id": 1,
        "license": null,
        "grade_passback_setting": null,
        "end_at": null,
        "public_syllabus": false,
        "public_syllabus_to_auth": false,
        "storage_quota_mb": 500,
        "is_public_to_auth_users": false,
        "homeroom_course": false,
        "course_color": null,
        "friendly_name": null,
        "apply_assignment_group_weights": false,
        "calendar": {
          "ics": "https://test.instructure.com/feeds/calendars/course_49328572893572348fg2394h.ics"
        },
        "time_zone": "Europe/Copenhagen",
        "blueprint": false,
        "template": false,
        "sis_course_id": "hvl220315-e763-akv",
        "integration_id": null,
        "enrollments": [
          {
            "type": "teacher",
            "role": "TeacherEnrollment",
            "role_id": 4,
            "user_id": 80000000001,
            "enrollment_state": "active",
            "limit_privileges_to_course_section": false
          }
        ],
        "hide_final_grades": false,
        "workflow_state": "unpublished",
        "restrict_enrollments_to_course_dates": false
    }
]
"""

ENROLLMENT_JSON = """\
 [
    {
        "associated_user_id": null,
        "course_id": 50001,
        "course_integration_id": null,
        "course_section_id": 351111,
        "created_at": "2024-01-06T06:13:12Z",
        "end_at": null,
        "enrollment_state": "active",
        "grades": {
            "current_grade": null,
            "current_score": null,
            "final_grade": null,
            "final_score": 0.0,
            "html_url": "https://test.instructure.com/courses/50001/grades/6969",
            "unposted_current_grade": null,
            "unposted_current_score": null,
            "unposted_final_grade": null,
            "unposted_final_score": 0.0
        },
        "html_url": "https://test.instructure.com/courses/50001/users/6969",
        "id": 9999999,
        "last_activity_at": "2024-03-16T00:44:53Z",
        "last_attended_at": null,
        "limit_privileges_to_course_section": false,
        "role": "StudentEnrollment",
        "role_id": 3,
        "root_account_id": 1,
        "section_integration_id": null,
        "sis_account_id": "ST_0203201000",
        "sis_course_id": "UE_203_ING301_1_2024_VÅR_1",
        "sis_section_id": "UE_203_ING301_1_2024_VÅR_1",
        "sis_user_id": "fs:691:123456",
        "start_at": null,
        "total_activity_time": 15405,
        "type": "StudentEnrollment",
        "updated_at": "2024-01-06T06:13:12Z",
        "user": {
            "created_at": "2021-07-29T03:45:36+02:00",
            "id": 6969,
            "integration_id": null,
            "login_id": "12345@hvl.no",
            "name": "Ole Nordmann",
            "root_account": "hvl.instructure.com",
            "short_name": "Ole Nordmann",
            "sis_user_id": "fs:691:123456",
            "sortable_name": "Nordmann, Ole"
        },
        "user_id": 6969
    }
]
"""

NOT_AUTHENTICATED_JSON = """
{
    "errors": [
        {
            "message": "brukergodkjenning kreves"
        }
    ],
    "status": "unauthenticated"
}
"""

SECRET_API_TOKEN = "detteerhjemmelig1234"

class MockResponse:

    def __init__(self, status_code: int, json_data: str | None) -> None:
        self.status_code = status_code
        self.content = json_data

    def json(self) -> Any:
        if self.content:
            return json.loads(self.content)
        return None

def fake_answers(*args, **kwargs):
    if 'headers' in kwargs and 'Authorization' in kwargs['headers']:
        if kwargs['headers']['Authorization'] != f"Bearer { SECRET_API_TOKEN }":
            return MockResponse(401, NOT_AUTHENTICATED_JSON)
    else: 
        return MockResponse(401, NOT_AUTHENTICATED_JSON)

    if args[0] == "https://test.instructure.com/api/v1/courses?per_page=50":
        return MockResponse(200, json_data=COURSES_JSON)
    else:
        return MockResponse(404, None)


def fake_get_token(token: str) -> str | None:
    if token == CANVAS_TOKEN:
        return SECRET_API_TOKEN
    else:
        return None

class CanvasClientTest(unittest.TestCase):
    pass

    
    @patch('requests.get', fake_answers)
    def test_read_courses(self):
        storage = MagicMock()
        storage.get_token = fake_get_token
        client = CanvasClient(storage, "https://test.instructure.com/api/v1", 50)
        actual_courses = client.get_courses()
        expected_courses = []
        expected_courses.append(Course(
            id=50001,
            code="ING301",
            year=2023,
            semester="spring",
            description="Datateknologi og videregående programmering for ingeniører"
        ))
        expected_courses.append(Course(
            id=500002,
            code=None,
            year=None,
            semester=None,
            description="Testemne for Ole Nordmann"

        ))
        self.assertEqual(actual_courses, expected_courses)


if __name__ == "__main__":
    unittest.main()
