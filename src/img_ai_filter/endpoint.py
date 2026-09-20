"""Validated, immutable local-area-network endpoint configuration.

This module holds the immutable endpoint contract for the LAN vision fallback.
It stays independent of the GUI and of any HTTP client so unit tests can
exercise the full contract without heavy dependencies, and it must never be
the place where credentials are stored.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit


class EndpointValidationError(ValueError):
    """Raised when an endpoint URL or model name is not a safe LAN target."""


_ALLOWED_PRIVATE_IPV4 = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
_CARRIER_GRADE_NAT_IPV4 = ipaddress.IPv4Network("100.64.0.0/10")
_LINK_LOCAL_IPV4 = ipaddress.IPv4Network("169.254.0.0/16")
_LOOPBACK_IPV4 = ipaddress.IPv4Network("127.0.0.0/8")

_LINK_LOCAL_IPV6 = ipaddress.IPv6Network("fe80::/10")
_UNIQUE_LOCAL_IPV6 = ipaddress.IPv6Network("fc00::/7")
_LOOPBACK_IPV6 = ipaddress.IPv6Address("::1")


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    """Immutable, validated endpoint for the LAN vision fallback."""

    url: str
    scheme: str
    hostname: str
    port: int
    path: str
    model: str

    @property
    def origin(self) -> str:
        """Scheme, display host, and port without the request path."""
        display_host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        return f"{self.scheme}://{display_host}:{self.port}"


@dataclass(frozen=True, slots=True)
class VisionEndpointConfig:
    """Immutable KoboldCpp API base and its derived request URLs."""

    base_url: str
    origin: str
    model: str | None

    @property
    def chat_completions_url(self) -> str:
        return self.base_url + "chat/completions"

    @property
    def models_url(self) -> str:
        return self.base_url + "models"

    @property
    def capabilities_url(self) -> str:
        return self.origin + "/api/extra/version"


def _default_resolver(hostname: str) -> tuple[str, ...]:
    results = socket.getaddrinfo(hostname, None)
    return tuple(info[4][0] for info in results)


def _is_loopback(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        isinstance(addr, ipaddress.IPv4Address) and addr in _LOOPBACK_IPV4
    ) or addr == _LOOPBACK_IPV6


def _is_allowed_destination(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if _is_loopback(addr):
        return True
    if isinstance(addr, ipaddress.IPv4Address):
        return (
            any(addr in network for network in _ALLOWED_PRIVATE_IPV4)
            or addr in _CARRIER_GRADE_NAT_IPV4
            or addr in _LINK_LOCAL_IPV4
        )
    return addr in _LINK_LOCAL_IPV6 or addr in _UNIQUE_LOCAL_IPV6


def build_endpoint_config(
    url: str,
    model: str,
    *,
    resolver: Callable[[str], Sequence[str]] | None = None,
) -> EndpointConfig:
    """Build an immutable endpoint config or raise EndpointValidationError."""
    stripped_url = url.strip()
    stripped_model = model.strip()
    if not stripped_url:
        raise EndpointValidationError("The URL must not be empty")
    if not stripped_model:
        raise EndpointValidationError("The model name must not be empty")

    try:
        parsed = urlsplit(stripped_url)
        port = parsed.port
    except ValueError:
        raise EndpointValidationError("The URL is not a valid endpoint") from None

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise EndpointValidationError("Only http and https endpoints are supported")

    hostname = parsed.hostname
    if hostname is None or hostname == "":
        raise EndpointValidationError("The URL must include a hostname")

    if parsed.fragment:
        raise EndpointValidationError("The URL must not include a fragment")

    if parsed.username is not None or parsed.password is not None:
        raise EndpointValidationError("The URL must not embed user information")

    if port is None:
        port = 80 if scheme == "http" else 443
    if port < 1 or port > 65535:
        raise EndpointValidationError("The port must be from 1 through 65535")

    path = parsed.path
    if parsed.query:
        path = path + "?" + parsed.query

    if hostname.casefold() == "localhost":
        resolve = resolver if resolver is not None else _default_resolver
        try:
            resolved = resolve(hostname)
        except OSError:
            raise EndpointValidationError(
                "The hostname could not be resolved"
            ) from None
        if not resolved:
            raise EndpointValidationError(
                "The hostname resolved to no addresses"
            )
        for address in resolved:
            try:
                resolved_address = ipaddress.ip_address(address)
            except ValueError:
                raise EndpointValidationError(
                    "The hostname resolved to a non-IP address"
                ) from None
            if not _is_loopback(resolved_address):
                raise EndpointValidationError(
                    "The hostname must resolve to loopback addresses only"
                )
        stored_hostname = "localhost"
    else:
        try:
            parsed_host = ipaddress.ip_address(hostname)
        except Exception:
            raise EndpointValidationError(
                "The destination must be localhost or a private-network IP address"
            ) from None
        if (
            isinstance(parsed_host, ipaddress.IPv6Address)
            and parsed_host.ipv4_mapped is not None
        ):
            parsed_host = parsed_host.ipv4_mapped
        if not _is_allowed_destination(parsed_host):
            raise EndpointValidationError(
                "The destination must be localhost or a private-network IP address"
            )
        stored_hostname = hostname

    return EndpointConfig(
        url=stripped_url,
        scheme=scheme,
        hostname=stored_hostname,
        port=port,
        path=path,
        model=stripped_model,
    )


def build_vision_endpoint_config(
    base_url: str,
    model: str | None = None,
    *,
    resolver: Callable[[str], Sequence[str]] | None = None,
) -> VisionEndpointConfig:
    """Validate and normalize a KoboldCpp ``/v1/`` API base URL."""
    stripped_url = base_url.strip()
    if "?" in stripped_url or "#" in stripped_url:
        raise EndpointValidationError(
            "The base URL must not include a query or fragment"
        )

    validated = build_endpoint_config(
        stripped_url,
        model if model is not None else "unused",
        resolver=resolver,
    )
    if validated.path not in {"/v1", "/v1/"}:
        raise EndpointValidationError("The base URL path must be /v1 or /v1/")

    normalized_model = None if model is None else model.strip()
    return VisionEndpointConfig(
        base_url=validated.origin + "/v1/",
        origin=validated.origin,
        model=normalized_model,
    )
