from __future__ import annotations
import re
from enum import Enum
import sys
from zoneinfo import ZoneInfo
from rich.console import Console
import typer
from fastoblig.canvas import LOCAL_TZ
from fastoblig.domain import Exercise, Submission, SubmissionState
from fastoblig.feedback import SubmissionFileState, create_system_prompt, determine_submission_file_state, collect_submission_files, contact_openai, AddressSettings
from fastoblig.storage import Storage, OPENAI_TOKEN, GITHUB_TOKEN
from rich.panel import Panel
from fastoblig.utils import run_test_bash, run_pytest
from datetime import datetime
from rich.prompt import Confirm, Prompt
from rich.markdown import Markdown
from rich.tree import Tree
import xml.etree.ElementTree as ET
from pathlib import Path
from rich.filesize import decimal
from fastoblig.canvas import CanvasClient
from fastoblig.github import upload_issue
import subprocess

from rich.text import Text
from rich import box

import git


def read_feedback_xml(file_path: Path) -> tuple[str | None, str | None]:
    text = None
    assesment = None
    document = ET.parse(file_path)
    root = document.getroot()
    review = root.find("review")
    if review is not None and review.text is not None:
        text = review.text
    ass = root.find("assessment")
    if ass is not None and ass.text is not None:
        assesment = ass.text.strip()
    return (text, assesment)


def walk_directory(root: Path, dir: Path, tree: Tree, index: dict[str, SubmissionFileState]):
    paths = sorted(
        dir.iterdir(),
        key=lambda path: (path.is_file(), path.name.lower()),
    )
    for path in paths:
        # Remove hidden files
        if path.name.startswith(".") or path.name.startswith("_"):
            continue
        if path.is_dir():
            branch = tree.add(
                f":open_file_folder: {path.name}",
            )
            walk_directory(root, path, branch, index)
        else:
            result = index[str(path.relative_to(root))] if str(path.relative_to(root)) in index else SubmissionFileState.UNCHANGED
            style = "dim" if result in {SubmissionFileState.UNCHANGED, SubmissionFileState.OLD, SubmissionFileState.IGNORED}  else ""
            if result in  { SubmissionFileState.CHANGED, SubmissionFileState.NEW }:
                style = "green bold"
            text_filename = Text(path.name)
            file_size = path.stat().st_size
            text_filename.append(f" ({decimal(file_size)})")
            text_filename.append(f" {result.name}")
            icon = "📄 "
            if path.suffix == ".py":
                icon = "🐍 " 
            elif path.suffix == ".java":
                icon = "☕ "
            elif path.suffix == ".rs":
                icon = "🦀 "
            tree.add(Text(icon) + text_filename, style=style, guide_style=style)

class AssessmentPhase(Enum):
    DOWNLOADING = 0
    TESTING = 1
    EVALUATION = 2
    PUBLISHING = 3
    FINISHING = 4

    @classmethod
    def next(cls, state: SubmissionState) -> AssessmentPhase:
        if state == SubmissionState.SUBMITTED:
            return AssessmentPhase.DOWNLOADING
        if state == SubmissionState.CHECKED_OUT:
            return AssessmentPhase.TESTING
        if state == SubmissionState.TESTED:
            return AssessmentPhase.EVALUATION
        if state == SubmissionState.FEEDBACK_GENERATED:
            return AssessmentPhase.PUBLISHING
        if state == SubmissionState.FEEDBACK_PUBLISHED:
            return AssessmentPhase.FINISHING
        errmsg = f"State '{state}' has not follow-up phase!"
        raise ValueError(errmsg)

