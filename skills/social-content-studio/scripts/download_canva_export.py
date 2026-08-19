#!/usr/bin/env python3
"""Safely download a Canva export and return a local-file receipt.

The downloader intentionally accepts no credentials or caller-supplied headers.
Canva export URLs are signed, short-lived tool results; they are used only for
the request and are never included in receipts or error output. Production
requests are restricted to Canva hosts and the CLI accepts the URL only through
bounded stdin.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_REDIRECTS = 3
MAX_STDIN_URL_LENGTH = 16 * 1024
HARD_MAX_BYTES = 250 * 1024 * 1024
HARD_MAX_TIMEOUT_SECONDS = 120.0
CHUNK_SIZE = 64 * 1024
DEFAULT_ALLOWED_HOST_SUFFIXES = ("canva.com",)
_HOSTNAME_RE = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)
_EXTENSION_RE = re.compile(r"^\.[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)


class DownloadError(RuntimeError):
    """A safe, URL-free failure suitable for user-facing output."""


Resolver = Callable[[str, int], Sequence[Any]]


class _NoRedirectHandler(HTTPRedirectHandler):
    """Return redirect responses so the caller can validate every hop."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None

    def http_error_301(self, req: Request, fp: Any, code: int, msg: str, headers: Any) -> Any:
        return fp

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def _default_resolver(host: str, port: int) -> Sequence[Any]:
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _invalid_endpoint(message: str = "The export endpoint is not allowed.") -> DownloadError:
    # Keep this helper centralized so no exception accidentally includes a URL,
    # query string, or resolver detail.
    return DownloadError(message)


def _validate_limits(max_bytes: int, timeout_seconds: float, max_redirects: int) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= HARD_MAX_BYTES:
        raise DownloadError("The maximum download size is invalid.")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise DownloadError("The download timeout is invalid.")
    if not 0 < float(timeout_seconds) <= HARD_MAX_TIMEOUT_SECONDS:
        raise DownloadError("The download timeout is outside the allowed bound.")
    if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or not 0 <= max_redirects <= 10:
        raise DownloadError("The redirect limit is invalid.")


def _normalize_extension(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DownloadError("The expected extension is invalid.")
    extension = value if value.startswith(".") else f".{value}"
    if not _EXTENSION_RE.fullmatch(extension):
        raise DownloadError("The expected extension is invalid.")
    return extension.casefold()


def _normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DownloadError("The expected media type is invalid.")
    media_type = value.split(";", 1)[0].strip().casefold()
    if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+*-]+", media_type):
        raise DownloadError("The expected media type is invalid.")
    return media_type


