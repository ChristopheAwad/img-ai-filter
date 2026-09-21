# F-010: Self-Contained Linux Test Distribution

## Status

Plan written and approved by the user on 2026-09-21. The user selected Fedora
x86-64 as the first test system and selected AppImage plus a compressed
portable-directory fallback. Implementation is in progress.

Approved baseline before feature tests:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
882 passed, 4 skipped, 1 warning in 60.48s
```

Baseline environment: Python 3.14.7, x86-64, glibc 2.43, PySide6 6.11.2, and
Pillow 12.3.0. This development environment is too new to define the Linux
compatibility floor. The test artifacts were built with Python 3.11 on Debian
Bookworm (glibc 2.36), with PySide6 6.11.2, Pillow 12.3.0, keyring 25.7.0,
PyInstaller 6.10.0, appimagetool 1.9.1, and a checksum-pinned AppImage runtime.

The required failing packaging/resource tests were written and observed failing
before their production changes. Focused verification after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_linux_artifacts.py tests/test_linux_packaging.py \
  tests/test_platform_integration.py tests/test_image_payload.py \
  tests/test_settings.py tests/test_window.py tests/test_window_server.py \
  tests/test_scan_workflow.py tests/test_quarantine.py -q
408 passed, 2 skipped in 5.40s
```

Complete offline verification after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
924 passed, 4 skipped, 1 existing Pillow warning in 32.66s

