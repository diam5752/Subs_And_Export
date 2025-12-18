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
        (api.factCheck as jest.Mock).mockResolvedValue({ items: [], balance: 900 });

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/fact check/i));

        await waitFor(() => expect(api.factCheck).toHaveBeenCalledWith(mockJobId));
        expect(__setBalanceMock).toHaveBeenCalledWith(900);
        expect(await screen.findByText('Fact Report')).toBeInTheDocument();
    });

    it('calls social copy endpoint and renders result', async () => {
        (api.socialCopy as jest.Mock).mockResolvedValue({
            social_copy: {
                title: 'Test Title',
                description: 'Test Description',
                hashtags: ['#test']
            },
            balance: 850
        });

        render(<ViralIntelligence jobId={mockJobId} />);

        fireEvent.click(screen.getByText(/social copy/i));

        await waitFor(() => expect(api.socialCopy).toHaveBeenCalledWith(mockJobId));
        expect(__setBalanceMock).toHaveBeenCalledWith(850);

        expect(await screen.findByText('Test Title')).toBeInTheDocument();
        expect(screen.getByText('Test Description')).toBeInTheDocument();
        expect(screen.getByText('#test')).toBeInTheDocument();
    });
});
