"""Run-directory locking and scheduler allocation checks."""
import os
from contextlib import contextmanager


@contextmanager
def run_lock(directory):
    """OS advisory lock, released on interruption, so no stale lock file needs removing."""
    handle = (directory / ".run.lock").open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("another batch process holds this run directory") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("another batch process holds this run directory") from exc
        locked = True
        yield
    finally:
        if locked and os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def check_allocation(settings, uses_orca: bool) -> None:
    """Refuse ORCA settings larger than the SLURM allocation before any calculation starts."""
    if not uses_orca:
        return
    cpus = os.environ.get("SLURM_CPUS_PER_TASK")
    if cpus and settings.orca_nprocs > int(cpus):
        raise ValueError("orca_nprocs exceeds SLURM_CPUS_PER_TASK")
    memory = os.environ.get("SLURM_MEM_PER_NODE")
    if memory and settings.orca_nprocs * settings.orca_maxcore_mb > int(memory):
        raise ValueError("ORCA nominal memory exceeds SLURM_MEM_PER_NODE; reserve overhead too")
