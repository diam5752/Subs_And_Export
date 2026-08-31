import { useCallback, useMemo, useState } from "react";
import type { Cue } from "@/components/SubtitleOverlay";

export function useCueResource(transcriptionSource: string | null) {
  const [cueResource, setCueResource] = useState<{
    source: string | null;
    cues: Cue[];
    error: string | null;
  }>({ source: transcriptionSource, cues: [], error: null });
  const cues = useMemo(
    () => (cueResource.source === transcriptionSource ? cueResource.cues : []),
    [cueResource, transcriptionSource],
  );
  const error =
    cueResource.source === transcriptionSource ? cueResource.error : null;
  const setCues = useCallback(
    (nextCues: Cue[]) => {
      setCueResource({
        source: transcriptionSource,
        cues: nextCues,
        error: null,
      });
    },
    [transcriptionSource],
  );
  return { cues, error, setCues, setCueResource };
}
