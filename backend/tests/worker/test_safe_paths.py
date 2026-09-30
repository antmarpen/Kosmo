import pytest
import errno

from shared.paths import safe_path


def test_safe_path_accepts_regular_name(tmp_path):
    assert safe_path(tmp_path, "report.md") == (tmp_path / "report.md").resolve()


@pytest.mark.parametrize("name", ["../secret", "C:/worker-secret", "/etc/passwd"])
def test_safe_path_rejects_absolute_and_traversal(tmp_path, name):
    with pytest.raises(ValueError):
        safe_path(tmp_path, name)


def test_safe_path_rejects_symlink_to_outside_file(tmp_path):
    outside = tmp_path.parent / "worker-secret-r05"
    outside.write_text("secret")
    try:
        (tmp_path / "link").symlink_to(outside)
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EACCES} or getattr(exc, "winerror", None) == 1314:
            pytest.skip("Creating symlinks requires Windows Developer Mode or elevated privileges")
        raise
    with pytest.raises(ValueError):
        safe_path(tmp_path, "link")


def test_safe_path_rejects_cross_task_path(tmp_path):
    task = tmp_path / "task-a"
    task.mkdir()
    with pytest.raises(ValueError):
        safe_path(task, tmp_path / "task-b" / "artifact")


@pytest.mark.parametrize("name", ["../bad", "/absolute", "", "x" * 65, ".."])
def test_safe_path_rejects_invalid_logical_name(tmp_path, name):
    with pytest.raises(ValueError):
        safe_path(tmp_path, name)
