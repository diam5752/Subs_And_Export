import { fireEvent, render, screen } from '@testing-library/react';
import { FeedbackWidgetLauncher } from '@/components/FeedbackWidgetLauncher';

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

jest.mock('@/components/FeedbackWidget', () => ({
    FeedbackWidget: ({ initiallyOpen }: { initiallyOpen?: boolean }) => (
        <div data-testid="loaded-feedback-widget">{String(initiallyOpen)}</div>
    ),
}));

describe('FeedbackWidgetLauncher', () => {
    it('keeps the full widget lazy until the user opens feedback', async () => {
        render(<FeedbackWidgetLauncher />);

        const trigger = screen.getByRole('button', { name: 'feedbackOpen' });
        expect(trigger).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByTestId('loaded-feedback-widget')).not.toBeInTheDocument();

        fireEvent.click(trigger);

        expect(await screen.findByTestId('loaded-feedback-widget')).toHaveTextContent('true');
    });
});
