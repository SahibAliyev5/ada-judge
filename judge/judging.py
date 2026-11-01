import re

from django.conf import settings

from .sandbox import SandboxError, execute

LANGUAGES = {
    "cpp20": {
        "source": "main.cpp", "time_multiplier": 1,
        "compile": [
            "/usr/bin/g++", "-std=c++20", "-O2", "-pipe",
            "-fdiagnostics-color=never", "/box/main.cpp", "-o", "/box/program",
        ],
        "run": ["/box/program"],
    },
    "python3": {
        "source": "main.py", "time_multiplier": 3, "compile": None,
        "run": ["/usr/bin/python3", "-I", "-B", "/box/main.py"],
    },
}


def outputs_match(actual, expected, mode):
    if mode == "tokens":
        return actual.split() == expected.split()
    if mode == "exact":
        return actual.replace(b"\r\n", b"\n") == expected.replace(b"\r\n", b"\n")
    raise SandboxError("Unknown output comparison mode.")


def compiler_diagnostics(data):
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"/(?:[^\s:'\"<>]+/?)+", "[path]", text)
    return "".join(character for character in text if character.isprintable()
                   or character in "\n\t")[:8192]


def judge_solution(problem, language, source, heartbeat=lambda: None):
    if language not in LANGUAGES:
        raise SandboxError("Unsupported language.")
    config = LANGUAGES[language]
    files = {config["source"]: source.encode("utf-8"), "input": b""}
    heartbeat()
    if config["compile"]:
        result = execute(
            files, config["compile"], settings.JUDGE_COMPILE_SECONDS,
            settings.JUDGE_COMPILE_MEMORY_MB, compiling=True,
        )
        if result["verdict"] != "AC":
            return {
                "verdict": "CE", "execution_time_ms": 0, "memory_used_kb": 0,
                "compiler_message": compiler_diagnostics(result["errors"]),
            }
        files = {"program": result["artifact"]}
    peak_time = 0
    peak_memory = 0
    tests = list(problem.tests.all())
    if not tests:
        raise SandboxError("Problem has no tests.")
    verdict = "AC"
    for test in tests:
        heartbeat()
        files["input"] = test.input_text.encode("utf-8")
        cpu_seconds = problem.time_limit_ms / 1000 * config["time_multiplier"]
        result = execute(files, config["run"], cpu_seconds, problem.memory_limit_mb)
        peak_time = max(peak_time, result["time_ms"])
        peak_memory = max(peak_memory, result["memory_kb"])
        verdict = result["verdict"]
        if verdict == "AC" and not outputs_match(
            result["output"], test.expected_output.encode("utf-8"),
            problem.comparison_mode,
        ):
            verdict = "WA"
        if verdict != "AC":
            break
    heartbeat()
    return {
        "verdict": verdict, "execution_time_ms": peak_time,
        "memory_used_kb": peak_memory, "compiler_message": "",
    }
