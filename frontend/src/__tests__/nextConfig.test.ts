describe('next.config', () => {
  const originalApiBase = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    if (originalApiBase === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = originalApiBase;
    }
  });

  it('allows media and images from API base', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8080';

    const nextConfigModule = await import('../../next.config');
    const headers = await nextConfigModule.default.headers?.();
    const csp = headers?.[0]?.headers?.find((header) => header.key === 'Content-Security-Policy')?.value;

    expect(csp).toContain("media-src 'self' http://localhost:8080");
    expect(csp).toContain("img-src 'self' http://localhost:8080");
    expect(csp).toContain("connect-src 'self' http://localhost:8080");
  });

  it('defaults CSP API access to the frontend API base fallback', async () => {
    delete process.env.NEXT_PUBLIC_API_URL;

    const nextConfigModule = await import('../../next.config');
    const headers = await nextConfigModule.default.headers?.();
    const csp = headers?.[0]?.headers?.find((header) => header.key === 'Content-Security-Policy')?.value;

    expect(csp).toContain("img-src 'self' http://localhost:8080");
    expect(csp).toContain("media-src 'self' http://localhost:8080");
    expect(csp).toContain("connect-src 'self' http://localhost:8080");
  });

  it('keeps production API access same-origin when configured with an empty base', async () => {
    process.env.NEXT_PUBLIC_API_URL = '';

    const nextConfigModule = await import('../../next.config');
    const headers = await nextConfigModule.default.headers?.();
    const csp = headers?.[0]?.headers?.find((header) => header.key === 'Content-Security-Policy')?.value;

    expect(csp).toContain("connect-src 'self' https://accounts.google.com");
    expect(csp).not.toContain('localhost:8080');
  });

  it('allows Google Identity Services in the production CSP', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'https://api.example.test';

    const nextConfigModule = await import('../../next.config');
    const headers = await nextConfigModule.default.headers?.();
    const csp = headers?.[0]?.headers?.find((header) => header.key === 'Content-Security-Policy')?.value;

    expect(csp).toContain("script-src 'self'");
    expect(csp).toContain('https://accounts.google.com');
    expect(csp).toContain('connect-src');
    expect(csp).toContain('frame-src https://accounts.google.com');
  });

  it('allows local loopback dev origins for Next assets in CI', async () => {
    // REGRESSION: GitHub Actions Playwright runs can request dev assets from
    // 127.0.0.1 even when the main page uses localhost, which otherwise breaks
    // dashboard hydration and E2E shell rendering.
    const nextConfigModule = await import('../../next.config');

    expect(nextConfigModule.default.allowedDevOrigins).toEqual(
      expect.arrayContaining(['127.0.0.1', 'localhost']),
    );
  });

  it('keeps the localhost QA surface free of framework UI', async () => {
    const nextConfigModule = await import('../../next.config');

    expect(nextConfigModule.default.devIndicators).toBe(false);
  });
});
