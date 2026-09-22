Image Filter - Linux x86-64 Test Distribution

This package includes Python and the required Python libraries. It does not
include KoboldCpp, a GGUF vision model, or the matching mmproj file.

Start the application by running ./image-filter from this directory. Do not move
the executable away from its _internal directory.

Image Filter sends supported images to the loopback or private-LAN KoboldCpp
server only after you approve the displayed destination. Plain HTTP traffic is
not encrypted. Use copied test images and a separate empty quarantine folder for
the first test.

This build targets Fedora x86-64 testing. It still relies on a normal Linux
desktop, its graphics drivers, display services, and compatible base libraries.
