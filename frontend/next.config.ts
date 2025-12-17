import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  async headers() {
    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    // Allow connecting to the API backend
    const isDev = process.env.NODE_ENV !== 'production';
    const scriptSrc = isDev ? `script-src 'self' 'unsafe-eval' 'unsafe-inline';` : `script-src 'self' 'unsafe-inline';`;
    const csp = [
      `default-src 'self';`,
      `base-uri 'self';`,
      `object-src 'none';`,
      `frame-ancestors 'none';`,
      `img-src 'self' ${apiBase} blob: data:;`,
      `media-src 'self' ${apiBase} blob: data:;`,
      scriptSrc,
      `style-src 'self' 'unsafe-inline';`,
      `connect-src 'self' ${apiBase};`,
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
