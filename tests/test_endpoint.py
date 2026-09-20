"""Endpoint-configuration tests for the LAN vision fallback.

These tests pin the immutable EndpointConfig contract and the private-network
validation rules from feature.md. The module must stay independent of the GUI
and of any HTTP client, and no test may contact a real network service.
"""

from __future__ import annotations

import inspect

import pytest

import img_ai_filter.endpoint as endpoint
from img_ai_filter.endpoint import (
    EndpointValidationError,
    build_endpoint_config,
    build_vision_endpoint_config,
)


def _loopback_resolver(_hostname: str) -> tuple[str, ...]:
    return ("127.0.0.1",)


def _build(url: str, model: str = "vision-model", **kwargs) -> endpoint.EndpointConfig:
    return build_endpoint_config(url, model, **kwargs)


def _vision_base(url: str, model: str | None = None, **kwargs):
    return build_vision_endpoint_config(url, model=model, **kwargs)


def test_builds_canonical_koboldcpp_urls_from_approved_default() -> None:
    config = _vision_base("http://192.168.0.239:5001/v1/")

    assert config.base_url == "http://192.168.0.239:5001/v1/"
    assert config.origin == "http://192.168.0.239:5001"
    assert config.chat_completions_url == (
        "http://192.168.0.239:5001/v1/chat/completions"
    )
    assert config.models_url == "http://192.168.0.239:5001/v1/models"
    assert config.capabilities_url == "http://192.168.0.239:5001/api/extra/version"
    assert config.model is None


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.0.239:5001/v1",
        "http://192.168.0.239:5001/v1/",
        "  http://192.168.0.239:5001/v1/  ",
    ],
)
def test_normalizes_equivalent_koboldcpp_base_urls(url: str) -> None:
    assert _vision_base(url).base_url == "http://192.168.0.239:5001/v1/"


def test_koboldcpp_base_accepts_optional_discovered_model() -> None:
    config = _vision_base(
        "http://localhost:5001/v1/",
        model="  koboldcpp/vision-model  ",
        resolver=_loopback_resolver,
    )

    assert config.model == "koboldcpp/vision-model"


@pytest.mark.parametrize("model", ["", "   ", "\n\t"])
def test_koboldcpp_base_rejects_blank_provided_model(model: str) -> None:
    with pytest.raises(EndpointValidationError, match="model"):
        _vision_base("http://192.168.0.239:5001/v1/", model=model)


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.0.239:5001",
        "http://192.168.0.239:5001/",
        "http://192.168.0.239:5001/v1/chat/completions",
        "http://192.168.0.239:5001/api/extra/version",
        "http://192.168.0.239:5001/custom/v1/",
        "http://192.168.0.239:5001/v1/?token=secret",
        "http://192.168.0.239:5001/v1/#fragment",
    ],
)
def test_koboldcpp_base_rejects_non_base_paths_queries_and_fragments(
    url: str,
) -> None:
    with pytest.raises(EndpointValidationError):
        _vision_base(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://8.8.8.8:5001/v1/",
        "http://example.com:5001/v1/",
        "ftp://192.168.0.239:5001/v1/",
        "http://user:pass@192.168.0.239:5001/v1/",
        "http://192.168.0.239:0/v1/",
    ],
)
def test_koboldcpp_base_preserves_existing_destination_safety(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _vision_base(url)


# ---------------------------------------------------------------------------
# Acceptance: loopback and private-origin destinations
# ---------------------------------------------------------------------------


def test_accepts_http_chat_completions_url_on_localhost() -> None:
    config = _build(
        "http://localhost:8000/v1/chat/completions",
        resolver=_loopback_resolver,
    )

    assert config.url == "http://localhost:8000/v1/chat/completions"
    assert config.scheme == "http"
    assert config.hostname == "localhost"
    assert config.port == 8000
    assert config.path == "/v1/chat/completions"
    assert config.model == "vision-model"
    assert config.origin == "http://localhost:8000"


def test_accepts_localhost_resolving_to_multiple_loopback_addresses() -> None:
    def resolver(_hostname: str) -> tuple[str, ...]:
        return ("127.0.0.1", "::1")

    config = _build("http://localhost:9000/v1/chat/completions", resolver=resolver)

    assert config.hostname == "localhost"


def test_accepts_uppercase_localhost_hostname() -> None:
    config = _build("http://LOCALHOST:8000/x", resolver=_loopback_resolver)

    assert config.hostname == "localhost"


def test_accepts_ipv4_loopback_literal() -> None:
    config = _build("http://127.0.0.1:9000/v1/chat/completions")

    assert config.hostname == "127.0.0.1"
    assert config.port == 9000
    assert config.origin == "http://127.0.0.1:9000"


def test_accepts_ipv6_loopback_literal() -> None:
    config = _build("http://[::1]:8000/v1/chat/completions")

    assert config.hostname == "::1"
    assert config.port == 8000
    assert config.origin == "http://[::1]:8000"


@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "10.255.255.254", "172.16.0.1", "172.31.255.254", "192.168.0.1"],
)
def test_accepts_private_ipv4_ranges(address: str) -> None:
    config = _build(f"http://{address}:8443/v1/chat/completions")

    assert config.hostname == address
    assert config.origin == f"http://{address}:8443"