git diff --check
clean
```

Final generated artifacts:

```text
packaging-build/ImageFilter-0.1.0-x86_64.AppImage       80 MB
packaging-build/ImageFilter-0.1.0-linux-x86_64.tar.gz  86 MB
packaging-build/SHA256SUMS
```

Both checksum entries pass. The frozen one-directory payload, extracted tarball,
and AppImage extraction mode each pass the bounded offscreen smoke test with
isolated XDG settings directories. Host `ldd` inspection of the XCB platform
plugin found no unresolved libraries. PyInstaller warned about graphical,
portal, D-Bus, XCB, and Wayland libraries absent from the minimal Debian build
container; these are normal desktop host libraries and require the planned
Fedora desktop acceptance test. Implementation is waiting for that test and
explicit user approval.

## Purpose

Make Image Filter practical to test on a separate Fedora x86-64 desktop without
installing Python, PySide6, Pillow, keyring, pip, or the source project. Produce
two artifacts from the same frozen application payload:

1. `ImageFilter-<version>-x86_64.AppImage` for one-file launch.
2. `ImageFilter-<version>-linux-x86_64.tar.gz` as a portable no-FUSE fallback.

KoboldCpp, its vision-capable GGUF model, and its matching `mmproj` remain
external user-managed dependencies. The app must continue to connect only to a
loopback or private-LAN KoboldCpp endpoint.

## Scope Definition

For this feature, "self-contained" means the artifacts include:

- a compatible CPython interpreter;
- all application modules;
- PySide6 and the Qt libraries and plugins required by the app;
- Pillow and the native image libraries required by supported formats;
- keyring and all required Python package metadata, even though credentials are
  dormant in the current GUI;
- Python standard-library modules used by the app, including HTTP and TLS
  support;
- application icons, desktop metadata, license notices, and launch files.

The artifacts may rely on facilities supplied by a normal Linux desktop:

- the Linux kernel and x86-64 CPU support;
- a compatible glibc baseline;
- graphics drivers;
- X11/XWayland or Wayland desktop services supported by bundled Qt;
- a user D-Bus session and desktop portal when native portal dialogs are used;
- a functioning certificate trust store for HTTPS;
- FUSE for direct AppImage mounting, with the tarball supplied when FUSE is not
  available.

Do not advertise the artifacts as having zero operating-system requirements.

## Goals

1. Launch Image Filter on Fedora x86-64 without system Python or pip.
2. Launch without a source checkout and without depending on the build working
   directory.
3. Preserve every existing scan, privacy, network, and quarantine contract.
4. Bundle all reachable Python runtime dependencies declared by the project.
5. Generate the AppImage and tarball from one byte-identical application
   payload before outer-container metadata differs.
6. Provide deterministic names, version metadata, SHA-256 checksums, and
   third-party notices.
7. Build in a controlled environment old enough to avoid tying the artifact to
   Fedora's newer glibc unnecessarily.
8. Make build failures clear when required Qt plugins, Pillow codecs, tools, or
   metadata are missing.
9. Add automated artifact tests that never contact a real network service.
10. Provide a safe manual Fedora checklist using disposable copied images and a
    user-managed KoboldCpp server.

## Frozen Product Decisions

- Track this feature as F-010. F-008 remains reserved for the separately
  planned reliability audit, and F-009 is already shipped.
- The first supported package target is Linux x86-64.
- Fedora x86-64 is the first manual acceptance system.
- Build the Linux artifact on a documented older compatible Linux base rather
  than on the target Fedora host. Prefer Ubuntu 22.04 x86-64 unless initial
  dependency probing proves that its toolchain cannot build the selected
  PySide6/PyInstaller combination.
- Use PyInstaller to create a one-directory payload.
- Do not use PyInstaller one-file mode. AppImage supplies the single-file outer
  artifact without adding a second extraction layer.
- Create both the AppImage and tarball from the validated one-directory payload.
- Use AppImage as the main tester-facing artifact.
- Use a gzip-compressed tar archive for the initial fallback because Fedora can
  extract it without another application package.
- Do not create a `.deb`, RPM, Flatpak, Snap, system package repository, or
  system-wide installer in F-010.
- Do not require root access to launch either artifact.
- Do not write application settings beside or inside the executable. Continue
  using the existing stable Qt `QSettings` identity.
- Do not bundle KoboldCpp, a GGUF model, an `mmproj`, sample user images,
  evaluation datasets, or endpoint credentials.
- Do not publish GitHub releases automatically in this feature. CI may retain
  downloadable workflow artifacts for approved test builds.
- Do not add automatic updates, crash reporting, telemetry, or analytics.
- Do not add Linux code signing as a release blocker for this test artifact.
  Generate SHA-256 checksums. Signing can be decided for a public release.
- Keep current application version `0.1.0` unless a separate approved release
  decision changes it. Artifact names derive from project metadata instead of a
  duplicate hard-coded version.
- Use one stable Linux desktop application identifier consistently in Qt,
  desktop metadata, icon names, and AppStream metadata. Prefer
  `io.github.ChristopheAwad.img_ai_filter` after verifying that it does not alter
  the existing `QSettings` storage identity.
- Add a project-owned application icon suitable for redistribution. Do not use
  copyrighted third-party artwork or model/provider branding.
- The application must remain usable if `xdgdesktopportal` platform-theme
  integration is unavailable. A missing optional portal component must not
  prevent startup or folder selection.
- Keep all automated network access blocked. Frozen smoke tests use no live
  KoboldCpp server or use only an injected/in-process fake where the existing
  architecture permits it without opening sockets.

## Existing Contracts To Preserve

- The server is user-managed and outside this package.
- Only loopback and private-LAN destinations are accepted.
- Redirects and public Internet destinations are rejected.
- Every scan requires an already tested endpoint and explicit transfer consent.
- Plain HTTP remains visibly identified as unencrypted.
- Images are processed one at a time with no retry.
- Source selection alone does not scan, open images, or contact a server.
- Scanning never edits, moves, renames, or deletes source files.
- Candidate previews remain bounded and in memory.
- Candidate selection continues to use the saved F-009 confidence threshold.
- Quarantine remains an explicit exact-path confirmed move, not deletion.
- Existing destinations are never overwritten.
- Sources are revalidated before movement.
- Cross-filesystem copies are verified before source removal.
- Activity history retains its bounded storage and privacy rules.
- Automated tests never contact any network service.
- Windows-only tests remain skipped outside Windows.

## Artifact Contract

### Common Frozen Payload

The PyInstaller output directory must:

- contain one documented executable entry point;
- contain the CPython runtime used by the frozen executable;
- contain application modules and required Python standard-library modules;
- contain PySide6 QtCore, QtGui, and QtWidgets support;
- contain a working Qt platform plugin for the supported display path;
- contain required Qt image format and style/plugin dependencies;
- contain Pillow plugins and native libraries for PNG, JPEG, WebP, BMP, and
  TIFF;
- contain keyring package code and metadata needed for its guarded dynamic
  import, without activating credentials in the GUI;
- contain SSL/OpenSSL components needed by the standard-library HTTPS client;
- contain application desktop/icon metadata and third-party notices;
- contain no absolute source-tree dependency at runtime;
- contain no `.venv`, test suite, coverage data, Git metadata, private datasets,
  source images, endpoint settings, credentials, caches, or build-host home
  paths unless a binary toolchain unavoidably embeds a nonfunctional debug path;
- be read-only at runtime without preventing normal startup, settings, history,
  scanning, or quarantine output to user-selected writable paths.

Treat PyInstaller warnings as review inputs. Maintain a small explicit allowlist
only for imports that are proven optional and unreachable on the packaged Linux
path. Do not suppress all missing-module warnings.

### Tarball

The tarball must:

- contain one top-level directory named with application version and target;
- preserve executable permissions;
- include a short packaged-use README and third-party notices;
- extract and launch from a user-writable location without installation;
- launch when the extraction path includes spaces;
- not require FUSE;
- not require root privileges;
- produce the same application behavior as the common frozen payload.

### AppImage

The AppImage must:

- target x86-64 and use the common frozen payload;
- contain a valid `AppRun` entry point;
- contain a valid desktop file and icon link/layout expected by AppImage tools;
- expose the product name, version, icon, categories, and executable identity;
- launch after the executable bit is set;
- not write inside the mounted AppImage;
- work from a path containing spaces;
- fail with documented guidance when direct mounting is unavailable;
- have the tarball fallback documented rather than requiring the tester to
  install FUSE.

### Checksums And Naming

Use these forms, populated from project version metadata:

```text
ImageFilter-0.1.0-x86_64.AppImage
ImageFilter-0.1.0-linux-x86_64.tar.gz
SHA256SUMS
```

`SHA256SUMS` must list both artifacts with standard lowercase SHA-256 digests.
Generating the file twice from unchanged artifacts must produce identical
content. Full byte-for-byte reproducibility of the compressed artifacts is a
goal only if it can be achieved with bounded timestamps and ordering without
substantial custom tooling; record any remaining nondeterminism honestly.

## Build And Dependency Contract

- Add packaging dependencies separately from application runtime dependencies.
  A source installation for normal development must not install PyInstaller or
  AppImage construction tools unless the packaging extra or documented build
  environment is selected.
- Pin PyInstaller and Python packaging tool versions used by CI.
- Resolve and record exact versions of runtime packages used in release
  artifacts. Do not silently resolve a different PySide6 or Pillow version on
  every build.
- Keep `pyproject.toml` as the application package authority. Do not turn
  `.opencode/package.json` into an application manifest.
- Prefer a checked-in PyInstaller `.spec` file over a long undocumented command.
- Keep hidden imports and collected metadata explicit when PyInstaller cannot
  infer them, especially for guarded keyring loading and Pillow plugins.
- Include only Qt modules and plugins required by the current application.
  Avoid collecting the complete Qt SDK without evidence that it is needed.
- Ensure `configure_native_file_dialogs()` still runs before Qt imports in the
  frozen process.
- Add a small, documented build script only where it removes error-prone manual
  sequencing. The script must validate its inputs, stop on failure, use paths
  relative to the repository root, and not delete unrelated directories.
- Put generated output under an ignored, dedicated packaging build directory.
- Never read developer credentials or normal user settings during artifact
  construction.
- Build commands must work non-interactively in CI.
- The CI workflow must use least-privilege read-only repository permissions and
  must not publish a release or push changes.

## Application Identity And Resources

Add only the runtime application identity needed for desktop packaging:

- set a stable application display name;
- set an application version from package metadata or one authoritative source;
- set a packaged application icon through Qt;
- preserve the existing organization/application names used by `QSettings` so
  package installation does not unexpectedly lose or fork existing settings;
- load icon/resource data through a frozen-safe method that also works during
  source development and tests;
- do not depend on the current working directory;
- provide PNG sizes and/or SVG as required by Qt, AppImage, desktop files, and
  AppStream metadata;
- include accessible text metadata and a valid desktop category;
- avoid file associations, MIME handlers, autostart, privileged capabilities,
  or shell integration not required to launch the app.

## Detailed Test Coverage First

### 1. Baseline And Worktree Inspection

Before test or implementation changes:

1. Run `git status --short --branch`.
2. Preserve all unrelated user or agent changes.
3. Run the complete suite exactly:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

4. Record passes, skips, warnings, and duration in this Status section.
5. Confirm `tests/conftest.py` still blocks sockets, DNS, and standard-library
   HTTP.
6. Record current Python, PySide6, Pillow, keyring, glibc, and architecture
   versions used by the development environment. Do not treat the current
   Python 3.14 venv as the release runtime automatically; select and document a
   supported build Python after compatibility tests.
7. If baseline tests fail, diagnose before packaging work. Do not modify
   unrelated behavior to make packaging appear successful.

### 2. Packaging Metadata Tests

Write failing tests for small parseable metadata and build helper behavior
before adding production packaging files. Prove:

- project name and version are obtained from `pyproject.toml`;
- an empty, missing, malformed, non-string, or unexpected version causes a safe
  build failure instead of an incorrectly named artifact;
- artifact names match the frozen naming contract exactly;
- only Linux and x86-64 are accepted by this first packaging target;
- unsupported architectures such as aarch64 fail with a clear message;
- the desktop file uses the agreed stable application identifier;
- the desktop `Exec` value points to the packaged launcher without shell
  interpolation;
- the desktop file does not request a terminal;
- desktop categories and icon names are present;
- AppStream XML, if added, parses and carries the matching ID, name, summary,
  launchable, version, and license fields;
- missing icon sizes, desktop metadata, notices, or launcher files fail artifact
  validation;
- no metadata embeds a KoboldCpp endpoint, username, home directory, or build
  checkout path.

Prefer tests of project-owned validators over brittle tests that duplicate an
external tool's complete implementation.

### 3. Resource Loading And Application Identity Tests

Write failing unit or `pytest-qt` tests proving:

- the app has the expected display name while source-run;
- the app icon loads while source-run;
- the icon resource can be resolved through a simulated frozen resource root;
- a missing or corrupt icon fails safely with a generic icon and does not stop
  the window from opening;
- the application version matches `pyproject.toml` or the selected single
  authoritative version source;
- setting desktop identity does not change the organization and application
  values used by existing `QSettings`;
- icon/resource resolution never depends on `Path.cwd()`;
- changing the current directory before launch does not prevent resource
  loading;
- initialization still configures Linux platform integration before importing
  Qt;
- no resource test writes into the source package or frozen resource root.

### 4. PyInstaller Specification Tests

Add tests or a deterministic validation command that initially fails until the
specification exists and proves:

- the spec builds from the intended application entry point;
- the build is one-directory, not PyInstaller one-file;
- GUI/windowed mode does not create an unnecessary console window where the
  option applies;
- the application package is collected;
- required PySide6 modules and Qt plugins are collected;
- required Pillow plugins are collected;
- keyring package code and metadata are collected despite dynamic import;
- standard-library SSL support is collected;
- application icons and notices are included;
- tests, evaluation datasets, `.git`, `.venv`, caches, and packaging output are
  excluded;
- missing required inputs fail the build;
- stale output is replaced only inside the dedicated generated build directory;
- the build does not mutate source files or user-selected data.

Do not assert exact internal PyInstaller-generated filenames unless they are a
required public contract. Validate capabilities and required classes of files.

### 5. Frozen Launch Smoke Tests

After observing the intended failures, build the one-directory payload and test
it in a clean environment. Prove:

- the executable starts with no system Python available on `PATH`;
- the executable starts outside the repository;
- the executable starts with an empty temporary `HOME`, `XDG_CONFIG_HOME`, and
  `XDG_DATA_HOME`;
- the executable starts when its path includes spaces;
- the executable starts while its installation directory is read-only;
- changing the working directory does not change startup behavior;
- startup succeeds without a KoboldCpp server;
- no startup network request occurs;
- the main window can be created with `QT_QPA_PLATFORM=offscreen` for automated
  smoke testing;
- a bounded smoke-test mode or external process harness exits cleanly instead
  of hanging CI;
- startup errors return a nonzero status and useful diagnostics without a Python
  traceback being shown as the normal GUI experience;
- no source checkout is opened or imported at runtime.

Do not add a production backdoor that bypasses application safety behavior just
for tests. A process-level smoke option may create and close the normal window,
or tests may use an external timeout and controlled Qt environment.

### 6. Frozen Image Codec Tests

Use generated temporary images, not repository user data. Prove through the
frozen payload that:

- valid PNG opens and produces a bounded PNG request payload and thumbnail;
- valid JPEG and `.jpeg` variants work;
- valid WebP works, including native codec availability;
- valid BMP works;
- valid TIFF and `.tif` variants work;
- corrupt data for every supported suffix fails safely;
- a suffix/decoded-format mismatch remains rejected;
- oversized dimensions and decompression-bomb limits retain existing behavior;
- EXIF orientation, transparency conversion, digest, byte count, and source
  identity behavior remain unchanged;
- codec tests write only to their temporary directories;
- source test files remain byte-for-byte unchanged.

If running the existing Python test modules through the frozen GUI is not
practical, add a narrow project-owned artifact probe that exercises the real
frozen `image_payload` module. Do not copy or reimplement its decoding logic in
the test probe.

### 7. Qt Plugin And Desktop Tests

Prove automatically where possible and manually where display services are
required:

- Qt can initialize in offscreen mode from the frozen payload;
- the required Linux display platform plugin is present;
- PNG thumbnails render through Qt;
- the desktop file validates with the available standard validator;
- AppStream metadata validates when that tool is available in the build image;
- icon files decode and have required dimensions;
- the app remains launchable when
  `QT_QPA_PLATFORMTHEME=xdgdesktopportal` cannot load an optional portal theme;
- an existing user-provided `QT_QPA_PLATFORMTHEME` remains respected;
- folder selection is tested manually on Fedora Wayland and X11/XWayland where
  available;
- missing FUSE affects only direct AppImage mounting and does not affect the
  tarball payload.

Do not assume that the PySide6 wheel contains a desktop portal theme plugin.
Verify actual contents and preserve a usable fallback.

### 8. Settings And History Persistence Tests

Use isolated temporary XDG paths. Prove with the frozen executable or a
project-owned frozen probe:

- first launch with no settings succeeds;
- the base URL, discovered model, confidence threshold, quarantine directory,
  and activity history use writable user configuration rather than the package
  directory;
- settings persist after process restart;
- settings persist when the AppImage filename changes but the application
  identity remains the same;
- settings are shared intentionally between source-run and packaged builds only
  according to the unchanged existing QSettings organization/application
  identity;
- malformed existing settings retain current safe fallback behavior;
- an unwritable configuration directory produces safe user-visible behavior
  rather than writing beside the executable;
- clearing history still leaves quarantine move logs untouched;
- no image bytes, candidate reasons, raw server responses, credentials, or
  endpoint address are added to activity-history records;
- no packaging test reads or changes the developer's real settings.

### 9. Network And Privacy Regression Tests

Retain the existing global network block and prove:

- launch performs no DNS lookup, socket creation, HTTP request, or HTTPS request;
- all existing endpoint validation tests pass unchanged;
- public hosts, public IP addresses, unsafe hostname resolution, userinfo,
  fragments, queries, and redirects remain rejected;
- loopback and private-LAN URL normalization remains unchanged;
- consent remains required before image preparation and transfer;
- no tests contact GitHub, package indexes, AppImage services, KoboldCpp, or any
  external host after dependencies are installed;
- build logs and artifact metadata contain no saved endpoint, credentials,
  image bytes, user paths, or model response;
- the package adds no telemetry, crash upload, update request, or analytics;
- HTTPS continues to use normal certificate validation and does not add an
  insecure bypass.

Dependency download is a controlled build-environment setup operation, not an
application runtime behavior. Separate it clearly from offline tests.

### 10. Scan And Quarantine Regression Tests

Run existing focused tests and add artifact-level probes only where needed to
prove packaging did not alter behavior:

- source folder selection remains idle and read-only;
- scan runs off the GUI thread;
- one image is processed at a time;
- cancellation and close behavior remain bounded;
- failed and uncertain results remain counted and omitted correctly;
- threshold boundaries and manual checkbox changes remain correct;
- thumbnails remain in memory;
- quarantine root overlap remains rejected;
- exact source and destination paths are shown before movement;
- declining confirmation changes no files;
- changed sources and destination conflicts remain untouched;
- verified cross-filesystem behavior remains unchanged;
- move logs are written only in the selected quarantine directory;
- read-only installation directories do not interfere with operations on
  explicitly selected writable data.

Automated tests continue to use fake transports and disposable files. Real-data
network testing occurs only in the manual acceptance gate.

### 11. Tarball Construction Tests

Write failing artifact tests before adding the final tarball construction step.
Prove:

- the expected output name derives from project metadata;
- exactly one expected top-level directory exists;
- the executable bit survives archive and extraction;
- extraction rejects or detects unexpected absolute paths and `..` traversal in
  the produced archive inspection;
- symlinks, if any are required for native libraries, remain internal and do
  not point outside the extracted directory;
- packaged README and third-party notices are present;
- no generated file is owned conceptually by a privileged user requirement;
- launch after extraction does not require root, Python, pip, or FUSE;
- extraction and launch work under a directory containing spaces;
- rebuilding does not append stale files from an earlier payload;
- checksum generation includes the final archive.

### 12. AppImage Construction Tests

Write failing artifact tests before adding the final AppImage construction step.
Prove:

- the AppDir has a valid `AppRun`;
- `AppRun` resolves its own location and does not depend on the launch working
  directory;
- the desktop file and icon are in the required AppDir locations;
- AppImage architecture is x86-64;
- the AppImage version/name matches project metadata;
- required payload files match the tested one-directory payload;
- executable permissions are correct;
- launch succeeds with a clean XDG environment where CI supports AppImage;
- extraction mode can inspect or run the payload when FUSE is unavailable;
- read-only AppImage mounting does not cause writes inside the package;
- no update metadata is advertised unless an update mechanism is separately
  approved and implemented;
- checksum generation includes the final AppImage.

If the CI host cannot mount AppImages, use AppImage extraction for automated
payload verification and retain direct-launch testing for the Fedora manual
gate. Do not weaken the manual acceptance requirement.

### 13. Native Library Inspection

Inspect the executable, extension modules, Qt plugins, and native libraries.
Record and review:

- unresolved `NEEDED` shared libraries;
- accidental links to build-directory paths;
- glibc and GLIBCXX symbol requirements relative to the selected baseline;
- bundled versus host-provided Qt libraries;
- Pillow JPEG, WebP, TIFF, zlib, and related native codec dependencies;
- OpenSSL dependencies used by Python HTTPS;
- XCB/Wayland platform plugin dependencies;
- duplicate libraries with incompatible versions;
- executable stack or unexpected writable/executable segment warnings where
  available tooling reports them;
- architecture of every executable/shared-object class sampled or validated.

Maintain an explicit host-library expectation list. A test must fail for a new
unresolved library unless it is reviewed and added deliberately.

### 14. Artifact Content And Secret Inspection

Before manual testing, inspect generated outputs and prove:

- no `.git` directory or Git credentials exist;
- no `.venv`, pytest cache, coverage output, bytecode cache, or local build log
  exists in the payload;
- no files from `evaluation/` or private datasets are present unless an
  explicitly required license notice is separately identified;
- no test fixture images are present;
- no source or quarantine folders are present;
- no QSettings files, history values, move logs, keyring data, tokens, passwords,
  endpoint URLs, or model names from the build host are present;
- no private keys or signing material are present;
- no unexpected large files or model weights are present;
- package licenses and third-party notices cover bundled Python, PyInstaller,
  PySide6/Qt, Pillow, keyring, and transitive packages;
- artifact size is reported and an unexpected material increase fails or
  requires review rather than passing silently.

### 15. CI Workflow Tests And Review

Add a Linux packaging workflow only after local construction and tests pass.
Prove by review and workflow execution:

- the workflow has `contents: read` permissions;
- it checks out the repository and uses a pinned major or commit for actions;
- it uses the approved Python and controlled build environment;
- it installs exact packaging/runtime dependency versions;
- it runs the complete network-blocked test suite before packaging;
- it builds the one-directory payload once;
- it validates that payload before creating either outer artifact;
- it builds both artifacts from the validated payload;
- it runs metadata, content, native-library, checksum, and smoke checks;
- it uploads only the two artifacts, checksum file, and necessary test reports;
- pull-request builds do not publish GitHub releases;
- failures stop artifact publication;
- caches cannot inject generated payload files into final artifacts;
- no secret is required for ordinary test-artifact builds.

### 16. Documentation Review

After implementation tests pass, update durable documentation:

- `README.md` provides a Linux test-build download/launch section;
- README states clearly that Python installation is not required for artifacts;
- README states clearly that KoboldCpp, model, and `mmproj` remain external;
- README explains `chmod +x` for AppImage without telling users to use root;
- README gives tarball extraction/launch as the FUSE fallback;
- README explains that plain HTTP image transfers are unencrypted;
- README describes supported first target as Fedora x86-64 testing, not all
  Linux distributions;
- README documents checksum verification;
- README documents where settings/history and quarantine move logs are stored or
  how to identify them safely after measuring actual packaged behavior;
- README has concise troubleshooting for startup, portal/file-dialog, display,
  FUSE, permissions, and KoboldCpp connectivity;
- `project-brief.md` records the packaging boundary and continued external
  server/model decision without claiming the broader Milestone 6 is complete;
- `roadmap.md` keeps F-010 in progress through desktop approval and the chosen
  Git workflow;
- no document calls the artifact universally portable or dependency-free at the
  operating-system level;
- no document claims signing, automatic updates, or support not tested here.

### 17. Focused Verification

Run at minimum after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_platform_integration.py tests/test_image_payload.py \
  tests/test_settings.py tests/test_window.py tests/test_window_server.py \
  tests/test_scan_workflow.py tests/test_quarantine.py -q
```

