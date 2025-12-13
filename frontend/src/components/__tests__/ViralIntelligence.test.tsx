import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ViralIntelligence } from '../ViralIntelligence';

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => {
        const en = require('@/i18n/en.json') as Record<string, string>;
        return { t: (key: string) => en[key] ?? key };
    },
}));

// Mock API
jest.mock('@/lib/api', () => ({
    api: {
        generateViralMetadata: jest.fn(),
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

    it('renders generate button initially', () => {
        render(<ViralIntelligence jobId={mockJobId} />);
        expect(screen.getByRole('button', { name: /generate viral metadata/i })).toBeInTheDocument();
    });

    it('shows loading state during generation', async () => {
        (api.generateViralMetadata as jest.Mock).mockImplementation(() => new Promise(() => { })); // Never resolves
        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByRole('button', { name: /generate viral metadata/i }));

        expect(screen.getByText(/analyzing transcript/i)).toBeInTheDocument();
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

        fireEvent.click(screen.getByRole('button', { name: /generate viral metadata/i }));

        await waitFor(() => expect(screen.getByText('Viral Intelligence')).toBeInTheDocument());
        expect(screen.getByText('Hook 1')).toBeInTheDocument();
        expect(screen.getByText('Caption Body')).toBeInTheDocument();
        expect(screen.getByText('#viral')).toBeInTheDocument();
    });

    it('displays error message on failure', async () => {
        (api.generateViralMetadata as jest.Mock).mockRejectedValue(new Error('API Error'));

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByRole('button', { name: /generate viral metadata/i }));

        await waitFor(() => expect(screen.getByText('API Error')).toBeInTheDocument());
        expect(screen.getByRole('button', { name: /generate viral metadata/i })).toBeInTheDocument(); // Button should reappear
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
        fireEvent.click(screen.getByRole('button', { name: /generate viral metadata/i }));

        await waitFor(() => expect(screen.getByText('Hook 1')).toBeInTheDocument());

        fireEvent.click(screen.getByText('Hook 1'));
        expect(mockWriteText).toHaveBeenCalledWith('Hook 1');

        // Copy Full Caption
        fireEvent.click(screen.getByText('Copy Full Caption'));
        expect(mockWriteText).toHaveBeenCalledWith(expect.stringContaining('Hook\n\nBody'));
    });
});
