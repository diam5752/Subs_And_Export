package com.ascentia.subs.auth;

import org.springframework.security.core.Authentication;
import org.springframework.web.server.ResponseStatusException;
import static org.springframework.http.HttpStatus.UNAUTHORIZED;

public final class CurrentUserAccess {

    private CurrentUserAccess() {
    }

    public static CurrentUser require(Authentication authentication) {
        if (authentication == null || !(authentication.getPrincipal() instanceof CurrentUser currentUser)) {
            throw new ResponseStatusException(UNAUTHORIZED, "Could not validate credentials");
        }
        return currentUser;
    }
}