Also run the dedicated packaging metadata, artifact, and frozen smoke-test files
added by this feature. Record pass, skip, warning, artifact-size, and duration
results in Status.

### 18. Full Regression And Final Inspection

After focused and artifact tests pass:

1. Run the full suite:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

2. Run `git diff --check`.
3. Run `git status --short --ignored` and inspect generated outputs.
4. Confirm generated build directories and artifacts are ignored and no source
   or user data is hidden in ignored output.
5. Re-run the artifact validators against the exact files supplied for manual
   testing.
6. Verify SHA-256 checksums from a separate working directory.
7. Extract the tarball into a clean temporary path and run its smoke test.
8. Extract and inspect the AppImage; directly launch it where FUSE is available.
9. Run native-library inspection and secret/content inspection.
10. Review the complete diff for changes outside packaging, identity, resources,
    tests, CI, and documentation.
11. Confirm no automated test contacted a real network service.
12. Record all commands and results in Status.

## Implementation Sequence

1. Obtain explicit user approval of this complete plan.
2. Inspect worktree state and preserve unrelated changes.
3. Run and record the complete offline baseline.
4. Verify the intended Linux build base, Python version, CPU architecture, and
   available AppImage construction tool without changing application code.
5. Add failing packaging metadata tests for valid, missing, malformed, boundary,
   and unsupported-target cases.
