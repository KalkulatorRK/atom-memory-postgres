import subprocess

import pytest

from vector_index_validate import normalize_mem


def test_normalize_mem_ok():
    assert normalize_mem("1GB") == "1GB"
    assert normalize_mem("512MB") == "512MB"


@pytest.mark.parametrize("bad", ["1gb", "5", "1kB", "0MB", ""])
def test_normalize_mem_rejects(bad):
    with pytest.raises(ValueError):
        normalize_mem(bad)


def test_vector_admin_validates_before_drop():
    root = __import__("os").path.dirname(__import__("os").path.dirname(__file__))
    script = __import__("os").path.join(root, "vector_index_admin.sh")
    r = subprocess.run(
        ["bash", script, "--model", "fake:hash-v1", "--dims", "768", "--drop", "--mem", "1kB"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "DROP INDEX" not in (r.stderr + r.stdout) or "1kB" in (r.stderr + r.stdout)