class Assessor:

    def __init__(self, console: Console, storage: Storage, exercise: Exercise, submission: Submission) -> None:
        self.console = console
        self.storage = storage
        self.submission = submission
        self.exercise = exercise


    def _do_checkout(self,):
        exercise = self.exercise
        submission = self.submission
        console = self.console


        # Print student header
        if len(submission.contributions) > 0:
            student_grou_md = f"Group: **{submission.submission_group_name}**, Members:\n\n"
        else:
            student_grou_md = f"Individual Submission: student_id={submission.contributions[0]}\n\n"
        for stud_id in submission.contributions:
            student = self.storage.get_student(stud_id)
            if student:
                student_grou_md += f" - {student.id}: {student.firstname} {student.lastname} <mailto:{student.email}>\n"


        console.print(Panel(Markdown(student_grou_md), title=f"Submission: {submission}", expand=False))
        if exercise.description_type == "git_repo" and exercise.grading_path is not None and submission.content is not None:
            base_path = exercise.grading_path
            submission_path = base_path / str(submission.id)

            console.print(f":file_folder: Working Directory (i.e. local storage) for this submission is: '{submission_path.resolve()}'")
            if submission_path.exists():
                console.print(""":construction: Warning: The aforementioned directory exists already!
    :arrow_right:  Please backup the contents of the folder (if needed) and delete it so that we can proceed afresh.""")
                # TODO: confirm if you want to delete the folder
            else:

                # do some url sanitization
                download_url = submission.content
                
                if download_url.endswith("/tree/main"):
                    cut_index = download_url.index("/tree/main")
                    download_url = download_url[:cut_index]

                submission.content = download_url

                console.print(f":arrow_down:  Cloning <{submission.content}> into the above directory")
                assert submission.submitted_at is not None
                try:
                    repo = git.Repo.clone_from(submission.content, submission_path)

                    # logic to check out the lates commit within the submission period
                    hexsha = None
                    flag = False
                    for commit in repo.iter_commits():
                        commit_dt = datetime.fromtimestamp(commit.authored_date).replace(tzinfo=LOCAL_TZ)
                        if commit_dt > submission.submitted_at and not flag:
                            console.print(f":see_no_evil: There are commits after solution was submitted on {submission.submitted_at.isoformat()} -> going to ignore those!")
                            flag = True
                        if commit_dt <= submission.submitted_at:
                            hexsha = commit.hexsha
                            break
                    if hexsha and flag:
                        repo.git.checkout(hexsha)
                        console.print(f":link: Checked out latest commit before submission: {hexsha}")

                    submission.state = SubmissionState.CHECKED_OUT
                    self.storage.update_submission(submission)
                    console.print(":wrench: You may now wish to inspect the repository content and make sure that all dependencies are resolved before running tests.")
                    self.assess()
                except git.GitCommandError as e:
                    console.print(e, style="red")

        else:
            console.print(f"Exercise is of type: '{exercise.description_type}'! This type of exercise is currently not supported in FastOblig!")
            sys.exit(1)


    def _do_testing(self):
        exercise = self.exercise
        submission = self.submission
        console = self.console

        base_path = exercise.grading_path
        assert exercise.grading_path is not None
        assert base_path is not None
        submission_path = base_path / str(submission.id)
        output_file_dir = submission_path / "__fastoblig__" 
        if not output_file_dir.exists():
            output_file_dir.mkdir(exist_ok=True, parents=True)
        output_file = output_file_dir / "testrestult.txt"

        submission_state = determine_submission_file_state(submission_path, exercise.grading_path / "exercise")
        r = git.Repo(submission_path)
        no_commits = len(list(r.iter_commits()))
        if no_commits <= 1 and len(submission_state) == 0:
            console.print(":warning: Only a single (initial) commit and no work seems to have been done :face_with_monocle:")
        else: 
            console.print("[bold]Student submission overview[/bold]")
            console.print(f"- {no_commits} commits")
            tree = Tree(label="Submission Directory")
            index = {k: v for k, v in submission_state}
            walk_directory(submission_path, submission_path, tree, index)
            console.print(tree)
        want_see_dir = Confirm.ask("Do you want to inspect the directory now?", default=False)
        if want_see_dir:
            typer.launch(str(submission_path.resolve()))

        # deamon = None
        # if test_deamon:
        #     console.print(f":japanese_ogre: Started a deamon process for testing: [dark_orange3]{test_deamon}")
        #     deamon = run_test_deamon(test_deamon, submission_path)
        test_backend = Prompt.ask(":direct_hit: Choose testing backend:", choices=['pytest', 'shell', 'none'], default='none')

        if test_backend == 'pytest':
            console.print(":microscope: Running tests with backend: pytest:", end=" ")
            return_code, result = run_pytest(str((submission_path).resolve()))
            result_regex = re.compile(r"=* (.+) =*")
            match = result_regex.match(result.splitlines()[-1])
            if match: 
                console.print(match.group(1))
            else:
                console.print(f"Return code: {return_code}")
            with open(output_file, mode="wt") as f:
                f.write(result)

            console.print(f":floppy_disk: Testresult written to '{output_file}'.")
        elif test_backend == 'shell':
            console.print(":mircoscope: Running tests with backend \\[shell]")
            console.print("  Please specify shell command below:")
            shell_cmd = Prompt.ask("$>")
            console.print(f":television: Running Shell command [cyan]{shell_cmd}[/cyan]")
            return_code, testresult, stderr = run_test_bash(shell_cmd, submission_path)
            console.print(f":checkered_flag: Test Command finished with return code {return_code}:")
            if len(testresult) > 0:
                console.print(Panel(testresult, box=box.DOUBLE, title="STDOUT"))
                with open(output_file, mode="wt") as f:
                    f.write(testresult)
            else: 
                console.print(Panel(stderr, box=box.ASCII, border_style="red", title="STDERR"))
                with open(output_file, mode="wt") as f:
                    f.write(stderr)

            console.print(f":floppy_disk: Testresult written to '{output_file}'.")
        elif test_backend == "none":
            console.print(":fast-forward_button: Skipping test execution.")
            with open(output_file, mode="wt") as f:
                f.write("NO TESTS EXECUTED")
        else:
            raise ValueError("unspecifiec test backend")

        submission.testresult_file = output_file.resolve()
        # if test_deamon and deamon:
        #     deamon.terminate()
        #     stdout, stderr = deamon.communicate()
        #     if stdout:
        #         with open(output_file_dir / "test_deamon_stdout.txt", mode="wb") as f:
        #             f.write(stdout)
        #     if stderr:
        #         with open(output_file_dir / "test_deamon_stderr.txt", mode="wb") as f:
        #             f.write(stderr)
        submission.state = SubmissionState.TESTED
        self.storage.update_submission(submission)
        self.assess()


    def _do_evaluation(self):
        exercise = self.exercise
        submission = self.submission
        console = self.console


        base_path = exercise.grading_path
        assert exercise.grading_path is not None
        assert base_path is not None
        submission_path = base_path / str(submission.id)
        output_file_dir = submission_path / "__fastoblig__" 
        feedback_file = output_file_dir / "feedback.xml"

        use_ai = Confirm.ask("Do you want to use AI for automatic evaluation", default=True)
        
        if use_ai:
            want_make_comment = Confirm.ask("Do you want to supply an additional comment for the AI-based assessment?", default=False)
            if want_make_comment:
                comment_file = output_file_dir / "comment.md"
                comment_text = Prompt.ask("Comment:" )
                with open(comment_file, 'wt') as f:
                    f.write(comment_text)
                console.print(f"Written comment to {comment_file.resolve()} (in case you want to edit it later)")
                submission.comment_file = comment_file

            lang = Prompt.ask(":norway: Locale:" , choices=['no', 'en', 'de'], default='no')
            address = AddressSettings(language=lang, is_multiple=len(submission.contributions) > 1) # type: ignore
            system_prompt = create_system_prompt(exercise.grading_path / "exercise",
                                                 "README.md", 
                                                 exercise.name,
                                                 address)
            user_prompt = collect_submission_files(submission_path,
                                                   exercise.grading_path,
                                                   submission.id, 
                                                   submission.testresult_file, 
                                                   submission.comment_file,
                                                   None,
                                                   None)
            access_token = self.storage.get_token(OPENAI_TOKEN)
            if access_token is None:
                console.print(":locked_with_key: [red]Sorry! Cannot contact GPT because the OpenAI API token was not set![/red] Use " +
                    "`fastoblig config --set-openai-token` to configure it!")
                return

            console.print(":rocket: Submission content sent to GPT for external assessment.")
            spinner = console.status(":zzz: waiting for response...")
            spinner.__enter__()
            response = contact_openai(access_token, user_prompt, system_prompt) 
            spinner.__exit__(None, None, None)
            console.print(":inbox_tray: Feedback received:")

            # fixing the sometimes weird formatting coming from GPT
            if response.startswith("```xml"):
                response = response[7:-3]
            response_lines = [l.strip() for l in response.splitlines()]
            response = "\n".join(response_lines)
            if response.startswith("<review>"):
                response = "<response>\n" + response + "\n</response>"
                
            with open(feedback_file, mode="wt") as f:
                f.write(response)
        else:
            with open(feedback_file, mode="wt") as f:
                f.write(f"""
<response>
    <review>
# Gruppe {submission.submission_group_name}

Hei! Det ser ut som om du ikke har gjort noen ting her?!

Kan du prøve igjen?
    </review>
    <assessment>F</assessment>
</response>
                """)
            console.print(f"You have chosen manual (human) feedback! Prepared feedback file: '{feedback_file}'")
            is_open_file = Confirm.ask("Do you want to edit this file now?", default=True)
            if is_open_file:
                subprocess.run(['nvim', feedback_file.resolve()]) # TODO: make text editor configurable


        submission.feedback_file = feedback_file.resolve()
        submission.state = SubmissionState.FEEDBACK_GENERATED
        self.storage.update_submission(submission)

        feedback, score = read_feedback_xml(feedback_file)
        if feedback is not None and use_ai:
            console.print(Panel(Markdown(feedback)))
            console.print(f":robot: First initial assesment: [bold magenta] {score}")
            console.print(f":face_with_monocle: You may now want to inspect and modify the current feedback " + 
                      f"at '{feedback_file.resolve()}' before publishing it!")
            self.assess()


    def _do_publish(self):
        exercise = self.exercise
        submission = self.submission
        console = self.console

        assert submission.feedback_file is not None
        feedback, _ = read_feedback_xml(submission.feedback_file)
        if feedback is not None:
            console.print(":speech_balloon: Current feedback is:")
            console.print(Panel(Markdown(feedback)))
            # TODO: ask if you wanto to edit?
            assert submission.content is not None
            posted_feedback = False
            if submission.content.startswith("https://github.com"):
                is_confirmed = Confirm.ask(f"Do you want to upload this feedback to {submission.content}?")
                lang = Prompt.ask(":norway: Locale:" , choices=['no', 'en', 'de'], default='no')
                address = AddressSettings(language=lang, is_multiple=len(submission.contributions) > 1) # type: ignore
                if is_confirmed:
                    github_access_token = self.storage.get_token(GITHUB_TOKEN)
                    if github_access_token is None:
                        console.print(":locked_with_key: [red]Error! The `github access token` is not set![/red] "+ 
                            "Please use `fastoblig config --set-github-token` to configure it!")
                        return
                    issue_url = upload_issue(github_access_token,
                                             submission.content , 
                                             f"Feedback: {exercise.name}",
                                             feedback+ "\n\n" + address.github_comment_addendum())
                    posted_feedback = True
                    console.print(f":open_mailbox_with_raised_flag: Feedback posted at: <{issue_url}>")
                    is_confirmed = Confirm.ask(f"Do you want to link to this issue on the LMS submission page?", default=True)
                    if is_confirmed and issue_url is not None:
                        client = CanvasClient(self.storage)
                        for contrib in submission.contributions:
                            client.update_submission(exercise.course,
                                                     exercise.id,
                                                     contrib, 
                                                     comment=address.see_also(issue_url))
            else:
                is_confirmed = Confirm.ask("Do you want to upload this feedback to the LMS submission page?")
                if is_confirmed:
                    client = CanvasClient(self.storage)
                    for contrib in submission.contributions:
                        client.update_submission(exercise.course,
                                                 exercise.id,
                                                 contrib, 
                                                 comment=feedback)
                    posted_feedback = True

            if not posted_feedback:
                is_confirmed = Confirm.ask(":exclamation: You did not post the feedback somewhere!" +
                    " Do you want to conclude this step anyways and proceed to the final grading :question_mark: ")
            if posted_feedback or is_confirmed:
                submission.state = SubmissionState.FEEDBACK_PUBLISHED
                self.storage.update_submission(submission)
                self.assess()
        else:
            console.print(f"Weird... The Feedback content is empty! Please check '{submission.feedback_file}'")
        return


    def _do_finish(self):
        submission = self.submission
        console = self.console
        exercise = self.exercise
        if submission.testresult_file is not None:
            with open(submission.testresult_file, mode="rt") as f:
                lines = f.readlines()
                if len(lines) > 0:
                    result_regex = re.compile(r"=* (.+) =*")
                    match = result_regex.match(lines[-1])
                    if match:
                        console.print(f":test_tube: Testresult was: [italic] {match.group(1)}")
        score = ""
        if submission.feedback_file is not None:
            _, score = read_feedback_xml(submission.feedback_file)
            if score:
                console.print(f":robot: suggested character grade was: [bold magenta] {score}")
        client = CanvasClient(self.storage)
        if exercise.grading_type == "pass_fail":
            score_input = Prompt.ask("Please enter grade", choices=['pass', 'complete', 'fail', 'incomplete'])
            comment_input = Prompt.ask("Additional Comment (optional)", default="")
            for contrib in submission.contributions:
                client.update_submission(exercise.course, 
                                         exercise.id,
                                         contrib,
                                         comment=comment_input if len(comment_input) > 0 else None,
                                         grading=score_input)
            
            if score_input in {'complete', 'pass'}:
                submission.state = SubmissionState.PASSED

                if score:
                    if score.strip() == "A":
                        submission.grade = 100.0
                    elif score.strip() == "B":
                        submission.grade = 85.0
                    elif score.strip() == "C":
                        submission.grade = 70.0
                    elif score.strip() == "D":
                        submission.grade = 60.0
                    else:
                        submission.grade = 50.0
            else:
                submission.grade = 0.0
                submission.state = SubmissionState.FAILED

        elif exercise.grading_type == "points":
            score_input = Prompt.ask("Enter point score (e.g. 42.0)")
            comment_input = Prompt.ask("Comment (optional)", default="")
            for contrib in submission.contributions:
                client.update_submission(exercise.course,
                                         exercise.id,
                                         contrib,
                                         comment=comment_input if len(comment_input) > 0 else None,
                                         grading=score_input)
            submission.grade = float(score_input)
            if float(score_input) > 0:
                submission.state = SubmissionState.PASSED
            else: 
                submission.state = SubmissionState.FAILED

        submission.graded_at = datetime.now(ZoneInfo("UTC"))
        self.storage.update_submission(submission)
        console.print(f":tada: Assessment of submission {submission.id} is now completed!")


    def assess(self):
        phase = AssessmentPhase.next(self.submission.state)
        self.console.rule(f"Current State: {self.submission.state.name} | Next Phase: {phase.name}")
        proceed = Confirm.ask(":play_button: Proceed?", default=True)
        if proceed: 
            if phase == AssessmentPhase.DOWNLOADING:
                self._do_checkout()
            elif phase == AssessmentPhase.TESTING:
                self._do_testing()
            elif phase == AssessmentPhase.EVALUATION:
                self._do_evaluation()
            elif phase == AssessmentPhase.PUBLISHING:
                self._do_publish()
            elif phase == AssessmentPhase.FINISHING:
                self._do_finish()
            else:
                errmsg = f"Phase '{phase}' is not supported yet!"
                raise ValueError(errmsg)
        else:
            self.console.print(f":play_or_pause_button: Stopping, you can always come back by calling: [green italic] fastoblig submission grade")



    # TODO: param: clear directory?
    def reset(self, target_state: SubmissionState = SubmissionState.SUBMITTED):
        self.submission.state = target_state
        self.storage.update_submission(self.submission)


    def files(self):
        submission = self.submission
        exercise = self.exercise
        base_path = exercise.grading_path
        assert exercise.grading_path is not None
        assert base_path is not None
        submission_path = base_path / str(submission.id)
        self.console.print(f"Files for submission {submission.id} located at: '{submission_path.resolve()}'")
        typer.launch(str(submission_path.resolve()))

