import { Page, Route } from '@playwright/test';

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
    social?: string | null;
    original_filename?: string | null;
    video_crf?: number;
    model_size?: string;
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
      original_filename: 'GreekSubtitles_CaseStudy_Vertical_Edit_v4.mp4',
      video_crf: 12,
      model_size: 'large-v3',
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
      model_size: 'turbo',
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
      model_size: 'balanced',
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
      model_size: 'fast',
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

  // Pre-set consent and locale to avoid banners/flicker
  await page.addInitScript(() => {
    localStorage.setItem('cookie-consent', 'accepted');
    localStorage.setItem('preferredLocale', 'el');
  });
  const shortCircuitOptions = async (route: Route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 200, headers: corsHeaders });
      return true;
    }
    return false;
  };

  await page.route('**/auth/me', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!authenticated) {
      await route.fulfill(unauthorizedResponse);
      return;
    }
    await route.fulfill(withCors(mockUser));
  });

  await page.route('**/auth/token', async (route) => {
    if (await shortCircuitOptions(route)) return;
    await route.fulfill(withCors({
      access_token: 'test-token',
      token_type: 'bearer',
      user_id: mockUser.id,
      name: mockUser.name,
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
    await route.fulfill(withCors({
      access_token: 'google-token',
      token_type: 'bearer',
      user_id: mockUser.id,
      name: mockUser.name,
    }));
  });

  await page.route('**/videos/process', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!authenticated) {
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

  await page.route('**/videos/jobs**', async (route) => {
    if (await shortCircuitOptions(route)) return;
    if (!authenticated) {
      await route.fulfill(unauthorizedResponse);
      return;
    }

    const url = new URL(route.request().url());

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
    if (!authenticated) {
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

    await route.fulfill({
      status: 200,
      headers: corsHeaders,
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
