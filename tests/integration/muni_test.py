import subprocess
import tempfile
import os
import pytest
import textwrap

MUNI = "python3 -m muni2wasm"

def compile_muni(src_path, out_wasm):
    # run the compiler, capturing both stdout and stderr
    res = subprocess.run(
        f"{MUNI} compile {src_path} {out_wasm}",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if res.returncode != 0:
        # embed the stderr in the failure so pytest will show it
        pytest.fail(
            f"muni2wasm compile failed (exit {res.returncode}):\n"
            f"{res.stderr}"
        )

def run_muni(src: str) -> list[str]:
    """
    Write `src` to a temporary .mun file, compile & run with muni2wasm,
    and return stdout lines.
    """
    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, "prog.mun")
        wasm_path = os.path.join(d, "out.wasm")
        # write the source
        with open(src_path, "w") as f:
            f.write("import env.print(int) -> void;" + textwrap.dedent(src))
        
        compile_muni(src_path, wasm_path)

        # run
        res = subprocess.run(f"{MUNI} run {wasm_path}",
                             shell=True, check=True,
                             stdout=subprocess.PIPE,
                             universal_newlines=True)
        return res.stdout.strip().splitlines()
