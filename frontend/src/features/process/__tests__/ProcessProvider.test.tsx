import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { I18nProvider } from '@/context/I18nContext';
import { ProcessProvider, useProcessContext } from '../ProcessContext';

function PositionReader() {
  const { subtitlePosition } = useProcessContext();
  return <div data-testid="position">{subtitlePosition}</div>;
}

function StartHarness() {
  const { fileInputRef, handleStart, setHasChosenModel, setTranscribeMode, setTranscribeProvider } = useProcessContext();
  return (
    <div>
      <input ref={fileInputRef} data-testid="file-input" type="file" />
      <button
        type="button"
        onClick={() => {
          setTranscribeProvider('whispercpp');
          setTranscribeMode('turbo');
          setHasChosenModel(true);
        }}
      >
        select-model
      </button>
      <button type="button" onClick={handleStart}>start</button>
    </div>
  );
}

function StepHarness() {
  const { currentStep, setHasChosenModel, setOverrideStep, setTranscribeMode, setTranscribeProvider } = useProcessContext();
  return (
    <div>
      <div data-testid="step">{currentStep}</div>
      <button
        type="button"
        onClick={() => {
          setTranscribeProvider('whispercpp');
          setTranscribeMode('turbo');
          setHasChosenModel(true);
          setOverrideStep(2);
        }}
      >
        pick-model
      </button>
    </div>
  );
}

const baseProps = {
  selectedFile: null,
  onFileSelect: jest.fn(),
  isProcessing: false,
  progress: 0,
  statusMessage: '',
  error: '',
  onStartProcessing: jest.fn(async () => { }),
  onReprocessJob: jest.fn(async () => { }),
  onReset: jest.fn(),
  onCancelProcessing: undefined,
  selectedJob: null,
  onJobSelect: jest.fn(),
  statusStyles: {},
  buildStaticUrl: jest.fn(() => null),
};

describe('ProcessProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(window, 'scrollTo', { value: jest.fn(), writable: true });
  });

  it('clamps stored subtitlePosition to backend limits', () => {
    localStorage.setItem(
      'lastUsedSubtitleSettings',
      JSON.stringify({
        position: 50,
        size: 85,
        lines: 2,
        color: '#FFFF00',
        karaoke: true,
        timestamp: Date.now(),
      }),
    );

    render(
      <I18nProvider initialLocale="en">
        <ProcessProvider {...baseProps}>
          <PositionReader />
        </ProcessProvider>
      </I18nProvider>,
    );

    expect(screen.getByTestId('position')).toHaveTextContent('35');
  });

  it('opens the file picker when starting without a file', () => {
    render(
      <I18nProvider initialLocale="en">
        <ProcessProvider {...baseProps}>
          <StartHarness />
        </ProcessProvider>
      </I18nProvider>,
    );

    const input = screen.getByTestId('file-input') as HTMLInputElement;
    const clickSpy = jest.spyOn(input, 'click');

    fireEvent.click(screen.getByRole('button', { name: 'select-model' }));
    fireEvent.click(screen.getByRole('button', { name: 'start' }));

    expect(clickSpy).toHaveBeenCalled();
  });

  it('reprocesses a completed job instead of opening the picker', () => {
    /**
     * REGRESSION: When a completed job is selected (thumbnail/preview available) and the user picks a new model,
     * clicking "Start Processing" must re-render the existing source video (create a reprocess job) instead of
     * opening the upload picker.
     */
    const completedJob = {
      id: 'job-1',
      status: 'completed',
      progress: 100,
      message: null,
      created_at: Date.now(),
      updated_at: Date.now(),
      result_data: { transcribe_provider: 'whispercpp', model_size: 'turbo' },
    };

    const onReprocessJob = jest.fn(async () => { });

    render(
      <I18nProvider initialLocale="en">
        <ProcessProvider {...baseProps} selectedJob={completedJob} onReprocessJob={onReprocessJob}>
          <StartHarness />
        </ProcessProvider>
      </I18nProvider>,
    );

    const input = screen.getByTestId('file-input') as HTMLInputElement;
    const clickSpy = jest.spyOn(input, 'click');

    fireEvent.click(screen.getByRole('button', { name: 'select-model' }));
    fireEvent.click(screen.getByRole('button', { name: 'start' }));

    expect(clickSpy).not.toHaveBeenCalled();
    expect(onReprocessJob).toHaveBeenCalledWith(
      'job-1',
      expect.objectContaining({
        transcribeProvider: 'whispercpp',
        transcribeMode: 'turbo',
      }),
    );
  });

  it('stays on Step 2 after selecting a model on a completed job', async () => {
    const completedJob = {
      id: 'job-1',
      status: 'completed',
      progress: 100,
      message: null,
      created_at: Date.now(),
      updated_at: Date.now(),
      result_data: { transcribe_provider: 'whispercpp', model_size: 'turbo' },
    };

    render(
      <I18nProvider initialLocale="en">
        <ProcessProvider {...baseProps} selectedJob={completedJob}>
          <StepHarness />
        </ProcessProvider>
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'pick-model' }));
    await waitFor(() => expect(screen.getByTestId('step')).toHaveTextContent('2'));
  });
});
