# Shared pytest fixtures: small test molecules (e.g. benzene, a small TADF donor-acceptor),
# a temporary run folder, and markers to skip tests when xtb / ORCA are not installed.
import os
import shutil

import pytest
from dotenv import load_dotenv

load_dotenv()
# ORCA is licensed and installed by hand; tests that launch it skip without it. xTB needs no
# marker: it runs through tblite, a regular dependency.
needs_orca = pytest.mark.skipif(not (os.environ.get("ORCA_BIN") or shutil.which("orca")),
                                reason="ORCA not installed (set ORCA_BIN or put orca on PATH)")
needs_mpi = pytest.mark.skipif(not (os.environ.get("OPENMPI_HOME") or shutil.which("mpirun")),
                               reason="Open MPI not found (set OPENMPI_HOME or put mpirun on PATH)")