@pytest.mark.parametrize("address", ["100.64.0.1", "100.127.255.254"])
def test_accepts_carrier_grade_nat_ranges(address: str) -> None:
    config = _build(f"http://{address}:8080/chat")

    assert config.hostname == address


def test_accepts_ipv4_link_local() -> None:
    config = _build("http://169.254.10.20:8080/chat")

    assert config.hostname == "169.254.10.20"


@pytest.mark.parametrize("address", ["fd00::1", "fc00::", "fd12:3456:789a::1"])
def test_accepts_unique_local_ipv6(address: str) -> None:
    config = _build(f"http://[{address}]:8080/v1/chat/completions")

    assert config.hostname == address
    assert config.origin == f"http://[{address}]:8080"


def test_accepts_ipv6_link_local() -> None:
    config = _build("http://[fe80::1]:8080/chat")

    assert config.hostname == "fe80::1"


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_accepts_http_and_https_on_private_origins(scheme: str) -> None:
    config = _build(f"{scheme}://192.168.1.10:8443/v1/chat/completions")

    assert config.scheme == scheme
    assert config.origin == f"{scheme}://192.168.1.10:8443"


def test_accepts_ipv4_mapped_ipv6_loopback() -> None:
    config = _build("http://[::ffff:127.0.0.1]:8000/chat")

    assert config.hostname == "::ffff:127.0.0.1"


# ---------------------------------------------------------------------------
# Acceptance: normalization and preservation
# ---------------------------------------------------------------------------


def test_preserves_explicit_non_default_port_and_path() -> None:
    config = _build("http://127.0.0.1:8081/a/v1/chat/completions")

    assert config.port == 8081
    assert config.path == "/a/v1/chat/completions"


def test_trims_leading_and_trailing_whitespace() -> None:
    config = _build(
        "   http://127.0.0.1:8000/v1/chat/completions   ",
        model="  vision-model  ",
    )

    assert config.url == "http://127.0.0.1:8000/v1/chat/completions"
    assert config.model == "vision-model"


def test_applies_default_port_when_omitted() -> None:
    assert _build("http://127.0.0.1/x").port == 80
    assert _build("https://127.0.0.1/x").port == 443


def test_pathless_url_has_empty_path() -> None:
    assert _build("http://127.0.0.1:8080").path == ""


# ---------------------------------------------------------------------------
# Rejection: invalid endpoint values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["", "   \n\t  "])
def test_rejects_empty_or_whitespace_url(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url)


@pytest.mark.parametrize("model", ["", "   \n\t  "])
def test_rejects_empty_or_whitespace_model_name(model: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build("http://127.0.0.1:8000/v1/chat/completions", model=model)


@pytest.mark.parametrize(
    "url",
    [
        "http://",
        "http:///v1/chat/completions",
        "http://:8000/x",
        "not a url",
        "localhost:8000",
        "127.0.0.1:8000/x",
    ],
)
def test_rejects_malformed_or_missing_host_urls(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url)


@pytest.mark.parametrize(
    "url",
    [
        "/v1/chat/completions",
        "v1/chat/completions",
        "//127.0.0.1:8000/x",
    ],
)
def test_rejects_relative_urls(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1/x",
        "file:///etc/passwd",
        "ws://127.0.0.1/x",
        "wss://127.0.0.1/x",
        "gopher://127.0.0.1/x",
    ],
)
def test_rejects_unsupported_schemes(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/x#fragment",
        "http://localhost:8000/x#frag",
    ],
)
def test_rejects_urls_containing_fragments(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url, resolver=_loopback_resolver)


