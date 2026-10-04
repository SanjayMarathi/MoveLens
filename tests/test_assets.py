"""Images are committed as base64 text (Hugging Face rejects binary files in a Space's git repo). See app/assets.py."""
import base64
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.assets import StaticFilesWithEncodedImages

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
SIGNATURES = {".jpg": b"\xff\xd8\xff", ".png": b"\x89PNG\r\n\x1a\n"}


def test_every_text_twin_decodes_to_a_real_image_and_matches_the_local_file():
    twins = sorted(STATIC.rglob("*.b64"))
    assert len(twins) >= 6                                       # 4 backgrounds + 2 icons
    for twin in twins:
        data = base64.b64decode(twin.read_text(encoding="ascii"))
        original = twin.with_suffix("")                          # sky.jpg.b64 -> sky.jpg
        assert data.startswith(SIGNATURES[original.suffix]), twin.name
        if original.exists():                                    # on a developer's computer the real file is there too
            assert original.read_bytes() == data, f"{twin.name} is out of date: run the tools/ script again"


def test_no_binary_file_would_be_committed():
    gitignore = (ROOT / ".gitignore").read_text()
    assert "static/bg/*.jpg" in gitignore and "static/icon-*.png" in gitignore
    allowed_local_only = set(STATIC.glob("bg/*.jpg")) | set(STATIC.glob("icon-*.png"))
    skip = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
    offenders = []
    for path in ROOT.rglob("*"):
        if path.is_dir() or skip & set(path.relative_to(ROOT).parts) or path in allowed_local_only or path.name.startswith("_fake_engine"):
            continue
        if b"\x00" in path.read_bytes()[:8192]:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"binary files would be rejected by Hugging Face: {offenders}"


@pytest.fixture()
def client(tmp_path):
    (tmp_path / "bg").mkdir()
    (tmp_path / "bg" / "sky.jpg.b64").write_text(base64.encodebytes(b"\xff\xd8\xff\xe0JPEGDATA").decode())   # text only
    (tmp_path / "real.png").write_bytes(b"\x89PNG\r\n\x1a\nREAL")                                              # a normal file
    (tmp_path / "real.png.b64").write_text(base64.encodebytes(b"STALE").decode())                             # the real file wins
    (tmp_path / "bad.jpg.b64").write_text("!!! not base64 !!!")
    (tmp_path.parent / "secret.png.b64").write_text(base64.encodebytes(b"SECRET").decode())
    app = Starlette(routes=[Mount("/static", StaticFilesWithEncodedImages(directory=tmp_path), name="static")])
    return TestClient(app)


def test_text_only_image_is_served_decoded(client):
    res = client.get("/static/bg/sky.jpg")
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"
    assert res.content == b"\xff\xd8\xff\xe0JPEGDATA" and "max-age" in res.headers["cache-control"]


def test_real_file_wins_over_its_text_twin(client):
    assert client.get("/static/real.png").content.endswith(b"REAL")


def test_missing_corrupt_and_escaping_paths_are_404(client):
    assert client.get("/static/bg/nope.jpg").status_code == 404
    assert client.get("/static/bad.jpg").status_code == 404
    assert client.get("/static/../secret.png").status_code == 404
    assert client.get("/static/%2e%2e/secret.png").status_code == 404
