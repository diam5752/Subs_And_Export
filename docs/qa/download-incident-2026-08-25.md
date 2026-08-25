# Private download incident — 2026-08-25

## User-visible symptom

At 22:52 Europe/Athens, an authenticated 49.0 MiB MP4 download from
`gsubs.gr` showed about three minutes remaining after only 5.4 MiB had arrived.
The transfer was not waiting for a render: the response had already started and
the artifact was complete and available through the owner-scoped static route.

## Production evidence

All GSubs measurements below used the same authenticated production artifact.
No provider, billing, transcription or other paid API was called.

| Measurement | Result |
| --- | ---: |
| Exact screenshot-era browser download | 49.0 MiB in 201.737 s, 0.243 MiB/s |
| Post-release full HTTP/3 browser transfer | 49.0 MiB in 194.966 s, 0.251 MiB/s |
| Backend emission for that HTTP/3 transfer | 49.0 MiB in 73.537 ms, 666.494 MiB/s |
| Controlled HTTP/2 16 MiB range | 16 MiB in 1.924 s, 8.318 MiB/s |
| Controlled HTTP/2 full response | 49.0 MiB in 7.818 s, 6.269 MiB/s |
| Final native-browser HTTP/2 download | 49.0 MiB in 7.835 s, 6.256 MiB/s |

The public Caddy recorded the exact screenshot-era browser request as a
successful HTTP/3 200 response containing all 51,392,720 bytes. It finished at
19:55:57 UTC after 201.737 seconds, putting its start at about 19:52:35 UTC and
matching the 19:52:55 UTC screenshot. Diagnostic range responses returned HTTP
206 with exact `Content-Range`, `Content-Length` and `Accept-Ranges: bytes`, and
omitted content encoding. This rules out render time, malformed range handling,
media recompression and a general browser or local-network throughput cap. It
also rules out concurrent application work: the production access log contains
no process or upload request during the incident window. The response was slow
only on the public HTTP/3 body path after authentication and headers completed.

## Root cause

The user-visible bottleneck was the shared public Caddy edge's HTTP/3/QUIC path,
not rendering, authentication, disk reads or the GSubs application. After the
application release added transfer telemetry, the backend emitted the complete
51,392,720-byte response in 73.537 ms while the outer Caddy still needed
194.966 seconds to finish the same HTTP/3 browser response. The same file and
client path completed in 7.818 seconds when constrained to HTTP/2. That A/B
result is about 25 times faster and isolates the defective transport layer.

The evidence does not distinguish a Caddy/quic-go congestion-control fault from
a path-MTU or other UDP-path interaction, so this record does not claim a
lower-level cause that production data cannot prove. It is sufficient to keep
HTTP/3 quarantined on this edge until a controlled full-file test demonstrates
acceptable throughput.

Starlette's default 64 KiB `FileResponse` chunk size was a real secondary
inefficiency: a 16 MiB response required 257 ASGI body writes because Uvicorn
does not advertise `http.response.pathsend`. Increasing the bounded chunk to
1 MiB reduces that to 17 writes and adds useful per-transfer telemetry, but the
post-release HTTP/3 result proved that write amplification was not the primary
incident cause.

## Observability gap

Before the release, the public Caddy access log recorded total response size,
status and end-to-end duration, but the application could not show its own
emission time. Structured `private_media_transfer` events now record completion,
cancellation or failure with emitted bytes, duration and throughput. Comparing
that event with the outer access log is what separated the fast backend from the
slow HTTP/3 edge without logging user identity, cookies, filenames or contents.

## Remediation

- Keep the shared public HTTPS listener on `protocols h1 h2`; do not advertise
  `Alt-Svc` for HTTP/3. The previous Caddyfile was backed up before the atomic
  change and both GSubs and Ascentia health endpoints were verified afterwards.
- Use a bounded 1 MiB private-media chunk size. The same 16 MiB response now
  requires 17 ASGI body writes instead of 257, a 15.1x reduction, while keeping
  memory bounded to about 1 MiB per active response.
- Preserve owner authentication, symlink isolation, `private, no-store`, exact
  byte ranges and safe content disposition.
- Emit one structured completion, cancellation or failure event per private
  transfer with job UUID, transfer kind, HTTP status, emitted bytes, duration,
  range presence and measured throughput. Do not log user identity, filename,
  query string, cookie, bearer token or media contents.
- Cover full responses, ranges, sendfile-capable servers, disconnects and
  malformed observer metadata with regression tests. The transfer module has
  100% focused line coverage.
- Fail production verification when `https://gsubs.gr/health` is not HTTP/2 200
  or advertises HTTP/3. Run the same external contract check nightly so a shared
  edge configuration regression is visible without waiting for a user report.

## Production acceptance

After disabling HTTP/3 on the outer edge, the normal authenticated History
dialog downloaded the complete 51,392,720-byte MP4 through Chromium in
8.691 seconds including browser event overhead. The outer Caddy recorded the
full HTTP/2 200 body in 7.835 seconds (6.256 MiB/s), and `ffprobe` validated the
downloaded H.264/AAC file as 1080x1920 with an 82.804-second duration. GSubs and
Ascentia both returned HTTP/2 200 after the shared-edge restart, and every GSubs
container remained healthy.

HTTP/3 may be reconsidered only after a full authenticated browser download on
the production Internet path is correct and sustains at least 2 MiB/s. Small
ranges, loopback tests and green health endpoints are explicitly insufficient.
