# Fix AppImage GitHub TLS Trust on Fedora

## Status

Plan only. Do not implement until the user approves this plan.

This is a bug fix, not a new roadmap feature. Do not add a roadmap ID and do not
change `roadmap.md`.

## Problem

The released `ImageFilter-0.2.0-x86_64.AppImage`, built on Ubuntu 22.04, shows
`GitHub could not be reached` when the user selects **Check for Updates** on a
different Fedora machine.

The GitHub releases API is currently available and returns HTTP 200. The public
`v0.2.0` release contains the correctly named AppImage, a valid GitHub download
URL, a positive size, and a GitHub-provided SHA-256 digest. The same update
transport succeeds from the repository virtual environment on the development
machine.

`fetch_release_metadata()` catches every unexpected connection exception and
replaces it with `UpdateTransportError("GitHub could not be reached")`. The
underlying DNS, TLS, certificate, timeout, or socket exception is intentionally
not shown in the GUI. Static inspection therefore cannot prove the exact
exception from the user's Fedora machine.

The most likely cause is TLS certificate trust discovery:

- PyInstaller bundles Python and OpenSSL from Ubuntu 22.04.
- OpenSSL's compiled default CA paths can refer to Ubuntu filesystem paths.
- Fedora provides its system trust store at different paths.
- The AppImage does not bundle a CA file or create an explicit SSL context.
- `http.client.HTTPSConnection` currently relies on OpenSSL's default CA lookup.

PR #13 did not change metadata connections. The later release-workflow fix only
changed how a draft GitHub release is found. Neither change explains malformed
release metadata, and malformed metadata would produce a different message.

## Goal

Make GitHub HTTPS certificate verification independent of the host Linux
distribution's CA file layout. Bundle a maintained Mozilla CA certificate file
and explicitly use it for every updater HTTPS connection.

## Non-Goals

- Do not disable TLS certificate verification.
- Do not accept self-signed certificates.
- Do not add public Internet access to automated pytest tests.
- Do not change the private-LAN-only KoboldCpp transport.
- Do not add proxy support in this fix.
- Do not change update selection, release parsing, download URL validation,
  digest verification, installation, or restart behavior.
- Do not expose raw SSL, socket, path, URL, or environment details in GUI error
  messages.
- Do not add retries or automatic update checks.
- Do not publish a release, create a commit, push, or open a PR without the
  required user approvals.

## Test-First Coverage

Write the tests below before implementation. Run only the focused tests and
confirm that the new assertions fail for the expected reason. Existing tests
must continue to use fake transports and must not touch DNS or the network.

### 1. Default HTTPS Connection Uses the Bundled CA File

File: `tests/test_update_transport.py`

Add a test for `_default_connection_factory()` with these exact checks:

1. Replace `http.client.HTTPSConnection` with a recording fake.
2. Replace the CA-path provider with a deterministic path such as
   `/bundled/cacert.pem`; do not depend on the developer machine's real path.
3. Call `_default_connection_factory("api.github.com", 15.0)`.
4. Assert that the connection receives exactly `api.github.com` as the host.
5. Assert that the connection receives exactly `15.0` as the timeout.
6. Assert that the connection receives an explicit `ssl.SSLContext` through the
   `context` keyword argument.
7. Assert that the context was created with the deterministic bundled CA path.
8. Assert that certificate verification remains required.
9. Assert that hostname verification remains enabled.

Keep the test independent of the network. Mock context creation or inspect a
real context only if doing so does not read host-specific trust configuration.
Prefer recording the `cafile` passed to `ssl.create_default_context` and return
a controlled fake context.

Expected pre-implementation failure: the current factory supplies no explicit
context and never asks for a bundled CA path.

### 2. Missing CA Bundle Fails Safely

File: `tests/test_update_transport.py`

Add a test with these checks:

1. Make the CA-path provider return a missing file path, or make SSL context
   creation raise the representative file/certificate exception.