#
# TODO: old paras
# course: int,
# exercise: int,
# submission: int,
# comment: Optional[str] = None,
# reset: Optional[str] = None,
# proceed: bool = False,
# lang: str = "NO",
# test_pytest: Optional[str] = None,
# test_shell: Optional[str] = None,
# test_deamon: Optional[str] = None,
# baseline_ts: Optional[datetime] = None, 
# ignore_file_pattern: Optional[str] = "tests/.*"

#
#
# def do_reset(exercise: Exercise, submission: Submission, target_state: str):
#     """
#     This method resets a submission to the "SUBMITTED"-state.
#     It also includes to remove the potentially checked out repository from disk.
#     """
#     try:
#         reset_to = SubmissionState[target_state]
#     except KeyError:
#         console.print(f":boom: [red] Given target reset stat \"{target_state}\" is unknown!")
#         return
#
#     if submission.state.value > reset_to.value and submission.state.value >= SubmissionState.FAILED.value:
#         console.print(f":black_left__pointing_double_triangle_with_vertical_bar: Resetting submission state: {submission.state.name}")
#         # apparently cnavas does not support changing the submission evaulation back
#         submission.graded_at = None 
#         submission.grade = None
#         submission.state = SubmissionState.FEEDBACK_PUBLISHED
#         
#     if submission.state.value > reset_to.value and submission.state.value >= SubmissionState.FEEDBACK_PUBLISHED.value:
#         console.print(f":black_left__pointing_double_triangle_with_vertical_bar: Resetting submission state: {SubmissionState.FEEDBACK_PUBLISHED.name}")
#         submission.state = SubmissionState.FEEDBACK_GENERATED
#         # later: have a look if one might delete the issue id -> probably requires saving it into the database also
#
#     if submission.state.value > reset_to.value and submission.state.value >= SubmissionState.FEEDBACK_GENERATED.value:
#         console.print(f":black_left__pointing_double_triangle_with_vertical_bar: Resetting submission state: {SubmissionState.FEEDBACK_GENERATED.name}")
#         submission.state = SubmissionState.TESTED
#         if submission.feedback_file:
#             console.print(f"Deleting: {submission.feedback_file}")
#             os.remove(submission.feedback_file)
#             submission.feedback_file = None
#
#     if submission.state.value > reset_to.value and submission.state.value >= SubmissionState.TESTED.value:
#         console.print(f":black_left__pointing_double_triangle_with_vertical_bar: Resetting submission state: {SubmissionState.TESTED.name}")
#         submission.state = SubmissionState.CHECKED_OUT
#         if submission.testresult_file:
#             console.print(f"Deleting: {submission.testresult_file}")
#             os.remove(submission.testresult_file)
#             submission.testresult_file = None
#
#     if submission.state.value > reset_to.value and submission.state.value >= SubmissionState.CHECKED_OUT.value:
#         console.print(f":black_left__pointing_double_triangle_with_vertical_bar: Resetting submission state: {SubmissionState.CHECKED_OUT.name}")
#         submission.state = SubmissionState.SUBMITTED
#         if submission.comment_file:
#             os.remove(submission.comment_file)
#             submission.comment_file = None
#         if exercise.grading_path:
#             base_path = exercise.grading_path
#             if submission.submission_group_no is not None:
#                 submission_path = base_path / f"group_{submission.submission_group_no}"
#             else:
#                 submission_path = base_path / str(submission.id)
#             if submission_path.exists():
#                 shutil.rmtree(submission_path)
#                 console.print(f"Removing directory: '{submission_path.resolve()}")
#
#     storage.upsert_submissions(exercise.id, [submission], force=True)
#     console.print(f"Submission {submission.id} is reset to state: {reset_to}")
#     elif submission.state == SubmissionState.FEEDBACK_PUBLISHED:
#         console.rule(f"Current State: {submission.state.name} | Next Phase: FINAL ASSESSMENT")
#         if submission.testresult is not None:
#             with open(submission.testresult, mode="rt") as f:
#                 lines = f.readlines()
#                 if len(lines) > 0:
#                     result_regex = re.compile(r"=* (.+) =*")
#                     match = result_regex.match(lines[-1])
#                     if match:
#                         console.print(f":test_tube: Testresult was: [italic] {match.group(1)}")
#         if submission.feedback is not None:
#             _, score = read_feedback_xml(submission.feedback)
#             if score:
#                 console.print(f":robot: GPT suggested character grade was: [bold magenta] {score}")
#         client = CanvasClient(storage)
#         if exercise.grading == "pass_fail":
#             score_input = prompt("Pleas enter grade (pass/complete/fail/incomplete)")
#             comment_input = prompt("Comment (optional)", default="")
#             client.update_submission(exercise.course, exercise.id, submission.members[0],
#                                      is_group=submission.submission_group_id is not None,
#                                      comment=comment_input if len(comment_input) > 0 else None,
#                                      grading=score_input)
#             if score_input in {'complete', 'pass'}:
#                 submission.state = SubmissionState.PASSED
#             else:
#                 submission.state = SubmissionState.FAILED
#         elif exercise.grading == "points":
#             score_input = prompt("Enter point score (e.g. 42.0)")
#             comment_input = prompt("Comment (optional)", default="")
#             client.update_submission(exercise.course, exercise.id, submission.members[0],
#                                      is_group=submission.submission_group_id is not None,
#                                      comment=comment_input if len(comment_input) > 0 else None,
#                                      grading=score_input)
#             if float(score_input) > 0:
#                 submission.state = SubmissionState.PASSED
#             else: 
#                 submission.state = SubmissionState.FAILED
#
#         storage.upsert_submissions(exercise.id, [submission])
#         console.print(f":tada: Assessment of submission {submission.id} is now completed!")
#
