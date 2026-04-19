package com.ascentia.subs.common;

import jakarta.servlet.http.HttpServletRequest;
import java.net.InetAddress;
import java.util.Arrays;
import org.springframework.stereotype.Component;

@Component
public class ClientIpResolver {

    public String resolve(HttpServletRequest request) {
        String remoteAddress = request.getRemoteAddr();
        if (remoteAddress != null && !remoteAddress.isBlank()) {
            return remoteAddress;
        }

        String forwarded = request.getHeader("x-forwarded-for");
        if (forwarded != null && !forwarded.isBlank()) {
            String[] parts = Arrays.stream(forwarded.split(",")).map(String::trim).filter(value -> !value.isEmpty()).toArray(String[]::new);
            if (parts.length > 0) {
                return normalize(parts[parts.length - 1]);
            }
        }

        String realIp = request.getHeader("x-real-ip");
        if (realIp != null && !realIp.isBlank()) {
            return normalize(realIp);
        }

        return "unknown";
    }

    private String normalize(String value) {
        try {
            return InetAddress.getByName(value.trim()).getHostAddress();
        } catch (Exception ignored) {
            return value.trim();
        }
    }
}
