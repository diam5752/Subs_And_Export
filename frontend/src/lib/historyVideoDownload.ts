import { api, type JobResponse } from "@/lib/api";
import { downloadArtifactWithGrant } from "@/lib/artifactDownload";
import { buildSubtitleExportFilename } from "@/lib/exportFilename";
import { parseResolutionString } from "@/lib/videoResolution";

type StaticUrlBuilder = (path?: string | null) => string | null;

function historyExportResolution(
  resolution: string | null | undefined,
): string {
  const dimensions = parseResolutionString(resolution);
  return dimensions ? `${dimensions.width}x${dimensions.height}` : "1080x1920";
}

export async function downloadHistoryVideo(
  job: JobResponse,
  buildStaticUrl: StaticUrlBuilder,
): Promise<void> {
  const result = job.result_data;
  if (!result || !(result.public_url || result.video_path)) {
    throw new Error("The secure download could not be prepared.");
  }

  // The main video is the clean editor preview. Render the current saved
  // captions before preparing any History download.
  const resolution = historyExportResolution(result.resolution);
  const exportedJob = await api.exportVideo(job.id, resolution);
  const artifact = exportedJob.result_data?.variants?.[resolution];
  if (!artifact) {
    throw new Error("Export did not include the requested video artifact");
  }
  const filename = buildSubtitleExportFilename(
    exportedJob.result_data?.original_filename ?? result.original_filename,
    "mp4",
  );
  await downloadArtifactWithGrant(job.id, artifact, filename, buildStaticUrl);
}
