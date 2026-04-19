package com.ascentia.subs.common;

import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.Map;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(ResponseStatusException.class)
    ResponseEntity<Map<String, Object>> handleStatus(ResponseStatusException exception, HttpServletRequest request) {
        return response(exception.getStatusCode(), messageOf(exception), request.getRequestURI());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException exception, HttpServletRequest request) {
        String detail = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(FieldError::getDefaultMessage)
                .orElse("Validation failed");
        return response(HttpStatus.BAD_REQUEST, detail, request.getRequestURI());
    }

    @ExceptionHandler({BadCredentialsException.class, AccessDeniedException.class})
    ResponseEntity<Map<String, Object>> handleSecurity(Exception exception, HttpServletRequest request) {
        HttpStatus status = exception instanceof AccessDeniedException ? HttpStatus.FORBIDDEN : HttpStatus.UNAUTHORIZED;
        return response(status, exception instanceof AccessDeniedException ? "Forbidden" : "Could not validate credentials", request.getRequestURI());
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Map<String, Object>> handleGeneric(Exception exception, HttpServletRequest request) {
        return response(HttpStatus.INTERNAL_SERVER_ERROR, sanitizeMessage(exception.getMessage()), request.getRequestURI());
    }

    private ResponseEntity<Map<String, Object>> response(HttpStatusCode status, String detail, String path) {
        return ResponseEntity.status(status)
                .body(Map.of(
                        "timestamp", Instant.now().toString(),
                        "status", status.value(),
                        "detail", detail,
                        "path", path
                ));
    }

    static String sanitizeMessage(String message) {
        if (message == null || message.isBlank()) {
            return "Request failed";
        }
        return message
                .replaceAll("sk-[A-Za-z0-9_-]+", "[API_KEY_REDACTED]")
                .replaceAll("gsk_[A-Za-z0-9_-]+", "[API_KEY_REDACTED]");
    }

    static String messageOf(ResponseStatusException exception) {
        ProblemDetail body = exception.getBody();
        if (body != null && body.getDetail() != null && !body.getDetail().isBlank()) {
            return body.getDetail();
        }
        String reason = exception.getReason();
        if (reason != null && !reason.isBlank()) {
            return reason;
        }
        return HttpStatus.valueOf(exception.getStatusCode().value()).getReasonPhrase();
    }
}
