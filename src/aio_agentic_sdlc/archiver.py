import datetime
import os

from .workspace import ARCHIVE_DIR


# aio-sdlc-mapping-approval: {"approved_at":"2026-08-10T10:12:30.970663-04:00","approved_by":"Felix","candidate_reality_id":"ac41eaca-b3f9-55fc-850a-a633ffc6b723","evidence_digest":"b822c46ff78c9fac9717f904f769a80af67e265b243ac951d72673e78c20bca9","intent_id":"6506870b-b262-4f54-b6e9-43de4a873a55","rationale":"Felix approved PRDArchiver as the implementation identity of the PRD Archiver component; behavioral completeness remains separately reviewable.","schema_version":1,"source_path":"src/aio_agentic_sdlc/archiver.py","source_sha256":"cdd5b44b21809aa5c94f6577b7302f2455e131ae8d9c9c3853c7f30487e90022","symbol_kind":"class","symbol_name":"PRDArchiver"}
# aio-sdlc-node: 6506870b-b262-4f54-b6e9-43de4a873a55
class PRDArchiver:
    def __init__(self, archive_dir: str = ARCHIVE_DIR):
        self.archive_dir = archive_dir

    def archive(self, file_path: str) -> str:
        """
        Moves a file to the archive directory.
        If a file with the same name exists, it appends a timestamp to prevent overwriting.
        Returns the new path of the archived file.
        """
        if not os.path.lexists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if not os.path.lexists(self.archive_dir):
            os.makedirs(self.archive_dir)
        elif not os.path.isdir(self.archive_dir):
            raise NotADirectoryError(
                f"Archive destination exists but is not a directory: {self.archive_dir}"
            )

        filename = os.path.basename(file_path)
        dest_path = os.path.join(self.archive_dir, filename)

        if os.path.lexists(dest_path):
            name, ext = os.path.splitext(filename)
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            new_filename = f"{name}_{timestamp}{ext}"
            dest_path = os.path.join(self.archive_dir, new_filename)

        os.replace(file_path, dest_path)
        return dest_path