6. Add failing resource and application identity tests, including changed
   working directory and simulated frozen root cases.
7. Run those tests and confirm failure is caused by missing F-010 behavior.
8. Add the minimal icon/resource identity implementation and metadata files.
9. Run focused source-mode tests until they pass.
10. Add failing PyInstaller specification validators and frozen smoke tests.
11. Run them and confirm failure because the frozen build is absent or incomplete.
12. Add pinned packaging inputs and the one-directory PyInstaller specification.
13. Build the payload and resolve only evidence-backed missing imports, Qt
    plugins, Pillow codecs, keyring metadata, SSL components, and native
    libraries.
14. Run frozen launch, clean-XDG, changed-working-directory, read-only-install,
    codec, Qt, settings, privacy, and application regression tests.
15. Add failing tarball structure, permissions, traversal, content, and launch
    tests.
16. Implement tarball construction from the already validated payload.
17. Run tarball tests until they pass.
18. Add failing AppDir/AppImage metadata, payload, permissions, extraction, and
    launch tests.
19. Implement AppImage construction from the same validated payload.
20. Run AppImage tests until they pass.
21. Add checksum generation and failing checksum-content tests, then implement
    the smallest deterministic checksum step.
22. Run native-library, host-dependency, secret, content, license, and size
    inspections; fix only demonstrated packaging defects.
