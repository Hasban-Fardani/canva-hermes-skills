#!/usr/bin/env python3
"""Deterministic tests for download_canva_export.py; no network is used."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from urllib.request import Request
from unittest import mock

from download_canva_export import MAX_STDIN_URL_LENGTH, DownloadError, download_canva_export, main


PUBLIC_IP = "93.184.216.34"


def make_url(path: str, *, host: str = "exports.canva.com", scheme: str = "https", userinfo: str | None = None, query: str | None = None) -> str:
    authority = f"{userinfo}@" if userinfo else ""
    suffix = f"?{query}" if query else ""
    return f"{scheme}:{'//' }{authority}{host}/{path.lstrip('/')}{suffix}"


def public_resolver(host: str, port: int):
    return [PUBLIC_IP]


class FakeResponse:
    def __init__(self, body: bytes = b"", *, status: int = 200, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None):
        self.status = status
        self.headers = headers or {}
        self._stream = iter(chunks if chunks is not None else [body])
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return next(self._stream, b"")

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        return self.responses[request.full_url]


class DownloadTests(unittest.TestCase):
    def test_receipt_is_structured_and_contains_no_signed_url(self) -> None:
        body = b"deterministic export"
        opener = FakeOpener(
            {
                make_url("file", query="temporary=placeholder"): FakeResponse(
                    body, headers={"Content-Type": "image/png", "Content-Length": str(len(body))}
                )
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export.png"
            receipt = download_canva_export(
                make_url("file", query="temporary=placeholder"),
                output,
                expected_media_type="image/png",
                expected_extension="png",
                opener=opener,
                resolver=public_resolver,
            )
            self.assertEqual(body, output.read_bytes())
            self.assertEqual(hashlib.sha256(body).hexdigest(), receipt["sha256"])
            self.assertEqual("sha256:" + receipt["sha256"], receipt["export_checksum"])
            self.assertEqual("downloaded", receipt["status"])
            self.assertEqual(len(body), receipt["size_bytes"])
            self.assertNotIn("signature", json.dumps(receipt))
            self.assertEqual(["GET"], [request.method for request in opener.requests])

    def test_rejects_insecure_local_and_private_endpoints_before_open(self) -> None:
        opener = FakeOpener({})
        cases = (
            make_url("file", scheme="http"),
            make_url("file", host="localhost"),
            make_url("file", host="127.0.0.1"),
            make_url("file", host="[::1]"),
            make_url("file", userinfo="user:placeholder"),
        )
        for url in cases:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(DownloadError):
                    download_canva_export(url, Path(directory) / "out.bin", opener=opener, resolver=public_resolver)
        self.assertEqual([], opener.requests)

    def test_rejects_private_dns_result(self) -> None:
        opener = FakeOpener({})

        def private_resolver(host: str, port: int):
            return [(socket_family, socket_type, 6, "", ("10.0.0.8", port)) for socket_family, socket_type in [(2, 1)]]

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DownloadError):
                download_canva_export(make_url("file"), Path(directory) / "out.bin", opener=opener, resolver=private_resolver)
        self.assertEqual([], opener.requests)

    def test_rejects_private_redirect_hop(self) -> None:
        first = make_url("start")
        opener = FakeOpener({first: FakeResponse(status=302, headers={"Location": make_url("private", host="127.0.0.1")})})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DownloadError):
                download_canva_export(first, Path(directory) / "out.bin", opener=opener, resolver=public_resolver)
        self.assertEqual([first], [request.full_url for request in opener.requests])

    def test_rejects_unexpected_public_non_canva_redirect_hop(self) -> None:
        first = make_url("start")
        unexpected = make_url("file", host="downloads.example.test")
        opener = FakeOpener({first: FakeResponse(status=302, headers={"Location": unexpected})})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DownloadError):
                download_canva_export(first, Path(directory) / "out.bin", opener=opener, resolver=public_resolver)
        self.assertEqual([first], [request.full_url for request in opener.requests])

    def test_bounds_content_length_and_streaming_size_without_replacing_target(self) -> None:
        url = make_url("large")
        existing = b"keep old output"
        opener = FakeOpener({url: FakeResponse(b"abcdefghij", headers={"Content-Length": "10"})})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export.bin"
            output.write_bytes(existing)
            with self.assertRaises(DownloadError):
                download_canva_export(url, output, max_bytes=5, opener=opener, resolver=public_resolver)
            self.assertEqual(existing, output.read_bytes())
            self.assertEqual([], list(Path(directory).glob("*.part")))

        stream_url = make_url("chunked")
        stream_opener = FakeOpener({stream_url: FakeResponse(chunks=[b"1234", b"5678"])})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export.bin"
            with self.assertRaises(DownloadError):
                download_canva_export(stream_url, output, max_bytes=5, opener=stream_opener, resolver=public_resolver)
            self.assertFalse(output.exists())
            self.assertEqual([], list(Path(directory).glob("*.part")))

    def test_media_type_extension_and_empty_response_are_atomic(self) -> None:
        cases = (
            (make_url("type"), FakeResponse(b"x", headers={"Content-Type": "text/plain"}), {"expected_media_type": "image/png"}),
            (make_url("ext"), FakeResponse(b"x", headers={"Content-Type": "image/png"}), {"expected_extension": "png"}),
            (make_url("empty"), FakeResponse(b""), {}),
        )
        with tempfile.TemporaryDirectory() as directory:
            for url, response, options in cases:
                with self.subTest(url=url):
                    opener = FakeOpener({url: response})
                    output = Path(directory) / ("wrong.bin" if "ext" in url else "output.png")
                    old = b"old" if output.exists() else None
                    if old is not None:
                        output.write_bytes(old)
                    with self.assertRaises(DownloadError):
                        download_canva_export(url, output, opener=opener, resolver=public_resolver, **options)
                    if old is not None:
                        self.assertEqual(old, output.read_bytes())
                    self.assertEqual([], list(Path(directory).glob("*.part")))

    def test_atomic_commit_replaces_output_symlink_without_following_target(self) -> None:
        url = make_url("symlink")
        body = b"new export"
        opener = FakeOpener({url: FakeResponse(body)})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "unrelated.bin"
            target.write_bytes(b"do not replace")
            output = Path(directory) / "export.bin"
            output.symlink_to(target)
            download_canva_export(url, output, opener=opener, resolver=public_resolver)
            self.assertEqual(body, output.read_bytes())
            self.assertFalse(output.is_symlink())
            self.assertEqual(b"do not replace", target.read_bytes())

    def test_redirects_are_bounded_and_validated(self) -> None:
        start = make_url("1")
        second = make_url("2")
        opener = FakeOpener(
            {
                start: FakeResponse(status=302, headers={"Location": second}),
                second: FakeResponse(status=302, headers={"Location": start}),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DownloadError):
                download_canva_export(start, Path(directory) / "out.bin", max_redirects=1, opener=opener, resolver=public_resolver)
        self.assertEqual([start, second], [request.full_url for request in opener.requests])

    def test_total_timeout_is_bounded_and_cleans_temporary_file(self) -> None:
        url = make_url("slow")
        opener = FakeOpener({url: FakeResponse(b"body")})
        ticks = iter([0.0, 0.0, 2.0])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.bin"
            with self.assertRaises(DownloadError):
                download_canva_export(
                    url,
                    output,
                    timeout_seconds=1,
                    opener=opener,
                    resolver=public_resolver,
                    clock=lambda: next(ticks),
                )
            self.assertFalse(output.exists())
            self.assertEqual([], list(Path(directory).glob("*.part")))

    def test_stdin_url_mode_does_not_echo_signed_url_or_query(self) -> None:
        signed_url = make_url("export", host="127.0.0.1", query="temporary=placeholder")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.bin"
            stderr = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(signed_url)), redirect_stderr(stderr):
                result = main(["--url-stdin", str(output)])
            self.assertEqual(1, result)
            self.assertNotIn(signed_url, stderr.getvalue())
            self.assertNotIn("signature", stderr.getvalue())

    def test_oversized_stdin_url_is_rejected_without_echo(self) -> None:
        oversized = make_url("".join(("a",) * MAX_STDIN_URL_LENGTH))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.bin"
            stderr = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(oversized)), redirect_stderr(stderr):
                result = main(["--url-stdin", str(output)])
            self.assertEqual(1, result)
            self.assertIn("maximum length", stderr.getvalue())
            self.assertNotIn(oversized, stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
