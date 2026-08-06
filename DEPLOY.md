# Production deployment

gsubs production runs on the self-managed Hetzner host with Docker Compose.
The complete release, verification, backup, restore, retention, and privacy
procedure is maintained in [`deploy/hetzner/README.md`](deploy/hetzner/README.md).

Persistent source media, extracted audio, subtitles, and generated videos must
remain in the dedicated local `subframe-app-data` Docker volume. The disclosed
ElevenLabs processor still receives the extracted audio needed for Scribe; it
is not a GSUBS storage destination. Do not add an external object-storage
upload path, storage credential, or stateless deployment lane for real customer
media.

Before a release, run the repository quality gates on a machine with JDK 25,
create and independently verify the required encrypted backups, and deploy an
immutable commit from `main`. The production deploy script keeps the public
edge stopped until retention and post-backup erasure reconciliation succeed.
It also refuses to start against restored user data when the current live
erasure-journal continuity state is missing; under the zero-extra-storage
policy that recovery must start empty instead of publishing stale personal
data.
Do not bypass those gates and do not deploy from an unreviewed working tree.
