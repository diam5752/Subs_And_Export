type ResolutionDimensions = { width: number; height: number };

export function parseResolutionString(
  resolution: string | null | undefined,
): ResolutionDimensions | null {
  if (!resolution) return null;
  const match = resolution.match(/(\d+)\s*[x×]\s*(\d+)/i);
  if (!match) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
  return { width, height };
}

export function describeResolution(
  width?: number,
  height?: number,
): { text: string; label: string } | null {
  if (!width || !height) return null;
  const verticalLines = Math.min(width, height);
  let label = "SD";
  if (verticalLines >= 2160) label = "4K / 2160p";
  else if (verticalLines >= 1440) label = "QHD / 1440p";
  else if (verticalLines >= 1080) label = "Full HD / 1080p";
  else if (verticalLines >= 720) label = "HD / 720p";
  return { text: `${width}×${height}`, label };
}

export function describeResolutionString(
  resolution?: string | null,
): { text: string; label: string } | null {
  const parsed = parseResolutionString(resolution);
  return parsed ? describeResolution(parsed.width, parsed.height) : null;
}