23. Add Linux CI after local artifact construction is stable.
24. Update README, project brief, roadmap, and packaged documentation.
25. Run focused tests, the full offline suite, artifact rebuild, all artifact
    validators, diff checks, and final inspections.
26. Supply the exact AppImage, tarball, and checksum files to the user through
    the agreed workspace or CI artifact location.
27. Ask the user to complete the Fedora manual checklist below.
28. Wait for exact `Approved` or failure evidence.
29. Only after approval ask whether to create a PR, commit, or push.

Do not delegate production implementation until the main session has written
and run the failing tests. The main session owns tests, approval gates,
integration, Git operations, and the full-suite result. Any delegated agent must
receive the exact artifact contract and may implement only an independent seam
after its failing tests exist.

## Expected Files

Planning and durable documentation:

- `feature.md`
- `roadmap.md`
- `project-brief.md`
- `README.md`

Likely application and metadata changes:

- `pyproject.toml`
- `src/img_ai_filter/__main__.py`
- a small package resource helper only if direct resource loading cannot remain
  clear in `__main__.py`
- project-owned icon/resource files under a new documented package or packaging
  resource directory
- Linux `.desktop` metadata
- AppStream metadata
- third-party notices or a generated-notice input manifest

Likely packaging files:

- a PyInstaller `.spec` file
- a pinned packaging requirements or constraints file
- a small Linux packaging script or scripts
- AppDir/AppImage launcher metadata
- generated-output ignore rules
- `.github/workflows/linux-package.yml`

