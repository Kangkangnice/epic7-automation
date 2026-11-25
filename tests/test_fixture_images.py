import os

import cv2
import numpy as np
from PIL import Image


def test_fixture_loaders_share_a_byte_budget_and_return_independent_images(tmp_path):
    from auto_game_unified.tests.fixture_images import FixtureImageCache

    screen = tmp_path / "screen.png"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(screen)
    cache = FixtureImageCache(tmp_path, 1_200)

    bgr = cache.imread(screen)
    assert bgr[0, 0].tolist() == [30, 20, 10]
    bgr[0, 0] = 0
    assert cache.imread(screen)[0, 0].tolist() == [30, 20, 10]

    pil = cache.open(screen)
    pil.putpixel((0, 0), (0, 0, 0))
    assert cache.open(screen).getpixel((0, 0)) == (10, 20, 30)
    assert cache.retained_bytes == 16 * 16 * 4

    rgb = cache.read_rgb_fixture(screen)
    assert rgb[0, 0].tolist() == [10, 20, 30]
    rgb[0, 0] = 0
    assert cache.read_rgb_fixture(screen)[0, 0].tolist() == [10, 20, 30]
    assert cache.retained_bytes == 16 * 16 * 3

    older_stamp = screen.stat()
    Image.new("RGB", (16, 16), (1, 2, 3)).save(screen)
    os.utime(screen, ns=(older_stamp.st_atime_ns, older_stamp.st_mtime_ns + 2_000_000_000))
    assert cache.read_rgb_fixture(screen)[0, 0].tolist() == [1, 2, 3]


def test_fixture_cache_bypasses_nonfixtures_and_preserves_real_decoding(tmp_path):
    from auto_game_unified.tests.fixture_images import FixtureImageCache

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    screen = fixtures / "screen.png"
    outside = tmp_path / "outside.png"
    Image.new("RGB", (2_000, 1_200), (10, 20, 30)).save(screen)
    Image.new("RGB", (10, 10), (10, 20, 30)).save(outside)
    cache = FixtureImageCache(fixtures, 0)
    assert cache.read_rgb_fixture(screen).shape == (1_132, 1_982, 3)
    assert cache.retained_bytes == 0

    cache = FixtureImageCache(fixtures, 1_200)
    with cache.open(outside) as image:
        assert image.format == "PNG"
    assert np.array_equal(cache.imread(outside), cv2.imread(str(outside)))
    assert cache.retained_bytes == 0


def test_full_and_cropped_replays_keep_their_own_dimensions(tmp_path):
    from auto_game_unified.tests.fixture_images import FixtureImageCache

    screen = tmp_path / "screen.png"
    Image.new("RGB", (2_000, 1_200)).save(screen)
    cache = FixtureImageCache(tmp_path, 16 * 1024**2)

    assert cache.read_rgb_fixture(screen).shape == (1_132, 1_982, 3)
    assert cache.read_rgb_fixture(screen, crop_to_reference=False).shape == (1_200, 2_000, 3)
    assert cache.read_rgb_fixture(screen).shape == (1_132, 1_982, 3)


def test_pytest_limits_the_opencv_thread_pool():
    assert cv2.getNumThreads() == 1


def test_png_fixture_selection_checks_dimensions_without_decoding_pixels(tmp_path, monkeypatch):
    from auto_game_unified.tests.fixture_images import png_fixtures_of_size

    matching = tmp_path / "nested" / "matching.png"
    matching.parent.mkdir()
    Image.new("RGB", (6, 9)).save(matching)
    Image.new("RGB", (9, 6)).save(tmp_path / "landscape.png")
    rotated = tmp_path / "rotated.png"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (9, 6)).save(rotated, exif=exif)
    (tmp_path / "broken.png").write_bytes(b"broken")

    def unexpected_load(image):
        raise AssertionError("selecting fixture paths should only inspect PNG headers")

    monkeypatch.setattr(Image.Image, "load", unexpected_load)
    assert list(png_fixtures_of_size(tmp_path, (6, 9))) == [matching, rotated]


def test_named_frame_replay_loads_each_frame_once_and_holds_the_last():
    from auto_game_unified.tests.fixture_images import named_frame_replay

    loaded = []

    def load(name):
        loaded.append(name)
        return np.zeros((2, 2, 3), dtype=np.uint8)

    start, capture = named_frame_replay(load, ("start", "start", "end"))
    assert loaded == ["start", "end"]
    assert capture() is start
    assert capture() is start
    last = capture()
    assert last is not start
    assert capture() is last
