import os
import tempfile

import pytest

from aio_agentic_sdlc.archiver import PRDArchiver


def test_archive_dir_is_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        inbox = os.path.join(temp_dir, "inbox")
        archive = os.path.join(temp_dir, "archive")
        os.makedirs(inbox)
        with open(archive, "w") as f:
            f.write("I am a file, not a dir")
        archiver = PRDArchiver(archive_dir=archive)
        test_file = os.path.join(inbox, "test1.md")
        with open(test_file, "w") as f:
            f.write("content")
        with pytest.raises(NotADirectoryError):
            archiver.archive(test_file)


def test_archive_file_is_broken_symlink(tmp_path):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    archive.mkdir()
    test_file = inbox / "test1.md"
    test_file.write_text("content")
    symlink_target = archive / "test1.md"
    try:
        os.symlink("nowhere.md", str(symlink_target))
    except OSError:
        pytest.skip("Symlinks not supported on this Windows machine")
    archiver = PRDArchiver(archive_dir=str(archive))
    dest = archiver.archive(str(test_file))
    assert os.path.exists(dest)