2. Call `fetch_release_metadata()` through the default connection path without
   allowing a real connection.
3. Assert that the caller receives `UpdateTransportError`.
4. Assert that the public message remains exactly
   `GitHub could not be reached`.
5. Assert that the missing path and raw exception text are absent from the
   public message.
6. Assert that no HTTP request is attempted after context creation fails.

This verifies a packaging failure path without leaking local paths.

### 3. Existing Injected Transport Contract Remains Valid

File: `tests/test_update_transport.py`

Retain the existing fake `ConnectionFactory` tests. Add or strengthen a focused
test only if needed to prove:

1. `fetch_release_metadata(connection_factory=fake)` still invokes the fake
   with two positional values: host and timeout.
2. Existing callers do not need to understand SSL contexts.
3. The fixed metadata path and safe request headers remain unchanged.
4. No authorization header is added.

Do not change `ConnectionFactory` to require a third argument. The explicit SSL
context belongs inside `_default_connection_factory()` so dependency injection
and all network-blocked tests stay simple.

### 4. Empty and Invalid Inputs Stay Unchanged

Files: `tests/test_update_transport.py`, `tests/test_update_release.py`

Do not duplicate broad parser coverage. Confirm the existing suite still covers
these contracts:

- Empty metadata bytes are rejected by release parsing.
- Invalid UTF-8 and invalid JSON are rejected.
- An empty release list means no update.
- Invalid `max_bytes`, including negative and non-integer values, is rejected
  before networking.
- Cancellation before connection is preserved.

Only add a regression assertion if one of these paths is affected by the
implementation. The CA fix must not alter their messages or behavior.

### 5. Boundary Behavior Stays Unchanged

File: `tests/test_update_transport.py`

Confirm existing tests retain these boundaries:

- Metadata exactly at the maximum byte count is accepted.
- Metadata one byte above the limit is rejected.
- Declared and streamed body limits are both enforced.
- The default metadata timeout remains 15 seconds.
- The default download timeout remains 30 seconds.

Add an exact timeout assertion to the default-factory test. Do not increase
timeouts as part of this bug fix.

### 6. Request, Response, and Read Failures Remain Sanitized

File: `tests/test_update_transport.py`

Parameterize or add focused cases that make each operation raise separately:

- connection construction;
- `request()`;
- `getresponse()`;
- `response.read()`.

For every case, assert:

1. `UpdateTransportError` is raised.
2. The metadata-check message is exactly `GitHub could not be reached`.
3. Secret-looking exception text is not present.
4. Any successfully constructed connection is closed.

These tests prevent the certificate fix from weakening safe error handling.

### 7. Downloads Use the Same Trusted Connection Factory

File: `tests/test_update_transport.py`

Add the smallest test necessary to prove that the default factory used by
`download_appimage()` is the same factory that creates the explicit trusted SSL
context. Do not perform a download and do not contact GitHub.

If the factory test already proves this structurally because both functions use
the same default callable, do not add a redundant test. Preserve all existing
redirect-host allowlisting and SHA-256 verification tests.

### 8. Runtime Dependency Is Declared and Pinned

File: `tests/test_linux_packaging.py`

Add packaging assertions that parse files rather than use fragile substring
checks where practical:

1. `pyproject.toml` declares `certifi` as a runtime dependency.
2. `packaging/linux/runtime-constraints.txt` pins `certifi` to one exact version.
3. The pinned version satisfies the runtime dependency requirement.
4. `packaging/linux/image-filter.spec` explicitly collects the CA file if the
   normal PyInstaller hook is not sufficient.
5. `packaging/linux/THIRD_PARTY_NOTICES.txt` identifies certifi and its Mozilla
   Public License 2.0 terms.

Expected pre-implementation failure: certifi is not declared, pinned, collected,
or documented.

### 9. Frozen Resource Availability

File: `tests/test_linux_packaging.py` or a new narrowly named packaging test
file only if clearer.

