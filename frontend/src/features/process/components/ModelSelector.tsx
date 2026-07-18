import React, { useCallback, useMemo } from 'react';
import { TokenIcon } from '@/components/icons';
import { useI18n } from '@/context/I18nContext';
import { formatPoints, processVideoCostForSelection } from '@/lib/points';
import { resolveTranscriptionTier } from '@/lib/transcription';
import { TranscribeMode, TranscribeProvider, useProcessContext } from '../ProcessContext';

interface StudioModel {
    id: string;
    testId?: string;
    name: string;
    description: string;
    badge: string;
    badgeColor: string;
    provider: TranscribeProvider;
    mode: TranscribeMode;
    available?: boolean;
    recommended?: boolean;
    costLabel?: string;
    icon: (selected: boolean) => React.ReactNode;
}

export function ModelSelector() {
    const { t } = useI18n();
    const {
        AVAILABLE_MODELS,
        transcribeProvider,
        transcribeMode,
        setTranscribeProvider,
        setTranscribeMode,
        setHasChosenModel,
        setOverrideStep,
        selectedJob,
    } = useProcessContext();

    const models = AVAILABLE_MODELS as StudioModel[];
    const selectedModel = useMemo(() => {
        const explicit = models.find(
            (model) => model.provider === transcribeProvider && model.mode === transcribeMode,
        );
        if (explicit) return explicit;
        const provider = selectedJob?.result_data?.transcribe_provider;
        const tier = resolveTranscriptionTier(provider, selectedJob?.result_data?.model_size);
        return models.find((model) => model.provider === provider && model.mode === tier)
            ?? models.find((model) => model.mode === tier);
    }, [models, selectedJob, transcribeMode, transcribeProvider]);

    const chooseModel = useCallback((model: StudioModel) => {
        if (model.available === false) return;
        setTranscribeProvider(model.provider);
        setTranscribeMode(model.mode);
        setHasChosenModel(true);
        setOverrideStep(selectedJob ? 2 : 1);
        window.setTimeout(() => {
            document.getElementById('primary-workspace')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 120);
    }, [selectedJob, setHasChosenModel, setOverrideStep, setTranscribeMode, setTranscribeProvider]);

    return (
        <section id="model-selection-step" className="studio-panel" aria-labelledby="engine-title">
            <div className="studio-panel-header">
                <div>
                    <span className="studio-kicker">01 · {t('modelSelectTitle')}</span>
                    <h2 id="engine-title" className="studio-title">{t('engineHeading')}</h2>
                    <p className="studio-subtitle">{t('engineSubtitle')}</p>
                </div>
                <div className="mock-status" data-testid="mock-mode-badge">
                    <span className="mock-status-dot" />
                    {t('mockModeActive')}
                </div>
            </div>

            <div className="engine-grid" role="radiogroup" aria-label={t('modelSelectTitle')}>
                {models.map((model) => {
                    const selected = selectedModel?.id === model.id;
                    const available = model.available !== false;
                    const credits = processVideoCostForSelection(model.provider, model.mode);
                    return (
                        <button
                            key={model.id}
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            aria-disabled={!available}
                            disabled={!available}
                            data-testid={model.testId ?? `model-${model.id}`}
                            onClick={() => chooseModel(model)}
                            className={`engine-card ${selected ? 'engine-card-selected' : ''}`}
                        >
                            <div className="engine-card-topline">
                                {model.icon(selected)}
                                <span className={`engine-badge ${model.badgeColor}`}>{model.badge}</span>
                            </div>
                            <div>
                                <div className="engine-name-row">
                                    <h3>{model.name}</h3>
                                    {model.recommended && <span className="recommended-pill">{t('recommended')}</span>}
                                </div>
                                <p>{model.description}</p>
                            </div>
                            <div className="engine-meta">
                                <span><TokenIcon className="h-3.5 w-3.5" /> {formatPoints(credits)}</span>
                                <span>{model.costLabel}</span>
                                {!available && <strong>{t('disabledForNow')}</strong>}
                            </div>
                        </button>
                    );
                })}
            </div>
        </section>
    );
}
