const INVALID_FILENAME_CHARACTERS = /[<>:"/\\|?*\u0000-\u001F\u007F]/g;

function filenameStem(originalFilename?: string | null): string {
    const basename = (originalFilename ?? '')
        .replace(/\\/g, '/')
        .split('/')
        .pop()
        ?.trim() ?? '';
    const extensionIndex = basename.lastIndexOf('.');
    const rawStem = extensionIndex > 0 ? basename.slice(0, extensionIndex) : basename;
    const safeStem = rawStem
        .replace(INVALID_FILENAME_CHARACTERS, '_')
        .replace(/[. ]+$/g, '')
        .trim();

    return safeStem || 'video';
}

export function buildSubtitleExportFilename(
    originalFilename: string | null | undefined,
    exportFormat: string,
): string {
    const normalizedFormat = exportFormat.toLowerCase();
    const extension = ['srt', 'vtt', 'txt'].includes(normalizedFormat)
        ? normalizedFormat
        : 'mp4';

    return `${filenameStem(originalFilename)}_subs.${extension}`;
}

export function withDownloadParameters(url: string, filename: string): string {
    const hashIndex = url.indexOf('#');
    const base = hashIndex >= 0 ? url.slice(0, hashIndex) : url;
    const hash = hashIndex >= 0 ? url.slice(hashIndex) : '';
    const separator = base.includes('?') ? '&' : '?';
    return `${base}${separator}download=true&filename=${encodeURIComponent(filename)}${hash}`;
}