Test the selected CA-path helper in both runtime modes:

1. In a normal source environment, it returns `certifi.where()`.
2. In a simulated frozen environment, it still resolves to the CA file bundled
   by PyInstaller.
3. The returned value is a file path, not a directory.
4. A missing bundled file is not silently replaced with an unverified context.

Do not hard-code PyInstaller's temporary extraction directory. Use monkeypatches
for `sys.frozen`, `sys._MEIPASS`, or certifi behavior only if the implementation
actually requires them. Prefer certifi's supported `where()` API and
PyInstaller's certifi hook over custom frozen-path logic.

### 10. GUI Error Contract Remains Safe

File: `tests/test_window_updates.py`

Add a GUI-level regression test that injects
`UpdateTransportError("GitHub could not be reached")` and verifies:

1. The main status text becomes `GitHub could not be reached`.
2. The warning dialog uses the same safe message.
3. The Check for Updates button is enabled again after completion.
4. A second check can be requested.

This test must inject the error. It must not contact the network.

## Implementation Steps

Implement only after the user approves this plan and the new tests fail as
expected.

### 1. Add the CA Provider Dependency

File: `pyproject.toml`

1. Add `certifi` to `[project].dependencies`.
2. Use a bounded supported range consistent with the project's dependency
   policy. Do not use an unbounded dependency.
3. Keep dependencies alphabetically or consistently ordered with the existing
   list.

File: `packaging/linux/runtime-constraints.txt`

4. Add an exact certifi version used by reproducible Linux builds.
5. Select an available maintained version compatible with Python 3.11 and the
   dependency range in `pyproject.toml`.

### 2. Build an Explicit Verified SSL Context

File: `src/img_ai_filter/update_transport.py`

1. Import `ssl` and `certifi`.
2. In `_default_connection_factory(host, timeout)`, obtain the bundled Mozilla
   CA path from `certifi.where()`.
3. Create a context with `ssl.create_default_context(cafile=certifi.where())`.
4. Pass that context to
   `http.client.HTTPSConnection(host, timeout=timeout, context=context)`.
5. Do not set `check_hostname` to false.
6. Do not set `verify_mode` to `CERT_NONE`.
7. Do not load arbitrary paths from environment variables.
8. Do not change the `ConnectionFactory` type or injected fake-factory API.

Use one fresh standard context per connection. Metadata checks make one
connection; downloads can follow redirects across approved hosts and therefore
can create multiple connections. Context reuse is unnecessary for this small,
manual operation and would add global mutable state.

The same default factory already serves metadata and AppImage downloads. This
ensures both operations use the same explicit trust source without duplicating
TLS configuration.

### 3. Ensure PyInstaller Includes the CA File

File: `packaging/linux/image-filter.spec`

1. First verify whether PyInstaller's installed certifi hook includes
   `certifi/cacert.pem` automatically.
2. Even if the hook exists, prefer an explicit collection in this project spec
   if that makes the release artifact contract testable and resistant to hook
   changes.
3. Use PyInstaller collection helpers instead of hard-coded site-package paths.
4. Include only certifi's required runtime data, not unrelated package files.
5. Keep the existing application resources, metadata, keyring data, and hidden
   imports unchanged.

### 4. Update Third-Party Notice

File: `packaging/linux/THIRD_PARTY_NOTICES.txt`

1. Add certifi to the principal bundled components.
2. State that certifi provides Mozilla CA certificates.
3. Identify the Mozilla Public License 2.0.
4. Link to certifi's upstream repository or license source.
5. Do not claim ownership of the certificate data.

### 5. Keep Public Errors Unchanged

File: `src/img_ai_filter/update_transport.py`

Do not expose the underlying TLS exception in this fix. If context creation,
certificate loading, DNS, request, response, or reading fails, metadata checks
must continue to report `GitHub could not be reached`.

Do not add logging that records local certificate paths without an established
application logging policy. Better diagnostic categories can be a separate
future improvement.

