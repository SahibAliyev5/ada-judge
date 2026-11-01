"""Real sandbox tests. Never run untrusted probes without IOI Isolate."""
import os
from types import SimpleNamespace

import pytest
from django.conf import settings

from judge.judging import judge_solution
from judge.sandbox import check_environment, execute

pytestmark = [
    pytest.mark.isolate,
    pytest.mark.skipif(
        os.getenv("RUN_ISOLATE_TESTS") != "1",
        reason="Requires the dedicated Linux VM; set RUN_ISOLATE_TESTS=1 there.",
    ),
]


@pytest.fixture(autouse=True)
def require_sandbox():
    check_environment()


def run_solution(source, language="python3", expected="8\n", cases=None):
    if cases is None:
        cases = [("3 5\n", expected)]
    tests = [SimpleNamespace(input_text=data, expected_output=output)
             for data, output in cases]
    problem = SimpleNamespace(
        time_limit_ms=300, memory_limit_mb=64, comparison_mode="tokens",
        tests=SimpleNamespace(all=lambda: tests),
    )
    return judge_solution(problem, language, source)


@pytest.mark.parametrize("source,language,verdict", [
    ("a, b = map(int, input().split())\nprint(a + b)", "python3", "AC"),
    ("print(7)", "python3", "WA"),
    ("pass", "python3", "WA"),
    ("print('8 extra')", "python3", "WA"),
    ("while True: pass", "python3", "TLE"),
    ("memory = bytearray(1024 * 1024 * 1024)", "python3", "MLE"),
    ("import os\nos.abort()", "python3", "RE"),
    ("while True: print('x' * 8192)", "python3", "OLE"),
    ("not valid C++", "cpp20", "CE"),
    ("#include <iostream>\nint main() { int a,b; std::cin >> a >> b; "
     "std::cout << a+b; }", "cpp20", "AC"),
])
def test_real_verdicts(source, language, verdict):
    assert run_solution(source, language)["verdict"] == verdict


def test_network_denial():
    source = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=0.2)\n"
        "except OSError:\n"
        "    print(8)\n"
    )
    assert run_solution(source)["verdict"] == "AC"


def test_no_host_files_or_worker_environment():
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "assert not Path('/etc/passwd').exists()\n"
        "assert not Path('/app').exists()\n"
        "assert not Path('/proc/1/root/etc/passwd').exists()\n"
        "assert 'POSTGRES_PASSWORD' not in os.environ\n"
        "assert 'SECRET_KEY' not in os.environ\n"
        "assert os.getuid() != 0\n"
        "print(8)\n"
    )
    assert run_solution(source)["verdict"] == "AC"


def test_process_limit():
    source = (
        "import os\n"
        "try:\n"
        "    child = os.fork()\n"
        "except OSError:\n"
        "    print(8)\n"
        "else:\n"
        "    os._exit(1)\n"
    )
    assert run_solution(source)["verdict"] == "AC"


def test_fresh_filesystem_each_case():
    source = (
        "from pathlib import Path\n"
        "assert not Path('/box/marker').exists()\n"
        "Path('/box/marker').write_text('previous test')\n"
        "a, b = map(int, input().split())\nprint(a + b)\n"
    )
    assert run_solution(source, cases=[("3 5\n", "8\n"), ("1 2\n", "3\n")])[
        "verdict"
    ] == "AC"


def test_bounded_stderr_and_output():
    result = execute(
        {"main.py": b"while True: print('x' * 8192)", "input": b""},
        ["/usr/bin/python3", "-I", "-B", "/box/main.py"], 2, 64,
    )
    assert result["verdict"] == "OLE"
    assert len(result["output"]) <= settings.JUDGE_OUTPUT_BYTES + 1
    assert len(result["errors"]) <= 8192


def test_host_loopback_is_separate():
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        source = (
            "import socket\n"
            "try:\n"
            f"    socket.create_connection(('127.0.0.1', {port}), timeout=0.2)\n"
            "except OSError:\n"
            "    print(8)\n"
        )
        assert run_solution(source)["verdict"] == "AC"
