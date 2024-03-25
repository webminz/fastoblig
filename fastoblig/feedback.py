from datetime import datetime
from pathlib import Path
import subprocess
from git import GitCommandError
import re
from openai import OpenAI
client = OpenAI()

cwd = Path('/Users/past-madm/Projects/teaching/ing301/assesment/a') # TODO: pass as  parameter
exercise_repo = cwd / "ing301-projectpartA-startcode"
readme_file = exercise_repo / "README.md"


def is_uninteresting(p: Path, project: Path) -> bool:
    fname = p.name
    pname = str(p.relative_to(project))
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
    if not p.is_file():
        return True
    if not p.suffix in INTERESTING_TYPES:
        return True
    if pname.startswith('.'):
        return True
    if "__" in pname:
        return True
    if fname.lower() in IGNORE_LIST:
        return True
    return False


def create_system_prompt(exercise_folder: Path, exercise_file: str) -> str:
    presult = subprocess.run(['tree'], cwd=exercise_folder, capture_output=True)
    presult_s = presult.stdout.decode('utf-8')
    dir_structure = re.sub(r"\x1b\[[0-9;]*m", "", presult_s).replace('\xa0', "")
    exercise_description = open(readme_file, mode="rt").read(-1)
    course = "ING301" # passed as parameter
    course_short_desc = "Datateknologi og videregående programmering for ingeniører" # passed as parameter
    langugage = "Norwegian" # passed as parameter
    persona = """\
    You are a teaching assistant for a Computer Science class. 
    You are very knowledgeable and and are concerned with supporting your students.
    Among the students you are known to give very helpful feedback and comments, likewise your 
    teaching philosophy is not to "spoon feed" them, i.e. you are never providing them with the 
    exercise solutions directly."""
    
    task = f"""\
    {persona}
    
    Your task is to review students submissions to a mandatory programming exercise in the course {course} ("{course_short_desc}").
    The exercise descriptions is given below demarcated by XML-tags:
    <exercise>
    {exercise_description}
    </exercise>
    
    The students are provided with the following "startcode":
    
    Directory structure:
    {dir_structure}
    
    File contents (given as XML-elements):
    {startcode_files}
    
    
    The user will prompt you with individual student submissions and your task is to respond with a extensive code review of the student submission.
    The student submssion will provided as an XML element containing 
    - an "id"-attribute identifying the submission, 
    - a list of "file"-elements showing the contents of the modified files that make up the student submission
    - optionally, a "testresult"-element showing the standard output of running the unit tests,
    - optionally, a "comment"-element containing externally provided context information that should be taken into account when asessing the submission.
    
    Your response should formatted as a XML document, which comprises three sub-elements:
    - review
    - quickfixes
    - assesment
    
    The "review"-element is mandatory. Here you should provide a comprehensive commentary on the student submission.
    Focus mainly only the content and program logic. Best practices concerning aspects such as writing comments are secondary here.
    This should be a markdown-formatted text that first highlights things that the students did well, second points out things that 
    are not as expected or potentials errors, and finally some tips on where to improve upon in the future or topics that the student 
    may look into (again). The text shall be written in such a way that it addresses the student directly. 
    The response to the student must be written in {langugage}.
    Write in a positive and motivating tone but remain moderate in you temper (e.g. avoid expressions such "jeg roser dere").
    The "quickfixes"-elements are optional: if the student submission contains syntax error or severe logic issues that make the program unrunnable. 
    You may provide a several quick-fixes, one per respective errorneous file (encoded in diff-format) to help the student advance.
    The "assesment"-elments is mandatory. Here you should provide a general overall assesment of the submission on the A-F scale, where "A" means "exceeding expecations",
    "B" means "very good = meeting all expectations" and so on.
    """
    return task


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


