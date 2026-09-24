from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Mapping, Protocol
from urllib.parse import urljoin, urlsplit

from . import __version__


class UnsafeUrlError(ValueError):
    pass


class NetworkTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    elapsed_ms: int = 0


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        approved_ip: str,
        timeout: float,
        max_body_bytes: int,
        user_agent: str,
    ) -> HttpResponse: ...


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, approved_ip: str, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self.approved_ip = approved_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self.approved_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, approved_ip: str, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.approved_ip = approved_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection((self.approved_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


class StdlibTransport:
    """HTTP transport pinned to an IP that passed the SSRF policy."""

    def request(
        self,
        method: str,
        url: str,
        *,
        approved_ip: str,
        timeout: float,
        max_body_bytes: int,
        user_agent: str,
    ) -> HttpResponse:
        parsed = urlsplit(url)
        default_port = 443 if parsed.scheme == "https" else 80
        port = parsed.port or default_port
        connection_type = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        connection = connection_type(parsed.hostname or "", port, approved_ip, timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host_header = parsed.hostname or ""
        if ":" in host_header:
            host_header = f"[{host_header}]"
        if port != default_port:
            host_header = f"{host_header}:{port}"
        headers = {
            "Host": host_header,
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Connection": "close",
        }
        if method == "GET":
            headers["Range"] = f"bytes=0-{max_body_bytes - 1}"
        started = time.monotonic()
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            if method == "GET":
                response.read(max_body_bytes)
            elapsed = int((time.monotonic() - started) * 1000)
            response_headers = {key.casefold(): value for key, value in response.getheaders()}
            return HttpResponse(response.status, response_headers, elapsed)
        except (TimeoutError, socket.timeout) as exc:
            raise NetworkTimeoutError(str(exc)) from exc
        finally:
            connection.close()


Resolver = Callable[[str, int], list[str]]


def system_resolver(hostname: str, port: int) -> list[str]:
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    }
    return sorted(addresses)


@dataclass
class UrlCheckResult:
    url: str
    status: str
    request_method: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    redirects: list[dict[str, object]] = field(default_factory=list)
    content_type: str | None = None
    elapsed_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    details: dict[str, object] = field(default_factory=dict)


class UrlValidator:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_redirects: int = 5,
        max_body_bytes: int = 65_536,
        user_agent: str = f"poi-evaluator/{__version__}",
        transport: Transport | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_body_bytes = max_body_bytes
        self.user_agent = user_agent
        self.transport = transport or StdlibTransport()
        self.resolver = resolver
        self._resolver_cache: dict[tuple[str, int], list[str]] = {}
        self._resolver_lock = threading.Lock()

    def _approve_url(self, url: str) -> tuple[str, list[str]]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeUrlError("Only http and https URLs are allowed")
        if not parsed.hostname:
            raise UnsafeUrlError("URL has no hostname")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeUrlError("Credentials in URLs are not allowed")
        hostname = parsed.hostname.rstrip(".").casefold()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise UnsafeUrlError("Localhost is blocked")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise UnsafeUrlError("Invalid port") from exc
        cache_key = (hostname, port)
        with self._resolver_lock:
            addresses = self._resolver_cache.get(cache_key)
        if addresses is None:
            try:
                addresses = self.resolver(hostname, port)
            except (OSError, socket.gaierror) as exc:
                raise ConnectionError(f"DNS lookup failed: {exc}") from exc
            with self._resolver_lock:
                self._resolver_cache.setdefault(cache_key, addresses)
        if not addresses:
            raise ConnectionError("DNS lookup returned no addresses")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise UnsafeUrlError("Resolver returned an invalid IP address") from exc
            if not ip.is_global:
                raise UnsafeUrlError(f"Non-public target address is blocked: {ip}")
        return addresses[0], addresses

    @staticmethod
    def _mime_matches(target_type: str, content_type: str | None) -> bool:
        if not content_type:
            return True
        mime = content_type.split(";", 1)[0].strip().casefold()
        if target_type == "image":
            return mime.startswith("image/")
        return mime.startswith("text/") or mime in {
            "application/xhtml+xml",
            "application/json",
            "application/ld+json",
            "application/pdf",
            "application/octet-stream",
        }

    def check(self, url: str, target_type: str = "link") -> UrlCheckResult:
        result = UrlCheckResult(url=url, status="unverified", final_url=url)
        current_url = url
        try:
            for redirect_index in range(self.max_redirects + 1):
                approved_ip, addresses = self._approve_url(current_url)
                result.details.setdefault("resolved_addresses", {})[current_url] = addresses
                method = "HEAD"
                response = self.transport.request(
                    method,
                    current_url,
                    approved_ip=approved_ip,
                    timeout=self.timeout,
                    max_body_bytes=self.max_body_bytes,
                    user_agent=self.user_agent,
                )
                content_type = response.headers.get("content-type")
                if response.status in {400, 403, 405, 501} or not content_type:
                    method = "GET"
                    response = self.transport.request(
                        method,
                        current_url,
                        approved_ip=approved_ip,
                        timeout=self.timeout,
                        max_body_bytes=self.max_body_bytes,
                        user_agent=self.user_agent,
                    )
                    content_type = response.headers.get("content-type")
                result.elapsed_ms += response.elapsed_ms
                result.request_method = method
                result.http_status = response.status
                result.content_type = content_type
                result.final_url = current_url

                if 300 <= response.status < 400:
                    location = response.headers.get("location")
                    if not location:
                        result.status = "unverified"
                        result.error_code = "redirect_without_location"
                        return result
                    if redirect_index >= self.max_redirects:
                        result.status = "unverified"
                        result.error_code = "too_many_redirects"
                        return result
                    next_url = urljoin(current_url, location)
                    # Approve before recording/following so redirects into local
                    # networks can never reach the transport.
                    self._approve_url(next_url)
                    result.redirects.append(
                        {"from": current_url, "to": next_url, "http_status": response.status}
                    )
                    current_url = next_url
                    continue

                if response.status in {404, 410}:
                    result.status = "not_found"
                elif response.status in {401, 403}:
                    result.status = "blocked"
                elif response.status == 429:
                    result.status = "rate_limited"
                elif 200 <= response.status < 300:
                    if not self._mime_matches(target_type, content_type):
                        result.status = "mime_mismatch"
                    else:
                        result.status = "redirected" if result.redirects else "reachable"
                else:
                    result.status = "unverified"
                return result
        except UnsafeUrlError as exc:
            result.status = "invalid_url"
            result.error_code = "ssrf_blocked" if "blocked" in str(exc).casefold() else "invalid_url"
            result.error_message = str(exc)
        except NetworkTimeoutError as exc:
            result.status = "timeout"
            result.error_code = "timeout"
            result.error_message = str(exc)
        except (ConnectionError, OSError, http.client.HTTPException, ssl.SSLError) as exc:
            result.status = "network_error"
            result.error_code = type(exc).__name__
            result.error_message = str(exc)
        return result


def iter_url_targets(connection: sqlite3.Connection) -> Iterable[tuple[str, int, str]]:
    yield from connection.execute("SELECT 'link', id, url FROM links ORDER BY id")
    yield from connection.execute("SELECT 'image', id, image_url FROM images ORDER BY id")
    yield from connection.execute("SELECT 'image_page', id, page_url FROM images WHERE page_url IS NOT NULL ORDER BY id")
    yield from connection.execute("SELECT 'evidence', id, url FROM evidence WHERE url IS NOT NULL ORDER BY id")
    yield from connection.execute("SELECT 'rating', id, source_url FROM ratings WHERE source_url IS NOT NULL ORDER BY id")


def validate_urls(
    connection: sqlite3.Connection,
    run_id: int,
    validator: UrlValidator,
    *,
    limit: int | None = None,
    workers: int = 16,
    per_host: int = 4,
    resume: bool = True,
) -> dict[str, object]:
    counts: dict[str, int] = {}
    workers = max(1, workers)
    per_host = max(1, per_host)
    prior_checks: set[tuple[str, int, str]] = set()
    if resume:
        prior_checks = {
            (row[0], row[1], row[2])
            for row in connection.execute(
                "SELECT target_type, target_id, url FROM url_checks GROUP BY target_type, target_id, url"
            )
        }

    targets: list[tuple[str, int, str]] = []
    skipped = 0
    for target_type, target_id, url in iter_url_targets(connection):
        key = (target_type, target_id, url)
        if key in prior_checks:
            skipped += 1
            continue
        if limit is not None and len(targets) >= limit:
            break
        targets.append(key)

    groups: dict[tuple[str, str], list[tuple[str, int, str]]] = {}
    for target in targets:
        target_type, _, url = target
        check_type = "image" if target_type == "image" else "link"
        groups.setdefault((url, check_type), []).append(target)
    grouped_targets = list(groups.items())

    cached_results: dict[tuple[str, str], tuple[int, UrlCheckResult]] = {}
    cache_rows = connection.execute(
        """
        SELECT u.*
        FROM url_checks u
        JOIN (
            SELECT url,
                   CASE WHEN target_type='image' THEN 'image' ELSE 'link' END AS check_type,
                   MAX(id) AS max_id
            FROM url_checks
            GROUP BY url, CASE WHEN target_type='image' THEN 'image' ELSE 'link' END
        ) latest ON latest.max_id=u.id
        """
    ).fetchall()
    for row in cache_rows:
        check_type = "image" if row["target_type"] == "image" else "link"
        cached_results[(row["url"], check_type)] = (
            row["id"],
            UrlCheckResult(
                url=row["url"],
                status=row["status"],
                request_method=row["request_method"],
                http_status=row["http_status"],
                final_url=row["final_url"],
                redirects=json.loads(row["redirect_chain_json"]),
                content_type=row["content_type"],
                elapsed_ms=row["elapsed_ms"] or 0,
                error_code=row["error_code"],
                error_message=row["error_message"],
                details=json.loads(row["details_json"]),
            ),
        )
    reused_groups = [item for item in grouped_targets if item[0] in cached_results]
    network_groups = [item for item in grouped_targets if item[0] not in cached_results]

    host_limits: dict[str, threading.Semaphore] = {}
    for (url, _), _targets in network_groups:
        hostname = (urlsplit(url).hostname or "<invalid>").casefold()
        host_limits.setdefault(hostname, threading.Semaphore(per_host))

    def check_group(item: tuple[tuple[str, str], list[tuple[str, int, str]]]):
        (url, check_type), _targets = item
        hostname = (urlsplit(url).hostname or "<invalid>").casefold()
        with host_limits[hostname]:
            return validator.check(url, check_type)

    checked = 0

    def persist_group(
        group: tuple[tuple[str, str], list[tuple[str, int, str]]],
        result: UrlCheckResult,
    ) -> None:
        nonlocal checked
        _, group_targets = group
        for target_type, target_id, url in group_targets:
            cursor = connection.execute(
                """
                INSERT INTO url_checks(
                    evaluation_run_id, target_type, target_id, url, validator_version,
                    status, request_method, http_status, final_url, redirect_chain_json,
                    content_type, elapsed_ms, error_code, error_message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    target_type,
                    target_id,
                    url,
                    __version__,
                    result.status,
                    result.request_method,
                    result.http_status,
                    result.final_url,
                    json.dumps(result.redirects, ensure_ascii=False),
                    result.content_type,
                    result.elapsed_ms,
                    result.error_code,
                    result.error_message,
                    json.dumps(result.details, ensure_ascii=False, sort_keys=True),
                ),
            )
            check_id = int(cursor.lastrowid)
            counts[result.status] = counts.get(result.status, 0) + 1
            checked += 1
            if result.status not in {"reachable", "redirected"}:
                priority = 75 if result.status in {"not_found", "mime_mismatch", "invalid_url"} else 55
                connection.execute(
                    "INSERT OR IGNORE INTO review_queue(evaluation_run_id, item_type, entity_type, entity_id, priority, reason_code, payload_json) VALUES (?, 'url_check', 'url_check', ?, ?, ?, ?)",
                    (
                        run_id,
                        check_id,
                        priority,
                        result.status,
                        json.dumps(
                            {"target_type": target_type, "target_id": target_id, "url": url, "error": result.error_message},
                            ensure_ascii=False,
                        ),
                    ),
                )

    for cache_index, group in enumerate(reused_groups, start=1):
        source_check_id, cached = cached_results[group[0]]
        reused = replace(
            cached,
            details={**cached.details, "reused_from_check_id": source_check_id},
        )
        persist_group(group, reused)
        if cache_index % 500 == 0:
            connection.commit()

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="poi-url") as executor:
        future_groups = {
            executor.submit(check_group, group): group for group in network_groups
        }
        for group_index, future in enumerate(as_completed(future_groups), start=1):
            group = future_groups[future]
            result = future.result()
            persist_group(group, result)
            if group_index % 100 == 0:
                connection.commit()
                print(
                    f"validated {group_index}/{len(network_groups)} unique URL checks "
                    f"({checked}/{len(targets)} targets)",
                    file=sys.stderr,
                    flush=True,
                )
    connection.commit()
    return {
        "checked": checked,
        "unique_requests": len(network_groups),
        "reused_results": len(reused_groups),
        "skipped_existing": skipped,
        "by_status": counts,
    }
