package com.ascentia.subs.auth;

public record CurrentUser(
        String id,
        String email,
        String name,
        String provider,
        String passwordHash,
        String googleSub,
        String avatarUrl,
        String createdAt,
        boolean emailVerified
) {
    public CurrentUser(
            String id,
            String email,
            String name,
            String provider,
            String passwordHash,
            String googleSub,
            String createdAt,
            boolean emailVerified
    ) {
        this(
                id,
                email,
                name,
                provider,
                passwordHash,
                googleSub,
                null,
                createdAt,
                emailVerified
        );
    }
}
