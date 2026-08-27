import { api } from '@/lib/api';

type StaticUrlBuilder = (path?: string | null) => string | null;

export async function downloadArtifactWithGrant(
    jobId: string,
    artifactPath: string,
    filename: string,
    buildStaticUrl: StaticUrlBuilder,
): Promise<void> {
    const grant = await api.createArtifactDownloadGrant(
        jobId,
        artifactPath,
        filename,
    );
    const grantedUrl = buildStaticUrl(grant.download_url);
    if (!grantedUrl) {
        throw new Error('Download grant did not include a usable URL');
    }

    // Keep large private artifacts streamed by the server. The short-lived,
    // exact URL remains usable if iOS hands it to a different browser that
    // does not share the authenticated session which created it.
    const link = document.createElement('a');
    link.href = grantedUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}
