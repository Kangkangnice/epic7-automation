"""Bound the decoded pixels retained by offline screenshot replays."""

import os
from collections import OrderedDict
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image

_IMREAD = cv2.imread
_OPEN = Image.open


def png_fixtures_of_size(root: Path, size: tuple[int, int]) -> Iterator[Path]:
    """Select PNGs by their capture dimensions without decoding their pixels."""
    for path in sorted(root.rglob("*.png")):
        try:
            with _OPEN(path, formats=["PNG"]) as header:
                dimensions = header.size
                if "exif" in header.info and header.getexif().get(274) in (5, 6, 7, 8):
                    dimensions = dimensions[::-1]
        except OSError:
            continue
        if dimensions == size:
            yield path


def named_frame_replay(
    load: Callable[[str], np.ndarray], names: tuple[str, ...]
) -> tuple[np.ndarray, Callable[[], np.ndarray]]:
    """Replay fixed captures in order, retaining one array per fixture name."""
    frames = {name: load(name) for name in dict.fromkeys(names)}
    sequence = iter(names)
    last = names[-1]

    def capture() -> np.ndarray:
        return frames[next(sequence, last)]

    return frames[names[0]], capture


class FixtureImageCache:
    def __init__(self, root: Path, budget_bytes: int):
        self.root = root
        self.budget_bytes = budget_bytes
        self.retained_bytes = 0
        self._entries = OrderedDict()
        self._lock = Lock()

    def _key(self, path, variant):
        if not self.budget_bytes:
            return None
        try:
            filename = Path(os.path.abspath(path))
            if not filename.is_relative_to(self.root):
                return None
            info = filename.stat()
        except (TypeError, ValueError, OSError):
            return None
        return filename, variant, info.st_mtime_ns, info.st_size

    def _read(self, key, decode):
        if key is None:
            return decode()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
        if entry is not None:
            return entry[0].copy()

        image = decode()
        if image is None or getattr(image, "is_animated", False):
            return image
        if isinstance(image, Image.Image):
            # Pillow stores common RGB images in four-byte pixel slots.
            size = image.width * image.height * 4
        else:
            size = image.nbytes
        if size > self.budget_bytes:
            return image
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self.retained_bytes -= previous[1]
            while self.retained_bytes + size > self.budget_bytes:
                _, (_, removed_size) = self._entries.popitem(last=False)
                self.retained_bytes -= removed_size
            self._entries[key] = (image, size)
            self.retained_bytes += size
        return image.copy()

    def imread(self, path, flags=cv2.IMREAD_COLOR):
        return self._read(self._key(path, ("cv2", flags)), lambda: _IMREAD(path, flags))

    def open(self, fp, mode="r", formats=None):
        key = self._key(fp, "pil") if mode == "r" and formats is None else None
        if key is None:
            return _OPEN(fp, mode, formats)

        def decode():
            image = _OPEN(fp)
            try:
                image.load()
            except Exception:
                image.close()
                raise
            return image

        try:
            return self._read(key, decode)
        except Exception:
            # Preserve lazy decoding when Pillow would report a damaged image on load.
            return _OPEN(fp)

    def read_rgb_fixture(self, path: Path, *, crop_to_reference: bool = True):
        def decode():
            raw = _IMREAD(str(path), cv2.IMREAD_COLOR)
            assert raw is not None, f"缺夹具 {path}"
            # The side-story captures include pixels outside the reference canvas.
            if crop_to_reference:
                raw = raw[:1132, :1982]
            return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)

        return self._read(self._key(path, ("rgb", crop_to_reference)), decode)


fixture_image_cache = FixtureImageCache(
    Path(__file__).resolve().parent / "fixtures",
    32 * 1024**2 if os.environ.get("EPIC7_TEST_FIXTURE_CACHE", "1") != "0" else 0,
)
read_rgb_fixture = fixture_image_cache.read_rgb_fixture
