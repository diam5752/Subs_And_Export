
export const parseResolutionString = (resolution?: string | null): { width: number; height: number } | null => {
    if (!resolution) return null;
    const match = resolution.match(/(\d+)\s*[x×]\s*(\d+)/i);
    if (!match) return null;
    const width = Number(match[1]);
    const height = Number(match[2]);
    if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
    return { width, height };
};

export const describeResolution = (width?: number, height?: number): { text: string; label: string } | null => {
    if (!width || !height) return null;
    const verticalLines = Math.min(width, height);
    let label = 'SD';
    if (verticalLines >= 2160) {
        label = '4K / 2160p';
    } else if (verticalLines >= 1440) {
        label = 'QHD / 1440p';
    } else if (verticalLines >= 1080) {
        label = 'Full HD / 1080p';
    } else if (verticalLines >= 720) {
        label = 'HD / 720p';
    }
    return { text: `${width}×${height}`, label };
};

export const describeResolutionString = (resolution?: string | null): { text: string; label: string } | null => {
    const parsed = parseResolutionString(resolution);
    if (!parsed) return null;
    return describeResolution(parsed.width, parsed.height);
};

const VIDEO_METADATA_READINESS_TIMEOUT_MS = 10_000;
const VIDEO_FRAME_CAPTURE_TIMEOUT_MS = 1_200;

export const validateVideoAspectRatio = (file: File): Promise<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null; durationSeconds: number }> => {
    return new Promise((resolve) => {
        const video = document.createElement('video');
        const objectUrl = URL.createObjectURL(file);
        let resolved = false;
        let captureStarted = false;
        let metadataTimeout: number | undefined;
        let frameCaptureTimeout: number | undefined;

        video.preload = 'auto';
        video.muted = true;
        video.playsInline = true;

        const cleanup = () => {
            if (metadataTimeout !== undefined) {
                window.clearTimeout(metadataTimeout);
            }
            if (frameCaptureTimeout !== undefined) {
                window.clearTimeout(frameCaptureTimeout);
            }
            URL.revokeObjectURL(objectUrl);
            video.removeAttribute('src');
            try {
                video.load();
            } catch {
                // Ignore load errors
            }
        };

        const finish = (thumbnailUrl: string | null) => {
            if (resolved) return;
            resolved = true;
            const width = video.videoWidth || 0;
            const height = video.videoHeight || 0;
            const durationSeconds = Number.isFinite(video.duration) && video.duration > 0
                ? video.duration
                : 0;
            const ratio = width && height ? width / height : 0;
            const is916 = ratio >= 0.5 && ratio <= 0.625;
            cleanup();
            resolve({ width, height, durationSeconds, aspectWarning: !is916, thumbnailUrl });
        };

        const captureFrame = () => {
            if (resolved) return;
            if (!video.videoWidth || !video.videoHeight) {
                finish(null);
                return;
            }
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            if (!ctx) {
                finish(null);
                return;
            }
            try {
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                finish(canvas.toDataURL('image/jpeg', 0.7));
            } catch {
                finish(null);
            }
        };

        const beginFrameCaptureWhenMetadataIsUsable = () => {
            if (
                resolved
                || captureStarted
                || !Number.isFinite(video.duration)
                || video.duration <= 0
                || !video.videoWidth
                || !video.videoHeight
            ) {
                return;
            }

            captureStarted = true;
            if (metadataTimeout !== undefined) {
                window.clearTimeout(metadataTimeout);
                metadataTimeout = undefined;
            }
            const targetTime = video.duration > 1
                ? Math.min(0.5, video.duration - 0.1)
                : 0;
            // Fallback in case the seek never resolves.
            frameCaptureTimeout = window.setTimeout(
                () => captureFrame(),
                VIDEO_FRAME_CAPTURE_TIMEOUT_MS,
            );
            try {
                video.currentTime = targetTime;
            } catch {
                captureFrame();
            }
        };

        video.addEventListener(
            'loadedmetadata',
            beginFrameCaptureWhenMetadataIsUsable,
            { once: true }
        );
        // WebKit can publish loadedmetadata before the local file duration is
        // finite. Keep a bounded durationchange recovery path open instead of
        // permanently classifying the file as unreadable at the frame fallback.
        video.addEventListener('durationchange', beginFrameCaptureWhenMetadataIsUsable);

        video.addEventListener('seeked', captureFrame, { once: true });
        video.addEventListener(
            'error',
            () => {
                beginFrameCaptureWhenMetadataIsUsable();
            },
            { once: true }
        );

        metadataTimeout = window.setTimeout(
            () => finish(null),
            VIDEO_METADATA_READINESS_TIMEOUT_MS,
        );
        video.src = objectUrl;
        try {
            video.load();
        } catch (e) {
            console.warn('Video load error ignored:', e);
        }
    });
};
