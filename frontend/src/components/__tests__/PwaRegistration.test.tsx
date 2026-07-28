import { render } from '@testing-library/react';
import { PwaRegistration } from '@/components/PwaRegistration';

describe('PwaRegistration', () => {
  it('renders no visible UI in the test environment', () => {
    const { container } = render(<PwaRegistration />);

    expect(container).toBeEmptyDOMElement();
  });

  it('registers the production service worker once after window load', () => {
    const originalNodeEnv = process.env.NODE_ENV;
    const register = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(process.env, 'NODE_ENV', {
      configurable: true,
      value: 'production',
    });
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { register },
    });

    const { unmount } = render(<PwaRegistration />);
    window.dispatchEvent(new Event('load'));

    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith('/sw.js', { scope: '/' });
    unmount();

    Object.defineProperty(process.env, 'NODE_ENV', {
      configurable: true,
      value: originalNodeEnv,
    });
    Reflect.deleteProperty(navigator, 'serviceWorker');
  });
});
