
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
const ISO_BMFF_HEADER_BYTES = 16;
const ISO_BMFF_MAX_TOP_LEVEL_BOXES = 512;
const ISO_BMFF_MAX_MOOV_BYTES = 8 * 1024 * 1024;
const ISO_BMFF_MAX_NESTED_BOXES = 2_048;
const ISO_BMFF_MAX_TRACKS = 64;
const ISO_BMFF_MAX_FILE_BYTES = 500 * 1024 * 1024;

type VideoContainerMetadata = {
    width: number;
    height: number;
    durationSeconds: number;
};

type IsoBox = {
    type: string;
    headerSize: number;
    end: number;
};

type IsoBoxBudget = { remaining: number };

function readUint64(view: DataView, offset: number): number | null {
    if (offset < 0 || offset + 8 > view.byteLength) return null;
    const high = view.getUint32(offset);
    const low = view.getUint32(offset + 4);
    const value = high * 0x1_0000_0000 + low;
    return Number.isSafeInteger(value) ? value : null;
}

function readIsoBox(view: DataView, start: number, containerEnd: number): IsoBox | null {
    if (start < 0 || containerEnd > view.byteLength || start + 8 > containerEnd) return null;
    const size32 = view.getUint32(start);
    const type = String.fromCharCode(
        view.getUint8(start + 4),
        view.getUint8(start + 5),
        view.getUint8(start + 6),
        view.getUint8(start + 7),
    );
    let headerSize = 8;
    let size = size32;
    if (size32 === 1) {
        if (start + 16 > containerEnd) return null;
        const extendedSize = readUint64(view, start + 8);
        if (extendedSize === null) return null;
        headerSize = 16;
        size = extendedSize;
    } else if (size32 === 0) {
        size = containerEnd - start;
    }
    if (!Number.isSafeInteger(size) || size < headerSize || size > containerEnd - start) {
        return null;
    }
    return { type, headerSize, end: start + size };
}

function readNestedIsoBox(
    view: DataView,
    start: number,
    containerEnd: number,
    budget: IsoBoxBudget,
): IsoBox | null {
    if (budget.remaining <= 0) return null;
    budget.remaining -= 1;
    return readIsoBox(view, start, containerEnd);
}

function parseMovieDuration(view: DataView, box: IsoBox, start: number): number | null {
    const contentStart = start + box.headerSize;
    if (contentStart + 4 > box.end) return null;
    const version = view.getUint8(contentStart);
    if (version !== 0 && version !== 1) return null;
    const minimumContentLength = version === 1 ? 112 : 100;
    if (box.end - contentStart < minimumContentLength) return null;
    const timescaleOffset = version === 1 ? contentStart + 20 : contentStart + 12;
    const durationOffset = version === 1 ? contentStart + 24 : contentStart + 16;
    if (timescaleOffset + 4 > box.end) return null;
    const timescale = view.getUint32(timescaleOffset);
    const duration = version === 1
        ? durationOffset + 8 <= box.end
            ? readUint64(view, durationOffset)
            : null
        : durationOffset + 4 <= box.end
            ? view.getUint32(durationOffset)
            : null;
    if (
        !timescale
        || duration === null
        || duration <= 0
        || (version === 0 && duration === 0xffff_ffff)
    ) return null;
    const durationSeconds = duration / timescale;
    return Number.isFinite(durationSeconds) && durationSeconds > 0
        ? durationSeconds
        : null;
}

function parseTrackDimensions(view: DataView, box: IsoBox, start: number): { width: number; height: number } | null {
    const contentStart = start + box.headerSize;
    if (contentStart + 4 > box.end) return null;
    const version = view.getUint8(contentStart);
    if (version !== 0 && version !== 1) return null;
    const minimumContentLength = version === 1 ? 96 : 84;
    if (box.end - contentStart < minimumContentLength) return null;
    const matrixOffset = contentStart + (version === 1 ? 52 : 40);
    const widthOffset = contentStart + (version === 1 ? 88 : 76);
    if (matrixOffset + 24 > widthOffset || widthOffset + 8 > box.end) return null;
    const matrixA = view.getInt32(matrixOffset) / 65_536;
    const matrixB = view.getInt32(matrixOffset + 4) / 65_536;
    const matrixC = view.getInt32(matrixOffset + 12) / 65_536;
    const matrixD = view.getInt32(matrixOffset + 16) / 65_536;
    let width = view.getUint32(widthOffset) / 65_536;
    let height = view.getUint32(widthOffset + 4) / 65_536;
    if (
        !Number.isFinite(width)
        || !Number.isFinite(height)
        || width <= 0
        || height <= 0
        || width > 16_384
        || height > 16_384
    ) {
        return null;
    }
    const isQuarterTurn = Math.abs(matrixA) < 0.01
        && Math.abs(matrixD) < 0.01
        && Math.abs(Math.abs(matrixB) - 1) < 0.01
        && Math.abs(Math.abs(matrixC) - 1) < 0.01
        && matrixB * matrixC < 0;
    if (isQuarterTurn) {
        [width, height] = [height, width];
    }
    return { width, height };
}

