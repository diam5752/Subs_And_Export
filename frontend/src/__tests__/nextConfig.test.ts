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
  });
});

