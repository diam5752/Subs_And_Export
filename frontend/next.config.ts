import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  // Playwright/Chromium can resolve dev assets from 127.0.0.1 in CI even when
  // the app is opened through localhost. Allow both loopback hosts so the dev
  // server does not block its own Next assets during E2E runs.
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
  async headers() {
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080';
    const apiSource = apiBase ? ` ${apiBase}` : '';
    // Allow connecting to the API backend
    const isDev = process.env.NODE_ENV !== 'production';
    const googleIdentityOrigin = 'https://accounts.google.com';
    const scriptSrc = isDev
      ? `script-src 'self' 'unsafe-eval' 'unsafe-inline' ${googleIdentityOrigin};`
      : `script-src 'self' 'unsafe-inline' ${googleIdentityOrigin};`;
    const csp = [
      `default-src 'self';`,
      `base-uri 'self';`,
      `object-src 'none';`,
      `frame-ancestors 'none';`,
      `img-src 'self'${apiSource} blob: data:;`,
      `media-src 'self'${apiSource} blob: data:;`,
      scriptSrc,
      `style-src 'self' 'unsafe-inline';`,
      `connect-src 'self'${apiSource} ${googleIdentityOrigin};`,
      `frame-src ${googleIdentityOrigin};`,
      `font-src 'self' data:;`,
    ].join(' ');

    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'X-DNS-Prefetch-Control',
            value: 'on'
          },
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=63072000; includeSubDomains; preload'
          },
          {
            key: 'X-Frame-Options',
            value: 'DENY'
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff'
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin'
          },
          {
            key: 'Content-Security-Policy',
            value: csp
          }
        ],
      },
    ]
  },
};

export default nextConfig;