def _media_type_matches(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    if actual is None:
        return False
    if expected.endswith("/*"):
        return actual.startswith(expected[:-1])
    return actual == expected


def _extract_address(record: Any) -> str | None:
    if isinstance(record, str):
        return record
    if isinstance(record, tuple) and len(record) >= 5:
        sockaddr = record[4]
        if isinstance(sockaddr, tuple) and sockaddr:
            return str(sockaddr[0])
    return None


def _is_forbidden_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return True
    return not address.is_global or any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _normalize_allowed_host_suffixes(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or not values:
        raise DownloadError("The allowed export host policy is invalid.")
    suffixes: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise DownloadError("The allowed export host policy is invalid.")
        suffix = value.rstrip(".").casefold()
        if not suffix or not _HOSTNAME_RE.fullmatch(suffix):
            raise DownloadError("The allowed export host policy is invalid.")
        suffixes.append(suffix)
    return tuple(dict.fromkeys(suffixes))


def _validate_endpoint(
    url: str,
    resolver: Resolver,
    allowed_host_suffixes: Sequence[str] = DEFAULT_ALLOWED_HOST_SUFFIXES,
) -> tuple[str, int, str]:
    if not isinstance(url, str) or not url or any(char.isspace() or ord(char) < 0x20 for char in url):
        raise _invalid_endpoint()
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise _invalid_endpoint() from exc
    if parsed.scheme.casefold() != "https" or not host or parsed.username or parsed.password or parsed.fragment:
        raise _invalid_endpoint()
    host = host.rstrip(".").casefold()
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise _invalid_endpoint()
    if host.startswith(".") or ".." in host:
        raise _invalid_endpoint()
    suffixes = _normalize_allowed_host_suffixes(allowed_host_suffixes)
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
        raise _invalid_endpoint()
    if not _HOSTNAME_RE.fullmatch(host):
        # A literal IPv6 address is valid even though it contains colons; it is
        # handled by ipaddress below. Other unusual host syntax is rejected.
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise _invalid_endpoint() from exc
    if port is None:
        port = 443
    if not 1 <= port <= 65535:
        raise _invalid_endpoint()

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_forbidden_ip(str(literal)):
            raise _invalid_endpoint()
        return host, port, parsed.geturl()

    try:
        records = resolver(host, port)
    except (OSError, ValueError):
        raise _invalid_endpoint("The export endpoint could not be resolved.")
    addresses = [_extract_address(record) for record in records]
    addresses = [address for address in addresses if address]
    if not addresses or any(_is_forbidden_ip(address) for address in addresses):
        raise _invalid_endpoint()
    return host, port, parsed.geturl()


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            value = headers.get(name)
        except (AttributeError, TypeError):
            value = None
        if value is not None:
            return str(value)
    getheader = getattr(response, "getheader", None)
    if callable(getheader):
        value = getheader(name)
        return None if value is None else str(value)
    return None


def _status(response: Any) -> int:
    value = getattr(response, "status", None)
    if value is None:
        getcode = getattr(response, "getcode", None)
        value = getcode() if callable(getcode) else None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DownloadError("The export response did not provide a valid status.")
    return value


def _remaining(deadline: float, clock: Callable[[], float]) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise DownloadError("The export download exceeded its time limit.")
    return remaining


def _read_to_temp(response: Any, temp_path: str, max_bytes: int, deadline: float, clock: Callable[[], float]) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        with open(temp_path, "wb") as handle:
            while True:
                _remaining(deadline, clock)
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise DownloadError("The export response was not binary data.")
                total += len(chunk)
                if total > max_bytes:
                    raise DownloadError("The export exceeds the configured size limit.")
                binary = bytes(chunk)
                handle.write(binary)
                digest.update(binary)
            handle.flush()
            os.fsync(handle.fileno())
    except DownloadError:
        raise
    except (OSError, TimeoutError, URLError) as exc:
        raise DownloadError("The export could not be written locally.") from exc
    if total == 0:
        raise DownloadError("The export response was empty.")
    return total, digest.hexdigest()


def download_canva_export(
    url: str,
    output_path: str | os.PathLike[str],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    expected_media_type: str | None = None,
    expected_extension: str | None = None,
    opener: Any | None = None,
    resolver: Resolver | None = None,
    allowed_host_suffixes: Sequence[str] = DEFAULT_ALLOWED_HOST_SUFFIXES,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Download one HTTPS export and return a URL-free structured receipt.

    ``opener`` and ``resolver`` are injectable for deterministic tests. The
    production defaults always validate DNS results and disable environment
    proxies; callers cannot supply credentials or request headers.
    """

    _validate_limits(max_bytes, timeout_seconds, max_redirects)
    media_type = _normalize_media_type(expected_media_type)
    extension = _normalize_extension(expected_extension)
    # Make the receipt path absolute without resolving the final component:
    # ``os.replace`` must replace an existing symlink itself, never follow it
    # into an unrelated target selected by an attacker.
    try:
        destination = Path(os.path.abspath(os.path.expanduser(os.fspath(output_path))))
    except (TypeError, ValueError) as exc:
        raise DownloadError("The output path is invalid.") from exc
    if destination.name in {"", ".", ".."}:
        raise DownloadError("The output path is invalid.")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadError("The output directory could not be created.") from exc

    resolve = resolver or _default_resolver
    current_url = url
    redirect_count = 0
    deadline = clock() + float(timeout_seconds)
    # Never route a signed export through ambient HTTP(S)_PROXY settings: the
    # endpoint policy is evaluated for the destination on every hop.
    request_opener = opener or build_opener(ProxyHandler({}), _NoRedirectHandler())
    temp_path: str | None = None
    try:
        while True:
            _, port, current_url = _validate_endpoint(current_url, resolve, allowed_host_suffixes)
            request = Request(current_url, method="GET")
            try:
                response = request_opener.open(request, timeout=min(float(timeout_seconds), _remaining(deadline, clock)))
            except (HTTPError, URLError, OSError, TimeoutError) as exc:
                raise DownloadError("The export request failed.") from exc
            try:
                response_status = _status(response)
                if 300 <= response_status < 400:
                    location = _header(response, "Location")
                    if redirect_count >= max_redirects or not location:
                        raise DownloadError("The export redirect policy was violated.")
                    next_url = urljoin(current_url, location)
                    # Validate before following. The next loop validates again
                    # immediately before its request, covering every hop.
                    _validate_endpoint(next_url, resolve, allowed_host_suffixes)
                    current_url = next_url
                    redirect_count += 1
                    continue
                if not 200 <= response_status < 300:
                    raise DownloadError("The export response was not successful.")

                content_length: int | None = None
                raw_length = _header(response, "Content-Length")
                if raw_length is not None:
                    try:
                        content_length = int(raw_length)
                    except ValueError as exc:
                        raise DownloadError("The export response size was invalid.") from exc
                    if content_length < 0 or content_length > max_bytes:
                        raise DownloadError("The export exceeds the configured size limit.")
                actual_media_type = _header(response, "Content-Type")
                if actual_media_type is not None:
                    actual_media_type = actual_media_type.split(";", 1)[0].strip().casefold() or None
                if not _media_type_matches(actual_media_type, media_type):
                    raise DownloadError("The export media type did not match the expected type.")

                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", prefix=f".{destination.name}.", suffix=".part", dir=destination.parent, delete=False
                    ) as temporary:
                        temp_path = temporary.name
                except OSError as exc:
                    raise DownloadError("The local temporary file could not be created.") from exc

                size_bytes, digest = _read_to_temp(response, temp_path, max_bytes, deadline, clock)
                if content_length is not None and size_bytes != content_length:
                    raise DownloadError("The export response size did not match its declared length.")
                if extension is not None and destination.suffix.casefold() != extension:
                    raise DownloadError("The output extension did not match the expected extension.")
                try:
                    os.replace(temp_path, destination)
                    temp_path = None
                except OSError as exc:
                    raise DownloadError("The downloaded export could not be committed atomically.") from exc
                if not destination.is_file() or destination.stat().st_size == 0:
                    raise DownloadError("The local export file was not created correctly.")
                return {
                    "receipt_version": "1.0",
                    "status": "downloaded",
                    "output_path": str(destination),
                    "size_bytes": size_bytes,
                    "sha256": digest,
                    "export_checksum": f"sha256:{digest}",
                    "content_type": actual_media_type,
                    "extension": destination.suffix.casefold() or None,
                    "redirect_count": redirect_count,
                }
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Local output file")
    parser.add_argument(
        "--url-stdin",
        action="store_true",
        required=True,
        help="Read the signed HTTPS export URL from stdin (preferred; never echo or persist it).",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-redirects", type=int, default=DEFAULT_MAX_REDIRECTS)
    parser.add_argument("--expected-media-type")
    parser.add_argument("--expected-extension")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw_url = sys.stdin.read(MAX_STDIN_URL_LENGTH + 1)
        if len(raw_url) > MAX_STDIN_URL_LENGTH:
            raise DownloadError("The stdin export URL exceeds the maximum length.")
        url = raw_url.strip()
        if not url:
            raise DownloadError("stdin did not contain an export URL.")
        receipt = download_canva_export(
            url,
            args.output,
            max_bytes=args.max_bytes,
            timeout_seconds=args.timeout_seconds,
            max_redirects=args.max_redirects,
            expected_media_type=args.expected_media_type,
            expected_extension=args.expected_extension,
        )
    except DownloadError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
