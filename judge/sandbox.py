import fcntl
import math
import os
import platform
import signal
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings


class SandboxError(Exception):
    pass


def check_environment():
    if not settings.JUDGE_ENABLED or platform.system() != "Linux":
        raise SandboxError("Judging requires an explicitly enabled Linux worker.")
    executable = Path(settings.JUDGE_ISOLATE)
    if not executable.is_absolute() or not executable.is_file():
        raise SandboxError("Isolate must be installed at an absolute path.")
    info = executable.stat()
    if info.st_uid != 0 or info.st_mode & 0o022 or not info.st_mode & stat.S_ISUID:
        raise SandboxError("Isolate must be root-owned, setuid, and not writable.")
    if os.geteuid() == 0:
        raise SandboxError("The worker must run as an unprivileged user.")
    root = Path(settings.JUDGE_ROOTFS).resolve()
    mounts = []
    for name in ("usr", "bin", "lib", "lib64", "dev"):
        path = root / name
        if name == "lib64" and not path.exists():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_dir():
            raise SandboxError("Invalid runtime filesystem.")
        info = resolved.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise SandboxError("Runtime filesystem must be root-owned and read-only.")
        options = "dev:norec" if name == "dev" else "norec"
        mounts.append(f"--dir=/{name}={resolved}:{options}")
    return mounts


def invoke(arguments, timeout):
    try:
        result = subprocess.run(
            [settings.JUDGE_ISOLATE, *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SandboxError("Isolate invocation failed.") from error
    if result.returncode not in (0, 1):
        message = result.stderr[:2048].decode("utf-8", errors="replace")
        raise SandboxError(f"Isolate infrastructure failure: {message}")
    return result


@contextmanager
def sandbox():
    mounts = check_environment()
    lock_path = Path(settings.JUDGE_LOCK_DIR) / f"box-{settings.JUDGE_BOX_ID}.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SandboxError("This box ID is already in use.") from error
        base = ["--cg", f"--box-id={settings.JUDGE_BOX_ID}"]
        initialized = False
        try:
            initialized = True
            result = invoke([
                *base, f"--quota={settings.JUDGE_DISK_BLOCKS},"
                f"{settings.JUDGE_DISK_INODES}", "--init",
            ], 10)
            if result.returncode != 0:
                raise SandboxError("Sandbox initialization failed.")
            initialized = True
            directory = Path(result.stdout.decode().strip()) / "box"
            if not directory.is_absolute() or not directory.is_dir():
                raise SandboxError("Invalid Isolate working directory.")
            with tempfile.TemporaryDirectory(prefix="judge-meta-") as temporary:
                yield directory, Path(temporary) / "result", base, mounts
        finally:
            # Cleanup failure is an infrastructure failure, never an AC.
            if initialized:
                result = invoke([*base, "--cleanup"], 10)
                if result.returncode != 0:
                    raise SandboxError("Sandbox cleanup failed.")


def read_file(path, limit):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return b""
    except OSError as error:
        raise SandboxError("Invalid sandbox output file.") from error
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SandboxError("Sandbox output is not a regular file.")
        return stream.read(limit + 1)


def parse_metadata(path):
    if not path.is_file():
        raise SandboxError("Missing Isolate metadata.")
    fields = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key] = value
    if fields.get("status") == "XX":
        raise SandboxError("Isolate reported an infrastructure failure.")
    if not fields.get("status") and "exitcode" not in fields:
        raise SandboxError("Missing program exit status.")
    if "time" not in fields or "cg-mem" not in fields:
        raise SandboxError("CPU or cgroup memory accounting unavailable.")
    try:
        cpu = float(fields["time"])
        memory = int(fields["cg-mem"])
        if not math.isfinite(cpu) or cpu < 0 or memory < 0:
            raise ValueError
    except ValueError as error:
        raise SandboxError("Invalid resource accounting.") from error
    return fields


def verdict_from_metadata(fields):
    status = fields.get("status", "")
    if status not in ("", "RE", "SG", "TO"):
        raise SandboxError("Unknown Isolate result.")
    if fields.get("cg-oom-killed") == "1":
        return "MLE"
    if fields.get("exitsig") == str(signal.SIGXFSZ):
        return "OLE"
    if status == "TO":
        return "TLE"
    if status in ("RE", "SG") or fields.get("exitcode", "0") != "0":
        return "RE"
    return "AC"


def execute(files, command, cpu_seconds, memory_mb, compiling=False):
    with sandbox() as (directory, metadata, base, mounts):
        for name, content in files.items():
            path = directory / name
            path.write_bytes(content)
            path.chmod(0o755 if name == "program" else 0o644)
        file_kb = math.ceil(settings.JUDGE_OUTPUT_BYTES / 1024) + 1
        if compiling:
            file_kb = settings.JUDGE_COMPILE_FILE_KB
        wall_seconds = cpu_seconds * 3 + 2
        arguments = [
            *base, "--no-default-dirs", *mounts,
            f"--dir=/box={directory}:rw", f"--dir=/tmp={directory}:rw",
            "--dir=/proc=proc",
            "--chdir=/box", "--env=PATH=/usr/bin:/bin", "--env=LANG=C",
            "--env=HOME=/box", "--env=TMPDIR=/box", "--syscalls=31",
            f"--time={cpu_seconds}", f"--wall-time={wall_seconds}",
            f"--cg-mem={memory_mb * 1024}",
            f"--processes={16 if compiling else 1}", "--open-files=64",
            f"--fsize={file_kb}", "--core=0", f"--meta={metadata}",
            "--stdin=/box/input", "--stdout=/box/output", "--stderr=/box/errors",
            "--run", "--", *command,
        ]
        result = invoke(arguments, wall_seconds + 10)
        fields = parse_metadata(metadata)
        verdict = verdict_from_metadata(fields)
        if result.returncode == 1 and verdict == "AC":
            raise SandboxError("Inconsistent Isolate exit status.")
        output = read_file(directory / "output", settings.JUDGE_OUTPUT_BYTES)
        errors = read_file(directory / "errors", settings.JUDGE_OUTPUT_BYTES)
        artifact = b""
        if compiling and verdict == "AC":
            artifact = read_file(directory / "program", file_kb * 1024)
            if not artifact or len(artifact) > file_kb * 1024:
                raise SandboxError("Missing or oversized compiler artifact.")
        if (len(output) > settings.JUDGE_OUTPUT_BYTES
                or len(errors) > settings.JUDGE_OUTPUT_BYTES):
            verdict = "OLE"
        return {
            "verdict": verdict, "output": output, "errors": errors[:8192],
            "artifact": artifact,
            "time_ms": math.ceil(float(fields["time"]) * 1000),
            "memory_kb": int(fields["cg-mem"]),
        }
