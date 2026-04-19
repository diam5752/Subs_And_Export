package com.ascentia.subs.common;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.UncheckedIOException;
import java.util.Map;
import org.postgresql.util.PGobject;
import org.springframework.stereotype.Component;

@Component
public class JsonCodec {

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private final ObjectMapper objectMapper;

    public JsonCodec(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public String write(Map<String, Object> value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception exception) {
            throw new UncheckedIOException(new java.io.IOException("Failed to serialize JSON", exception));
        }
    }

    public Map<String, Object> readMap(String json) {
        if (json == null || json.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(json, MAP_TYPE);
        } catch (Exception exception) {
            throw new UncheckedIOException(new java.io.IOException("Failed to parse JSON", exception));
        }
    }

    public PGobject toJsonb(Map<String, Object> value) {
        try {
            PGobject jsonObject = new PGobject();
            jsonObject.setType("jsonb");
            jsonObject.setValue(value == null ? null : objectMapper.writeValueAsString(value));
            return jsonObject;
        } catch (Exception exception) {
            throw new UncheckedIOException(new java.io.IOException("Failed to create jsonb value", exception));
        }
    }
}
