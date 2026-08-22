"""Serialized mutation helpers for canonical DAG files."""

import os
import stat
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TypeVar

from filelock import FileLock

from .dag_manager import DAGManager

T = TypeVar("T")


class GuardedPathError(ValueError):
    """Raised when a state or artifact path fails non-following validation."""


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def guarded_file_path(
    filepath: str | Path,
    *,
    create_parent: bool = False,
) -> Path:
    """Return one absolute, non-following path after rejecting redirection."""

    dag_path = Path(os.path.abspath(os.fspath(filepath)))
    for parent in reversed(dag_path.parents):
        if os.path.lexists(parent):
            if _is_link_like(parent) or not parent.is_dir():
                raise GuardedPathError(f"DAG parent must be a real directory: {parent}")
        elif create_parent:
            parent.mkdir(exist_ok=True)
            if _is_link_like(parent) or not parent.is_dir():
                raise GuardedPathError(f"DAG parent must be a real directory: {parent}")
        else:
            raise GuardedPathError(f"DAG parent does not exist: {parent}")
    if os.path.lexists(dag_path) and (
        _is_link_like(dag_path) or not dag_path.is_file()
    ):
        raise GuardedPathError(f"DAG path must be a regular file: {dag_path}")
    return dag_path


def guarded_directory_path(directory: str | Path) -> Path:
    """Return an absolute real directory after rejecting reparse redirection."""

    path = Path(os.path.abspath(os.fspath(directory)))
    for candidate in (*reversed(path.parents), path):
        if not os.path.lexists(candidate):
            raise GuardedPathError(f"Directory does not exist: {candidate}")
        if _is_link_like(candidate) or not candidate.is_dir():
            raise GuardedPathError(f"Directory must be a real directory: {candidate}")
    return path


def guarded_dag_path(
    filepath: str | Path,
    *,
    create_parent: bool = False,
) -> Path:
    """Backward-compatible semantic name for a guarded DAG file path."""

    return guarded_file_path(filepath, create_parent=create_parent)


@contextmanager
def dag_file_lock(filepath: str | Path) -> Iterator[Path]:
    """Lock one exact non-following DAG path and revalidate it under lock."""

    dag_path = guarded_file_path(filepath, create_parent=True)
    lock_path = guarded_file_path(
        dag_path.parent / f".{dag_path.name}.lock",
        create_parent=True,
    )
    with FileLock(lock_path, timeout=10, preserve_lock_file=True):
        yield guarded_file_path(dag_path)


def mutate_dag_file(
    filepath: str | Path,
    mutation: Callable[[DAGManager], T],
) -> T:
    """Load, mutate, validate through the callback, and atomically save under one lock."""

    with dag_file_lock(filepath) as dag_path:
        guarded_file_path(dag_path)
        manager = DAGManager.load(str(dag_path))
        result = mutation(manager)
        guarded_file_path(dag_path)
        manager.save(str(dag_path))
        return result