Likely tests:

- a focused packaging metadata test file
- a focused resource/application identity test file or additions to existing
  platform/window tests
- artifact validation tests
- frozen smoke/probe support kept separate from normal application behavior
- existing image, settings, endpoint, scan, GUI, and quarantine regression tests

Exact filenames are implementation details to select after tests establish the
smallest clear structure. Do not add a broad packaging framework, release
server, updater, installer service, or general build system.

## Manual Fedora Desktop Acceptance Checklist

Use a separate Fedora x86-64 test system. Use disposable copies of images and a
new quarantine directory. Keep the originals outside both directories. The
automated suite does not test a live server.

1. Download or transfer the AppImage, tarball, and `SHA256SUMS` into one folder.
2. Run `sha256sum --check SHA256SUMS` and confirm both artifacts report `OK`.
3. Confirm Python is not required by temporarily using a shell where `python`,
   `python3`, and `pip` are not on `PATH`; do not uninstall system components.
4. Mark the AppImage executable with
   `chmod +x ImageFilter-0.1.0-x86_64.AppImage`.
5. Launch the AppImage from the file manager and from a terminal.
6. Confirm one Image Filter window opens with the expected title and icon and no
   terminal traceback.
7. Close and relaunch it from a directory whose path contains spaces.
8. If AppImage mounting fails, record the exact message, extract the tarball,
   and launch its documented executable without installing FUSE.
