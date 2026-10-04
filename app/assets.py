"""
Serving the page's files, including images stored as text.

Hugging Face Spaces refuse binary files in a Space's git repository (unless you set up their Xet storage). So the
background photos and app icons are committed as base64 text, next to the real image on a developer's computer:

    static/bg/sky.jpg        the real image (git-ignored; created by tools/make_backgrounds.js)
    static/bg/sky.jpg.b64    the same image as text (committed)

This StaticFiles serves `sky.jpg` from the real file when it exists, and otherwise decodes `sky.jpg.b64` on the fly.
"""
from __future__ import annotations

import base64
import binascii
import mimetypes
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

ENCODED_SUFFIX = ".b64"


def encoded_twin(root: Path, relative: str) -> Path | None:
    """The base64 text file for `relative` inside `root`, if there is one (and it really is inside `root`)."""
    root = root.resolve()
    candidate = (root / (relative + ENCODED_SUFFIX)).resolve()
    if root in candidate.parents and candidate.is_file():
        return candidate
    return None


def decode_file(path: Path) -> bytes:
    return base64.b64decode(path.read_text(encoding="ascii"))


class StaticFilesWithEncodedImages(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            twin = encoded_twin(Path(self.directory), path)
            if twin is None:
                raise
            try:
                data = decode_file(twin)
            except (binascii.Error, ValueError, OSError):
                raise exc
            media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
            return Response(data, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
