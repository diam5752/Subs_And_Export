import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ProcessView } from '@/components/ProcessView';
import { AppEnvProvider } from '@/context/AppEnvContext';
import { api, type JobResponse } from '@/lib/api';

global.fetch = jest.fn();

jest.mock('@/components/VideoModal', () => ({
  VideoModal: () => <div data-testid="video-modal" />,
}));

jest.mock('@/components/ViralIntelligence', () => ({
  ViralIntelligence: () => <div data-testid="viral-intelligence" />,
}));

jest.mock('@/components/SubtitlePositionSelector', () => ({
  SubtitlePositionSelector: () => <div data-testid="subtitle-selector" />,
}));

jest.mock('@/components/PreviewPlayer', () => ({
  PreviewPlayer: () => <div data-testid="preview-player" />,
}));

jest.mock('@/components/PhoneFrame', () => ({
  PhoneFrame: ({ children }: { children: React.ReactNode }) => <div data-testid="phone-frame">{children}</div>,
}));

jest.mock('@/context/I18nContext', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/lib/video', () => ({
  describeResolution: jest.fn(),
  describeResolutionString: jest.fn(),
  validateVideoAspectRatio: jest.fn().mockResolvedValue({
    width: 1080,
    height: 1920,
    aspectWarning: false,
    thumbnailUrl: null,
  }),
}));

jest.mock('@/lib/api', () => ({
  api: {
    loadDevSampleJob: jest.fn(),
    exportVideo: jest.fn(),
    updateJobTranscription: jest.fn(),
  },
}));

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = jest.fn();

describe('ProcessView', () => {
  const defaultProps = {
    selectedFile: null,
    onFileSelect: jest.fn(),
    isProcessing: false,
    progress: 0,
    statusMessage: '',
    error: '',
    onStartProcessing: jest.fn(),
    onReset: jest.fn(),
    selectedJob: null,
    onJobSelect: jest.fn(),
    statusStyles: {},
    buildStaticUrl: (path?: string | null) => path || null,
  };

  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as unknown as jest.Mock).mockReset();
  });

  it('shows upload immediately in dev', () => {
    render(
      <AppEnvProvider appEnv="dev">
        <ProcessView {...defaultProps} />
      </AppEnvProvider>
    );

    expect(screen.getByText('uploadDropTitle')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Load sample video/i })).toBeInTheDocument();
  });

  it('requires model selection before upload in production', async () => {
    render(
      <AppEnvProvider appEnv="production">
        <ProcessView {...defaultProps} />
      </AppEnvProvider>
    );

    expect(screen.queryByText('uploadDropTitle')).not.toBeInTheDocument();
    expect(screen.getByText('modelSelectTitle')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /modelEnhancedName/ }));

    await waitFor(() => {
      expect(screen.getByText('uploadDropTitle')).toBeInTheDocument();
    });
  });

  it('allows editing and saving transcript cues', async () => {
    const job: JobResponse = {
      id: 'job-1',
      status: 'completed',
      progress: 100,
      message: 'Done',
      created_at: Date.now(),
      updated_at: Date.now(),
      result_data: {
        video_path: 'uploads/job-1_input.mp4',
        artifacts_dir: 'artifacts/job-1',
        public_url: '/static/uploads/job-1_input.mp4',
        transcription_url: '/static/artifacts/job-1/transcription.json',
      },
    };

    (global.fetch as unknown as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          start: 0,
          end: 1,
          text: 'hello world',
          words: [
            { start: 0, end: 0.5, text: 'hello' },
            { start: 0.5, end: 1, text: 'world' },
          ],
        },
      ],
    });

    (api.updateJobTranscription as jest.Mock).mockResolvedValueOnce({ status: 'ok' });

    render(
      <AppEnvProvider appEnv="dev">
        <ProcessView {...defaultProps} selectedJob={job} />
      </AppEnvProvider>
    );

    await screen.findByText('hello world');

    fireEvent.click(screen.getByRole('button', { name: 'transcriptEdit' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hello there world' } });
    fireEvent.click(screen.getByRole('button', { name: 'transcriptSave' }));

    await waitFor(() => {
      expect(api.updateJobTranscription).toHaveBeenCalledWith(
        'job-1',
        expect.arrayContaining([
          expect.objectContaining({
            text: 'hello there world',
            words: expect.arrayContaining([
              expect.objectContaining({ text: 'hello' }),
              expect.objectContaining({ text: 'there' }),
              expect.objectContaining({ text: 'world' }),
            ]),
          }),
        ])
      );
    });
  });
});
