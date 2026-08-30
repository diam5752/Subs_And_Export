# GSubs for iOS

The first native client keeps source video, preview, subtitle editing and final
rendering on the iPhone. It sends only a locally extracted AAC/M4A audio track to
the authenticated GSUBS endpoint and receives word-timed subtitle JSON.

This distinction is important: the app avoids video upload and server-side FFmpeg
storage/compute, but Scribe v2 cannot work without temporarily transferring audio.
True zero-transfer transcription would require a separate on-device speech model.

## Build

The generated Xcode project is committed for direct use. Regenerate it after
editing `project.yml` with:

```bash
cd ios
xcodegen generate --spec project.yml
```

Open `GSubs.xcodeproj`, choose an iPhone simulator or device, and run the `GSubs`
scheme. The default API base is `https://gsubs.gr`, stored as
`GSubsAPIBaseURL` in the generated Info.plist. Signing requires selecting the
owner's Apple Developer team before installing on a physical iPhone.

Run the native regression suite with:

```bash
xcodebuild \
  -project GSubs.xcodeproj \
  -scheme GSubs \
  -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.4' \
  test
```

The export test creates a real H.264 source, burns a Greek cue locally, exports an
MP4, and reopens it with AVFoundation to prove the artifact is decodable.

## Privacy and billing contract

- The app has no code path that posts the selected video or exported MP4.
- Temporary device files are removed when the project is reset or replaced.
- The API rejects any request containing a video stream. Its body must be AAC
  audio only and is capped at 16 MiB at both edge and backend.
- Server-authoritative duration and the explicitly confirmed 30-credit ceiling are
  checked before dispatch.
- Each request uses an idempotency key; failures refund the reservation and a
  replay cannot dispatch or charge twice.
- Replay-safe subtitle cues remain in the live database for at most the existing
  24-hour terminal-job window. They can remain only in encrypted backups for up
  to the documented 14-day backup-retention window.
- Production chooses ElevenLabs Scribe v2 server-side. Local/default development
  remains deterministic and zero-cost.
