import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { SubtitleOverlay } from '@/components/SubtitleOverlay';

function firePointer(
    element: Element,
    type: 'pointerdown' | 'pointermove' | 'pointerup',
    init: MouseEventInit & { pointerId: number },
) {
    const event = new MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        ...init,
    });
    Object.defineProperties(event, {
        pointerId: { configurable: true, value: init.pointerId },
        pointerType: { configurable: true, value: 'mouse' },
    });
    fireEvent(element, event);
}

describe('SubtitleOverlay', () => {
    it('renders karaoke words with spaces (no margin-based spacing)', () => {
        // REGRESSION: spacing via per-word margins reduced effective line capacity and caused
        // extra wrapped lines (e.g., selecting 1 line but seeing 2 in preview).
        render(
            <SubtitleOverlay
                currentTime={0.5}
                cues={[
                    {
                        start: 0,
                        end: 2,
                        text: ' hello world',
                        words: [
                            { start: 0, end: 1, text: ' hello' },
                            { start: 1, end: 2, text: ' world' },
                        ],
                    },
                ]}
                settings={{
                    position: 20,
                    color: '#FFFF00',
                    fontSize: 100,
                    karaoke: true,
                    maxLines: 2,
                    shadowStrength: 4,
                }}
                videoWidth={1080}
            />
        );

        expect(screen.getByText('HELLO')).toBeInTheDocument();
        expect(screen.getByText('WORLD')).toBeInTheDocument();
        const textContainer = screen.getByText('HELLO').parentElement;
        expect(textContainer).not.toBeNull();
        expect(textContainer?.textContent).toBe('HELLO WORLD');

        const wordSpan = screen.getByText('HELLO');
        expect(wordSpan.getAttribute('style')).not.toContain('margin');
        expect(wordSpan.getAttribute('style')).not.toContain('transform');
    });

    it('renders three explicit, stable rows without scaling the active word', () => {
        const getContextSpy = jest
            .spyOn(HTMLCanvasElement.prototype, 'getContext')
            .mockImplementation(() => ({
                measureText: (text: string) => ({
                    width: text === ' ' ? 20 : 300,
                }),
            }) as unknown as CanvasRenderingContext2D);

        try {
            render(
                <SubtitleOverlay
                    currentTime={2.5}
                    cues={[
                        {
                            start: 0,
                            end: 6,
                            text: 'one two three four five six',
                            words: [
                                { start: 0, end: 1, text: 'one' },
                                { start: 1, end: 2, text: 'two' },
                                { start: 2, end: 3, text: 'three' },
                                { start: 3, end: 4, text: 'four' },
                                { start: 4, end: 5, text: 'five' },
                                { start: 5, end: 6, text: 'six' },
                            ],
                        },
                    ]}
                    settings={{
                        position: 20,
                        color: '#FFFF00',
                        fontSize: 100,
                        karaoke: true,
                        maxLines: 3,
                        shadowStrength: 4,
                    }}
                    videoWidth={1080}
                />
            );

            const overlay = screen.getByTestId('subtitle-overlay');
            const lines = screen.getAllByTestId('subtitle-line');
            const activeWord = screen.getByText('THREE');

            expect(overlay).toHaveAttribute('data-line-count', '3');
            expect(lines).toHaveLength(3);
            expect(lines.map((line) => line.textContent)).toEqual([
                'ONE TWO',
                'THREE FOUR',
                'FIVE SIX',
            ]);
            expect(activeWord).toHaveAttribute('data-active', 'true');
            expect(activeWord.getAttribute('style')).not.toContain('transform');
            expect(lines.every((line) => line.classList.contains('whitespace-nowrap'))).toBe(true);
        } finally {
            getContextSpy.mockRestore();
        }
    });

    it('opens and controls the synchronized editor directly on the active subtitle', () => {
        const onBeginEdit = jest.fn();
        const onChange = jest.fn();
        const onSave = jest.fn();
        const onCancel = jest.fn();
        const cue = {
            start: 0,
            end: 2,
            text: 'hello world',
            words: [
                { start: 0, end: 1, text: 'hello' },
                { start: 1, end: 2, text: 'world' },
            ],
        };
        const labels = {
            editAction: 'Edit active subtitle',
            title: 'Edit subtitle',
            textarea: 'Subtitle text',
            save: 'Save',
            cancel: 'Cancel',
            shortcut: 'Ctrl+Enter to save',
            saving: 'Saving…',
        };
        const settings = {
            position: 20,
            color: '#FFFF00',
            fontSize: 100,
            karaoke: true,
            maxLines: 2,
            shadowStrength: 4,
        };

        const { rerender } = render(
            <SubtitleOverlay
                currentTime={0.5}
                cues={[cue]}
                settings={settings}
                inlineEditor={{
                    cueIndex: 0,
                    isEditing: false,
                    draftText: cue.text,
                    isSaving: false,
                    labels,
                    onBeginEdit,
                    onChange,
                    onSave,
                    onCancel,
                }}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: 'Edit active subtitle' }));
        expect(onBeginEdit).toHaveBeenCalledTimes(1);

        rerender(
            <SubtitleOverlay
                currentTime={0.5}
                cues={[cue]}
                settings={settings}
                inlineEditor={{
                    cueIndex: 0,
                    isEditing: true,
                    draftText: cue.text,
                    isSaving: false,
                    labels,
                    onBeginEdit,
                    onChange,
                    onSave,
                    onCancel,
                }}
            />,
        );

        const textarea = screen.getByRole('textbox', { name: 'Subtitle text' });
        expect(textarea).toHaveValue('hello world');
        fireEvent.change(textarea, { target: { value: 'corrected subtitle' } });
        expect(onChange).toHaveBeenCalledWith('corrected subtitle');

        fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });
        expect(onSave).toHaveBeenCalledTimes(1);
        fireEvent.keyDown(textarea, { key: 'Escape' });
        expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it('moves subtitles vertically with a pointer and suppresses editing after a drag', () => {
        // REGRESSION: desktop users need to manipulate the subtitle directly on
        // the preview without a drag accidentally opening the text editor.
        const onPositionChange = jest.fn();
        const onBeginEdit = jest.fn();
        const onInteractionStart = jest.fn();

        render(
            <SubtitleOverlay
                currentTime={0.5}
                cues={[{
                    start: 0,
                    end: 2,
                    text: 'drag me',
                    words: [
                        { start: 0, end: 1, text: 'drag' },
                        { start: 1, end: 2, text: 'me' },
                    ],
                }]}
                settings={{
                    position: 20,
                    color: '#FFFF00',
                    fontSize: 100,
                    karaoke: true,
                    maxLines: 2,
                    shadowStrength: 4,
                }}
                videoWidth={500}
                videoHeight={1000}
                inlineEditor={{
                    cueIndex: 0,
                    isEditing: false,
                    draftText: 'drag me',
                    isSaving: false,
                    labels: {
                        editAction: 'Edit active subtitle',
                        title: 'Edit subtitle',
                        textarea: 'Subtitle text',
                        save: 'Save',
                        cancel: 'Cancel',
                        shortcut: 'Ctrl+Enter to save',
                        saving: 'Saving…',
                    },
                    onBeginEdit,
                    onChange: jest.fn(),
                    onSave: jest.fn(),
                    onCancel: jest.fn(),
                }}
                transformControls={{
                    labels: {
                        move: 'Move subtitles',
                        resize: 'Resize subtitles',
                    },
                    onPositionChange,
                    onSizeChange: jest.fn(),
                    onInteractionStart,
                }}
            />,
        );

        const overlay = screen.getByTestId('subtitle-overlay');
        const editTrigger = screen.getByRole('button', { name: 'Edit active subtitle' });
        firePointer(editTrigger, 'pointerdown', {
            button: 0,
            pointerId: 6,
            clientX: 250,
            clientY: 600,
        });
        firePointer(editTrigger, 'pointerup', {
            button: 0,
            pointerId: 6,
            clientX: 250,
            clientY: 600,
        });
        fireEvent.click(editTrigger);
        expect(onBeginEdit).toHaveBeenCalledTimes(1);
        onBeginEdit.mockClear();
        onInteractionStart.mockClear();

        firePointer(overlay, 'pointerdown', {
            button: 0,
            pointerId: 7,
            clientX: 250,
            clientY: 600,
        });
        firePointer(overlay, 'pointermove', {
            pointerId: 7,
            clientX: 250,
            clientY: 500,
        });
        firePointer(overlay, 'pointerup', {
            pointerId: 7,
            clientX: 250,
            clientY: 500,
        });
        fireEvent.click(editTrigger);

        expect(onInteractionStart).toHaveBeenCalledTimes(1);
        expect(onPositionChange).toHaveBeenLastCalledWith(30);
        expect(onBeginEdit).not.toHaveBeenCalled();
    });

    it('resizes subtitles with a pointer, clamps bounds, and supports keyboard control', () => {
        // REGRESSION: resizing must stay within the same 50-150 range used by
        // the sidebar and export pipeline.
        const onPositionChange = jest.fn();
        const onSizeChange = jest.fn();

        render(
            <SubtitleOverlay
                currentTime={0.5}
                cues={[{ start: 0, end: 2, text: 'resize me' }]}
                settings={{
                    position: 20,
                    color: '#FFFF00',
                    fontSize: 100,
                    karaoke: false,
                    maxLines: 2,
                    shadowStrength: 4,
                }}
                videoWidth={400}
                videoHeight={1000}
                transformControls={{
                    labels: {
                        move: 'Move subtitles',
                        resize: 'Resize subtitles',
                    },
                    onPositionChange,
                    onSizeChange,
                }}
            />,
        );

        const overlay = screen.getByTestId('subtitle-overlay');
        const moveHandle = screen.getByRole('slider', { name: 'Move subtitles' });
        const resizeHandle = screen.getByRole('slider', { name: 'Resize subtitles' });

        expect(moveHandle).toHaveAttribute('aria-valuemin', '5');
        expect(moveHandle).toHaveAttribute('aria-valuemax', '95');
        expect(moveHandle).toHaveAttribute('aria-valuenow', '20');
        expect(resizeHandle).toHaveAttribute('aria-valuemin', '50');
        expect(resizeHandle).toHaveAttribute('aria-valuemax', '150');
        expect(resizeHandle).toHaveAttribute('aria-valuenow', '100');

        firePointer(resizeHandle, 'pointerdown', {
            button: 0,
            pointerId: 8,
            clientX: 100,
            clientY: 100,
        });
        firePointer(overlay, 'pointermove', {
            pointerId: 8,
            clientX: 180,
            clientY: 180,
        });
        firePointer(overlay, 'pointerup', {
            pointerId: 8,
            clientX: 180,
            clientY: 180,
        });
        expect(onSizeChange).toHaveBeenLastCalledWith(120);

        firePointer(resizeHandle, 'pointerdown', {
            button: 0,
            pointerId: 9,
            clientX: 100,
            clientY: 100,
        });
        firePointer(overlay, 'pointermove', {
            pointerId: 9,
            clientX: 1000,
            clientY: 1000,
        });
        expect(onSizeChange).toHaveBeenLastCalledWith(150);

        fireEvent.keyDown(moveHandle, { key: 'ArrowUp' });
        fireEvent.keyDown(moveHandle, { key: 'End' });
        expect(onPositionChange).toHaveBeenNthCalledWith(1, 21);
        expect(onPositionChange).toHaveBeenLastCalledWith(95);

        fireEvent.keyDown(resizeHandle, { key: 'ArrowLeft' });
        fireEvent.keyDown(resizeHandle, { key: 'Home' });
        expect(onSizeChange).toHaveBeenNthCalledWith(3, 95);
        expect(onSizeChange).toHaveBeenLastCalledWith(50);
    });
});
