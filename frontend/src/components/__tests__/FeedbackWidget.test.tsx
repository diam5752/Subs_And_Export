import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FeedbackWidget } from '@/components/FeedbackWidget';
import { api } from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

jest.mock('@/lib/api', () => ({
  api: {
    createProductFeedback: jest.fn(),
  },
}));

jest.mock('@/context/AuthContext', () => ({
  useAuth: jest.fn(),
}));

jest.mock('@/context/I18nContext', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}));

describe('FeedbackWidget', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useAuth as jest.Mock).mockReturnValue({
      user: {
        id: 'user-1',
        email: 'person@example.com',
        name: 'Person',
        provider: 'local',
      },
    });
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

  it('does not close for clicks inside the dialog but closes on its backdrop', () => {
    render(<FeedbackWidget initiallyOpen />);
    const dialog = screen.getByRole('dialog', { name: 'feedbackTitle' });

    fireEvent.mouseDown(dialog);
    expect(dialog).toBeInTheDocument();

    const backdrop = dialog.parentElement;
    expect(backdrop).not.toBeNull();
    fireEvent.mouseDown(backdrop!);
    expect(screen.queryByRole('dialog', { name: 'feedbackTitle' })).not.toBeInTheDocument();
  });

  it('validates short messages before any feedback request is sent', async () => {
    jest.useFakeTimers();
    try {
      render(<FeedbackWidget initiallyOpen />);
      fireEvent.change(screen.getByLabelText('feedbackMessageLabel'), {
        target: { value: 'short' },
      });
      await act(async () => {
        jest.advanceTimersByTime(2_100);
      });

      fireEvent.submit(screen.getByLabelText('feedbackMessageLabel').closest('form')!);

      expect(await screen.findByText('feedbackMessageTooShort')).toBeInTheDocument();
      expect(api.createProductFeedback).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });

  it('supports anonymous success, sending another message, and finishing', async () => {
    jest.useFakeTimers();
    try {
      (useAuth as jest.Mock).mockReturnValue({ user: null });
      (api.createProductFeedback as jest.Mock).mockResolvedValue({
        status: 'received',
        id: 'feedback-2',
      });
      window.history.replaceState({}, '', '/');
      Object.defineProperty(document, 'title', {
        configurable: true,
        value: '',
      });
      render(<FeedbackWidget initiallyOpen />);

      expect(screen.getByText('feedbackAnonymousNotice')).toBeInTheDocument();
      fireEvent.change(screen.getByLabelText('feedbackMessageLabel'), {
        target: { value: 'Ανώνυμο μήνυμα με αρκετούς χαρακτήρες.' },
      });
      await act(async () => {
        jest.advanceTimersByTime(2_100);
      });
      fireEvent.click(screen.getByRole('button', { name: 'feedbackSubmit' }));

      expect(await screen.findByRole('status')).toHaveTextContent('feedbackSuccess');
      expect(api.createProductFeedback).toHaveBeenCalledWith(expect.objectContaining({
        source_path: '/',
        page_title: 'GSUBS',
      }));

      fireEvent.click(screen.getByRole('button', { name: 'feedbackSendAnother' }));
      expect(screen.getByLabelText('feedbackMessageLabel')).toHaveValue('');
      expect(screen.getByRole('button', { name: 'feedbackWaitMoment' })).toBeDisabled();
      fireEvent.change(screen.getByLabelText('feedbackMessageLabel'), {
        target: { value: 'Και δεύτερο ανώνυμο μήνυμα για δοκιμή.' },
      });
      await act(async () => {
        jest.advanceTimersByTime(2_100);
      });
      fireEvent.click(screen.getByRole('button', { name: 'feedbackSubmit' }));
      expect(await screen.findByRole('status')).toHaveTextContent('feedbackSuccess');
      fireEvent.click(screen.getByRole('button', { name: 'feedbackDone' }));
      expect(screen.queryByRole('dialog', { name: 'feedbackTitle' })).not.toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  it('cycles focus within the open feedback dialog', () => {
    const rectSpy = jest.spyOn(HTMLElement.prototype, 'getClientRects')
      .mockReturnValue({ length: 1 } as DOMRectList);
    try {
      render(<FeedbackWidget initiallyOpen />);
      const dialog = screen.getByRole('dialog', { name: 'feedbackTitle' });
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      last.focus();
      fireEvent.keyDown(document, { key: 'Tab' });
      expect(first).toHaveFocus();

      first.focus();
      fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
      expect(last).toHaveFocus();
    } finally {
      rectSpy.mockRestore();
    }
  });
});
