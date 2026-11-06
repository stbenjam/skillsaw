"""A deliberately slow rule for testing editor cancellation of an installed CLI."""

import os
import time

from skillsaw import Rule, Severity


class SlowRule(Rule):
    rule_id = "editor-test-slow"
    description = "Pause after publishing the interpreter PID to the test harness."

    def default_severity(self):
        return Severity.WARNING

    def check(self, context):
        marker = context.root_path / "ready"
        temporary = marker.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{os.getpid()}\n")
        temporary.replace(marker)
        time.sleep(60)
        return []
