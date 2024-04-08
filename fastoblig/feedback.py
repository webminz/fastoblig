from datetime import datetime
from pathlib import Path
import subprocess
from git import GitCommandError
from openai import OpenAI 
from typing import Literal
from pydantic import BaseModel

# TODO: make class for LLMs

class AddressSettings(BaseModel):
    language: Literal["NO"] | Literal["EN"] | Literal["DE"]
    is_multiple: bool = False

    def mk_prompt_part(self):
        result = ""
        if self.language == "NO":
            result += "Write your feedback in Norwegian!"
        elif self.language == "EN":
            result += "Write your feedback in English."
        elif self.language == "DE":
            result += "Write you feedback in German."
        result += "\n"
        if self.is_multiple:
            result += "Address the students in plural."
        return result

    def pronoun(self) -> str:
        if self.language == "EN":
            return "You"
        elif self.language == "NO":
            if self.is_multiple:
                return "Dere"
            else:
                return "Du"
        elif self.language == "DE":
            if self.is_multiple:
                return "Ihr"
            else:
                return "Du"
        else:
            return ""

    def see_also(self, details: str):
        if self.language == "NO":
            return "Se flere detaljer her: " + details
        elif self.language == "EN":
            return "See more details at: " + details
        elif self.language == "DE":
            return "Mehr information hier: " + details

    def github_comment_addendum(self) -> str:
        if self.language == "NO":
            return self.pronoun() + " kan bare _lukke_ dette \"issue\" som _løst_ når " + self.pronoun().lower() + " har lest gjenomm den :wink:"
        elif self.language == "EN":
            return "You can just _close_ this \"issue\" as _completed_ when you have read through the comments :wink:"
        elif self.language == "DE":
            if self.is_multiple:
                return self.pronoun() + " könnt diesen \"issue\" als _fertig_ abschliessen wenn " + self.pronoun().lower() + " die Kommentare durchgelesen habt :wink:"
            else:
                return self.pronoun() + " kannst diesen \"issue\": als _fertig_ abschliessen wenn " + self.pronoun().lower() + " die Kommentare duchgelesen hast :wink:"
        else:
            return ""



IGNORE_LIST = [
    'requirements.txt',
    'readme.md',
    'pyproject.toml',
    'build.gradle',
]
INTERESTING_TYPES = [
    '.md',
    '.txt',
    '.py',
    '.java',
    '.xml',
    '.toml',
    '.yml',
    '.yaml',
    '.csv',
]

def is_uninteresting(p: Path, project: Path) -> bool:
    fname = p.name
    pname = str(p.relative_to(project))
    if not p.is_file():
        return True
    if not p.suffix in INTERESTING_TYPES:
        return True
    if pname.startswith('.'):
        return True
    if pname.startswith("_"):
        return True
    if "__" in pname:
        return True
    if fname.lower() in IGNORE_LIST:
        return True
    return False

PERSONA = """\
You are a teaching assistant for a Computer Science class. 
You are very knowledgeable and and are concerned with supporting your students.
Among the students you are known to give very helpful feedback and comments, likewise your 
teaching philosophy is not to "spoon feed" them, i.e. you are never providing them with the 
exercise solutions directly.
"""

def collect_startcode_files(folder: Path) -> str:
    input_files = []
    for f in [x for x in folder.rglob("*") if not is_uninteresting(x, folder)]:
        fil_content = open(f, mode="rt").read(-1)
        fil_templat = f"""\
    <file path="{f.relative_to(folder)}">
{fil_content}
    </file>
    """
        input_files.append(fil_templat)
    return "\n".join(input_files)


def create_system_prompt(
        exercise_folder: Path,
        exercise_file: str,
        course_desc: str, 
        exercise_name: str,
        address_settings : AddressSettings
    ) -> str:
    description_file = exercise_folder / exercise_file
    exercise_description = open(description_file, mode="rt").read(-1)
    startcode_files = collect_startcode_files(exercise_folder)
    
    task = f"""\
{PERSONA}

Your task is to review students submissions to a mandatory programming exercise in the course: "{course_desc}".
The exercise descriptions is given below as a XML-element:

<exercise name=\"{exercise_name}\">
{exercise_description}
</exercise>

The students are provided with "startcode" in a GitHub repository, that they will use as a template repository for their submission.
The contents of this repository are given below in XML, where each "file"-element provides the relative "path" of the file inside the repository 
as as the startcode-file contents:


File contents (given as XML-elements):
<startcode>
{startcode_files}
</startcode>


The user will prompt you with individual student submissions and your task is to respond with a extensive code review of the student submission.
The student submssion will provided as an XML element containing 
- an "id"-attribute identifying the submission, 
- a list of "file"-elements showing the contents of the files that make up the student submission,
- optionally, a "testresult"-element showing the standard output of running the unit tests on the submission,
- optionally, a "comment"-element containing comments on the submission provided by the course teacher,
  which should be taken into account when asessing the submission.

Your response should formatted as a XML document, which comprises two sub-elements:
- review
- assesment

The "review"-element contains your comprehensive commentary on the student submission.
Focus mainly only the program logic and the student's reasoning, less on syntax and code aesthetics.
Best practices concerning aspects such as commenting are secondary here.
It should be a markdown-formatted text that 
  1. first, highlights things that the students did well, 
  2. secondly, pointing out potential errors, 
  3. thirdly, providing some tips on where to improve upon in the future or topics that the student may look into again.
The text shall be written in such a way that it addresses the student(s) directly. 
Write in a positive and motivating tone but remain moderate in you temper (i.e. avoid exaggerated expressions such 
"I am applauding you" but write in a more modest tone like "good work").
{address_settings.mk_prompt_part()}
The "assessment"-elment contains a general overall assesment of the submission on the A-F scale, where "A" means "exceeding expecations",
"B" means "very good = meeting all expectations" and so on.
"""
    return task


def collect_submission_files(
        folder: Path,
        submission_id: int,
        testresult_file: str | None, 
        comment_file: str | None
    ) -> str:
    files = []
    for f in [x for x in folder.rglob("*") if not is_uninteresting(x, folder)]:
        # TODO: make it proper by comparing the files for changes based on index
        if not f.name.startswith("test_"):
            c = open(f, mode="rt").read(-1)
            t = f"""\
<file path="{f.relative_to(folder)}">
{c}
</file>\
"""
            files.append(t)
    files_text = "\n".join(files)
    testresult = ""
    if testresult_file:
        with open(testresult_file, mode="rt") as f:
            testresult = f"""\
<testresult>
{f.read(-1)}
</testresult>\
            """
    comment = ""
    if comment_file:
        with open(comment_file, mode="rt") as f:
            comment = f"""\
<comment>
{f.read(-1)}
</comment>
            """
    result = f"""\
<submission id={submission_id}>
{files_text}
{testresult}
{comment}
</submission>
    """
    return result


def contact_openai(
    access_token: str, 
    user_prompt: str,
    system_prompt: str = "You are a helpful assistant",
    use_model: str = "gpt-4-turbo-preview"
    ) -> str:
    client = OpenAI(api_key=access_token)
    completion = client.chat.completions.create(
        model=use_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
      ]
    )
    assesment_result = completion.choices[0].message.content
    assert assesment_result is not None
    return assesment_result




