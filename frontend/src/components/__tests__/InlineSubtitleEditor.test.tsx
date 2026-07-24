import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { InlineSubtitleEditor } from '@/components/InlineSubtitleEditor';

const labels = {
    title: 'Edit subtitle',
    textarea: 'Subtitle text',
    save: 'Save',
    cancel: 'Cancel',
    shortcut: 'Ctrl+Enter to save',
    saving: 'Saving…',
};

describe('InlineSubtitleEditor', () => {
    const onChange = jest.fn();
    const onSave = jest.fn();
    const onCancel = jest.fn();

    beforeEach(() => {
        jest.clearAllMocks();
        jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
            callback(0);
            return 1;
        });
        jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => { });
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    it('focuses without scrolling and supports form, keyboard, error, and cancel actions', () => {
        const { unmount } = render(
            <InlineSubtitleEditor
                cueIndex={3}
                draftText="Original subtitle"
                isSaving={false}
                error="Save failed"
                position={95}
                videoWidth={320}
                videoHeight={560}
                labels={labels}
                onChange={onChange}
                onSave={onSave}
                onCancel={onCancel}
            />,
        );

        const textarea = screen.getByRole('textbox', { name: 'Subtitle text' });
        const form = screen.getByRole('form', { name: 'Edit subtitle' });
        expect(textarea).toHaveFocus();
        expect(textarea).toHaveAttribute('aria-describedby', 'inline-subtitle-shortcut-3');
        expect(form).toHaveStyle({ top: '5%', transform: 'translateY(0)' });
        expect(screen.getByRole('alert')).toHaveTextContent('Save failed');

        fireEvent.change(textarea, { target: { value: 'Updated subtitle' } });
        expect(onChange).toHaveBeenCalledWith('Updated subtitle');
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));
        fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true });
        expect(onSave).toHaveBeenCalledTimes(2);

        fireEvent.keyDown(textarea, { key: 'Escape' });
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
        expect(onCancel).toHaveBeenCalledTimes(2);

        fireEvent.click(form);
        fireEvent.pointerDown(form);
        unmount();
        expect(window.cancelAnimationFrame).toHaveBeenCalledWith(1);
    });

    it('stays inert while saving and centers itself in a compact video', () => {
        render(
            <InlineSubtitleEditor
                cueIndex={0}
                draftText="Saving subtitle"
                isSaving
                autoFocus={false}
                position={20}
                videoWidth={220}
                videoHeight={200}
                labels={labels}
                onChange={onChange}
                onSave={onSave}
                onCancel={onCancel}
            />,
        );

        const form = screen.getByRole('form', { name: 'Edit subtitle' });
        const textarea = screen.getByRole('textbox', { name: 'Subtitle text' });
        expect(form).toHaveClass('top-1/2', '-translate-y-1/2');
        expect(textarea).toBeDisabled();
        expect(textarea).not.toHaveFocus();
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
        const savingButton = screen.getByRole('button', { name: 'Saving…' });
        expect(savingButton).toBeDisabled();
        expect(savingButton.querySelector('svg')).not.toBeNull();

        fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });
        fireEvent.submit(form);
        expect(onSave).not.toHaveBeenCalled();
    });
});
