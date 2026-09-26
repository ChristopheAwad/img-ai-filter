Image Filter - Windows x86-64 Test Distribution

This package includes Python and the required Python libraries. It does not
include KoboldCpp, a GGUF vision model, or the matching mmproj file.

Start the application by running image-filter.exe from this directory. Do not
move the executable away from its _internal directory.

This build is unsigned. Windows SmartScreen may warn when you first run the
installer or the portable executable. Only continue if you obtained the file
from the official project release and its SHA-256 matches SHA256SUMS.

Image Filter sends supported images to the loopback or private-LAN KoboldCpp
server only after you approve the displayed destination. Plain HTTP traffic is
not encrypted. Use copied test images and a separate empty quarantine folder for
the first test.

This build targets Windows x86-64 testing. It still relies on a normal Windows
desktop and its graphics drivers.
