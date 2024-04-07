from datetime import datetime
from pathlib import Path
import subprocess
from git import GitCommandError
from openai import OpenAI 
from typing import Literal
from pydantic import BaseModel
# client = OpenAI()

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


def perform_assesment(
    work_dir: str,
    student_id: str,
    exercise_repo_url: str,
    student_repo_url: str, 
    additional_comment: str | None = None,
    not_after: datetime | None = None,
    test_command: list[str] = ["/opt/homebrew/bin/python3", "tests/test_part_a.py"],
    glob_pattern: str = "*",
    llm: str = "gpt-4-turbo-preview",
    exercise_file: str = "README.md",
    exercise_folder_name: str = "exercise",
) -> None:
    cwd = Path(work_dir)
    exercise_repo = cwd / exercise_folder_name
    if not exercise_repo.exists():
        try:
            print(f"Exercise Description does not exist! Cloning {exercise_repo_url} to {exercise_repo} now!")
            repo = git.Repo.clone_from(exercise_repo_url, exercise_repo)
            print("Done.")

        except GitCommandError as e:
            print("Error while cloning exercise repository!")
            print(e)
            print("Aborting!")
            return
    readme_file = exercise_repo / exercise_file
    system_prompt = create_system_prompt(exercise_repo, readme_file)

    print(f"Assessing Student Submission '{student_id}'")
    submission_repo = cwd / student_id
    if not submission_repo.exists():  
        try:
            print(f"Cloning {student_repo_url} to {submission_repo}")
            repo = git.Repo.clone_from(student_repo_url, submission_repo)
            print("Done.")
            
            if not_after:
                hexsha = None
                flag = False
                for commit in repo.iter_commits():
                    commit_dt = datetime.fromtimestamp(commit.authored_date)
                    if commit_dt > not_after and not flag:
                        print(f"There are commits after set deadline {not_after.isoformat()} -> going to ignore those!")
                        flag = True
                    if commit_dt <= not_after:
                        hexsha = commit.hexsha
                        break
                if hexsha and flag:
                    print(f"Checking out latest commit before deadline: {hexsha}")
                    repo.git.checkout(hexsha)
                    print("Done.")
                
        except GitCommandError as e:
            print("Error while cloning submission repository!")
            print(e)
            print("Aborting!")
            return

    print("Unit Test Results:")
    testrun = subprocess.run(test_command, capture_output=True, env={"PYTHONPATH": "."}, cwd=submission_repo)
    testresult = testrun.stderr.decode('utf-8')
    print(testresult)

    files = []
    for f in [x for x in submission_repo.rglob("*") if not is_uninteresting(x, submission_repo)]:
        if not f.name.startswith("test_"):
            c = open(f, mode="rt").read(-1)
            t = f"""\
<file path="{f.relative_to(submission_repo)}">
{c}
</file>\
"""
            files.append(t)
    files_text = "\n".join(files)
    submission_text = f"""
<submission id={student_id}>
{files_text}
<testresult>
{testresult}
</testresult>
<comment>
{additional_comment}
</comment>
</submission>
"""
    print("\nContacting OpenAI API...")
    completion = client.chat.completions.create(
        model="gpt-4-turbo-preview",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": submission_text}
      ]
    )
    print("...Feedback received")
    assesment_result = completion.choices[0].message.content
    if assesment_result.startswith("```xml"):
        assesment_result = assesment_result[7:-3]
    fil = open(submission_repo / 'assessment.xml', mode="wt")
    fil.write(assesment_result)
    fil.close()
    print("Result:")
    print(assesment_result)
    print("Dere kan bare lukke dette _\"Issue\"_ som _\"løst\"_ når når dere har lest gjennom :wink:")



def main():
    perform_assesment('/Users/past-madm/Projects/teaching/ing301/assesment/a',
                  '24',
                  'https://github.com/selabhvl/ing301-projectpartA-startcode',
                  'https://github.com/AndersCOlsen/Opppgave4DelA', 
                  #not_after=datetime(2024, 2, 26, 6),
                  additional_comment="""\
Submission contains an attempt for a domain model.
However there are several issues:
It is very anemic, there are not attributes and only one type of arrows, which probably represent associations.
Additionally, it contains the conrete devices from the "demo house" example becuase the concrete UUIDs are mentioned.
This looks like a mix of class and object diagram features.\
""",
                  exercise_folder_name='ing301-projectpartA-startcode')
       

if __name__ == "__main__":
    main()


