import { render, screen, fireEvent } from '@testing-library/react';
import { SubtitlePositionSelector } from '../SubtitlePositionSelector';

jest.mock('@/context/I18nContext', () => ({
    useI18n: () => {
        const en = require('@/i18n/en.json') as Record<string, string>;
        return { t: (key: string) => en[key] ?? key };
    },
}));

describe('SubtitlePositionSelector', () => {
    const defaultProps = {
        value: 'default',
        onChange: jest.fn(),
        lines: 2,
        onChangeLines: jest.fn(),
    };

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('renders all three position options', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        expect(screen.getByText('High')).toBeInTheDocument();
        expect(screen.getByText('Higher positioning')).toBeInTheDocument();

        expect(screen.getByText('Middle')).toBeInTheDocument();
        expect(screen.getByText('Social Standard')).toBeInTheDocument();

        expect(screen.getByText('Low')).toBeInTheDocument();
        expect(screen.getByText('Cinematic style')).toBeInTheDocument();
    });

    it('highlights the selected option', () => {
        render(<SubtitlePositionSelector {...defaultProps} value="top" />);

        const topButton = screen.getByText('High').closest('button');
        expect(topButton?.className).toContain('border-[var(--accent)]');
    });

    it('calls onChange when option is clicked', () => {
        const onChange = jest.fn();
        render(<SubtitlePositionSelector {...defaultProps} onChange={onChange} />);

        fireEvent.click(screen.getByText('Low'));
        expect(onChange).toHaveBeenCalledWith('bottom');
    });

    it('renders subtitle preview bar at correct position for default', () => {
        const { container } = render(<SubtitlePositionSelector {...defaultProps} value="default" />);

        const previewBar = container.querySelector('.subtitle-preview-bar');
        expect(previewBar).toBeInTheDocument();
        expect(previewBar).toHaveStyle({ bottom: '16%' });
    });

    it('renders subtitle preview bar at correct position for top', () => {
        const { container } = render(<SubtitlePositionSelector {...defaultProps} value="top" />);

        const previewBar = container.querySelector('.subtitle-preview-bar');
        expect(previewBar).toBeInTheDocument();
        expect(previewBar).toHaveStyle({ bottom: '32%' });
    });

    it('renders subtitle preview bar at correct position for bottom', () => {
        const { container } = render(<SubtitlePositionSelector {...defaultProps} value="bottom" />);

        const previewBar = container.querySelector('.subtitle-preview-bar');
        expect(previewBar).toBeInTheDocument();
        expect(previewBar).toHaveStyle({ bottom: '6%' });
    });

    it('renders thumbnail when provided', () => {
        render(<SubtitlePositionSelector {...defaultProps} thumbnailUrl="data:image/png;base64,test" />);

        const img = screen.getByAltText('Video preview');
        expect(img).toBeInTheDocument();
        expect(img).toHaveAttribute('src', 'data:image/png;base64,test');
    });

    it('renders fallback gradient when no thumbnail', () => {
        const { container } = render(<SubtitlePositionSelector {...defaultProps} thumbnailUrl={null} />);

        // Should have the fallback gradient div
        const fallbackGradient = container.querySelector('.bg-gradient-to-br');
        expect(fallbackGradient).toBeInTheDocument();
    });

    it('stops propagation on button click', () => {
        const parentClick = jest.fn();
        const onChange = jest.fn();

        render(
            <div onClick={parentClick}>
                <SubtitlePositionSelector {...defaultProps} onChange={onChange} />
            </div>
        );

        fireEvent.click(screen.getByText('High'));

        expect(onChange).toHaveBeenCalledWith('top');
        expect(parentClick).not.toHaveBeenCalled();
    });

    it('renders descriptive text for each option', () => {
        render(<SubtitlePositionSelector {...defaultProps} />);

        expect(screen.getByText('Social Standard')).toBeInTheDocument();
        expect(screen.getByText('Higher positioning')).toBeInTheDocument();
        expect(screen.getByText('Cinematic style')).toBeInTheDocument();
    });

    it('renders phone mockup UI elements', () => {
        const { container } = render(<SubtitlePositionSelector {...defaultProps} />);

        // Check for notch
        expect(container.querySelector('.rounded-full.bg-black\\/60')).toBeInTheDocument();

        // Check for social sidebar dots
        const sidebarDots = container.querySelectorAll('.bg-white\\/30.rounded-full');
        expect(sidebarDots.length).toBe(4);
    });

    it('renders color picker when colors are provided', () => {
        const colors = [{ label: 'Yellow', value: '#FFFF00', ass: '&H0000FFFF' }];
        const onChangeColor = jest.fn();
        render(<SubtitlePositionSelector {...defaultProps} colors={colors} onChangeColor={onChangeColor} />);

        const colorButton = screen.getByRole('radio', { name: 'Yellow' });
        expect(colorButton).toBeInTheDocument();

        // Find the swatch inside the button (it has the background color style)
        const swatch = colorButton.querySelector('div[style*="background-color"]');
        expect(swatch).toHaveStyle({ backgroundColor: '#FFFF00' });
    });

    it('calls onChangeColor when color is clicked', () => {
        const colors = [{ label: 'Yellow', value: '#FFFF00', ass: '&H0000FFFF' }];
        const onChangeColor = jest.fn();
        render(<SubtitlePositionSelector {...defaultProps} colors={colors} onChangeColor={onChangeColor} />);

        const colorButton = screen.getByRole('radio', { name: 'Yellow' });
        fireEvent.click(colorButton);
        expect(onChangeColor).toHaveBeenCalledWith('#FFFF00');
    });

    it('calls onChangeLines when line option button is clicked', () => {
        const onChangeLines = jest.fn();
        render(<SubtitlePositionSelector {...defaultProps} lines={2} onChangeLines={onChangeLines} />);

        // Find line option button labeled "Single Line"
        const lineButton1 = screen.getByRole('button', { name: /Single Line/i });
        fireEvent.click(lineButton1);
        expect(onChangeLines).toHaveBeenCalledWith(1);
    });
    it('shows Auto message when disableMaxLines is true', () => {
        render(<SubtitlePositionSelector {...defaultProps} disableMaxLines={true} />);
        expect(screen.getByText('Auto (Sync Priority)')).toBeInTheDocument();
        expect(screen.queryByText('Single Line')).not.toBeInTheDocument();
    });

    it('renders and interactions with size selector', () => {
        const onChangeSize = jest.fn();
        render(<SubtitlePositionSelector {...defaultProps} onChangeSize={onChangeSize} subtitleSize="medium" />);

        expect(screen.getByText('Big')).toBeInTheDocument();
        expect(screen.getByText('Small')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Big'));
        expect(onChangeSize).toHaveBeenCalledWith('big');
    });

    it('renders and toggles karaoke mode', () => {
        const onChangeKaraoke = jest.fn();
        render(
            <SubtitlePositionSelector
                {...defaultProps}
                karaokeEnabled={true}
                onChangeKaraoke={onChangeKaraoke}
                karaokeSupported={true}
            />
        );

        expect(screen.getByText('Karaoke Mode')).toBeInTheDocument();

        const toggleBtn = screen.getByText('Karaoke Mode').closest('button');
        fireEvent.click(toggleBtn!);

        // It should call with !enabled -> !true -> false
        expect(onChangeKaraoke).toHaveBeenCalledWith(false);
    });

    it('hides karaoke toggle if not supported', () => {
        render(
            <SubtitlePositionSelector
                {...defaultProps}
                karaokeEnabled={true}
                karaokeSupported={false}
            />
        );
        expect(screen.queryByText('Karaoke Mode')).not.toBeInTheDocument();
    });
});