9. Confirm the tarball version opens with the same title, icon, and controls.
10. Open the source-folder and quarantine-folder pickers. Confirm each dialog is
    usable under the current Fedora session and cancellation changes nothing.
11. Start KoboldCpp with a vision-capable GGUF and matching `mmproj` on loopback
    or a private-LAN computer.
12. Enter the `/v1/` base URL and select **Test Connection**. Confirm the version
    and discovered model appear.
13. Try one deliberately public URL and confirm the app rejects it without
    sending a request.
14. Select a disposable folder containing copied PNG, JPEG, WebP, BMP, and TIFF
    examples, including ordinary photos, screenshots, and memes.
15. Select **Scan Folder**. Check the displayed destination carefully and
    consent only if it is the intended private server.
16. Confirm the UI remains responsive, progress advances, previews display, and
    ordinary photos are omitted from candidate rows.
17. Confirm the automatic-selection threshold and **Select All**/**Clear All**
    behavior match the existing settings.
18. Confirm scanning did not change any source filename, bytes, or location.
19. Close and reopen the app. Confirm endpoint/model settings, threshold, and
    activity history persist while candidate rows and checkbox choices do not.
20. Select a new empty, non-overlapping quarantine folder.
21. Check only disposable candidates, request quarantine, and inspect every
    source and destination path before approval.
22. Decline once and confirm nothing moves.
23. Repeat and approve one safe disposable move. Confirm only selected files
    move and `.img-ai-filter-moves.jsonl` appears in the quarantine folder.
24. Confirm no settings, logs, images, or other files were written beside the
    AppImage or into the extracted application directory.
25. Open **Activity History** and confirm expected scan/quarantine events without
    image content, server address, credentials, or raw responses.
26. Report Fedora version, desktop environment, Wayland or X11, which artifact
    was used, and any warnings shown in the terminal.

Reply `Approved` if every applicable step passes. Otherwise provide the failed
step, exact error text, terminal output, and a screenshot when the failure is
visible.

## Acceptance Criteria

- The AppImage and tarball are created from one validated PyInstaller
  one-directory payload.
- Both launch on the selected Fedora x86-64 test system without a separately
  installed Python environment or source checkout.
- The tarball works without FUSE and neither artifact requires root.
- Required Python packages, Qt plugins, Pillow codecs, SSL support, application
  resources, and metadata are present.
- Missing or optional desktop portal integration does not prevent normal use.
- Settings and activity history persist in user configuration, not inside or
  beside the artifacts.
- Existing endpoint, consent, scan, threshold, privacy, and quarantine contracts
  remain unchanged.
- Automated tests remain fully network-blocked.
- Artifact validation finds no user data, credentials, private datasets, model
  files, build caches, or source-control metadata.
- Native-library inspection finds no unexplained unresolved dependency on the
  supported Fedora target.
- Desktop and AppStream metadata validate.
- SHA-256 checksums verify both final artifacts.
- Documentation accurately states the supported target and external KoboldCpp
  requirements.
- The complete automated suite passes.
- The user approves the Fedora desktop checklist before any Git operation is
  proposed.

## Explicitly Deferred

- Bundling KoboldCpp, GGUF models, or `mmproj` files.
- GPU driver installation or hardware-specific KoboldCpp builds.
- ARM/aarch64, 32-bit x86, or other CPU architectures.
- Declaring support for every Linux distribution.
- RPM, DEB, Flatpak, Snap, Nix, or system repository packaging.
- Windows and macOS packaging.
- Public GitHub release publication.
- Automatic updates or update metadata.
- Code signing, certificate procurement, or trusted-store integration.
- Full byte-for-byte reproducible-build guarantees if upstream tools retain
  uncontrolled metadata.
- Bundling a CA trust store or accepting untrusted HTTPS certificates.
- Activating dormant credential UI or promising every Linux keyring backend.
- Changing settings identity or adding settings migration.
- F-008 reliability-audit implementation.
- Completing the full cross-platform Milestone 6 release-readiness claim.
