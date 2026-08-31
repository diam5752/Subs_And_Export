import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type MutableRefObject,
} from "react";
import type { Cue, SubtitlePositionScope } from "@/components/SubtitleOverlay";
import { api } from "@/lib/api";
import { reportProductAction } from "@/lib/observability";
import {
  SUBTITLE_POSITION_MAX,
  SUBTITLE_POSITION_MIN,
} from "@/lib/subtitleUtils";

interface CuePositionEdit {
  scope: SubtitlePositionScope;
  sourceCueIndex: number;
  jobId: string | null;
  previousCues: Cue[];
  draftCues: Cue[];
  previousSharedPosition: number;
  sourceStartPosition: number;
}

interface UseCuePositioningOptions {
  cues: Cue[];
  setCues: (cues: Cue[]) => void;
  subtitlePosition: number;
  setSubtitlePosition: (position: number) => void;
  selectedJobId: string | null;
  selectedJobIdRef: MutableRefObject<string | null>;
  isSavingTranscriptRef: MutableRefObject<boolean>;
  setIsSavingTranscript: (saving: boolean) => void;
  setTranscriptSaveError: (error: string | null) => void;
  onRefreshJobs?: () => Promise<void>;
  saveErrorMessage: string;
}

function clampSubtitlePosition(position: number): number {
  return Math.round(
    Math.max(SUBTITLE_POSITION_MIN, Math.min(SUBTITLE_POSITION_MAX, position)),
  );
}

function shiftCustomCuePositions(cues: Cue[], delta: number): Cue[] {
  return cues.map((cue) =>
    cue.position === undefined || cue.position === null
      ? cue
      : {
          ...cue,
          position: clampSubtitlePosition(cue.position + delta),
        },
  );
}

function cuePositionsChanged(previousCues: Cue[], draftCues: Cue[]): boolean {
  return previousCues.some(
    (cue, index) => cue.position !== draftCues[index]?.position,
  );
}

function useCuePositionState({
  cues,
  setCues,
  selectedJobId,
  isSavingTranscriptRef,
  setIsSavingTranscript,
}: Pick<
  UseCuePositioningOptions,
  | "cues"
  | "setCues"
  | "selectedJobId"
  | "isSavingTranscriptRef"
  | "setIsSavingTranscript"
>) {
  const cuesRef = useRef(cues);
  const editRef = useRef<CuePositionEdit | null>(null);
  useEffect(() => {
    cuesRef.current = cues;
  }, [cues]);
  useEffect(() => {
    editRef.current = null;
  }, [selectedJobId]);
  const updateCues = useCallback(
    (nextCues: Cue[]) => {
      cuesRef.current = nextCues;
      setCues(nextCues);
    },
    [setCues],
  );
  const setSaving = useCallback(
    (saving: boolean) => {
      isSavingTranscriptRef.current = saving;
      setIsSavingTranscript(saving);
    },
    [isSavingTranscriptRef, setIsSavingTranscript],
  );
  return { cuesRef, editRef, setSaving, updateCues };
}

function matchesCuePositionEdit(
  edit: CuePositionEdit | null,
  sourceCueIndex: number,
  scope: SubtitlePositionScope,
): edit is CuePositionEdit {
  return edit?.sourceCueIndex === sourceCueIndex && edit.scope === scope;
}

function draftCuePositions(
  cues: Cue[],
  sourceCueIndex: number,
  position: number,
  scope: SubtitlePositionScope,
  delta: number,
): Cue[] {
  if (scope === "all") return shiftCustomCuePositions(cues, delta);
  return cues.map((cue, index) =>
    index === sourceCueIndex ? { ...cue, position } : cue,
  );
}

function buildCuePositionEdit({
  existingEdit,
  currentCues,
  sourceCueIndex,
  position,
  scope,
  sharedPosition,
  jobId,
}: {
  existingEdit: CuePositionEdit | null;
  currentCues: Cue[];
  sourceCueIndex: number;
  position: number;
  scope: SubtitlePositionScope;
  sharedPosition: number;
  jobId: string | null;
}): CuePositionEdit | null {
  const continuesEdit = matchesCuePositionEdit(
    existingEdit,
    sourceCueIndex,
    scope,
  );
  const previousCues = continuesEdit ? existingEdit.previousCues : currentCues;
  const targetCue = previousCues[sourceCueIndex];
  if (!targetCue) return null;
  const previousSharedPosition = continuesEdit
    ? existingEdit.previousSharedPosition
    : sharedPosition;
  const sourceStartPosition = continuesEdit
    ? existingEdit.sourceStartPosition
    : (targetCue.position ?? previousSharedPosition);
  const delta = position - sourceStartPosition;
  return {
    scope,
    sourceCueIndex,
    jobId,
    previousCues,
    draftCues: draftCuePositions(
      previousCues,
      sourceCueIndex,
      position,
      scope,
      delta,
    ),
    previousSharedPosition,
    sourceStartPosition,
  };
}

