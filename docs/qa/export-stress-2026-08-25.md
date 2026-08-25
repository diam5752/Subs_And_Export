# Five-user export stress evidence — 2026-08-25

## Safety boundary

The upload path ran against an isolated local PostgreSQL database with six
synthetic accounts and `GSP_MOCK_EXTERNAL_SERVICES=1`. The completed jobs
reported `transcribe_provider=mock`. All provider budgets and paid Checkout
were disabled, so no transcription, LLM, Stripe, or other paid API request was
made.

The exact production-host comparison bypassed accounts, credits, the job
database, and transcription entirely. It invoked only the repository's FFmpeg
wrapper inside the running backend container, using the live render-capacity
locks. The production database had no active media job before either run.

## Workload

- Synthetic, high-motion `testsrc2` video; no customer media.
- H.264 + AAC, 720×1280, 30 fps, 30.0 seconds, 29,047,041 bytes.
- Export: 1080×1920 H.264, balanced CRF 23, `veryfast`, karaoke ASS burn-in,
  AAC stream copy, `+faststart`.
- Concurrency groups: 1, 2, 3, and 5 distinct authenticated local users.
- During each export group, `/health` was sampled about every 100 ms.

## Isolated end-to-end baseline

Uploads include real bearer authentication, streaming request handling,
filesystem persistence, PostgreSQL job state, audio extraction, deterministic
mock transcription, subtitle generation, render locks, and FFmpeg export.

| Users | Upload makespan | Export completion times | Export makespan | API heartbeat |
| ---: | ---: | --- | ---: | --- |
| 1 | 0.205 s | 8.652 s | 8.653 s | p50 1.74 ms, max 17.74 ms, 0 failures |
| 2 | 0.359 s | 9.220 / 9.275 s | 9.275 s | p50 1.97 ms, max 3.10 ms, 0 failures |
| 3 | 0.418 s | 9.209 / 9.291 / 17.624 s | 17.624 s | p50 1.81 ms, max 43.31 ms, 0 failures |
| 5 | 0.506 s | 9.106 / 9.106 / 18.555 / 18.625 / 26.999 s | 27.000 s | p50 1.84 ms, max 4.17 ms, 0 failures |

All eleven uploads completed, all exports returned HTTP 200, and every output
was 13,646,926 bytes. Five uploads completed their mock processing stage in at
most 0.131 seconds. The 3- and 5-user completion times show the intended
two-lane queue rather than hidden serialization or unbounded encoders.

## Exact production-container comparison

The host has four cores. The backend was running the deployed release
`740cfc478bacbb2262b05e2861d355e309aea8d8` with a 3-CPU, 3-GiB, 256-PID
cgroup. Five identical exports were submitted through the real two-slot render
pool.

| Threads per lane | Completion waves | Makespan | Throughput | Cgroup CPU | Peak memory | Peak PIDs | API heartbeat |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 16.089 / 16.165 / 31.957 / 32.007 / 47.395 s | 47.400 s | 6.33/min | 230.72% | 626.48 MB | 28 | p50 2.39 ms, max 7.59 ms, 0 failures |
| 2 | 13.656 / 13.854 / 27.195 / 27.240 / 34.189 s | 34.194 s | 8.77/min | 295.07% | 811.56 MB | 42 | p50 1.51 ms, max 27.62 ms, 0 failures |

Two bounded threads per lane reduced five-user makespan by 27.9% and raised
throughput by 38.5%. It remained far below the memory and PID limits. The
encoders run at niceness 10, and the API stayed responsive even while the
backend consumed its full idle CPU allowance.

## Post-change end-to-end rerun

The isolated application was restarted from the changed source without an
explicit thread override, proving the new default. The complete
auth/upload/mock-transcription/export flow then passed again for 1, 2, 3, and
5 users:

| Users | Upload makespan | Export completion times | Export makespan | API heartbeat |
| ---: | ---: | --- | ---: | --- |
| 1 | 0.222 s | 3.520 s | 3.520 s | p50 2.35 ms, max 18.88 ms, 0 failures |
| 2 | 0.213 s | 4.663 / 4.675 s | 4.675 s | p50 3.77 ms, max 8.54 ms, 0 failures |
| 3 | 0.289 s | 4.738 / 4.836 / 8.569 s | 8.570 s | p50 3.18 ms, max 48.48 ms, 0 failures |
| 5 | 0.511 s | 4.890 / 5.011 / 9.969 / 10.127 / 13.996 s | 13.997 s | p50 3.53 ms, max 5.83 ms, 0 failures |

Every request returned HTTP 200 and every job again reported the mock provider.
The slowest five-user mock-processing stage was 0.200 seconds. The final local
five-export makespan was 48.2% lower than the one-thread baseline, with no API
heartbeat failure.

Five authenticated full downloads were then requested together. All five
13,647,399-byte files completed in 0.256 seconds on loopback (68,236,995 bytes
total), had one identical SHA-256, advertised `Accept-Ranges: bytes`, omitted
`Content-Encoding`, and retained `Cache-Control: private, no-store`. Five
independent `bytes=0-1023` checks returned HTTP 206 with exact `Content-Range`
and 1,024-byte bodies. This verifies application delivery and range semantics;
loopback throughput is not an Internet-speed claim.

## Output equivalence

Both profiles produced 30.000-second, 1080×1920, 30-fps H.264 video with AAC
audio. The representative output sizes were 13,776,191 and 13,779,334 bytes
(a 0.023% difference). A decoded frame-by-frame comparison reported SSIM
`All:0.998258`, while both copied AAC streams had the same MD5
`7b3f71c12f752b33d7f1246267226075`. The thread change does not alter preset,
CRF, subtitle layout, resolution, frame rate, audio codec, or duration.

## Decision

Keep two render lanes so memory, storage reservations, and process count remain
bounded, but raise each normal lane from one to two FFmpeg worker threads. A 4K
export still reserves both lanes and the global FFmpeg guard still caps it at
two threads. This improves the measured bottleneck without changing machine,
quality settings, user capacity, provider traffic, or the fail-closed storage
contract.
