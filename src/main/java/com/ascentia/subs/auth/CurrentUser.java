package com.ascentia.subs.auth;

public record CurrentUser(
        String id,
        String email,
        String name,
        String provider,
        String passwordHash,
        String googleSub,
        String createdAt,
        boolean emailVerified
) {
}
