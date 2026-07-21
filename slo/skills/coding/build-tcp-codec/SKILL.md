---
name: build-tcp-codec
description: Generating a length-prefixed TCP message codec (framing, header, checksum, size bounds) with parallel Python and Go reference implementations.
when_to_use: Use when building the wire-framing layer for a TCP client/server — turning a raw byte stream into discrete, validated messages (length-prefix framing, header fields, CRC, size bounds), in either Python or Go.
group: coding
kind: skill
source_prompt: build-tcp-codec.md
---

# Build a TCP Message Codec

## Skill summary

- **Name:** `build-tcp-codec`
- **Description:** Generating a length-prefixed TCP message codec (framing, header, checksum, size bounds) with parallel Python and Go reference implementations.
- **When to use:** Use when building the wire-framing layer for a TCP client/server — turning a raw byte stream into discrete, validated messages (length-prefix framing, header fields, CRC, size bounds), in either Python or Go.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-tcp-codec.md`

## Examples

- The user asks: "Write the codec / framing layer for my TCP client and server."
- You are building a socket-based protocol package and need message boundaries over a raw stream.
- You have a Go codec and need the equivalent in Python (or vice versa) with identical wire format.
- A peer "hangs forever" or reads garbled messages and you need the canonical framing design to compare against.

## Guidance

Generate the wire-framing layer for a TCP client/server: the code that turns a
raw byte stream into discrete, validated messages and back again. This skill
gives you one canonical design and parallel reference implementations in **Go**
and **Python**. Follow it whenever you need a codec, a framing layer, or a
"protocol" package for a socket-based service. Pick the language section you
need; the design is identical across both.

### The one fact everything follows from

**TCP is a stream of bytes, not a stream of messages.** A single `write` on one
side does not correspond to a single `read` on the other. The kernel may split,
merge, or dribble your bytes in any grouping. TCP guarantees **order** and
**delivery**, not **message boundaries**. So if you send `HELLO` then `WORLD`,
the reader may see `HELLOWORLD`, `HEL` + `LOWORLD`, or one byte at a time.

A codec's entire job is to impose message boundaries on that shapeless stream —
plus identity (what kind of message) and integrity (was it corrupted). The
piece that does this in both directions (encode + decode) is the **codec**
(coder-decoder).

### Choose the boundary strategy: length-prefix

Three classic ways to mark boundaries:

1. **Delimiter** (e.g. `\n`) — fragile for binary; the delimiter can appear in
   the data and must be escaped.
2. **Fixed-size messages** — too rigid.
3. **Length-prefix** — write the message length first, then the message. The
   reader reads the length, then reads *exactly* that many bytes. Robust, binary-safe.

**Always use length-prefix.** It is the single most important idea in the codec:
*read a small fixed header that tells you how big the rest is, then read exactly
that much.*

### The frame layout

A "frame" is one framed message. Use a fixed 8-byte header, a variable payload,
and a 4-byte trailing checksum:

```
┌───────────────────── HEADER (8 bytes, fixed) ─────────────────────┐
│ bytes 0-3 │ byte 4  │ byte 5 │ byte 6 │  byte 7   │
│ TotalLen  │ Version │  Type  │ Flags  │ Reserved  │
│ (uint32)  │ (uint8) │(uint8) │(uint8) │  (=0)     │
└───────────┴─────────┴────────┴────────┴───────────┘
┌──────────── PAYLOAD (variable) ────────────┐
│           the message bytes                │
└────────────────────────────────────────────┘
┌──────────── CRC-32 (4 bytes, fixed) ───────┐
│      checksum computed over the payload    │
└────────────────────────────────────────────┘
```

Every field earns its place:

- **TotalLen (bytes 0-3, big-endian uint32):** the length prefix. Store the
  **total frame length** (header + payload + CRC), not just the payload length.
  The decoder subtracts the fixed overhead to recover the payload size. (Either
  convention works — just make both sides agree.)
- **Version (byte 4):** the wire-protocol version, restated on *every* frame so a
  peer can reject an incompatible format before interpreting any payload byte.
- **Type (byte 5):** which kind of message (handshake, ping, data, …). The codec
  carries it faithfully; the layer above routes on it.
- **Flags (byte 6):** one byte of per-message option bits. Reserved for growth.
- **Reserved (byte 7):** always `0`. Rounds the header to a clean 8 bytes and
  leaves room to extend later.
- **CRC-32 (last 4 bytes):** a checksum computed over the payload. The sender
  appends it; the receiver recomputes and compares. Catches corruption *and*
  framing desync (a one-byte length drift makes the CRC fail immediately instead
  of silently misreading every later frame). Worth it even though TCP has its own
  weak 16-bit checksum: the CRC is end-to-end and survives relays/proxies and
  above-TCP bugs.

Pin the sizes as named constants shared by encoder and decoder:

- `FrameHeaderSize = 8`
- `FrameOverhead = FrameHeaderSize + 4` (= 12; header + CRC)
- `MaxPayloadSize = 16 * 1024 * 1024` (16 MiB — a DoS guard, see below)
- `ProtocolVersion = 1`

### The two non-negotiable safety rules

1. **Bound the length before you allocate.** The payload size comes from bytes a
   stranger sent you. A corrupt/malicious length of `0xFFFFFFFF` must never turn
   into a 4 GB allocation. Reject any length `< FrameOverhead` (can't even cover
   header+CRC) or any payload `> MaxPayloadSize`, *before* allocating the buffer.
2. **Read exactly N bytes.** Never trust one `read` to return a whole header or a
   whole payload. Use a read-fully primitive (`io.ReadFull` in Go,
   `recv_exactly` loop in Python) that loops until the buffer is full. This is the
   direct answer to the boundary problem.

Two more rules that matter:

- **Validate the version early** — right after reading the header, before payload
  allocation.
- **Verify the CRC last** — return a frame only when version, length, and checksum
  all pass. Callers must never see a half-valid frame.
- **Surface a clean close as EOF.** If the stream ends exactly where a new header
  would begin, that is a normal connection close (EOF). If it ends *partway*
  through a header or payload, that is a truncation error.

### Encode path (WriteFrame)

Keep the top-level method a small table of contents; one helper per phase:

1. `validateFramePayloadSize` — reject oversized payloads before writing a byte.
2. `writeHeader` — serialize the 8 bytes (big-endian total length, version, type,
   flags, reserved `0`).
3. `writePayload` — write the raw payload (skip if empty).
4. `writeCRC` — compute CRC-32 over the payload and append 4 big-endian bytes.
5. `flush` — the buffered writer holds everything until you flush; **the flush is
   what makes the frame observable to the peer.** Forgetting it is the classic
   "peer hangs forever" bug.

### Decode path (ReadFrame)

The mirror image:

1. `readHeader` — read exactly 8 bytes; unpack fields; validate version; return the
   decoded total length.
2. `readPayload` — convert total length → payload length, **bound it**, then read
   exactly that many bytes (skip if zero).
3. `readAndVerifyCRC` — read the 4 trailing bytes, recompute CRC over the payload,
   compare; mismatch is an error.

Return the frame only after all three succeed.

### Go reference implementation

```go
// Package protocol defines the wire protocol: framing, versioning, and the codec.
package protocol

