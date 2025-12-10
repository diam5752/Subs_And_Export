
export const describeResolution = jest.fn((w, h) => (w && h ? { text: `${w}x${h}`, label: 'HD' } : null));
export const describeResolutionString = jest.fn(() => ({ text: '1080x1920', label: 'HD' }));
export const validateVideoAspectRatio = jest.fn(() => Promise.resolve({ width: 1080, height: 1920, aspectWarning: false, thumbnailUrl: 'blob:thumb' }));
export const parseResolutionString = jest.fn(() => ({ width: 1080, height: 1920 }));
