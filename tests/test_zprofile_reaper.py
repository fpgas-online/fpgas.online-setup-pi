"""onpi/tmux/zprofile reaps abandoned login sessions (setup-pi #21).

Each login runs `exec tmux new-session -t default`, which adds a new session
to the session group of `default`. tmux names it itself: `default-<id>` on
tmux 3.x (3.3a on bookworm, 3.5a on trixie), a bare `<id>` on older tmux,
where <id> is the number in its `#{session_id}` (`$<id>`). When the login goes
away the session stays, so each login first kills the sessions it should.

The rule: kill a session only when it is in the `default` group, is not
`default` itself, has no client attached, and still has the name tmux gave
it. A session the user renamed is kept, as the zprofile's header promises.

The test runs the zprofile's own reaper lines under zsh: from the "# Reap"
comment up to but not including the `exec tmux new-session` line (which would
replace the shell with a tmux client). `tmux` is a zsh function that sends
every call to a private tmux server (`-L <unique name> -f /dev/null`), which
the fixture kills afterwards, so the user's own tmux server is never touched.
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

pytestmark = pytest.mark.skipif(
    shutil.which("zsh") is None or shutil.which("tmux") is None,
    reason="needs zsh and tmux (apt install zsh tmux)",
)

# Where tmux puts the socket of `tmux -L <name>`.
SOCKET_DIR = pathlib.Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}"

# Every `tmux` the zprofile lines run goes to the private server.
TMUX_FUNCTION = 'tmux() { command tmux -L "${TEST_TMUX_SOCKET:?}" -f /dev/null "$@" }\n'


def reaper_block() -> str:
    """The zprofile's reaper: from the "# Reap" comment to `exec tmux new-session`."""
    lines = ZPROFILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("# Reap"))
    end = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("exec tmux new-session"))
    block = "\n".join(lines[start:end]) + "\n"
    assert "exec" not in block
    return block


@pytest.fixture
def server(tmp_path):
    """A private tmux server: (socket name, environment for the zprofile lines)."""
    socket = f"setup-pi-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    env.update(HOME=str(tmp_path), TEST_TMUX_SOCKET=socket, TERM="xterm-256color")
    clients = []
    try:
        yield socket, env, clients
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
        # tmux leaves the socket file behind; it is where tmux puts -L sockets.
        (SOCKET_DIR / socket).unlink(missing_ok=True)
        for client in clients:
            client.kill()
            client.wait()


def tmux(socket, *args, env=None):
    result = subprocess.run(
        ["tmux", "-L", socket, "-f", "/dev/null", *args], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def sessions(socket):
    return set(tmux(socket, "list-sessions", "-F", "#{session_name}").split("\n")) - {""}


def login_session(socket, env):
    """A session made the way a login makes one; tmux picks its name."""
    return tmux(socket, "new-session", "-d", "-t", "default", "-P", "-F", "#{session_name}", env=env).strip()


def attach(socket, env, clients, session):
    """Attach a client to `session` on a pseudo-terminal, as a live login would be."""
    controller, terminal = pty.openpty()
    client = subprocess.Popen(
        ["tmux", "-L", socket, "-f", "/dev/null", "attach-session", "-t", session],
        stdin=terminal, stdout=terminal, stderr=terminal, env=env, start_new_session=True,
    )
    os.close(terminal)
    clients.append(client)
    for _ in range(100):
        if tmux(socket, "display-message", "-p", "-t", session, "#{session_attached}").strip() == "1":
            return
        time.sleep(0.05)
    pytest.fail(f"client did not attach to {session}")


def run_reaper(tmp_path, env):
    script = tmp_path / "reap.zsh"
    script.write_text(TMUX_FUNCTION + reaper_block())
    return subprocess.run(["zsh", "-f", str(script)], env=env, capture_output=True, text=True, timeout=30)


def test_reaper(tmp_path, server):
    socket, env, clients = server
    tmux(socket, "new-session", "-d", "-s", "default", "-n", "h", env=env)

    abandoned = login_session(socket, env)  # default-<id> on tmux 3.x
    in_use = login_session(socket, env)
    attach(socket, env, clients, in_use)
    renamed = login_session(socket, env)
    tmux(socket, "rename-session", "-t", renamed, "my-tiles", env=env)
    # A login session as older tmux named it: the bare number of its session id.
    old_style = tmux(socket, "display-message", "-p", "#{next_session_id}", env=env).strip().lstrip("$")
    tmux(socket, "new-session", "-d", "-t", "default", "-s", old_style, env=env)
    # Sessions outside the default group are never touched.
    tmux(socket, "new-session", "-d", "-s", "other", env=env)
    other_member = tmux(socket, "new-session", "-d", "-t", "other", "-P", "-F", "#{session_name}", env=env).strip()
    tmux(socket, "new-session", "-d", "-s", "42", env=env)  # numeric, ungrouped

    result = run_reaper(tmp_path, env)

    assert result.returncode == 0, result.stderr
    assert sessions(socket) == {"default", in_use, "my-tiles", "other", other_member, "42"}, (
        f"abandoned={abandoned} old_style={old_style}\n{result.stderr}"
    )


def test_reaper_keeps_default_alone(tmp_path, server):
    socket, env, _ = server
    tmux(socket, "new-session", "-d", "-s", "default", "-n", "h", env=env)

    result = run_reaper(tmp_path, env)

    assert result.returncode == 0, result.stderr
    assert sessions(socket) == {"default"}
