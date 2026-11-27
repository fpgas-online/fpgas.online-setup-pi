"""onpi/tmux/zprofile creates the shared tmux session `default` (setup-pi #20).

Every interactive login runs `exec tmux new-session -t default \\; new-window`,
which joins the session group of `default` and gives the login a window of its
own, so `default` has to exist first. The zprofile checks with
`tmux has-session -t '=default'` (exactly `default`, not a prefix match) and
creates it when it is missing: inside the group `default` when that group
still has a member, so it gets the group's windows, otherwise fresh with the
help window `h`.

The tests run the zprofile's own lines under zsh: the body of the
"start tmux?" `if` up to the `exec tmux new-session` line, and for the login
itself that line's command without `exec`, as a client on a pseudo-terminal.
`tmux` is a zsh function that sends every call to a private tmux server
(`-L <unique name>`, with `-f /dev/null` or the shipped onpi/tmux/tmux.conf),
which the fixture kills afterwards, so the user's own tmux server is never
touched.

Skipped when zsh or tmux is missing; ZPROFILE_TESTS_REQUIRED=1 (set in CI)
makes that a failure instead.
"""

import os
import pathlib
import pty
import shutil
import subprocess
import time
import uuid

import pytest

ZPROFILE = pathlib.Path(__file__).parent.parent / "onpi" / "tmux" / "zprofile"
TMUX_CONF = ZPROFILE.parent / "tmux.conf"

REQUIRED = os.environ.get("ZPROFILE_TESTS_REQUIRED") == "1"
MISSING = [tool for tool in ("zsh", "tmux") if shutil.which(tool) is None]


@pytest.fixture(autouse=True)
def _needs_zsh_and_tmux():
    if MISSING:
        if REQUIRED:
            pytest.fail(f"{' and '.join(MISSING)} not installed and ZPROFILE_TESTS_REQUIRED=1")
        pytest.skip(f"needs {' and '.join(MISSING)} (apt install zsh tmux)")


# Where tmux puts the socket of `tmux -L <name>`.
SOCKET_DIR = pathlib.Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}"

# Every `tmux` the zprofile lines run goes to the private server.
TMUX_FUNCTION = (
    'tmux() { command tmux -L "${TEST_TMUX_SOCKET:?}" -f "${TEST_TMUX_CONF:-/dev/null}" "$@" }\n'
)


def zprofile_lines():
    return ZPROFILE.read_text().splitlines()


def exec_line_index(lines):
    return next(i for i, line in enumerate(lines) if line.strip().startswith("exec tmux new-session"))


def login_block() -> str:
    """The zprofile lines a login runs before `exec tmux new-session`."""
    lines = zprofile_lines()
    start = next(i for i, line in enumerate(lines) if line.lstrip().startswith("if [[") and "STY" in line)
    block = "\n".join(lines[start + 1 : exec_line_index(lines)]) + "\n"
    assert "exec" not in block
    return block


def login_command() -> str:
    """The exec line's command, without `exec`."""
    lines = zprofile_lines()
    return lines[exec_line_index(lines)].strip().removeprefix("exec ") + "\n"


