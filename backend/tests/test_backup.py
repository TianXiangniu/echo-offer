import sqlite3

from app.backup import backup_database


def test_backup_creates_timestamped_copy_without_changing_source(tmp_path):
    source = tmp_path / "app.db"
    with sqlite3.connect(source) as connection:
        connection.execute("create table notes (value text)")
        connection.execute("insert into notes values ('kept')")
        connection.commit()

    backup = backup_database(source, tmp_path / "backups")

    assert backup.exists()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("select value from notes").fetchone() == ("kept",)
    assert backup.parent.name == "backups"
    assert backup != source
