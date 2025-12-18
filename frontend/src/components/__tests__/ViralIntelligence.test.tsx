import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ViralIntelligence } from '../ViralIntelligence';

jest.mock('@/context/I18nContext', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const en = require('@/i18n/en.json');
    return {
        useI18n: () => ({ t: (key: string) => en[key] ?? key }),
    };
});

// Mock API
jest.mock('@/lib/api', () => ({
    api: {
        generateViralMetadata: jest.fn(),
        factCheck: jest.fn(),
    },
}));

import { api } from '@/lib/api';

// Mock Clipboard API
const mockWriteText = jest.fn();
Object.assign(navigator, {
    clipboard: {
        writeText: mockWriteText,
    },
});

describe('ViralIntelligence', () => {
    const mockJobId = 'job-123';

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('renders metadata button and fact check button with tooltips', () => {
        render(<ViralIntelligence jobId={mockJobId} />);
        expect(screen.getByText(/generate viral metadata/i)).toBeInTheDocument();
        expect(screen.getByText(/fact check/i)).toBeInTheDocument();

        // Check for info tooltips by their ARIA labels
        expect(screen.getByRole('button', { name: /analyze your video/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /verify the accuracy/i })).toBeInTheDocument();

        // Ensure internal title "Intelligence" is gone
        expect(screen.queryByText(/^Intelligence$/)).not.toBeInTheDocument();
    });

    it('shows loading state during generation', async () => {
        (api.generateViralMetadata as jest.Mock).mockImplementation(() => new Promise(() => { })); // Never resolves
        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/generate viral metadata/i));

        expect(screen.getByText(/processing content/i)).toBeInTheDocument();
    });

    it('displays metadata results on success', async () => {
        const mockData = {
            hooks: ['Hook 1', 'Hook 2'],
            caption_hook: 'Caption Hook',
            caption_body: 'Caption Body',
            cta: 'Follow for more',
            hashtags: ['#viral', '#test'],
        };
        (api.generateViralMetadata as jest.Mock).mockResolvedValue(mockData);

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/generate viral metadata/i));

        await waitFor(() => expect(screen.getByText('Generated Output')).toBeInTheDocument());
        expect(screen.getByText('Hook 1')).toBeInTheDocument();
        expect(screen.getByText('Caption Body')).toBeInTheDocument();
        expect(screen.getByText('#viral')).toBeInTheDocument();
    });

    it('displays error message on failure', async () => {
        (api.generateViralMetadata as jest.Mock).mockRejectedValue(new Error('API Error'));

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/generate viral metadata/i));

        await waitFor(() => expect(screen.getByText('API Error')).toBeInTheDocument());
        expect(screen.getByText(/generate viral metadata/i)).toBeInTheDocument(); // Button content should reappear
    });

    it('copies content to clipboard', async () => {
        const mockData = {
            hooks: ['Hook 1'],
            caption_hook: 'Hook',
            caption_body: 'Body',
            cta: 'CTA',
            hashtags: ['#tag'],
        };
        (api.generateViralMetadata as jest.Mock).mockResolvedValue(mockData);

        render(<ViralIntelligence jobId={mockJobId} />);
        fireEvent.click(screen.getByText(/generate viral metadata/i));

        await waitFor(() => expect(screen.getByText('Hook 1')).toBeInTheDocument());

        const hookButton = screen.getByRole('button', { name: 'Hook 1' });
        fireEvent.click(hookButton);
        expect(mockWriteText).toHaveBeenCalledWith('Hook 1');

        // Copy Full Caption
        fireEvent.click(screen.getByRole('button', { name: 'Copy All' }));
        expect(mockWriteText).toHaveBeenCalledWith(expect.stringContaining('Hook\n\nBody'));

        // Check for feedback on caption
        await waitFor(() => expect(screen.getByText('Copied')).toBeInTheDocument());
    });

    it('calls fact check endpoint and renders report', async () => {
        (api.factCheck as jest.Mock).mockResolvedValue({ items: [] });

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/fact check/i));

        await waitFor(() => expect(api.factCheck).toHaveBeenCalledWith(mockJobId));
        expect(await screen.findByText('Report')).toBeInTheDocument();
    });

    it('resets results when jobId changes', async () => {
        (api.generateViralMetadata as jest.Mock).mockResolvedValue({
            hooks: ['Hook 1'],
            caption_hook: 'Caption Hook',
            caption_body: 'Caption Body',
            cta: 'CTA',
            hashtags: ['#tag'],
        });

        const { rerender } = render(<ViralIntelligence jobId="job-1" />);

        fireEvent.click(screen.getByText(/generate viral metadata/i));
        await waitFor(() => expect(screen.getByText('Generated Output')).toBeInTheDocument());
        expect(screen.getByText('Hook 1')).toBeInTheDocument();

        rerender(<ViralIntelligence jobId="job-2" />);

        await waitFor(() => expect(screen.queryByText('Generated Output')).not.toBeInTheDocument());
        expect(screen.getByText(/generate viral metadata/i)).toBeInTheDocument();
        expect(screen.queryByText('Hook 1')).not.toBeInTheDocument();
    });
});
