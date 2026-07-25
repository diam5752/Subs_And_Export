'use client';

import Image from 'next/image';
import { useState } from 'react';

interface ProfileAvatarProps {
    name: string;
    avatarUrl?: string | null;
}

export function ProfileAvatar({ name, avatarUrl }: ProfileAvatarProps) {
    const normalizedAvatarUrl = avatarUrl?.trim() || null;
    const [failedUrl, setFailedUrl] = useState<string | null>(null);
    const showImage = normalizedAvatarUrl !== null && failedUrl !== normalizedAvatarUrl;
    const initial = name.trim().charAt(0).toUpperCase() || 'A';

    return (
        <>
            <span className="profile-avatar-fallback" aria-hidden="true">
                {initial}
            </span>
            {showImage && (
                <Image
                    key={normalizedAvatarUrl}
                    src={normalizedAvatarUrl}
                    alt=""
                    width={34}
                    height={34}
                    unoptimized
                    referrerPolicy="no-referrer"
                    className="profile-avatar-image"
                    data-testid="profile-avatar-image"
                    onError={() => setFailedUrl(normalizedAvatarUrl)}
                />
            )}
        </>
    );
}
