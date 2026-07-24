import os

import pytest

from aio_agentic_sdlc.archiver import PRDArchiver


def test_symlink_arbitrary_write_vulnerability(tmp_path):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    archive.mkdir()

    # Target location outside the archive, currently does not exist
    target_file = tmp_path / "arbitrary_location.txt"

    malicious_symlink = archive / "malicious_prd.md"
    try:
        os.symlink(str(target_file), str(malicious_symlink))
    except OSError:
        pytest.skip("Symlinks not supported")

    test_file = inbox / "malicious_prd.md"
    test_file.write_text("MALICIOUS PAYLOAD")

    archiver = PRDArchiver(archive_dir=str(archive))
    archiver.archive(str(test_file))

    assert (
        not target_file.exists()
    ), "VULNERABILITY: Symlink attack successfully wrote to an arbitrary location outside the archive!"
