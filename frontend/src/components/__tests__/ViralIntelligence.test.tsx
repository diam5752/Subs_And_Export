import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ViralIntelligence } from '../ViralIntelligence';

let mockLocale: 'el' | 'en' = 'en';

jest.mock('@/context/I18nContext', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const en = require('@/i18n/en.json');
    return {
        useI18n: () => ({ t: (key: string) => en[key] ?? key, locale: mockLocale }),
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
        jest.resetAllMocks();
        mockLocale = 'en';
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

    it('renders every fact severity, localized evidence, and score band', async () => {
        mockLocale = 'el';
        (api.factCheck as jest.Mock)
            .mockResolvedValueOnce({
                items: [
                    {
                        mistake_el: 'Μεγάλο λάθος',
                        mistake_en: 'Major mistake',
                        correction_el: 'Μεγάλη διόρθωση',
                        correction_en: 'Major correction',
                        explanation_el: 'Εξήγηση Α',
                        explanation_en: 'Explanation A',
                        severity: 'major',
                        confidence: 99,
                        real_life_example_el: 'Παράδειγμα ζωής',
                        real_life_example_en: '',
                        scientific_evidence_el: 'Επιστημονική τεκμηρίωση',
                        scientific_evidence_en: '',
                    },
                    {
                        mistake_el: 'Μεσαίο λάθος',
                        mistake_en: 'Medium mistake',
                        correction_el: 'Μεσαία διόρθωση',
                        correction_en: 'Medium correction',
                        explanation_el: 'Εξήγηση Β',
                        explanation_en: 'Explanation B',
                        severity: 'medium',
                        confidence: 70,
                        real_life_example_el: '',
                        real_life_example_en: '',
                        scientific_evidence_el: '',
                        scientific_evidence_en: '',
                    },
                    {
                        mistake_el: 'Μικρό λάθος',
                        mistake_en: 'Minor mistake',
                        correction_el: 'Μικρή διόρθωση',
                        correction_en: 'Minor correction',
                        explanation_el: 'Εξήγηση Γ',
                        explanation_en: 'Explanation C',
                        severity: 'minor',
                        confidence: 55,
                        real_life_example_el: '',
                        real_life_example_en: '',
                        scientific_evidence_el: '',
                        scientific_evidence_en: '',
                    },
                ],
                truth_score: 60,
                supported_claims_pct: 50,
                claims_checked: 3,
            })
            .mockResolvedValueOnce({
                items: [],
                truth_score: 20,
                supported_claims_pct: 0,
                claims_checked: 1,
                balance: null,
            });

        render(<ViralIntelligence jobId={mockJobId} />);
        fireEvent.click(screen.getByText(/Verify Facts/i));

        expect(await screen.findByText(/Μεγάλο λάθος/)).toBeInTheDocument();
        expect(screen.getByText(/Μεσαία διόρθωση/)).toBeInTheDocument();
        expect(screen.getByText(/Μικρό λάθος/)).toBeInTheDocument();
        expect(screen.getByText('Παράδειγμα ζωής')).toBeInTheDocument();
        expect(screen.getByText('Επιστημονική τεκμηρίωση')).toBeInTheDocument();
        expect(__setBalanceMock).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: /Close/i }));
        fireEvent.click(screen.getByText(/Verify Facts/i));
        expect(await screen.findByText(/All claims verified/)).toBeInTheDocument();
        expect(screen.getByText('20')).toBeInTheDocument();
    });

    it('shows safe API errors for both intelligence actions', async () => {
        (api.factCheck as jest.Mock).mockRejectedValueOnce(new Error('fact service offline'));
        (api.socialCopy as jest.Mock).mockRejectedValueOnce('social service offline');

        render(<ViralIntelligence jobId={mockJobId} />);
        fireEvent.click(screen.getByText(/Verify Facts/i));
        expect(await screen.findByText('fact service offline')).toBeInTheDocument();

        fireEvent.click(screen.getByText(/Generate Metadata/i));
        expect(await screen.findByText('Failed to generate social copy')).toBeInTheDocument();
    });

    it('keeps rejected clipboard writes harmless and closes metadata results', async () => {
        const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
        mockWriteText.mockRejectedValueOnce(new Error('clipboard blocked'));
        (api.socialCopy as jest.Mock).mockResolvedValue({
            social_copy: {
                title_en: 'Safe Title',
                title_el: 'Ασφαλής τίτλος',
                description_en: 'Safe Description',
                description_el: 'Ασφαλής περιγραφή',
                hashtags: [],
            },
        });

        render(<ViralIntelligence jobId={mockJobId} />);
        fireEvent.click(screen.getByText(/Generate Metadata/i));
        await screen.findByText('Safe Title');
        fireEvent.click(screen.getByLabelText('Copy Title'));
        await waitFor(() => expect(errorSpy).toHaveBeenCalledWith(
            'Failed to copy',
            expect.any(Error),
        ));
        fireEvent.click(screen.getByRole('button', { name: /Close/i }));
        expect(screen.queryByText('Safe Title')).not.toBeInTheDocument();
        errorSpy.mockRestore();
    });

    it('ignores fact and social responses that finish after unmount', async () => {
        let resolveFact!: (value: unknown) => void;
        let resolveSocial!: (value: unknown) => void;
        (api.factCheck as jest.Mock).mockReturnValue(new Promise((resolve) => {
            resolveFact = resolve;
        }));
        const factView = render(<ViralIntelligence jobId="late-fact" />);
        fireEvent.click(screen.getByText(/Verify Facts/i));
        factView.unmount();
        resolveFact({ items: [], truth_score: 100, supported_claims_pct: 100, claims_checked: 1 });

        (api.socialCopy as jest.Mock).mockReturnValue(new Promise((resolve) => {
            resolveSocial = resolve;
        }));
        const socialView = render(<ViralIntelligence jobId="late-social" />);
        fireEvent.click(screen.getByText(/Generate Metadata/i));
        socialView.unmount();
        resolveSocial({
            social_copy: {
                title_en: 'Late', title_el: 'Αργά',
                description_en: 'Late', description_el: 'Αργά', hashtags: [],
            },
        });

        await Promise.resolve();
        expect(__setBalanceMock).not.toHaveBeenCalled();
    });

    it('renders English evidence and Greek social copy from the same session', async () => {
        (api.factCheck as jest.Mock).mockResolvedValue({
            items: [{
                mistake_el: 'Λάθος',
                mistake_en: 'English mistake',
                correction_el: 'Διόρθωση',
                correction_en: 'English correction',
                explanation_el: 'Εξήγηση',
                explanation_en: 'English explanation',
                severity: 'minor',
                confidence: 88,
                real_life_example_el: '',
                real_life_example_en: 'English real-world example',
                scientific_evidence_el: '',
                scientific_evidence_en: 'English scientific evidence',
            }],
            truth_score: 88,
            supported_claims_pct: 100,
            claims_checked: 1,
        });
        (api.socialCopy as jest.Mock).mockResolvedValue({
            social_copy: {
                title_en: 'English title',
                title_el: 'Ελληνικός τίτλος',
                description_en: 'English description',
                description_el: 'Ελληνική περιγραφή',
                hashtags: ['#δίγλωσσο'],
            },
        });

        render(<ViralIntelligence jobId={mockJobId} />);
        fireEvent.click(screen.getByText(/Verify Facts/i));
        expect(await screen.findByText(/English mistake/)).toBeInTheDocument();
        expect(screen.getByText('English correction')).toBeInTheDocument();
        expect(screen.getByText('English real-world example')).toBeInTheDocument();
        expect(screen.getByText('English scientific evidence')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /Close/i }));
        mockLocale = 'el';
        fireEvent.click(screen.getByText(/Generate Metadata/i));
        expect(await screen.findByText('Ελληνικός τίτλος')).toBeInTheDocument();
        expect(screen.getByText('Ελληνική περιγραφή')).toBeInTheDocument();
    });
});
