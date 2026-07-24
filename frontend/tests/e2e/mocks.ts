import { Page, Route } from '@playwright/test';
import el from '@/i18n/el.json';

type MockJob = {
  id: string;
  status: 'completed' | 'processing' | 'pending' | 'failed';
  progress: number;
  message: string | null;
  created_at: number;
  updated_at: number;
  result_data: {
    video_path: string;
    artifacts_dir: string;
    public_url?: string;
    artifact_url?: string;
    transcription_url?: string;
    variants?: Record<string, string>;
    social?: string | null;
    original_filename?: string | null;
    video_crf?: number;
    transcribe_tier?: string;
    transcribe_provider?: string;
  } | null;
};

type MockHistoryEvent = {
  ts: string;
  user_id: string;
  email: string;
  kind: string;
  summary: string;
  data: Record<string, unknown>;
};

type MockApiOptions = {
  authenticated?: boolean;
};

const corsHeaders = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': '*',
  'access-control-allow-methods': 'GET,POST,PUT,OPTIONS',
};

const mockUser = {
  id: 'user-demo-1',
  email: 'demo@futurist.studio',
  name: 'Eleni Papadopoulou',
  provider: 'local',
};

const mockTranscription = [
  {
    start: 0,
    end: 4,
    text: 'ΒΑΛΤΕ ΥΠΟΘΕΣΕΙΣ ΚΑΙ ΕΛΑΤΕ ΝΑ ΦΤΙΑΞΟΥΜΕ ΜΙΑ ΟΜΑΔΑ',
    words: [
      { start: 0, end: 0.5, text: 'ΒΑΛΤΕ' },
      { start: 0.5, end: 1, text: 'ΥΠΟΘΕΣΕΙΣ' },
      { start: 1, end: 1.5, text: 'ΚΑΙ' },
      { start: 1.5, end: 2, text: 'ΕΛΑΤΕ' },
      { start: 2, end: 2.5, text: 'ΝΑ' },
      { start: 2.5, end: 3, text: 'ΦΤΙΑΞΟΥΜΕ' },
      { start: 3, end: 3.5, text: 'ΜΙΑ' },
      { start: 3.5, end: 4, text: 'ΟΜΑΔΑ' },
    ],
  },
];

const mockJobs: MockJob[] = [
  {
    id: 'job-futurist',
    status: 'completed',
    progress: 100,
    message: 'Rendered safely for mobile viewports',
    created_at: 1_714_000_000,
    updated_at: 1_714_003_600,
    result_data: {
      video_path: '/static/videos/futurist-showcase.mp4',
      artifacts_dir: '/static/artifacts/futurist-showcase.zip',
      public_url: '/static/videos/futurist-showcase.mp4',
      artifact_url: '/static/artifacts/futurist-showcase.zip',
      transcription_url: '/static/transcriptions/futurist-showcase.json',
      original_filename: 'GreekSubtitles_CaseStudy_Vertical_Edit_v4.mp4',
      video_crf: 12,
      transcribe_tier: 'pro',
      transcribe_provider: 'local',
    },
  },
  {
    id: 'job-creative-cut',
    status: 'processing',
    progress: 62,
    message: 'Aligning captions to the beat',
    created_at: 1_714_010_000,
    updated_at: 1_714_011_200,
    result_data: {
      video_path: '/static/videos/creative-cut.mp4',
      artifacts_dir: '/static/artifacts/creative-cut.zip',
      original_filename: 'GreekSubtitles_TrendingClip_Highlight.mp4',
      video_crf: 14,
      transcribe_tier: 'standard',
      transcribe_provider: 'openai',
    },
  },
  {
    id: 'job-long-form',
    status: 'pending',
    progress: 0,
    message: 'Queued for local turbo',
    created_at: 1_714_020_000,
    updated_at: 1_714_020_050,
    result_data: {
      video_path: '/static/videos/long-form.mp4',
      artifacts_dir: '/static/artifacts/long-form.zip',
      original_filename: 'A_very_long_filename_showing_wrapping_behavior_in_buttons.mp4',
      video_crf: 20,
      transcribe_tier: 'standard',
      transcribe_provider: 'local',
    },
  },
  {
    id: 'job-failed',
    status: 'failed',
    progress: 0,
    message: 'Upload failed — please retry',
    created_at: 1_714_030_000,
    updated_at: 1_714_030_100,
    result_data: {
      video_path: '/static/videos/failed.mp4',
      artifacts_dir: '/static/artifacts/failed.zip',
      original_filename: 'Short_fail_case.mp4',
      video_crf: 28,
      transcribe_tier: 'standard',
      transcribe_provider: 'local',
    },
  },
];

