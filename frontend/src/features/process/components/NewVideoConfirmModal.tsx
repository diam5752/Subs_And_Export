import { useI18n } from '@/context/I18nContext';
import { ConfirmActionModal } from '@/components/ConfirmActionModal';

interface NewVideoConfirmModalProps {
    isOpen: boolean;
    onClose: () => void;
    onConfirm: () => void;
}

export function NewVideoConfirmModal({ isOpen, onClose, onConfirm }: NewVideoConfirmModalProps) {
    const { t } = useI18n();

    return (
        <ConfirmActionModal
            isOpen={isOpen}
            title={t('newVideoModalTitle') || 'Start a new project?'}
            description={t('newVideoModalDesc') || 'This closes the current editing view.'}
            cancelLabel={t('newVideoCancel') || 'Keep Working'}
            confirmLabel={t('newVideoConfirm') || 'Start Fresh'}
            onClose={onClose}
            onConfirm={onConfirm}
        />
    );
}
