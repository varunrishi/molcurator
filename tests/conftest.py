# Shared pytest fixtures: small test molecules (e.g. benzene, a small TADF donor-acceptor),
# a temporary run folder, and markers to skip tests when xtb / ORCA are not installed.
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()


def openmpi_4_1() -> bool:
    """The Open MPI that chem/orca.py would use (OPENMPI_HOME, else mpirun on PATH) is a 4.1.x release:
    ORCA 6.1.1 is built against Open MPI 4.1 (4.1.1 on macOS, 4.1.8 on Linux), and a parallel run
    with another major version (e.g. Homebrew's 5.0) crashes inside MPI rather than testing anything."""
    home = os.environ.get("OPENMPI_HOME")
    mpirun = str(Path(home) / "bin" / "mpirun") if home else shutil.which("mpirun")
    if not mpirun:
        return False
    try:
        out = subprocess.run([mpirun, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return re.search(r"\(Open MPI\) 4\.1\.", out) is not None


# ORCA is licensed and installed by hand; tests that launch it skip without it. xTB needs no
# marker: it runs through tblite, a regular dependency.
needs_orca = pytest.mark.skipif(not (os.environ.get("ORCA_BIN") or shutil.which("orca")),
                                reason="ORCA not installed (set ORCA_BIN or put orca on PATH)")
needs_mpi = pytest.mark.skipif(not openmpi_4_1(),
                               reason="Open MPI 4.1.x not found (ORCA 6.1.1's MPI): set OPENMPI_HOME to it")