import (
	"bufio"
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
)

const (
	FrameHeaderSize = 8
	FrameOverhead   = FrameHeaderSize + 4
	MaxPayloadSize  = 16 * 1024 * 1024
	ProtocolVersion = 1
)

var (
	ErrPayloadTooLarge      = errors.New("payload exceeds maximum size")
	ErrUnsupportedVersion   = errors.New("unsupported protocol version")
	ErrInvalidPayloadLength = errors.New("invalid payload length")
	ErrCRCMismatch          = errors.New("frame crc mismatch")
)

// FrameType identifies the kind of message a frame carries.
type FrameType uint8

const (
	FrameTypeHandshake FrameType = iota
	FrameTypePing
	FrameTypePong
	FrameTypeData
)

// Frame is the in-memory form of one wire message. The codec derives the
// length field and CRC at write time, so callers set only the semantic fields.
type Frame struct {
	Version uint8
	Type    FrameType
	Flags   uint8
	Payload []byte
}

// totalLength returns the full encoded size: header + payload + CRC.
func (f Frame) totalLength() uint32 {
	return uint32(FrameOverhead + len(f.Payload))
}

// Codec reads and writes frames over one bidirectional stream.
type Codec struct {
	reader *bufio.Reader
	writer *bufio.Writer
}

// NewCodec builds a codec over any reader/writer — a socket, a TLS conn, or an
// in-memory pipe in tests. It does not care what the bytes travel over.
func NewCodec(r io.Reader, w io.Writer) *Codec {
	return &Codec{reader: bufio.NewReader(r), writer: bufio.NewWriter(w)}
}

