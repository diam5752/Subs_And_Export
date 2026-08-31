# GSubs for iOS

The first native client keeps source video, preview, subtitle editing and final
rendering on the iPhone. It sends only a locally extracted AAC/M4A audio track to
the authenticated GSUBS endpoint and receives word-timed subtitle JSON.

This distinction is important: the app avoids video upload and server-side FFmpeg
storage/compute, but Scribe v2 cannot work without temporarily transferring audio.
True zero-transfer transcription would require a separate on-device speech model.

## On-device editor

Once cues arrive, the phone editor uses one fixed, non-scrolling screen in
portrait and landscape. Select a cue with Previous/Next or the `1 / N` picker;
selection pauses and seeks the preview to that cue. Text, cue position, and
global size, color, and position controls remain available together, including
the compact keyboard layout.

Cues inherit the global position by default. Moving one cue creates an optional
override; Common/reset removes only that override. Text edits preserve it, and
preview and burned-in export use the same placement geometry. Editing and
playback pause while an export is running so the visible preview cannot diverge
from the MP4 snapshot.

## Build

The app requires iOS 17.0 or newer and supports portrait plus both landscape
orientations.

The generated Xcode project is committed for direct use. Regenerate it after
editing `project.yml` with:

```bash
cd ios
xcodegen generate --spec project.yml
```

Open `GSubs.xcodeproj`, choose an iPhone simulator or device, and run the `GSubs`
scheme. It uses the immutable production API base `https://gsubs.gr`. The
`GSubs Local` scheme is a deliberate development-only alternative that injects
`http://localhost:8080` through `GSUBS_API_BASE_URL`; Release builds ignore that
environment override. Automatic signing is pinned to the owner's non-secret
Apple Developer team identifier, while certificates and provisioning profiles
remain outside the repository.

Format every native source with the repository's canonical Swift policy, then
lint it without allowing warnings:

```bash
cd ios
xcrun swift-format format \
  --configuration .swift-format \
  --recursive \
  --in-place \
  GSubs GSubsTests GSubsUITests
xcrun swift-format lint \
  --configuration .swift-format \
  --recursive \
  --strict \
  GSubs GSubsTests GSubsUITests
```

Every handwritten Swift file is limited to 700 physical lines. The path-scoped
macOS GitHub workflow regenerates the Xcode project, enforces both policies, and
runs the unit plus customer-path UI suite on an available iPhone simulator.

Run the native regression suite with:

```bash
cd ios
xcodebuild \
  -project GSubs.xcodeproj \
  -scheme GSubs \
  -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.4' \
  test
```

Run the focused model, local-media, and renderer regressions with:

```bash
cd ios
xcodebuild test \
  -project GSubs.xcodeproj \
  -scheme GSubs \
  -destination 'platform=iOS Simulator,name=iPhone 15,OS=17.4' \
  -only-testing:GSubsTests/SubtitleCueTests \
  -only-testing:GSubsTests/VideoExporterTests \
  -only-testing:GSubsTests/LocalMediaStoreTests \
  -only-testing:GSubsTests/VideoPreviewPreparerTests
```

Run the compact-editor acceptance checks on iPhone SE with:

```bash
cd ios
xcodebuild test \
  -project GSubs.xcodeproj \
  -scheme GSubs \
  -destination 'platform=iOS Simulator,name=iPhone SE (3rd generation),OS=17.4' \
  -only-testing:GSubsUITests/GSubsUITests/testSubtitleEditorFitsOnOneScreenAndKeyboard \
  -only-testing:GSubsUITests/GSubsUITests/testLandscapeKeyboardKeepsEveryEditorControlVisible \
  -only-testing:GSubsUITests/GSubsUITests/testLandscapeExportShowsSaveAndShareActions \
  -only-testing:GSubsUITests/GSubsUITests/testAccessibilityMaximumEditorFitsWithoutScrolling \
  -only-testing:GSubsUITests/GSubsUITests/testOnlySelectedCueGetsAPositionOverride \
  -only-testing:GSubsUITests/GSubsUITests/testEditingControlsFreezeWhileExporting
```

The full suite remains the final regression command.

The export test creates a real H.264 source, burns a Greek cue locally, exports an
MP4, and reopens it with AVFoundation to prove the artifact is decodable.

## Privacy and billing contract

- The app has no code path that posts the selected video or exported MP4.
- Video selection first enters a scratch area. Clips with a display dimension
  above 1920 pixels receive a local 720p preview proxy, while final export always
  uses the source video.
- After validation, the current source, optional preview proxy, cues, style and
  transcription idempotency key are committed atomically as one owner-bound
  draft under Application Support. The manifest contains only validated relative
  paths; the files use iOS data protection and are excluded from device backups.
  A draft is exposed only after `/auth/me` confirms the exact owner.
- Videos are limited to 3 minutes. Extracted M4A and rendered MP4 exports remain
  scratch files and are removed after use, reset or replacement. Reset,
  replacement, sign-out, invalid authentication and confirmed or ambiguous
  account deletion purge the persistent draft. Transient network/server failures
  keep it locked for a later authenticated retry. Stale scratch media is
  quarantined during launch cleanup.
- A confirmed account deletion removes the local token and private media. If a
  DELETE response is lost, the client retries once and still clears local
  private state when server confirmation remains ambiguous.
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
- `PrivacyInfo.xcprivacy` declares account, audio, and subtitle handling as app
  functionality, linked to the account and never used for tracking. The in-app
  privacy sheet links to `https://gsubs.gr/privacy`; App
  Store Connect must publish matching answers and that policy URL.
- This build is a free companion for an existing GSubs account: it can consume
  eligible credits but contains neither a purchase control nor a link that asks
  the customer to buy outside the app. Adding native credit purchases requires
  reviewed StoreKit products and server-side transaction verification before
  App Store submission.
