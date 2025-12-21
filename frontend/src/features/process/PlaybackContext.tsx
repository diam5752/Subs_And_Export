import React, { createContext, useContext, useState, useMemo } from 'react';

interface PlaybackContextType {
    currentTime: number;
    setCurrentTime: (time: number) => void;
}

const PlaybackContext = createContext<PlaybackContextType | undefined>(undefined);

export function usePlaybackContext() {
    const context = useContext(PlaybackContext);
    if (!context) {
        throw new Error('usePlaybackContext must be used within a PlaybackProvider');
    }
    return context;
}

export function PlaybackProvider({ children }: { children: React.ReactNode }) {
    const [currentTime, setCurrentTime] = useState(0);

    const value = useMemo(() => ({
        currentTime,
        setCurrentTime
    }), [currentTime]);

    return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
}