// WriteFrame encodes one frame and flushes it so the peer can observe it.
func (c *Codec) WriteFrame(frame Frame) error {
	if len(frame.Payload) > MaxPayloadSize {
		return fmt.Errorf("%w: %d > %d", ErrPayloadTooLarge, len(frame.Payload), MaxPayloadSize)
	}

	header := make([]byte, FrameHeaderSize)
	binary.BigEndian.PutUint32(header[0:4], frame.totalLength())
	header[4] = frame.Version
	header[5] = uint8(frame.Type)
	header[6] = frame.Flags
	header[7] = 0
	if _, err := c.writer.Write(header); err != nil {
		return fmt.Errorf("write frame header: %w", err)
	}

	if len(frame.Payload) > 0 {
		if _, err := c.writer.Write(frame.Payload); err != nil {
			return fmt.Errorf("write frame payload: %w", err)
		}
	}

	crc := make([]byte, 4)
	binary.BigEndian.PutUint32(crc, crc32.ChecksumIEEE(frame.Payload))
	if _, err := c.writer.Write(crc); err != nil {
		return fmt.Errorf("write frame crc: %w", err)
	}

	if err := c.writer.Flush(); err != nil {
		return fmt.Errorf("flush frame: %w", err)
	}
	return nil
}

// ReadFrame reads the next whole frame. A clean close before a new header
// begins is surfaced as io.EOF.
func (c *Codec) ReadFrame() (Frame, error) {
	header := make([]byte, FrameHeaderSize)
	if _, err := io.ReadFull(c.reader, header); err != nil {
		if err == io.EOF {
			return Frame{}, io.EOF
		}
		return Frame{}, fmt.Errorf("read frame header: %w", err)
	}

	frame := Frame{Version: header[4], Type: FrameType(header[5]), Flags: header[6]}
	if frame.Version != ProtocolVersion {
		return Frame{}, fmt.Errorf("%w: %d", ErrUnsupportedVersion, frame.Version)
	}

	total := binary.BigEndian.Uint32(header[0:4])
	if total < FrameOverhead {
		return Frame{}, fmt.Errorf("%w: %d", ErrInvalidPayloadLength, int(total)-FrameOverhead)
	}
	payloadLen := int(total - FrameOverhead)
	if payloadLen > MaxPayloadSize {
		return Frame{}, fmt.Errorf("%w: %d", ErrInvalidPayloadLength, payloadLen)
	}

	if payloadLen > 0 {
		frame.Payload = make([]byte, payloadLen)
		if _, err := io.ReadFull(c.reader, frame.Payload); err != nil {
			return Frame{}, fmt.Errorf("read frame payload: %w", err)
		}
	}

	crc := make([]byte, 4)
	if _, err := io.ReadFull(c.reader, crc); err != nil {
		return Frame{}, fmt.Errorf("read frame crc: %w", err)
	}
	expected := binary.BigEndian.Uint32(crc)
	if actual := crc32.ChecksumIEEE(frame.Payload); actual != expected {
		return Frame{}, fmt.Errorf("%w: expected %08x, got %08x", ErrCRCMismatch, expected, actual)
	}
	return frame, nil
}
```

### Python reference implementation

Mirror the Go design exactly. Use `struct` for big-endian packing, `zlib.crc32`
for the checksum, and a `recv_exactly` loop as the read-fully primitive.

```python
"""Wire protocol: framing, versioning, and the codec for a TCP client/server."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from enum import IntEnum
from typing import BinaryIO

FRAME_HEADER_SIZE = 8
FRAME_OVERHEAD = FRAME_HEADER_SIZE + 4  # header + CRC
MAX_PAYLOAD_SIZE = 16 * 1024 * 1024
PROTOCOL_VERSION = 1

# "!" = network byte order (big-endian); I=uint32, B=uint8.
_HEADER_STRUCT = struct.Struct("!IBBBB")  # total_len, version, type, flags, reserved
_CRC_STRUCT = struct.Struct("!I")


class CodecError(Exception):
    """Base class for all framing errors."""


class PayloadTooLargeError(CodecError):
    """A caller tried to encode a payload larger than MAX_PAYLOAD_SIZE."""


class UnsupportedVersionError(CodecError):
    """A decoded frame advertised a protocol version we do not implement."""


class InvalidPayloadLengthError(CodecError):
    """The decoded total length cannot describe a legal payload."""


class CRCMismatchError(CodecError):
    """Payload bytes did not match the appended CRC-32 checksum."""


class FrameType(IntEnum):
    """Identifies the kind of message a frame carries."""

    HANDSHAKE = 0
    PING = 1
    PONG = 2
    DATA = 3


@dataclass
class Frame:
    """In-memory form of one wire message.

    The codec derives the length field and CRC at write time, so callers set
    only the semantic fields.
    """

    version: int = PROTOCOL_VERSION
    type: FrameType = FrameType.DATA
    flags: int = 0
    payload: bytes = field(default=b"")

    def total_length(self) -> int:
        """Return the full encoded size: header + payload + CRC."""
        return FRAME_OVERHEAD + len(self.payload)


def _recv_exactly(*, reader: BinaryIO, count: int) -> bytes:
    """Read exactly ``count`` bytes, looping over short reads.

    Raises:
        EOFError: If the stream closes before ``count`` bytes arrive. An empty
            read on the very first byte is a clean close; a short read after
            some bytes is a truncation.
    """
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = reader.read(remaining)
        if not chunk:
            raise EOFError("stream closed before frame was complete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class Codec:
    """Reads and writes frames over one bidirectional stream.

    Bind one codec per connection. The stream is any file-like object with
    ``read``/``write``/``flush`` — a socket's ``makefile()``, a TLS wrapper, or
    an ``io.BytesIO`` in tests.
    """

    def __init__(self, *, reader: BinaryIO, writer: BinaryIO) -> None:
        """Store the reader and writer this codec frames over."""
        self._reader = reader
        self._writer = writer

    def write_frame(self, *, frame: Frame) -> None:
        """Encode one frame and flush it so the peer can observe it."""
        if len(frame.payload) > MAX_PAYLOAD_SIZE:
            raise PayloadTooLargeError(
                f"{len(frame.payload)} > {MAX_PAYLOAD_SIZE}"
            )

        header = _HEADER_STRUCT.pack(
            frame.total_length(),
            frame.version,
            int(frame.type),
            frame.flags,
            0,  # reserved
        )
        checksum = zlib.crc32(frame.payload) & 0xFFFFFFFF
        self._writer.write(header + frame.payload + _CRC_STRUCT.pack(checksum))
        self._writer.flush()

    def read_frame(self) -> Frame:
        """Read the next whole frame from the stream.

        Raises:
            EOFError: On a clean close before a new header begins.
            CodecError: On an unsupported version, illegal length, or bad CRC.
        """
        header = _recv_exactly(reader=self._reader, count=FRAME_HEADER_SIZE)
        total_length, version, raw_type, flags, _reserved = _HEADER_STRUCT.unpack(header)
        if version != PROTOCOL_VERSION:
            raise UnsupportedVersionError(str(version))

        if total_length < FRAME_OVERHEAD:
            raise InvalidPayloadLengthError(str(total_length - FRAME_OVERHEAD))
        payload_length = total_length - FRAME_OVERHEAD
        if payload_length > MAX_PAYLOAD_SIZE:
            raise InvalidPayloadLengthError(str(payload_length))

        payload = (
            _recv_exactly(reader=self._reader, count=payload_length)
            if payload_length
            else b""
        )

        (expected,) = _CRC_STRUCT.unpack(
            _recv_exactly(reader=self._reader, count=4)
        )
        actual = zlib.crc32(payload) & 0xFFFFFFFF
        if actual != expected:
            raise CRCMismatchError(f"expected {expected:08x}, got {actual:08x}")

        return Frame(
            version=version,
            type=FrameType(raw_type),
            flags=flags,
            payload=payload,
        )
```

#### Wiring the Python codec to a real socket

`socket` objects are not ideal file-likes for framed reads; wrap them:

```python
def build_codec_for_socket(*, sock: socket.socket) -> Codec:
    """Build a buffered Codec over a connected TCP socket."""
    reader = sock.makefile("rb")  # buffered, supports short-read looping
    writer = sock.makefile("wb")
    return Codec(reader=reader, writer=writer)
```

### Testing the codec (do this for every field and guard)

Write these before declaring the codec done — they prove the guarantees:

1. **Round-trip:** encode a frame, decode it back, assert equality — for empty,
   small, and `MaxPayloadSize` payloads, and for every `FrameType`.
2. **Split reads:** feed the encoded bytes to the decoder one byte at a time (or
   in odd chunks) and assert it still reconstructs one frame. This proves the
   read-fully primitive handles TCP fragmentation.
3. **Clean EOF:** an empty stream decodes to EOF, not an error.
4. **Truncation:** a stream that ends mid-header or mid-payload raises a
   truncation error, not EOF and not a partial frame.
5. **Oversized length:** hand-craft a header claiming a huge payload; assert the
   decoder rejects it *without allocating* (invalid-length error).
6. **Bad version:** flip the version byte; assert an unsupported-version error.
7. **Corruption:** flip one payload byte after encoding; assert a CRC-mismatch
   error.

### Checklist

- [ ] Length-prefix framing (never delimiters for binary).
- [ ] Fixed header with version, type, flags, reserved; big-endian integers.
- [ ] Shared named constants for header size, overhead, max payload, version.
- [ ] Bound the payload length **before** allocating the buffer.
- [ ] Read exactly N bytes with a read-fully loop; never trust one read.
- [ ] Validate version right after the header; verify CRC last.
- [ ] Flush after writing a frame.
- [ ] Clean close → EOF; partial frame → truncation error.
- [ ] One small orchestrator method per direction, one helper per phase.
- [ ] Tests for round-trip, split reads, EOF, truncation, oversized length,
      bad version, and corruption.
