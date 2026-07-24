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
        value: 16,
        onChange: jest.fn(),
        lines: 2,
        onChangeLines: jest.fn(),
        subtitleSize: 100,
        onChangeSize: jest.fn(),
        karaokeEnabled: true,
        onChangeKaraoke: jest.fn(),
        subtitleColor: '#FFFFFF',
        onChangeColor: jest.fn(),
        colors: [{ label: 'White', value: '#FFFFFF', ass: '&H00FFFFFF' }],
        watermarkEnabled: false,
        onChangeWatermark: jest.fn(),
    };

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('renders size slider and presets', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        // Verify accessible label connection
        expect(screen.getByLabelText('sizeLabel')).toHaveAttribute('type', 'range');

        // Presets
        expect(screen.getByText('sizeSmall')).toBeInTheDocument();
        expect(screen.getByText('sizeMedium')).toBeInTheDocument();
        expect(screen.getByText('sizeBig')).toBeInTheDocument();
        expect(screen.getByText('sizeExtraBig')).toBeInTheDocument();
    });

    it('renders position slider and presets', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        // Verify accessible label
        const slider = screen.getByLabelText('positionLabel');
        expect(slider).toHaveAttribute('type', 'range');
        expect(slider).toHaveAttribute('min', '5');
        expect(slider).toHaveAttribute('max', '95');

        // Presets
        expect(screen.getByText('positionLow')).toBeInTheDocument();
        expect(screen.getByText('positionMiddle')).toBeInTheDocument();
        expect(screen.getByText('positionHigh')).toBeInTheDocument();
    });

    it('calls onChangeSize when size preset is clicked', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        fireEvent.click(screen.getByText('sizeBig'));
        expect(defaultProps.onChangeSize).toHaveBeenCalledWith(100);
    });

    it('calls onChange when position preset is clicked', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        fireEvent.click(screen.getByText('positionHigh'));
        expect(defaultProps.onChange).toHaveBeenCalledWith(95);
    });

    it('calls onChangeLines when line option is clicked', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        expect(screen.getByText('linesSingle')).toBeInTheDocument();
        fireEvent.click(screen.getByText('linesSingle'));
        expect(defaultProps.onChangeLines).toHaveBeenCalledWith(1);
    });

    it('renders and updates the karaoke toggle', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        const switchControl = screen.getByRole('switch', { name: 'karaokeLabel' });
        expect(switchControl).toBeInTheDocument();
        expect(switchControl).toHaveAttribute('aria-checked', 'true');

        fireEvent.click(switchControl);
        expect(defaultProps.onChangeKaraoke).toHaveBeenCalledWith(false); // toggles
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
        assertTooltip('infoPrefix positionLabel', 'tooltipPositionDesc');
        assertTooltip('infoPrefix maxLinesLabel', 'tooltipMaxLinesDesc');
        assertTooltip('infoPrefix colorLabel', 'tooltipColorDesc');
        assertTooltip('infoPrefix karaokeLabel', 'tooltipKaraokeDesc');
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

});
