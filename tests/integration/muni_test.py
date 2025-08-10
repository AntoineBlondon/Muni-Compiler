# muni_test.py
import subprocess
import tempfile
import os
import sys
import pytest
import textwrap

MUNI_CMD = [sys.executable, "-m", "muni2wasm"]

def _run(cmd, *, cwd=None, env=None, text=True):
    # unified runner that always captures stdout/stderr
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        text=text
    )

def compile_muni(src_path: str, out_wasm: str, *, fail_on_error: bool = True):
    """Compile and return CompletedProcess. If fail_on_error, raise with stderr on non-zero."""
    res = _run(MUNI_CMD + ["compile", src_path, out_wasm])
    if fail_on_error and res.returncode != 0:
        pytest.fail(
            f"muni2wasm compile failed (exit {res.returncode}):\n{res.stderr}"
        )
    return res

def run_wasm(wasm_path: str, *, fail_on_error: bool = True):
    """Run and return CompletedProcess. If fail_on_error, raise with stderr on non-zero."""
    res = _run(MUNI_CMD + ["run", wasm_path])
    if fail_on_error and res.returncode != 0:
        pytest.fail(
            f"muni2wasm run failed (exit {res.returncode}):\n{res.stderr}"
        )
    return res

def run_muni(src: str) -> list[str]:
    """
    Write `src` to a temp .mun, compile & run, return stdout lines.
    """
    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, "prog.mun")
        wasm_path = os.path.join(d, "out.wasm")

        with open(src_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(src))

        # compile (fail if error)
        compile_muni(src_path, wasm_path, fail_on_error=True)

        # run (fail if error)
        res = run_wasm(wasm_path, fail_on_error=True)
        return res.stdout.strip().splitlines()

def compile_error(src: str) -> str:
    """
    Compile expecting a failure. Return stderr string.
    Fails the test if compilation unexpectedly succeeds.
    """
    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, "prog.mun")
        wasm_path = os.path.join(d, "out.wasm")

        with open(src_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(src))

        res = compile_muni(src_path, wasm_path, fail_on_error=False)
        if res.returncode == 0:
            pytest.fail("Expected compilation to fail, but it succeeded.")
        return res.stderr

def runtime_error(src: str) -> str:
    """
    Compile successfully, then run expecting a runtime failure.
    Return stderr string.
    """
    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, "prog.mun")
        wasm_path = os.path.join(d, "out.wasm")

        with open(src_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(src))

        cres = compile_muni(src_path, wasm_path, fail_on_error=True)
        rres = run_wasm(wasm_path, fail_on_error=False)
        if rres.returncode == 0:
            pytest.fail("Expected program to fail at runtime, but it succeeded.")
        return rres.stderr