function parseHandlerType(view: DataView, box: IsoBox, start: number): string | null {
    const contentStart = start + box.headerSize;
    if (contentStart + 24 > box.end || view.getUint8(contentStart) !== 0) return null;
    return String.fromCharCode(
        view.getUint8(contentStart + 8),
        view.getUint8(contentStart + 9),
        view.getUint8(contentStart + 10),
        view.getUint8(contentStart + 11),
    );
}

function parseVideoTrackDimensions(
    view: DataView,
    track: IsoBox,
    trackStart: number,
    budget: IsoBoxBudget,
): { width: number; height: number } | null {
    let dimensions: { width: number; height: number } | null = null;
    let handlerType: string | null = null;
    let sawTrackHeader = false;
    let sawMedia = false;
    let sawHandler = false;
    let childOffset = trackStart + track.headerSize;
    while (childOffset < track.end) {
        const child = readNestedIsoBox(view, childOffset, track.end, budget);
        if (!child) return null;
        if (child.type === 'tkhd') {
            if (sawTrackHeader) return null;
            sawTrackHeader = true;
            dimensions = parseTrackDimensions(view, child, childOffset);
        } else if (child.type === 'mdia') {
            if (sawMedia) return null;
            sawMedia = true;
            let mediaOffset = childOffset + child.headerSize;
            while (mediaOffset < child.end) {
                const mediaChild = readNestedIsoBox(view, mediaOffset, child.end, budget);
                if (!mediaChild) return null;
                if (mediaChild.type === 'hdlr') {
                    if (sawHandler) return null;
                    sawHandler = true;
                    handlerType = parseHandlerType(view, mediaChild, mediaOffset);
                }
                mediaOffset = mediaChild.end;
            }
            if (mediaOffset !== child.end) return null;
        }
        childOffset = child.end;
    }
    if (childOffset !== track.end || handlerType !== 'vide') return null;
    return dimensions;
}

function parseIsoBmffMovieBox(buffer: ArrayBuffer): VideoContainerMetadata | null {
    const view = new DataView(buffer);
    const budget = { remaining: ISO_BMFF_MAX_NESTED_BOXES };
    const movieBox = readNestedIsoBox(view, 0, view.byteLength, budget);
    if (!movieBox || movieBox.type !== 'moov' || movieBox.end !== view.byteLength) return null;

    let durationSeconds: number | null = null;
    let dimensions: { width: number; height: number } | null = null;
    let trackCount = 0;
    let sawMovieHeader = false;
    let childOffset = movieBox.headerSize;
    while (childOffset < movieBox.end) {
        const child = readNestedIsoBox(view, childOffset, movieBox.end, budget);
        if (!child) return null;
        if (child.type === 'mvhd') {
            if (sawMovieHeader) return null;
            sawMovieHeader = true;
            durationSeconds = parseMovieDuration(view, child, childOffset);
        } else if (child.type === 'trak') {
            trackCount += 1;
            if (trackCount > ISO_BMFF_MAX_TRACKS) return null;
            const candidate = parseVideoTrackDimensions(view, child, childOffset, budget);
            if (candidate && (!dimensions || candidate.width * candidate.height > dimensions.width * dimensions.height)) {
                dimensions = candidate;
            }
        }
        childOffset = child.end;
    }
    if (childOffset !== movieBox.end || durationSeconds === null || !dimensions) return null;
    return {
        width: dimensions.width,
        height: dimensions.height,
        durationSeconds,
    };
}

async function readBlobArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
    if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer();
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.addEventListener('load', () => {
            if (reader.result instanceof ArrayBuffer) resolve(reader.result);
            else reject(new Error('The selected video could not be read'));
        }, { once: true });
        reader.addEventListener('error', () => reject(reader.error ?? new Error('The selected video could not be read')), { once: true });
        reader.readAsArrayBuffer(blob);
    });
}

