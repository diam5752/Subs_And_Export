import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { SubtitlePositionSelector } from '@/components/SubtitlePositionSelector';

// Mock I18nContext
jest.mock('@/context/I18nContext', () => ({
    useI18n: () => ({ t: (key: string) => key }),
}));

describe('SubtitlePositionSelector', () => {
    const defaultProps = {
        lines: 2,
        onChangeLines: jest.fn(),
        subtitleSize: 100,
        onChangeSize: jest.fn(),
        subtitleColor: '#8B5CF6',
        onChangeColor: jest.fn(),
        colors: [{ label: 'Purple', value: '#8B5CF6', ass: '&H00F65C8B' }],
    };

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('renders size slider and presets', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        expect(screen.getByTestId('style-size-control')).toHaveClass(
            'editor-style-size-control',
        );
        expect(screen.getByTestId('style-color-control')).toHaveClass(
            'editor-style-color-control',
        );
        expect(screen.getByTestId('style-lines-control')).toHaveClass(
            'editor-style-lines-control',
        );

        // Verify accessible label connection
        expect(screen.getByLabelText('sizeLabel')).toHaveAttribute('type', 'range');

        // Presets
        expect(screen.getByText('sizeSmall')).toBeInTheDocument();
        expect(screen.getByText('sizeMedium')).toBeInTheDocument();
        expect(screen.getByText('sizeBig')).toBeInTheDocument();
        expect(screen.getByText('sizeExtraBig')).toBeInTheDocument();
    });

    it('does not render a redundant position control', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        // Position is manipulated directly on the video with touch or mouse.
        expect(screen.queryByLabelText('positionLabel')).not.toBeInTheDocument();
        expect(screen.queryByText('positionLow')).not.toBeInTheDocument();
        expect(screen.queryByText('positionMiddle')).not.toBeInTheDocument();
        expect(screen.queryByText('positionHigh')).not.toBeInTheDocument();
    });

    it('calls onChangeSize when size preset is clicked', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        fireEvent.click(screen.getByText('sizeBig'));
        expect(defaultProps.onChangeSize).toHaveBeenCalledWith(100);
    });

    it('calls onChangeLines when line option is clicked', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        expect(screen.getByText('linesSingle')).toBeInTheDocument();
        fireEvent.click(screen.getByText('linesSingle'));
        expect(defaultProps.onChangeLines).toHaveBeenCalledWith(1);
    });

    it('does not expose advanced output toggles', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        expect(screen.queryByRole('switch')).not.toBeInTheDocument();
        expect(screen.queryByText('karaokeLabel')).not.toBeInTheDocument();
        expect(screen.queryByText('watermarkLabel')).not.toBeInTheDocument();
    });

    it('shows info tooltips for subtitle controls', () => {
        const colors = [{ label: 'Green', value: '#00FF00', ass: '&H0000FF00' }];
        const onChangeColor = jest.fn();
        render(
            <SubtitlePositionSelector
                {...defaultProps}
                colors={colors}
                onChangeColor={onChangeColor}
                subtitleColor="#00FF00"
            />
        );

        const assertTooltip = (buttonLabel: string, tooltipText: string) => {
            const button = screen.getByRole('button', { name: buttonLabel });
            fireEvent.focus(button);
            expect(screen.getByText(tooltipText)).toBeInTheDocument();
            fireEvent.blur(button);
            expect(screen.queryByText(tooltipText)).not.toBeInTheDocument();
        };

        assertTooltip('infoPrefix sizeLabel', 'tooltipSizeDesc');
        assertTooltip('infoPrefix maxLinesLabel', 'tooltipMaxLinesDesc');
        assertTooltip('infoPrefix colorLabel', 'tooltipColorDesc');
    });

    it('renders color selector if colors provided', () => {
        const colors = [{ label: 'Green', value: '#00FF00', ass: '&H0000FF00' }];
        const onChangeColor = jest.fn();
        render(<SubtitlePositionSelector {...defaultProps} colors={colors} onChangeColor={onChangeColor} subtitleColor="#00FF00" />);

        expect(screen.getByText('colorLabel')).toBeInTheDocument();
        const colorBtn = screen.getByRole('radio', { name: 'Green' });
        fireEvent.click(colorBtn);
        expect(onChangeColor).toHaveBeenCalledWith('#00FF00');
    });

    it('uses a four-column responsive grid for preset colors and the color picker', () => {
        const colors = [
            { label: 'Yellow', value: '#FFFF00', ass: '&H0000FFFF' },
            { label: 'Purple', value: '#8B5CF6', ass: '&H00F65C8B' },
            { label: 'Cyan', value: '#00FFFF', ass: '&H00FFFF00' },
        ];
        render(<SubtitlePositionSelector {...defaultProps} colors={colors} />);

        const options = screen.getByTestId('style-color-options');
        expect(options).toHaveClass('editor-style-color-options');
        expect(options.querySelectorAll('.editor-style-color-swatch')).toHaveLength(4);
        const purple = screen.getByRole('radio', { name: 'Purple' });
        expect(purple).toHaveAttribute('aria-checked', 'true');
        expect(purple.querySelector('.editor-style-color-dot')).toHaveStyle(
            'background-color: #8B5CF6',
        );
    });

});
