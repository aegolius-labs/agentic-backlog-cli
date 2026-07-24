import os
from unittest.mock import patch

from aio_agentic_sdlc.archiver import PRDArchiver


def test_symlink_toctou_vulnerability(tmp_path):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    archive.mkdir()

    target_file = tmp_path / "arbitrary_location.txt"
    target_file.write_text("SAFE")

    test_file = inbox / "malicious_prd.md"
    test_file.write_text("MALICIOUS PAYLOAD")

    archiver = PRDArchiver(archive_dir=str(archive))
    dest_path = archive / "malicious_prd.md"

    original_lexists = os.path.lexists

    def mocked_lexists(path):
        if path == str(dest_path):
            try:
                os.symlink(str(target_file), str(dest_path))
            except OSError:
                pass
            return False
        return original_lexists(path)

    with patch("os.path.lexists", side_effect=mocked_lexists):
        archiver.archive(str(test_file))

    assert (
        target_file.read_text() == "SAFE"
    ), "VULNERABILITY: TOCTOU Symlink attack successfully overwrote an arbitrary file outside the archive!"