async function readIsoBmffMetadata(
    file: File,
    signal?: AbortSignal,
): Promise<VideoContainerMetadata | null> {
    if (
        !Number.isSafeInteger(file.size)
        || file.size <= 0
        || file.size > ISO_BMFF_MAX_FILE_BYTES
    ) return null;
    if (
        !/\.(?:mp4|mov)$/i.test(file.name)
        && file.type !== 'video/mp4'
        && file.type !== 'video/quicktime'
    ) {
        return null;
    }

    let offset = 0;
    let boxCount = 0;
    let sawFileType = false;
    let movieRange: { start: number; size: number } | null = null;
    while (offset + 8 <= file.size && boxCount < ISO_BMFF_MAX_TOP_LEVEL_BOXES) {
        if (signal?.aborted) return null;
        const headerLength = Math.min(ISO_BMFF_HEADER_BYTES, file.size - offset);
        const headerBuffer = await readBlobArrayBuffer(file.slice(offset, offset + headerLength));
        if (signal?.aborted) return null;
        const headerView = new DataView(headerBuffer);
        if (headerView.byteLength < 8) return null;

        const size32 = headerView.getUint32(0);
        const type = String.fromCharCode(
            headerView.getUint8(4),
            headerView.getUint8(5),
            headerView.getUint8(6),
            headerView.getUint8(7),
        );
        let headerSize = 8;
        let size = size32;
        if (size32 === 1) {
            if (headerView.byteLength < 16) return null;
            const extendedSize = readUint64(headerView, 8);
            if (extendedSize === null) return null;
            headerSize = 16;
            size = extendedSize;
        } else if (size32 === 0) {
            size = file.size - offset;
        }
        if (!Number.isSafeInteger(size) || size < headerSize || size > file.size - offset) {
            return null;
        }
        if (type === 'ftyp') {
            if (sawFileType || movieRange || headerSize !== 8 || size < 16) return null;
            const majorBrandIsPrintable = [8, 9, 10, 11].every((index) => (
                headerView.getUint8(index) >= 0x20 && headerView.getUint8(index) <= 0x7e
            ));
            if (!majorBrandIsPrintable) return null;
            sawFileType = true;
        } else if (type === 'moov') {
            if (!sawFileType || movieRange) return null;
            if (size > ISO_BMFF_MAX_MOOV_BYTES) return null;
            movieRange = { start: offset, size };
        }
        offset += size;
        boxCount += 1;
    }
    if (offset !== file.size || !sawFileType || !movieRange) return null;
    if (signal?.aborted) return null;
    const movieBuffer = await readBlobArrayBuffer(file.slice(
        movieRange.start,
        movieRange.start + movieRange.size,
    ));
    if (signal?.aborted) return null;
    if (movieBuffer.byteLength !== movieRange.size) return null;
    return parseIsoBmffMovieBox(movieBuffer);
}

export const validateVideoAspectRatio = (
    file: File,
    signal?: AbortSignal,
): Promise<{ width: number; height: number; aspectWarning: boolean; thumbnailUrl: string | null; durationSeconds: number }> => {
    return new Promise((resolve) => {
        const video = document.createElement('video');
        const objectUrl = URL.createObjectURL(file);
        let resolved = false;
        let captureStarted = false;
        let containerMetadata: VideoContainerMetadata | null = null;
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
            if (signal) {
                signal.removeEventListener('abort', abortHandler);
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
            const nativeDimensionsAreUsable = Number.isFinite(video.videoWidth)
                && Number.isFinite(video.videoHeight)
                && video.videoWidth > 0
                && video.videoHeight > 0;
            const width = nativeDimensionsAreUsable
                ? video.videoWidth
                : containerMetadata?.width ?? 0;
            const height = nativeDimensionsAreUsable
                ? video.videoHeight
                : containerMetadata?.height ?? 0;
            const durationSeconds = Number.isFinite(video.duration) && video.duration > 0
                ? video.duration
                : containerMetadata?.durationSeconds ?? 0;
            const ratio = width && height ? width / height : 0;
            const is916 = ratio >= 0.5 && ratio <= 0.625;
            cleanup();
            resolve({ width, height, durationSeconds, aspectWarning: !is916, thumbnailUrl });
        };

        const abortHandler = () => finish(null);
        if (signal?.aborted) {
            abortHandler();
            return;
        }
        signal?.addEventListener('abort', abortHandler, { once: true });

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

        // REGRESSION: iOS/WebKit can fail to publish finite media-element
        // metadata for a valid local MP4 even after the normal readiness
        // window. Only after native metadata has exhausted that window, read
        // bounded ISO BMFF headers as a deterministic fallback. Healthy files
        // therefore keep the native thumbnail path and perform no file reads.
        metadataTimeout = window.setTimeout(() => {
            metadataTimeout = undefined;
            void readIsoBmffMetadata(file, signal).then((metadata) => {
                if (resolved) return;
                containerMetadata = metadata;
                beginFrameCaptureWhenMetadataIsUsable();
                if (captureStarted) return;
                finish(null);
            }).catch(() => {
                if (resolved) return;
                beginFrameCaptureWhenMetadataIsUsable();
                if (!captureStarted) finish(null);
            });
        }, VIDEO_METADATA_READINESS_TIMEOUT_MS);
        video.src = objectUrl;
        try {
            video.load();
        } catch (e) {
            console.warn('Video load error ignored:', e);
        }
    });
};