class Server:
    """A private tmux server, the environment that uses it, and its pty clients."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.socket = f"setup-pi-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        home = tmp_path / "home"
        home.mkdir()
        (home / ".tmux-help").write_text("help\n")
        self.env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        self.env.update(HOME=str(home), TEST_TMUX_SOCKET=self.socket, TERM="xterm-256color")
        self.clients = []

    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", self.socket, *args], capture_output=True, text=True, env=self.env)

    def run_login_block(self):
        script = self.tmp_path / "login.zsh"
        script.write_text(TMUX_FUNCTION + login_block())
        return subprocess.run(["zsh", "-f", str(script)], env=self.env, capture_output=True, text=True, timeout=30)

    def login(self):
        """A whole login on a pty: the block, then the exec line's command. Returns its session."""
        script = self.tmp_path / "login-attached.zsh"
        script.write_text(TMUX_FUNCTION + login_block() + login_command())
        before = set(self.tmux("list-clients", "-F", "#{client_tty}").stdout.split())
        controller, terminal = pty.openpty()
        client = subprocess.Popen(
            ["zsh", "-f", str(script)],
            stdin=terminal, stdout=terminal, stderr=terminal, env=self.env, start_new_session=True,
        )
        os.close(terminal)
        self.clients.append((client, controller))
        for _ in range(100):
            for line in self.tmux("list-clients", "-F", "#{client_tty} #{client_session}").stdout.splitlines():
                tty, session = line.split(" ", 1)
                if tty not in before:
                    return session
            time.sleep(0.05)
        pytest.fail("the login did not attach a tmux client")

    def close(self):
        # Clients first: nothing reads their pty, so one can block on a full
        # pty buffer, and kill-server would then wait for it.
        for client, controller in self.clients:
            client.kill()
            client.wait()
            os.close(controller)
        self.tmux("kill-server")
        # tmux leaves the socket file behind; it is where tmux puts -L sockets.
        (SOCKET_DIR / self.socket).unlink(missing_ok=True)


@pytest.fixture
def server(tmp_path):
    s = Server(tmp_path)
    try:
        yield s
    finally:
        s.close()


def window_names(server, session):
    return server.tmux("list-windows", "-t", f"={session}", "-F", "#{window_name}").stdout.split()


def test_login_creates_default_session(server):
    assert server.tmux("has-session", "-t", "=default").returncode != 0

    result = server.run_login_block()

    assert server.tmux("has-session", "-t", "=default").returncode == 0, result.stderr
    assert window_names(server, "default") == ["h"]


def test_login_keeps_existing_default_session(server):
    first = server.run_login_block()
    assert server.tmux("has-session", "-t", "=default").returncode == 0, first.stderr
    created = server.tmux("display-message", "-p", "-t", "=default:", "#{session_id}").stdout

    second = server.run_login_block()

    assert "duplicate session" not in second.stderr
    assert server.tmux("display-message", "-p", "-t", "=default:", "#{session_id}").stdout == created


def test_login_recreates_default_when_only_a_login_session_is_left(server):
    """`has-session -t default` would prefix-match `default-1`; the check is exact."""
    first = server.run_login_block()
    assert server.tmux("has-session", "-t", "=default").returncode == 0, first.stderr
    left = server.tmux("new-session", "-d", "-t", "=default", "-P", "-F", "#{session_name}").stdout.strip()
    assert left == "default-1"
    assert server.tmux("kill-session", "-t", "=default").returncode == 0

    result = server.run_login_block()

    assert server.tmux("has-session", "-t", "=default").returncode == 0, result.stderr
    assert window_names(server, "default") == ["h"]


def test_first_login_prints_no_tmux_error(server):
    """No server runs after boot; the has-session check must not print "error connecting"."""
    result = server.run_login_block()

    assert "error connecting" not in result.stdout + result.stderr


@pytest.mark.parametrize("default_exists", [False, True], ids=["first-login", "later-login"])
def test_login_gets_a_live_window_of_its_own(server, default_exists):
    """The help window h is a dead pane; a login must land on a new, live window."""
    server.env["TEST_TMUX_CONF"] = str(TMUX_CONF)
    if default_exists:
        server.run_login_block()

    session = server.login()

    windows = server.tmux("list-windows", "-t", "=default", "-F", "#{window_id} #{window_name}").stdout
    h = [line.split()[0] for line in windows.splitlines() if line.split()[1:] == ["h"]]
    assert len(h) == 1, windows
    current = server.tmux("display-message", "-p", "-t", f"={session}:", "#{window_id} #{pane_dead}").stdout.split()
    assert current[1] == "0", f"the login's current window {current[0]} is a dead pane"
    assert current[0] not in h
