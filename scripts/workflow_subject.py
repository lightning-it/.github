"""Bounded data-only Git object reads for native ingress and ancestry."""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time

import single_review_resources as resources
from workflow_control import ControlError, require


def capture(command, *, environment, limit, timeout=120):
    """Consume both pipes incrementally; overflow kills the entire child group."""
    require(type(limit) is int and limit > 0, "git-memory-admission")
    process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    output = bytearray()
    consumed = 0
    deadline = time.monotonic() + timeout
    complete = False
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "git-deadline")
                for key, _ in selector.select(min(remaining, 1)):
                    # At most one extra byte is ever allocated beyond admission.
                    data = os.read(key.fileobj.fileno(), min(65536, limit - consumed + 1))
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    consumed += len(data)
                    require(consumed <= limit, "git-output-exceeds-memory-admission")
                    if key.fileobj is process.stdout:
                        output.extend(data)
            require(process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0, "git-integration-unavailable")
        complete = True
        return bytes(output)
    except subprocess.TimeoutExpired as error:
        raise ControlError("git-deadline") from error
    finally:
        if not complete:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        process.stdout.close()
        process.stderr.close()


def git(directory, *args, binary=False):
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "0"}
    payload = capture(["git", "--git-dir", str(directory), *args], environment=environment,
                      limit=resources.wire_limit())
    return payload if binary else payload.decode().strip()
