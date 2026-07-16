import { render } from '@testing-library/react';
import { PwaRegistration } from '@/components/PwaRegistration';

describe('PwaRegistration', () => {
  it('renders no visible UI in the test environment', () => {
    const { container } = render(<PwaRegistration />);

    expect(container).toBeEmptyDOMElement();
  });
});
