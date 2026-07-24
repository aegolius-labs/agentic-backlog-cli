import os
import tempfile

import pytest

from aio_agentic_sdlc.archiver import PRDArchiver


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as temp_dir:
        inbox = os.path.join(temp_dir, "inbox")
        archive = os.path.join(temp_dir, "archive")
        os.makedirs(inbox)
        yield temp_dir, inbox, archive


def test_archive_creates_archive_dir(temp_workspace):
    temp_dir, inbox, archive = temp_workspace
    archiver = PRDArchiver(archive_dir=archive)

    test_file = os.path.join(inbox, "test1.md")
    with open(test_file, "w") as f:
        f.write("content")

    archiver.archive(test_file)
    assert os.path.exists(os.path.join(archive, "test1.md"))
    assert not os.path.exists(test_file)


def test_archive_name_collision(temp_workspace):
    temp_dir, inbox, archive = temp_workspace
    os.makedirs(archive, exist_ok=True)
    archiver = PRDArchiver(archive_dir=archive)

    existing_file = os.path.join(archive, "test2.md")
    with open(existing_file, "w") as f:
        f.write("old")

    test_file = os.path.join(inbox, "test2.md")
    with open(test_file, "w") as f:
        f.write("new")

    dest_path = archiver.archive(test_file)
    assert dest_path != existing_file
    assert dest_path.startswith(os.path.join(archive, "test2_"))
    assert dest_path.endswith(".md")

    with open(dest_path, "r") as f:
        assert f.read() == "new"

    with open(existing_file, "r") as f:
        assert f.read() == "old"


def test_archive_file_not_found(temp_workspace):
    temp_dir, inbox, archive = temp_workspace
    archiver = PRDArchiver(archive_dir=archive)
    with pytest.raises(FileNotFoundError):
        archiver.archive(os.path.join(inbox, "nonexistent.md"))


def test_archive_dir_is_a_file(temp_workspace):
    temp_dir, inbox, archive = temp_workspace

    # create 'archive' as a file
    with open(archive, "w") as f:
        f.write("not a directory")

    archiver = PRDArchiver(archive_dir=archive)

    test_file = os.path.join(inbox, "test3.md")
    with open(test_file, "w") as f:
        f.write("content")

    with pytest.raises(NotADirectoryError):
        archiver.archive(test_file)
