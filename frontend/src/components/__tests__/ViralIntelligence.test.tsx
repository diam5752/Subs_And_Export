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
        socialCopy: jest.fn(),
    },
}));

jest.mock('@/context/PointsContext', () => ({
    __esModule: true,
    ...(() => {
        const setBalanceMock = jest.fn();
        return {
            usePoints: () => ({ setBalance: setBalanceMock }),
            __setBalanceMock: setBalanceMock,
        };
    })(),
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
    const { __setBalanceMock } = jest.requireMock('@/context/PointsContext') as {
        __setBalanceMock: jest.Mock;
    };

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('calls fact check endpoint and renders report', async () => {
        (api.factCheck as jest.Mock).mockResolvedValue({
            items: [],
            truth_score: 95,
            supported_claims_pct: 100,
            claims_checked: 5,
            balance: 900
        });

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/Verify Facts/i));

        await waitFor(() => expect(api.factCheck).toHaveBeenCalledWith(mockJobId));
        expect(__setBalanceMock).toHaveBeenCalledWith(900);
        expect(await screen.findByText('Fact Report')).toBeInTheDocument();
    });

    it('calls social copy endpoint and renders result', async () => {
        (api.socialCopy as jest.Mock).mockResolvedValue({
            social_copy: {
                title_en: 'Test Title',
                title_el: 'Test Title El',
                description_en: 'Test Description',
                description_el: 'Test Description El',
                hashtags: ['#test']
            },
            balance: 850
        });

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/Generate Metadata/i));

        await waitFor(() => expect(api.socialCopy).toHaveBeenCalledWith(mockJobId));
        expect(__setBalanceMock).toHaveBeenCalledWith(850);

        expect(await screen.findByText('Test Title')).toBeInTheDocument();
        expect(screen.getByText('Test Description')).toBeInTheDocument();
        expect(screen.getByText('#test')).toBeInTheDocument();
    });

    it('allows copying metadata', async () => {
        (api.socialCopy as jest.Mock).mockResolvedValue({
            social_copy: {
                title_en: 'Copy Title',
                title_el: 'Copy Title El',
                description_en: 'Copy Description',
                description_el: 'Copy Description El',
                hashtags: ['#copy']
            },
            balance: 850
        });

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/generate metadata/i));

        await waitFor(() => expect(screen.getByText('Copy Title')).toBeInTheDocument());

        // Find and click the copy button for title
        const titleCopyBtn = screen.getByLabelText('Copy Title');
        fireEvent.click(titleCopyBtn);

        expect(mockWriteText).toHaveBeenCalledWith('Copy Title');

        // Check for visual feedback
        await waitFor(() => expect(screen.getByLabelText('Copied')).toBeInTheDocument());
    });
});
