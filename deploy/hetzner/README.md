# Hetzner production lane

SUBFRAME runs as an independent Docker Compose project on the MizAI Hetzner VM.
It shares only the existing edge network so `mizai-cloudflared-1` can reach the
`subframe-edge` alias. PostgreSQL, media data, logs, images and private network
are separate from MizAI.

```bash
cp deploy/hetzner/subframe.env.example .env.production
# Fill the random database password, exact SHA and age public recipient.
SUBFRAME_ENV_FILE=/home/mizai/subframe/.env.production \
  ./deploy/hetzner/deploy-production.sh
```

The tracked production compose forces mock services and zero external-provider
budgets. It exposes no host ports. Cloudflare Tunnel should route
`subframe.mizai.gr` to `http://subframe-edge:8080`.

Before every release, back up MizAI and copy that encrypted backup off-server.
After SUBFRAME has user data, run `deploy/hetzner/backup.sh` and copy its output
off-server as well.
