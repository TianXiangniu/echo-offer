from datetime import datetime
import os
from pathlib import Path
import sqlite3


def backup_database(database_path: Path, backup_root: Path) -> Path:
    """Create a consistent backup, including data currently held in a WAL file."""
    source = database_path.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"database not found: {source}")

    backup_root = backup_root.resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_root / f"{source.stem}-{timestamp}{source.suffix}"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    source_connection = None
    destination_connection = None
    try:
        source_connection = sqlite3.connect(str(source), timeout=10)
        destination_connection = sqlite3.connect(str(temporary), timeout=10)
        source_connection.backup(destination_connection)
        destination_connection.commit()
        destination_connection.close()
        destination_connection = None
        source_connection.close()
        source_connection = None
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
    return destination
