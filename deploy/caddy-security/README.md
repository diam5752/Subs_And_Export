# Patched stock Caddy

The production Compose file requires `CADDY_IMAGE`. Keep its value in the existing private production environment as an immutable, locally loaded image ID.

This recipe builds upstream Caddy 2.11.7 commit `72dd0fb067f6d7826c7f79907670ba4a713bfe37` with Go 1.27.3, golang.org/x/net 0.60.0 and chi 5.4.0. The source archive SHA-256 and both official base image digests are pinned. Available Alpine security updates are applied to the final image. The upstream stock module set is preserved.

On the Linux production build host, run:

```sh
CADDY_IMAGE="$(./deploy/caddy-security/build.sh)"
docker image inspect "$CADDY_IMAGE" >/dev/null
printf 'CADDY_IMAGE=%s\n' "$CADDY_IMAGE"
```

The helper loads a local linux/amd64 image and prints its actual image ID. Build logs go to stderr. It publishes no image and requires no registry credentials. `CADDY_BUILD_PLATFORM` and `CADDY_BUILD_IMAGE` allow another local build target.

Record the printed value in the private mode-0600 production environment, preserving all existing settings. On the shared production host, the reviewed 27 October artifact is `sha256:7593ef0066af1c00f671db8b35880ceb1097fcef2ea07c250e45f5c6bece8ad1`. Use the ID printed by each later build; Docker build metadata can change that ID.

Before promotion, scan the actual image and validate the deployed Caddy configurations and module set. Check HTTP, streamed SSE and WebSocket behavior on isolated fixtures, then follow the project's exact-release, backup, lock and live-verification procedure. Never replace the loaded image ID with an older floating Caddy tag.

## Existing proxy user context

The final stock Caddy stage retains the upstream and current production UID0 contract for existing root-owned TLS keys, data/config volumes and listener bindings. This dependency update introduces no user, capability, privilege or mount change. The structured trivy-role-exception.yaml records DS-0002 for this recipe file only. Trivy cannot apply an inline ignore to an absent USER instruction. Its scope is the recipe file and current final-image role; it does not exempt dependency CVEs or application images.

Retain caller-owned isolation and controls: private Docker networks, loopback host bindings, read-only configuration mounts, log rotation and configured process/resource limits. Keep any deployment-level no-new-privileges policy in place. Changes to proxy UID or volume/key custody require their own permissions, configuration and runtime validation.

For configuration scans, use `trivy config --ignorefile deploy/caddy-security/trivy-role-exception.yaml .`. Keep normal image vulnerability scans enabled separately. The same ignore configuration must still reject an unrelated root application Dockerfile.
