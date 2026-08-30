import type { TranscriptionCue as Cue } from "./api";

export function findCueIndexAtTime(cues: Cue[], time: number): number {
  let low = 0;
  let high = cues.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const cue = cues[mid];
    if (time >= cue.start && time < cue.end) return mid;
    if (time < cue.start) high = mid - 1;
    else low = mid + 1;
  }
  return -1;
}

export function findCueAtTime(cues: Cue[], time: number): Cue | undefined {
  const index = findCueIndexAtTime(cues, time);
  return index !== -1 ? cues[index] : undefined;
}