@pytest.mark.parametrize(
    "url",
    [
        "http://user@127.0.0.1:8000/x",
        "http://user:pass@127.0.0.1:8000/x",
        "http://alice@localhost:8000/x",
    ],
)
def test_rejects_embedded_user_information(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url, resolver=_loopback_resolver)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:0/x",
        "http://127.0.0.1:65536/x",
        "http://127.0.0.1:notaport/x",
        "http://[::1]:0/x",
        "http://[::1]:notaport/x",
    ],
)
def test_rejects_invalid_ports(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url)


# ---------------------------------------------------------------------------
# Rejection: destinations that must never receive image data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8",
        "1.1.1.1",
        "11.0.0.1",
        "128.0.0.1",
        "172.32.0.1",
        "172.15.0.1",
        "192.0.2.1",
        "198.51.100.1",
        "203.0.113.1",
        "100.63.0.1",
        "100.128.0.1",
    ],
)
def test_rejects_public_ipv4_destinations(address: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(f"http://{address}:8000/x")


@pytest.mark.parametrize(
    "address",
    ["2001:4860:4860::8888", "2001:db8::1", "2606:4700::1", "::ffff:8.8.8.8"],
)
def test_rejects_public_ipv6_destinations(address: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(f"http://[{address}]:8000/x")


@pytest.mark.parametrize(
    "url",
    [
        "http://224.0.0.1:8000/x",
        "http://239.255.255.250:8000/x",
        "http://[ff02::1]:8000/x",
        "http://[ff05::2]:8000/x",
    ],
)
def test_rejects_multicast_destinations(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8000/x",
        "http://[::]:8000/x",
    ],
)
def test_rejects_unspecified_addresses(url: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(url)


def test_rejects_ipv4_broadcast_address() -> None:
    with pytest.raises(EndpointValidationError):
        _build("http://255.255.255.255:8000/x")


# ---------------------------------------------------------------------------
# Rejection: hostname resolution safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostname",
    [
        "example.com",
        "localhost.localdomain",
        "my-pc",
        "gpt-server",
        "host.docker.internal",
        "192.168.1.1.example.com",
    ],
)
def test_rejects_arbitrary_dns_hostnames(hostname: str) -> None:
    with pytest.raises(EndpointValidationError):
        _build(f"http://{hostname}:8000/x", resolver=_loopback_resolver)


@pytest.mark.parametrize(
    "resolved",
    [
        ("8.8.8.8",),
        ("192.168.0.1",),
        ("2001:db8::1",),
        ("2001:4860:4860::8888",),
        ("127.0.0.1", "8.8.8.8"),
    ],
)
def test_rejects_localhost_that_resolves_outside_loopback(resolved: tuple[str, ...]) -> None:
    with pytest.raises(EndpointValidationError):
        _build(
            "http://localhost:8000/x",
            resolver=lambda _hostname: resolved,
        )


def test_rejects_localhost_with_no_resolution() -> None:
    with pytest.raises(EndpointValidationError):
        _build("http://localhost:8000/x", resolver=lambda _hostname: ())


def test_rejects_localhost_when_resolver_fails() -> None:
    def failing_resolver(_hostname: str) -> tuple[str, ...]:
        raise OSError("no such host")

    with pytest.raises(EndpointValidationError):
        _build("http://localhost:8000/x", resolver=failing_resolver)


# ---------------------------------------------------------------------------
# Contract guards
# ---------------------------------------------------------------------------


def test_endpoint_config_is_immutable() -> None:
    config = _build("http://127.0.0.1:8000/x")

    with pytest.raises(AttributeError):
        config.hostname = "8.8.8.8"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        config.model = "other"  # type: ignore[misc]


def test_module_must_not_import_pyside6() -> None:
    source = inspect.getsource(endpoint)
    assert "PySide6" not in source
