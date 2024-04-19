import sys
import io
import pytest
import pygit2
from pathlib import Path
import subprocess
from typer import progressbar


class GitProgressbar(pygit2.RemoteCallbacks):

    def __init__(self):
        super().__init__(None, None)
        self.bar = progressbar(length=100)
        self.bar.__enter__()

    def fin(self):
        self.bar.update(100)
        self.bar.__exit__(None, None, None)

    def fail(self):
        self.bar.update(0)
        self.bar.__exit__(None, None, None)

    def transfer_progress(self, stats):
        self.bar.update(int(stats.indexed_objects / stats.total_objects * 100))


def run_pytest(directory: str, args: str = "/tests") -> tuple[int, str]:
    base_dir = directory
    if not args.startswith("/"):
        args = "/" + args
    test_dir = directory + args
    sys.path.insert(0, test_dir)
    sys.path.insert(0, base_dir)
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    capture = io.StringIO()
    sys.stdout = capture
    sys.stderr = capture
    exit_code = pytest.main([test_dir])
    sys.stdout = original_stdout
    sys.stderr = original_stderr
    sys.path.pop(0)
    sys.path.pop(0)
    return (exit_code, capture.getvalue())


def run_test_bash(command: str, cwd: Path | None) -> tuple[int, str, str]:
    completed = subprocess.run(command, capture_output=True, cwd=cwd, shell=True)
    return (completed.returncode, completed.stdout.decode(), completed.stderr.decode())


def run_test_deamon(
    command: str,
    cwd: Path | None,
    default_shell="/bin/zsh",
) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        cwd=cwd,
        start_new_session=True,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        executable=default_shell
    )