const jobLookup = new Map(mockJobs.map((job) => [job.id, job]));

const mockHistory: MockHistoryEvent[] = [
  {
    ts: '2024-04-25T10:04:00Z',
    user_id: mockUser.id,
    email: mockUser.email,
    kind: 'processing_completed',
    summary: 'Completed reel with safe subtitle margins',
    data: {},
  },
  {
    ts: '2024-04-25T09:55:00Z',
    user_id: mockUser.id,
    email: mockUser.email,
    kind: 'auth_login',
    summary: 'Signed in from Chrome on macOS',
    data: {},
  },
  {
    ts: '2024-04-24T18:20:00Z',
    user_id: mockUser.id,
    email: mockUser.email,
    kind: 'processing_started',
    summary: 'Queued long form cut for transcription',
    data: {},
  },
];

const unauthorizedResponse = {
  status: 401,
  headers: corsHeaders,
  contentType: 'application/json',
  body: JSON.stringify({ detail: 'Unauthorized' }),
};

function withCors(body: unknown, status = 200) {
  return {
    status,
    headers: corsHeaders,
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

export async function mockApi(page: Page, options: MockApiOptions = {}): Promise<void> {
  const { authenticated = true } = options;
  let signedIn = authenticated;
  let currentTranscription = mockTranscription.map((cue) => ({
    ...cue,
    words: cue.words.map((word) => ({ ...word })),
  }));

  // Pre-set consent and locale to avoid banners/flicker
  await page.addInitScript(({ authenticated: isAuthenticated }) => {
    localStorage.setItem('cookie-consent', 'accepted');
    localStorage.setItem('preferredLocale', 'el');
    localStorage.removeItem('lastActiveJobId');
    if (isAuthenticated) {
      localStorage.setItem('auth_token', 'test-token');
    } else {
      localStorage.removeItem('auth_token');
    }
  }, { authenticated });
  const shortCircuitOptions = async (route: Route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 200, headers: corsHeaders });
      return true;
    }
    return false;
  };

  await page.route('**/auth/me', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!signedIn) {
      await route.fulfill(unauthorizedResponse);
      return;
    }
    await route.fulfill(withCors(mockUser));
  });

  await page.route('**/auth/token', async (route) => {
    if (await shortCircuitOptions(route)) return;
    signedIn = true;
    await route.fulfill(withCors({
      access_token: 'test-token',
      token_type: 'bearer',
      user_id: mockUser.id,
      name: mockUser.name,
    }));
  });

  await page.route('**/auth/points', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!signedIn) {
      await route.fulfill(unauthorizedResponse);
      return;
    }
    await route.fulfill(withCors({
      balance: 125,
      paid_balance: 100,
      promotional_balance: 25,
      reversal_debt: 0,
      ai_spendable_balance: 100,
    }));
  });

  await page.route('**/billing/catalog', async (route) => {
    if (await shortCircuitOptions(route)) return;
    await route.fulfill(withCors({
      catalog_version: '2026-07-23-v1',
      currency: 'eur',
      checkout_enabled: true,
      packages: [
        { key: 'starter', credits: 100, amount_eur_cents: 100, featured: false },
        { key: 'core', credits: 350, amount_eur_cents: 300, featured: true },
        { key: 'pro', credits: 1200, amount_eur_cents: 1000, featured: false },
      ],
      video_pricing: [
        { key: 'up_to_3m', max_duration_seconds: 180, credits: 30 },
        { key: 'up_to_6m', max_duration_seconds: 360, credits: 60 },
        { key: 'up_to_10m', max_duration_seconds: 600, credits: 100 },
      ],
    }));
  });

  await page.route('**/billing/checkout', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!signedIn) {
      await route.fulfill(unauthorizedResponse);
      return;
    }
    await route.fulfill(withCors({
      purchase_id: 'purchase-e2e',
      checkout_session_id: 'cs_test_subframe',
      checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_subframe',
      status: 'checkout_created',
    }));
  });

  await page.route('**/auth/register', async (route) => {
    if (await shortCircuitOptions(route)) return;
    await route.fulfill(withCors(mockUser));
  });

  await page.route('**/auth/google/url', async (route) => {
    if (await shortCircuitOptions(route)) return;
    await route.fulfill(withCors({
      auth_url: 'https://accounts.google.com/o/oauth2/auth?mock',
      state: 'mock-state',
    }));
  });

  await page.route('**/auth/google/callback', async (route) => {
    if (await shortCircuitOptions(route)) return;
    signedIn = true;
    await route.fulfill(withCors({
      access_token: 'google-token',
      token_type: 'bearer',
      user_id: mockUser.id,
      name: mockUser.name,
    }));
  });

  await page.route('**/videos/process', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!signedIn) {
      await route.fulfill(unauthorizedResponse);
      return;
    }
    await route.fulfill(withCors({
      ...mockJobs[1],
      id: 'job-new',
      status: 'processing',
      progress: 12,
      message: 'Uploading…',
    }));
  });

  await page.route('**/videos/jobs/*/export', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!signedIn) {
      await route.fulfill(unauthorizedResponse);
      return;
    }

    const url = new URL(route.request().url());
    const parts = url.pathname.split('/');
    const jobId = parts[parts.indexOf('jobs') + 1] ?? mockJobs[0].id;
    const job = jobLookup.get(jobId) ?? mockJobs[0];
    const request = route.request().postDataJSON() as { resolution?: string };
    const resolution = request.resolution ?? '1080x1920';
    const extension = ['srt', 'vtt', 'txt'].includes(resolution) ? resolution : 'mp4';
    const variantPath = `/static/artifacts/${jobId}/processed_${resolution}.${extension}`;

    await route.fulfill(withCors({
      ...job,
      result_data: {
        ...(job.result_data ?? {}),
        variants: {
          ...(job.result_data?.variants ?? {}),
          [resolution]: variantPath,
        },
      },
    }));
  });

  await page.route('**/videos/jobs**', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!signedIn) {
      await route.fulfill(unauthorizedResponse);
      return;
    }

    const url = new URL(route.request().url());

    if (route.request().method() === 'PUT' && url.pathname.endsWith('/transcription')) {
      const payload = route.request().postDataJSON() as { cues?: typeof mockTranscription };
      currentTranscription = (payload.cues ?? []).map((cue) => ({
        ...cue,
        words: cue.words?.map((word) => ({ ...word })) ?? [],
      }));
      await route.fulfill(withCors({ status: 'ok' }));
      return;
    }

    if (url.pathname.includes('/videos/jobs/paginated')) {
      await route.fulfill(withCors({
        items: mockJobs,
        total: mockJobs.length,
        page: 1,
        page_size: 5,
        total_pages: 1,
      }));
      return;
    }

    if (url.pathname.startsWith('/videos/jobs/') && url.pathname !== '/videos/jobs') {
      const id = url.pathname.split('/').pop() ?? '';
      const job = jobLookup.get(id) ?? mockJobs[0];
      await route.fulfill(withCors(job));
      return;
    }

    await route.fulfill(withCors(mockJobs));
  });

  await page.route('**/history/**', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!signedIn) {
      await route.fulfill(unauthorizedResponse);
      return;
    }
    await route.fulfill(withCors(mockHistory));
  });

  await page.route('**/static/**', async (route) => {
    const url = new URL(route.request().url());

    // Never intercept Next.js assets (e.g. `/_next/static/**`) or we break hydration.
    if (url.pathname.startsWith('/_next/static/')) {
      await route.fallback();
      return;
    }

    // Only stub backend-served assets under `/static/**`.
    if (!url.pathname.startsWith('/static/')) {
      await route.fallback();
      return;
    }

    if (url.pathname === '/static/transcriptions/futurist-showcase.json') {
      await route.fulfill(withCors(currentTranscription));
      return;
    }

    const headers: Record<string, string> = { ...corsHeaders };
    if (url.searchParams.get('download') === 'true') {
      const filename = url.pathname.split('/').pop() || 'processed.txt';
      headers['content-disposition'] = `attachment; filename="${filename}"`;
    }

    await route.fulfill({
      status: 200,
      headers,
      contentType: 'text/plain',
      body: 'stub',
    });
  });
}

export async function stabilizeUi(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  await page.evaluate(async () => {
    if ('fonts' in document) {
      await document.fonts.ready;
    }
  });
  await page.addStyleTag({
    content: `
      *, *::before, *::after { 
        transition-duration: 0s !important;
        animation-duration: 0s !important;
        caret-color: transparent !important;
      }
      video { background: #000 !important; }
    `,
  });
}

export async function waitForDashboardShell(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded');
  await page.getByRole('button', { name: el.profileLabel }).waitFor({
    state: 'visible',
    timeout: 30_000,
  });
}

export async function waitForUploadWorkspace(
  page: Page,
  options: { authenticated?: boolean } = {},
): Promise<void> {
  const { authenticated = true } = options;
  await page.waitForLoadState('domcontentloaded');
  if (authenticated) {
    await waitForDashboardShell(page);
  } else {
    await page.getByRole('button', { name: el.guestSignIn }).waitFor({
      state: 'visible',
      timeout: 30_000,
    });
  }
  await page.getByTestId('upload-section').waitFor({
    state: 'visible',
    timeout: 30_000,
  });
}
