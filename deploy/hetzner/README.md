# Hetzner production lane

SUBFRAME runs as an independent Docker Compose project on the MizAI Hetzner VM.
It shares only the existing edge network so a reverse proxy can reach the
`subframe-edge` alias. PostgreSQL, media data, logs, images and the private
network remain separate from MizAI and the other projects on the host.

```bash
cp deploy/hetzner/subframe.env.example .env.production
# Fill the random database password, exact SHA and age public recipient.
SUBFRAME_ENV_FILE=/home/mizai/subframe/.env.production \
  ./deploy/hetzner/deploy-production.sh
SUBFRAME_ENV_FILE=/home/mizai/subframe/.env.production \
  ./deploy/hetzner/verify-production.sh
```

The tracked production compose forces mock services and zero external-provider
budgets. It exposes only the edge service on `127.0.0.1:18090` by default; no
port is reachable from the public internet. Until a domain exists, an operator
can preview it through an SSH local-forward and open `http://127.0.0.1:18090`:

```bash
ssh -N -L 127.0.0.1:18090:127.0.0.1:18090 root@SERVER
```

The deploy script does not prune the shared Docker build cache by default,
because the VM also hosts MizAI and other projects. Set
`SUBFRAME_PRUNE_BUILD_CACHE=1` only during an explicit disk-recovery operation.

When the final domain is chosen:

1. Set `SUBFRAME_HOSTNAME`, `GSP_ALLOWED_ORIGINS`, and `GSP_TRUSTED_HOSTS` in
   `.env.production`.
2. Route the hostname through the existing reverse proxy or Cloudflare Tunnel
   to `http://subframe-edge:8080`.
3. Create the DNS record and rerun the deploy and verification scripts.
4. Verify the public HTTPS UI, `/health`, upload-to-login gate, and mock export.

The frontend uses a same-origin API URL, so changing the domain does not require
a separate frontend code change.

Before every release, back up MizAI and copy that encrypted backup off-server.
After SUBFRAME has user data, run `deploy/hetzner/backup.sh` and copy its output
off-server as well.