function takeCuePositionEdit(
  editRef: MutableRefObject<CuePositionEdit | null>,
  sourceCueIndex: number,
  scope: SubtitlePositionScope,
): CuePositionEdit | null {
  const edit = editRef.current;
  if (!matchesCuePositionEdit(edit, sourceCueIndex, scope)) return null;
  editRef.current = null;
  if (!edit.jobId || !cuePositionsChanged(edit.previousCues, edit.draftCues)) {
    return null;
  }
  return edit;
}

interface PersistCuePositionEditOptions {
  selectedJobIdRef: MutableRefObject<string | null>;
  setSaving: (saving: boolean) => void;
  setSubtitlePosition: (position: number) => void;
  setTranscriptSaveError: (error: string | null) => void;
  updateCues: (cues: Cue[]) => void;
  onRefreshJobs?: () => Promise<void>;
  saveErrorMessage: string;
}

async function persistCuePositionEdit(
  edit: CuePositionEdit,
  options: PersistCuePositionEditOptions,
): Promise<void> {
  const jobId = edit.jobId;
  if (!jobId) return;
  options.setSaving(true);
  options.setTranscriptSaveError(null);
  try {
    await api.updateJobTranscription(jobId, persistedCues(edit.draftCues));
    if (options.selectedJobIdRef.current !== jobId) return;
    void options.onRefreshJobs?.();
    reportProductAction("subtitle_saved", { outcome: "succeeded" });
  } catch (error) {
    if (options.selectedJobIdRef.current !== jobId) return;
    options.updateCues(edit.previousCues);
    if (edit.scope === "all") {
      options.setSubtitlePosition(edit.previousSharedPosition);
    }
    options.setTranscriptSaveError(
      error instanceof Error ? error.message : options.saveErrorMessage,
    );
  } finally {
    if (options.selectedJobIdRef.current === jobId) {
      options.setSaving(false);
    }
  }
}

interface ChangeCuePositionOptions {
  cuesRef: MutableRefObject<Cue[]>;
  editRef: MutableRefObject<CuePositionEdit | null>;
  isSavingTranscriptRef: MutableRefObject<boolean>;
  selectedJobIdRef: MutableRefObject<string | null>;
  subtitlePosition: number;
  setSubtitlePosition: (position: number) => void;
  setTranscriptSaveError: (error: string | null) => void;
  updateCues: (cues: Cue[]) => void;
}

function changeCuePositionDraft(
  sourceCueIndex: number,
  position: number,
  scope: SubtitlePositionScope,
  options: ChangeCuePositionOptions,
): void {
  if (sourceCueIndex < 0 || options.isSavingTranscriptRef.current) return;
  const roundedPosition = clampSubtitlePosition(position);
  const edit = buildCuePositionEdit({
    existingEdit: options.editRef.current,
    currentCues: options.cuesRef.current,
    sourceCueIndex,
    position: roundedPosition,
    scope,
    jobId: options.selectedJobIdRef.current,
    sharedPosition: options.subtitlePosition,
  });
  if (!edit) return;
  options.editRef.current = edit;
  options.setTranscriptSaveError(null);
  if (scope === "all") {
    options.setSubtitlePosition(
      clampSubtitlePosition(
        edit.previousSharedPosition +
          roundedPosition -
          edit.sourceStartPosition,
      ),
    );
  }
  options.updateCues(edit.draftCues);
}

interface CancelCuePositionOptions {
  editRef: MutableRefObject<CuePositionEdit | null>;
  setSubtitlePosition: (position: number) => void;
  updateCues: (cues: Cue[]) => void;
}

function cancelCuePositionDraft(
  sourceCueIndex: number,
  scope: SubtitlePositionScope,
  options: CancelCuePositionOptions,
): void {
  const edit = options.editRef.current;
  if (!matchesCuePositionEdit(edit, sourceCueIndex, scope)) return;
  options.editRef.current = null;
  if (edit.scope === "all") {
    options.setSubtitlePosition(edit.previousSharedPosition);
  }
  options.updateCues(edit.previousCues);
}

