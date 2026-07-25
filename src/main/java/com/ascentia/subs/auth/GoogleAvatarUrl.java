package com.ascentia.subs.auth;

import java.net.URI;

final class GoogleAvatarUrl {

    private static final String HOST = "lh3.googleusercontent.com";
    private static final int MAX_LENGTH = 2_048;

    private GoogleAvatarUrl() {
    }

    static String normalize(String value) {
        if (value == null) {
            return null;
        }
        String candidate = value.strip();
        if (candidate.isEmpty() || candidate.length() > MAX_LENGTH) {
            return null;
        }
        try {
            URI uri = URI.create(candidate);
            int port = uri.getPort();
            if (!"https".equalsIgnoreCase(uri.getScheme())
                    || !HOST.equalsIgnoreCase(uri.getHost())
                    || uri.getUserInfo() != null
                    || (port != -1 && port != 443)
                    || uri.getPath() == null
                    || !uri.getPath().startsWith("/")
                    || uri.getFragment() != null) {
                return null;
            }
            return candidate;
        } catch (IllegalArgumentException exception) {
            return null;
        }
    }
}
