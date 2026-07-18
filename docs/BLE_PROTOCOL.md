# BLE protocol v1

## Service

Device name: `Codex Display`

Service UUID:

```text
7d8b6c20-8f6d-4b44-a0f8-1b6570c0de01
```

| Characteristic | UUID suffix | Direction | Properties |
|---|---:|---|---|
| Status | `02` | Mac → ESP32 | encrypted Write |
| Command | `03` | ESP32 → Mac | encrypted Read + Notify |
| Result | `04` | Mac → ESP32 | encrypted Write |
| Device info | `05` | ESP32 → Mac | Read |

The first 34 characters of every characteristic UUID are identical to the service UUID.

Pairing uses BLE Secure Connections with bonding, MITM protection, and a random six-digit display passkey. The ESP32 shows the passkey; the user enters it in the macOS pairing dialog.

## Status snapshot

UTF-8 JSON, at most 180 bytes:

```json
{"v":1,"s":42,"t":1784341234,"o":480,"r":68,"u":10080,"q":201600,"d":1250000,"w":6840000,"c":2,"x":358400,"a":3}
```

| Key | Meaning |
|---|---|
| `v` | protocol version |
| `s` | sequence within the current connection |
| `t` | Unix time when generated |
| `o` | local UTC offset in minutes |
| `r` | Codex limit remaining percent |
| `u` | limit window duration in minutes |
| `q` | seconds until quota reset |
| `d` | tokens used today |
| `w` | tokens used in the last seven local dates |
| `c` | available reset credit count |
| `x` | seconds until the nearest available credit expires; zero if unknown |
| `a` | active thread count |

The Companion sends a snapshot immediately after connecting and every 15 seconds. It refreshes Codex account data every 60 seconds. The ESP32 marks retained data stale when no snapshot arrives for 60 seconds.

## Command

```json
{"v":1,"sid":319028314,"id":7,"a":"focus_codex"}
```

`sid` is a random firmware boot-session identifier. `id` increases within that session.

Allowed action values:

- `focus_codex`
- `refresh`
- `new_task`

Arbitrary prompts and shell commands are not accepted.

## Result

```json
{"v":1,"id":7,"ok":1,"m":"FOCUSED"}
```

The Companion caches the 32 most recent results by `(sid, id)`. A repeated request after a BLE reconnect receives the cached result and does not execute the action twice; a device reboot starts a new session and cannot collide with an old request ID.
