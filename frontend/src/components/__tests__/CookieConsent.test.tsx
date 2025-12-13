import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import CookieConsent from '@/components/CookieConsent';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

jest.mock('@/context/I18nContext', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

describe('CookieConsent', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('shows the consent prompt when not yet accepted', async () => {
    render(<CookieConsent />);

    await waitFor(() => {
      expect(screen.getByText('cookieTitle')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'cookieAccept' }));

    expect(localStorage.getItem('cookie-consent')).toBe('accepted');
    expect(screen.queryByText('cookieTitle')).not.toBeInTheDocument();
  });

  it('does not render when consent is already stored', async () => {
    localStorage.setItem('cookie-consent', 'accepted');
    render(<CookieConsent />);

    await waitFor(() => {
      expect(screen.queryByText('cookieTitle')).not.toBeInTheDocument();
    });
  });
});
