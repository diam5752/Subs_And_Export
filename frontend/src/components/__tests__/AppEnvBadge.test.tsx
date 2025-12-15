import { render, screen } from '@testing-library/react';
import { AppEnvProvider } from '@/context/AppEnvContext';
import { AppEnvBadge } from '@/components/AppEnvBadge';

describe('AppEnvBadge', () => {
  it('renders DEV when appEnv is dev', () => {
    render(
      <AppEnvProvider appEnv="dev">
        <AppEnvBadge />
      </AppEnvProvider>
    );
    expect(screen.getByText('DEV')).toBeInTheDocument();
  });

  it('renders PROD when appEnv is production', () => {
    render(
      <AppEnvProvider appEnv="production">
        <AppEnvBadge />
      </AppEnvProvider>
    );
    expect(screen.getByText('PROD')).toBeInTheDocument();
  });
});