## Verification Sequence

Run commands from the repository root.

### 1. Confirm New Tests Fail First

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_update_transport.py \
  tests/test_linux_packaging.py \
  tests/test_window_updates.py
```

Before implementation, confirm failures specifically show that no explicit CA
context/dependency/package data exists. Do not proceed if failures are caused by
test syntax, accidental network access, or unrelated application behavior.

### 2. Install Updated Local Dependencies

After dependency files are changed, update the existing virtual environment:

```bash
.venv/bin/python -m pip install -e '.[test,eval]' -c packaging/linux/runtime-constraints.txt
```

Do not delete or recreate the environment unless necessary.

### 3. Run Focused Tests After Implementation

Run the same focused command and require all tests to pass.

### 4. Run the Full Network-Blocked Suite

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

All tests must pass. The autouse socket blocker must remain active. Do not add an
exception for GitHub.

### 5. Build the Linux Artifacts

Use the established Linux packaging process. Obtain and verify AppImage tooling
exactly as documented by the workflow or use already verified local copies. Run
the project build command with the required tool paths:

```bash
.venv/bin/python tools/build_linux.py --appimagetool <verified-appimagetool> --runtime <verified-runtime>
```

Do not publish these artifacts.

### 6. Inspect the Built Payload

Verify without contacting GitHub:

1. Extract the AppImage or inspect the tar payload.
2. Confirm certifi's `cacert.pem` exists inside the packaged application.
3. Run the existing `--smoke-test` from the packaged payload.
4. Confirm the application starts and exits successfully.
5. Confirm artifact checksum validation succeeds.

### 7. Fedora Manual Reproduction Test

After automated tests and the local package build pass, ask the user to test the
new AppImage on the same Fedora machine that reproduced the bug.

Provide the exact launch command using the actual built filename:

```bash
chmod +x ./ImageFilter-<new-version>-x86_64.AppImage
./ImageFilter-<new-version>-x86_64.AppImage
```

Manual checklist:

1. Use the same Fedora machine and network where `v0.2.0` failed.
2. Start the replacement AppImage.
3. Select **Check for Updates**.
4. Confirm the status no longer says `GitHub could not be reached`.
5. If testing a build with the same version as the newest public release,
   confirm the application reports that it is up to date.
6. If a newer test release is intentionally available and test releases are
   enabled, confirm the update prompt shows only expected release information.
7. Cancel before download unless download behavior also needs regression
   testing; this bug concerns metadata TLS connection setup.
8. Confirm normal private-LAN image scanning still works with safe sample data.

Ask the user to reply with exactly `Approved` if all steps pass. If a step fails,
ask for the error text, a screenshot, the Fedora version, and the failed step.

## Acceptance Criteria

- The updater uses an explicit verified SSL context backed by the bundled
  certifi CA file.
- Both release metadata checks and AppImage downloads use that context.
- Hostname verification and certificate verification remain enabled.
- No test contacts the network.
- Missing or invalid CA data fails closed and returns a sanitized message.
- Existing endpoint, host allowlist, redirect, size, digest, cancellation, and
  release-selection rules remain unchanged.
- certifi is declared, reproducibly pinned for Linux artifacts, bundled, and
  documented.
- The focused tests pass.
- The full network-blocked suite passes.
- The packaged smoke test passes.
- The CA file is present in the built artifact.
- The user confirms the update check works on the original Fedora machine.

## Approval Gates

1. Wait for user approval of this plan.
2. Write failing tests before implementation.
3. Implement the smallest fix described above.
4. Run focused tests and the full suite.
5. Build and inspect the AppImage.
6. Ask the user to perform the Fedora GUI checklist.
7. Wait for explicit `Approved` from the user.
8. Only then ask whether the user wants a PR, commit, or push.
9. Never create a release as part of this bug-fix session unless the user gives
   separate explicit instructions after approval.
