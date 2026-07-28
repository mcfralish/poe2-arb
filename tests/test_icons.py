"""Disk cache for item icons."""

from __future__ import annotations

import httpx
import pytest

from poe2arb.icons import (
    IMAGE_HOST,
    MAX_ICON_BYTES,
    cache_name,
    cache_size_bytes,
    cached_path,
    clear,
    fetch,
    fetch_and_store,
    icon_dir,
    image_url,
    load,
    store,
)

PATH_A = "/gen/image/WzI1LDE0/c0ca392a78/CurrencyRerollRare.png"
PATH_B = "/gen/image/WzI1LDE0/aaaaaaaaaa/CurrencyModValues.png"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


def transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestNaming:
    def test_distinct_paths_never_collide(self):
        """A collision would show one item's art on another — hash, don't sanitise."""
        assert cache_name(PATH_A) != cache_name(PATH_B)

    def test_same_path_is_stable(self):
        assert cache_name(PATH_A) == cache_name(PATH_A)

    def test_name_is_filesystem_safe(self):
        name = cache_name(PATH_A)
        assert name.endswith(".png")
        assert all(c.isalnum() or c == "." for c in name)

    def test_icons_live_in_their_own_subdirectory(self, tmp_path):
        """So clearing them can't touch cached API responses."""
        assert icon_dir(tmp_path).name == "icons"
        assert cached_path(tmp_path, PATH_A).parent == icon_dir(tmp_path)


class TestUrl:
    def test_cdn_path_gets_the_host(self):
        assert image_url(PATH_A) == IMAGE_HOST + PATH_A

    def test_absolute_url_is_left_alone(self):
        assert image_url("https://example.com/x.png") == "https://example.com/x.png"


class TestStoreLoad:
    def test_round_trip(self, tmp_path):
        assert store(tmp_path, PATH_A, PNG)
        assert load(tmp_path, PATH_A) == PNG

    def test_missing_is_none(self, tmp_path):
        assert load(tmp_path, PATH_A) is None

    def test_empty_payload_is_refused(self, tmp_path):
        assert not store(tmp_path, PATH_A, b"")
        assert load(tmp_path, PATH_A) is None

    def test_oversized_payload_is_refused(self, tmp_path):
        """A 64px icon that big is an error page, not art."""
        assert not store(tmp_path, PATH_A, b"x" * (MAX_ICON_BYTES + 1))
        assert load(tmp_path, PATH_A) is None

    def test_no_partial_file_left_behind(self, tmp_path):
        store(tmp_path, PATH_A, PNG)
        assert [p.suffix for p in icon_dir(tmp_path).iterdir()] == [".png"]

    def test_unwritable_cache_is_not_fatal(self, tmp_path):
        blocker = tmp_path / "cache"
        blocker.write_text("not a directory", encoding="utf-8")
        assert not store(blocker, PATH_A, PNG)


class TestFetch:
    def test_successful_fetch(self):
        client = transport(
            lambda r: httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        )
        assert fetch(PATH_A, client) == PNG

    def test_requests_the_cdn_host(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

        fetch(PATH_A, transport(handler))
        assert seen["url"] == IMAGE_HOST + PATH_A

    def test_http_error_is_none(self):
        client = transport(lambda r: httpx.Response(404))
        assert fetch(PATH_A, client) is None

    def test_non_image_response_is_rejected(self):
        """A 200 that isn't an image means the CDN served an error page."""
        client = transport(
            lambda r: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        )
        assert fetch(PATH_A, client) is None

    def test_network_failure_is_none_not_an_exception(self):
        def handler(request):
            raise httpx.ConnectError("no route")

        assert fetch(PATH_A, transport(handler)) is None


class TestFetchAndStore:
    def test_disk_wins_over_network(self, tmp_path):
        store(tmp_path, PATH_A, PNG)
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, content=b"other", headers={"content-type": "image/png"})

        assert fetch_and_store(tmp_path, PATH_A, transport(handler)) == PNG
        assert calls == []

    def test_fetches_and_caches_a_miss(self, tmp_path):
        client = transport(
            lambda r: httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        )
        assert fetch_and_store(tmp_path, PATH_A, client) == PNG
        assert load(tmp_path, PATH_A) == PNG

    def test_failure_caches_nothing(self, tmp_path):
        client = transport(lambda r: httpx.Response(500))
        assert fetch_and_store(tmp_path, PATH_A, client) is None
        assert load(tmp_path, PATH_A) is None


class TestHousekeeping:
    def test_size_reporting(self, tmp_path):
        assert cache_size_bytes(tmp_path) == 0
        store(tmp_path, PATH_A, PNG)
        store(tmp_path, PATH_B, PNG)
        assert cache_size_bytes(tmp_path) == 2 * len(PNG)

    def test_clear_removes_everything(self, tmp_path):
        store(tmp_path, PATH_A, PNG)
        store(tmp_path, PATH_B, PNG)
        assert clear(tmp_path) == 2
        assert cache_size_bytes(tmp_path) == 0

    def test_clear_on_a_missing_dir_is_harmless(self, tmp_path):
        assert clear(tmp_path) == 0

    def test_clearing_icons_leaves_api_responses_alone(self, tmp_path):
        """They share a cache_dir; only the icons subdirectory may be touched."""
        (tmp_path / "ninja_overview.json").write_text("{}", encoding="utf-8")
        store(tmp_path, PATH_A, PNG)
        clear(tmp_path)
        assert (tmp_path / "ninja_overview.json").exists()
