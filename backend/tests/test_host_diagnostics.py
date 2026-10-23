import subprocess
from types import SimpleNamespace
from typing import Any

from scripts.collect_host_diagnostics import COMMANDS, MAX_OUTPUT, collect


def test_collector_is_bounded_and_keeps_going_after_missing_commands() -> None:
    calls = []

    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(args)
        assert kwargs["timeout"] == 8
        assert not kwargs.get("shell")
        if args[0] == "coredumpctl":
            raise FileNotFoundError()
        return SimpleNamespace(stdout="x" * (MAX_OUTPUT + 1), stderr="", returncode=0)

    result = collect(run)
    assert len(calls) == len(COMMANDS)
    assert result["commands"]["last_bluetooth_core"]["error"] == "FileNotFoundError"
    assert result["commands"]["bluetooth_journal"]["truncated"]
    assert len(result["commands"]["bluetooth_journal"]["output"]) == MAX_OUTPUT
    assert not any("restart" in args or "sudo" in args for args in calls)


def test_collector_records_timeouts_without_stopping_other_sections() -> None:
    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(args, 8)

    result = collect(run)
    assert len(result["commands"]) == len(COMMANDS)
    assert all(row["error"] == "TimeoutExpired" for row in result["commands"].values())
