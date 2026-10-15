"""Exercise real pipe overflow/deadline and complete in-bound object output."""
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow_subject as subject
from workflow_control import ControlError


class GitCaptureTests(unittest.TestCase):
    def test_complete_binary_output_is_preserved_without_truncation(self):
        result = subject.capture([sys.executable, '-c', "import sys;sys.stdout.buffer.write(b'abc\\x00'*4000)"],
                                 environment=os.environ.copy(), limit=20000)
        self.assertEqual(b'abc\x00' * 4000, result)

    def test_stdout_or_stderr_overflow_terminates_original_child(self):
        for pipe in ('stdout', 'stderr'):
            started = []
            original = subprocess.Popen
            def launch(*args, original=original, started=started, **kwargs):
                child = original(*args, **kwargs); started.append(child); return child
            before = time.monotonic()
            with patch.object(subject.subprocess, 'Popen', side_effect=launch), \
                 self.assertRaisesRegex(ControlError, 'git-output-exceeds-memory-admission'):
                subject.capture([sys.executable, '-c', f"import sys,time;sys.{pipe}.buffer.write(b'x'*1000000);sys.{pipe}.flush();time.sleep(20)"],
                                environment=os.environ.copy(), limit=4096)
            self.assertLess(time.monotonic() - before, 5)
            self.assertIsNotNone(started[0].poll())

    def test_silent_child_is_terminated_on_deadline(self):
        with self.assertRaisesRegex(ControlError, 'git-deadline'):
            subject.capture([sys.executable, '-c', 'import time;time.sleep(20)'],
                            environment=os.environ.copy(), limit=4096, timeout=0.1)


if __name__ == '__main__':
    unittest.main()
