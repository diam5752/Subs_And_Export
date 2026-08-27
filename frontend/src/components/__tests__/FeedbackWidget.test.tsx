import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FeedbackWidget } from '@/components/FeedbackWidget';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    createProductFeedback: jest.fn(),
  },
}));

jest.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1',
      email: 'person@example.com',
      name: 'Person',
      provider: 'local',
    },
  }),
}));

jest.mock('@/context/I18nContext', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}));

describe('FeedbackWidget', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.scrollTo = jest.fn();
    window.history.replaceState({}, '', '/account?private=value');
    Object.defineProperty(document, 'title', {
      configurable: true,
      value: 'GSUBS Account',
    });
  });

  it('opens as an accessible, scroll-locked dialog and restores focus on Escape', () => {
    render(<FeedbackWidget />);
    const trigger = screen.getByRole('button', { name: 'feedbackOpen' });

    fireEvent.click(trigger);

    const dialog = screen.getByRole('dialog', { name: 'feedbackTitle' });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.position).toBe('fixed');
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'feedbackTitle' })).not.toBeInTheDocument();
    expect(document.body.style.position).toBe('');
    expect(trigger).toHaveFocus();
  });

  it('submits the selected category and path without query data', async () => {
    jest.useFakeTimers();
    try {
      (api.createProductFeedback as jest.Mock).mockResolvedValue({
        status: 'received',
        id: 'feedback-1',
      });
      render(<FeedbackWidget />);
      fireEvent.click(screen.getByRole('button', { name: 'feedbackOpen' }));
      fireEvent.click(screen.getByRole('radio', { name: 'feedbackCategoryBug' }));
      fireEvent.change(screen.getByLabelText('feedbackMessageLabel'), {
        target: { value: 'Το export κόλλησε στο τελευταίο βήμα.' },
      });
      await act(async () => {
        jest.advanceTimersByTime(2_100);
      });
      fireEvent.click(screen.getByRole('button', { name: 'feedbackSubmit' }));

      await waitFor(() => expect(api.createProductFeedback).toHaveBeenCalledWith({
        category: 'bug',
        message: 'Το export κόλλησε στο τελευταίο βήμα.',
        source_path: '/account',
        page_title: 'GSUBS Account',
        form_started_at: expect.any(Number),
        website: '',
      }));
      expect(await screen.findByRole('status')).toHaveTextContent('feedbackSuccess');
    } finally {
      jest.useRealTimers();
    }
  });

  it('keeps a failed message available for retry', async () => {
    jest.useFakeTimers();
    try {
      (api.createProductFeedback as jest.Mock).mockRejectedValue(new Error('offline'));
      render(<FeedbackWidget />);
      fireEvent.click(screen.getByRole('button', { name: 'feedbackOpen' }));
      fireEvent.change(screen.getByLabelText('feedbackMessageLabel'), {
        target: { value: 'Χρειάζομαι βοήθεια με το export μου.' },
      });
      await act(async () => {
        jest.advanceTimersByTime(2_100);
      });
      fireEvent.click(screen.getByRole('button', { name: 'feedbackSubmit' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('feedbackError');
      expect(screen.getByLabelText('feedbackMessageLabel')).toHaveValue(
        'Χρειάζομαι βοήθεια με το export μου.',
      );
    } finally {
      jest.useRealTimers();
    }
  });
});