interface ResetCuePositionOptions {
  cuesRef: MutableRefObject<Cue[]>;
  isSavingTranscriptRef: MutableRefObject<boolean>;
  selectedJobIdRef: MutableRefObject<string | null>;
  setSaving: (saving: boolean) => void;
  setTranscriptSaveError: (error: string | null) => void;
  updateCues: (cues: Cue[]) => void;
  onRefreshJobs?: () => Promise<void>;
  saveErrorMessage: string;
}

async function resetCuePositionOverride(
  sourceCueIndex: number,
  options: ResetCuePositionOptions,
): Promise<void> {
  if (sourceCueIndex < 0 || options.isSavingTranscriptRef.current) return;
  const previousCues = options.cuesRef.current;
  const targetCue = previousCues[sourceCueIndex];
  if (
    !targetCue ||
    targetCue.position === undefined ||
    targetCue.position === null
  ) {
    return;
  }
  const nextCues = previousCues.map((cue, index) => {
    if (index !== sourceCueIndex) return cue;
    const cueWithoutPosition = { ...cue };
    delete cueWithoutPosition.position;
    return cueWithoutPosition;
  });
  const jobId = options.selectedJobIdRef.current;
  options.updateCues(nextCues);
  if (!jobId) return;
  options.setSaving(true);
  options.setTranscriptSaveError(null);
  try {
    await api.updateJobTranscription(jobId, persistedCues(nextCues));
    if (options.selectedJobIdRef.current !== jobId) return;
    void options.onRefreshJobs?.();
    reportProductAction("subtitle_saved", { outcome: "succeeded" });
  } catch (error) {
    if (options.selectedJobIdRef.current !== jobId) return;
    options.updateCues(previousCues);
    options.setTranscriptSaveError(
      error instanceof Error ? error.message : options.saveErrorMessage,
    );
  } finally {
    if (options.selectedJobIdRef.current === jobId) options.setSaving(false);
  }
}

interface CuePositionActionsOptions
  extends ChangeCuePositionOptions, ResetCuePositionOptions {
  setSubtitlePosition: (position: number) => void;
}

function createCuePositionActions(options: CuePositionActionsOptions) {
  return {
    changeCuePosition(
      sourceCueIndex: number,
      position: number,
      scope: SubtitlePositionScope = "cue",
    ) {
      changeCuePositionDraft(sourceCueIndex, position, scope, options);
    },
    async commitCuePosition(
      sourceCueIndex: number,
      scope: SubtitlePositionScope = "cue",
    ) {
      const edit = takeCuePositionEdit(options.editRef, sourceCueIndex, scope);
      if (!edit) return;
      await persistCuePositionEdit(edit, options);
    },
    cancelCuePosition(
      sourceCueIndex: number,
      scope: SubtitlePositionScope = "cue",
    ) {
      cancelCuePositionDraft(sourceCueIndex, scope, options);
    },
    async resetCuePosition(sourceCueIndex: number) {
      await resetCuePositionOverride(sourceCueIndex, options);
    },
  };
}

export function persistedCues(cues: Cue[]): Cue[] {
  return cues.map((cue) => {
    const persistedCue = { ...cue };
    delete persistedCue.sourceCueIndex;
    return persistedCue;
  });
}

export function useCuePositioning({
  cues,
  setCues,
  subtitlePosition,
  setSubtitlePosition,
  selectedJobId,
  selectedJobIdRef,
  isSavingTranscriptRef,
  setIsSavingTranscript,
  setTranscriptSaveError,
  onRefreshJobs,
  saveErrorMessage,
}: UseCuePositioningOptions) {
  const { cuesRef, editRef, setSaving, updateCues } = useCuePositionState({
    cues,
    setCues,
    selectedJobId,
    isSavingTranscriptRef,
    setIsSavingTranscript,
  });

  return useMemo(
    () =>
      createCuePositionActions({
        cuesRef,
        editRef,
        isSavingTranscriptRef,
        selectedJobIdRef,
        subtitlePosition,
        setSubtitlePosition,
        setTranscriptSaveError,
        updateCues,
        setSaving,
        onRefreshJobs,
        saveErrorMessage,
      }),
    [
      cuesRef,
      editRef,
      isSavingTranscriptRef,
      selectedJobIdRef,
      setSaving,
      setSubtitlePosition,
      setTranscriptSaveError,
      subtitlePosition,
      updateCues,
      onRefreshJobs,
      saveErrorMessage,
    ],
  );
}
