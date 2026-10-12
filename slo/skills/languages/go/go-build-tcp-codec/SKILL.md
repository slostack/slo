---
name: go-build-tcp-codec
description: Go typed framed protocol adapters with bounded decoding, partial-read/write handling, connection-owned
  cancellation and fuzz/race tests.
when_to_use: Go typed framed protocol adapters with bounded decoding, partial-read/write handling, connection-owned
  cancellation and fuzz/race tests.
group: languages
kind: skill
---

# Go Build Tcp Codec

## Skill summary

Go typed framed protocol adapters with bounded decoding, partial-read/write handling, connection-owned cancellation and fuzz/race tests.

## Examples

- Apply this guidance to the scoped task before implementing or reviewing.

## Guidance

Separate wire framing/encoding from domain policy and connection lifecycle. A named FrameDAO carries protocol fields; a resolved connection/runtime owns the socket and cancellation. Decode validates intrinsic length/version/type limits before allocating; the application owns contextual policy. Preserve byte order, tags and error rendering as external contracts.

For a length-prefixed protocol, use io.ReadFull for the fixed header and bounded payload. Reject lengths above the approved maximum before make([]byte, n), check integer overflow, distinguish clean EOF between frames from io.ErrUnexpectedEOF within a frame, and translate errors without losing errors.Is. A writer must handle short writes and return an error if n == 0 without progress. A single connection owner serializes writes so concurrent frames cannot interleave.

A named `ReadFrame(ctx, ReadDAO{Reader: reader, MaxBytes: limit}) (FrameDAO, error)` is appropriate only if cancellation is actually implemented: io.Reader alone cannot observe context. A net.Conn adapter sets deadlines or closes on owned cancellation; stop and join any cancellation watcher. Pure Encode/Decode byte transformations do not take context.

Test zero/max/over-limit lengths, unknown versions, truncation at each header/payload byte, fragmented reads, short writes, no-progress writers, multiple consecutive frames, deadline and cancellation, errors.Is, and cleanup after decode failure. Use bytes.Buffer for pure codec units, net.Pipe or ephemeral loopback for connection integration, and fuzz decode with bounded allocation invariants. `go test -race` covers concurrent writers/lifecycle. Golden byte fixtures protect wire compatibility; do not update them merely to hide a change.

