# Contributing

## Development setup

The firmware can be built with PlatformIO or Arduino IDE. The macOS
Companion requires Python 3.9 or newer. Follow the setup instructions in
`README.md` before making changes.

## Before submitting a change

Run:

```bash
python3 -m unittest discover -s companion/tests -v
pio run
```

Keep changes focused, update documentation when behavior changes, and do not
commit `.pio`, `companion/.venv`, Codex transcripts, Hook event queues,
credentials, pairing data, or compiled firmware.

Hardware-dependent changes should include the board revision, Arduino-ESP32
version, library versions, and a short description of the on-device test.

## Pull requests

Explain the problem, the chosen behavior, and how it was verified. Screenshots
or a short video are useful for UI changes. Security issues should be
reported privately as described in `SECURITY.md`.
