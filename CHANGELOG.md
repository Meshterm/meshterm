# Changelog

## [0.2.0] - 2026-11-07

### Security
- Sanitize untrusted text and disable markup rendering for external data.
- Restrict XDG directories to 0700 and databases, config, exports, and logs to 0600.
- Serialize SQLite writes and bound in-memory chat/log buffers.
- Validate packet IDs, PSK lengths, region values, and mesh text byte length.
- Scope replies and reactions to exact DM endpoint pairs or a distinct broadcast scope.
- Bound and expire early-ACK reconciliation entries.

### Fixed
- Lock chat input before registering a pending send so a synchronous ACK cannot leave a delivered send locked.
- Restore channel and config protobuf state when device writes fail.
- Dispatch connection and DM callbacks to the UI thread.
- Use an explicit serial port even when autodetection finds no `/dev/ttyACM*` or `/dev/ttyUSB*`.
- Respect the active log filter for live packets and keep reply previews attached to the direct parent.
- Convert empty owner names and meshtastic `SystemExit` paths into write failures instead of exiting the TUI.
- Ignore stale interface events and make repeated connection-established events idempotent.
- Show typed text in the chat composer instead of clipping it to a one-line input.
- Make header tabs selectable with the mouse.

### Changed
- Require Python 3.10 or newer.
- Pin CI actions, dev tools, and transitive dependencies with hashes.
- Raise the coverage threshold and add property-based tests.
