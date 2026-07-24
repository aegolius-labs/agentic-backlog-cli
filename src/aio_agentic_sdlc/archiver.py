import datetime
import os


class PRDArchiver:
    def __init__(self, archive_dir: str = "archive"):
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
