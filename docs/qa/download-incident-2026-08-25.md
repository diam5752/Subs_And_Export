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
| Exact browser download in the public Caddy access log | 49.0 MiB in 201.737 s, 0.243 MiB/s |
| Initial 8 MiB range | 1.031 s, 7.74 MiB/s |
| Isolated 16 MiB range, no cache and no competing request | 50.721 s, 0.315 MiB/s |
| Isolated range response start | 0.394 s |
| Isolated range response body after headers | 50.327 s |
| Same-browser independent 16 MiB control | 1.154 s, 13.86 MiB/s |

The public Caddy recorded the exact screenshot-era browser request as a
successful HTTP/3 200 response containing all 51,392,720 bytes. It finished at
19:55:57 UTC after 201.737 seconds, putting its start at about 19:52:35 UTC and
matching the 19:52:55 UTC screenshot. Diagnostic range responses returned HTTP
206 with exact `Content-Range`, `Content-Length` and `Accept-Ranges: bytes`, and
omitted content encoding. This rules out render time, malformed range handling,
media recompression and a general browser or local-network throughput cap. It
localizes the delay to the GSubs private-file response body after authentication
and headers completed.

## Root cause

The private route used Starlette's default `FileResponse.chunk_size` of 64 KiB.
With Uvicorn, which does not advertise Starlette's `http.response.pathsend`
extension, a 16 MiB response is emitted as 257 ASGI body writes. Production
serves that stream through the internal GSubs Caddy and the public edge. The
observed long-response backpressure was therefore amplified across hundreds of
small application writes: the isolated sample spent about 196 ms per emitted
write on average after the response started.

The short 8 MiB burst did not expose the steady-state backpressure, which is why
the earlier loopback and small-range checks passed while a real 49 MiB browser
download remained slow. The previous five-download loopback check explicitly
was not an Internet-path claim and did not simulate chained-proxy backpressure.

## Observability gap

The public Caddy access log recorded the successful request's total response
size, status and end-to-end duration. The application itself did not record the
transfer: `uvicorn.access` is disabled, the internal GSubs Caddy has no access
log, and pipeline metrics are disabled by default in production. The existing
logs could therefore prove the 201.737-second symptom, but not how the backend's
body writes progressed, whether a disconnect was partial, or the application-
side throughput of each authenticated transfer.

## Remediation

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
  malformed observer metadata with regression tests. The new transfer module
  has 100% focused line coverage.

## Production acceptance

After deployment, repeat an isolated authenticated 16 MiB range against the
same public route and read back its structured completion event. The release is
accepted only if range semantics remain exact, the transfer completes without
errors and the sustained public-path result is materially above the incident's
0.315 MiB/s. A result below 2 MiB/s triggers the next bounded step: move the
post-authentication file body to a dedicated static-serving process rather than
weakening authentication or caching private media.
