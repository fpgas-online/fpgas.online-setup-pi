"""onpi/tmux/zprofile creates the shared tmux session `default` (setup-pi #20).

Every interactive login runs `exec tmux new-session -t default`, which joins
the session group of `default`, so `default` has to exist first. The zprofile
checks with `tmux has-session -t default` and creates it when it is missing.

The test runs the zprofile's own lines under zsh: the body of the
"start tmux?" `if`, up to but not including the `exec tmux new-session` line
(which would replace the shell with a tmux client). `tmux` is a zsh function
that sends every call to a private tmux server (`-L <unique name> -f
/dev/null`), which the fixture kills afterwards, so the user's own tmux server
is never touched.
"""

import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

ZPROFILE = pathlib.Path(__file__).parent.parent / "onpi" / "tmux" / "zprofile"

pytestmark = pytest.mark.skipif(
    shutil.which("zsh") is None or shutil.which("tmux") is None,
    reason="needs zsh and tmux (apt install zsh tmux)",
)

# Where tmux puts the socket of `tmux -L <name>`.
SOCKET_DIR = pathlib.Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}"

# Every `tmux` the zprofile lines run goes to the private server.
TMUX_FUNCTION = 'tmux() { command tmux -L "${TEST_TMUX_SOCKET:?}" -f /dev/null "$@" }\n'


def login_block() -> str:
    """The zprofile lines a login runs before `exec tmux new-session`."""
    lines = ZPROFILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.lstrip().startswith("if [[") and "STY" in line)
    end = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("exec tmux new-session"))
    block = "\n".join(lines[start + 1 : end]) + "\n"
    assert "exec" not in block
    return block


@pytest.fixture
def private_tmux(tmp_path):
    """A private tmux server's socket name and the environment that uses it."""
    socket = f"setup-pi-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    home = tmp_path / "home"
    home.mkdir()
    (home / ".tmux-help").write_text("help\n")
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env.update(HOME=str(home), TEST_TMUX_SOCKET=socket)
    try:
        yield socket, env
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
        # tmux leaves the socket file behind; it is where tmux puts -L sockets.
        (SOCKET_DIR / socket).unlink(missing_ok=True)


def tmux(socket, *args):
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True)


def run_login_block(tmp_path, env):
    script = tmp_path / "login.zsh"
    script.write_text(TMUX_FUNCTION + login_block())
    return subprocess.run(["zsh", "-f", str(script)], env=env, capture_output=True, text=True, timeout=30)


def test_login_creates_default_session(tmp_path, private_tmux):
    socket, env = private_tmux
    assert tmux(socket, "has-session", "-t", "default").returncode != 0

    result = run_login_block(tmp_path, env)

    assert tmux(socket, "has-session", "-t", "default").returncode == 0, result.stderr
    windows = tmux(socket, "list-windows", "-t", "default", "-F", "#{window_name}")
    assert windows.stdout.split() == ["h"]


def test_login_keeps_existing_default_session(tmp_path, private_tmux):
    socket, env = private_tmux
    first = run_login_block(tmp_path, env)
    assert tmux(socket, "has-session", "-t", "default").returncode == 0, first.stderr
    created = tmux(socket, "display-message", "-p", "-t", "default", "#{session_id}").stdout

    second = run_login_block(tmp_path, env)

    assert "duplicate session" not in second.stderr
    assert tmux(socket, "display-message", "-p", "-t", "default", "#{session_id}").stdout == created
