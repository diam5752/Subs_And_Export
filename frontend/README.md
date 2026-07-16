# SUBFRAME web app

Next.js 16 / React 19 / Tailwind CSS 4 frontend for the SUBFRAME subtitle
studio. `npm` and `package-lock.json` are the package-manager source of truth.

```bash
npm ci
npm run dev
```

Useful checks:

```bash
npm run lint
npm test -- --runInBand
npm run build
npm run e2e
```

The production build is an installable PWA. It caches only the safe application
shell; authenticated API, job, media and export responses are never stored by
the service worker.
