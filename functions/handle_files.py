import os
import shutil

from settings import DOWNLOADED_FILES_RECORD

import gc


def collection_folder_to_clear(col, folder_path: str):
    collections_to_clear = {
        "EO:EUM:DAT:MSG:HRSEVIRI",
        "EO:EUM:DAT:0662",
        "EO:EUM:DAT:0691",
    }

    if col in collections_to_clear:
        if os.path.exists(folder_path):
            gc.collect()  # <-- Force Python to release open file handles
            try:
                shutil.rmtree(folder_path)  # Now delete safely
            except Exception as e:
                print(f"Error deleting folder {folder_path}: {e}")

    os.makedirs(folder_path, exist_ok=True)


def manage_downloaded_files():
    """Check if the downloaded files record has more than 300 lines, and keep only the last 50."""
    if not os.path.exists(DOWNLOADED_FILES_RECORD):
        return

    with open(DOWNLOADED_FILES_RECORD, "r") as file:
        lines = file.readlines()

    # Keep only the last 50 lines if there are more than 300 lines
    if len(lines) > 400:
        lines = lines[-50:]

    # Write the last 50 lines back to the file
    with open(DOWNLOADED_FILES_RECORD, "w") as file:
        file.writelines(lines)


def load_downloaded_files():
    """Load previously downloaded filenames (both full paths and filenames only)."""
    manage_downloaded_files()
    if not os.path.exists(DOWNLOADED_FILES_RECORD):
        return set()

    with open(DOWNLOADED_FILES_RECORD, "r") as file:
        return {line.strip() for line in file}


def is_file_downloaded(filename, downloaded_files):
    """Check if the full path or just the filename exists in the record."""
    filename_only = os.path.basename(filename)
    for record in downloaded_files:
        if filename in record or filename_only in record:
            return True
    return False


def save_downloaded_file(filename):
    """Append a new downloaded filename to the record file."""
    with open(DOWNLOADED_FILES_RECORD, "a") as file:
        file.write(filename + "\n")
