package com.ascentia.subs.common;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RateLimitServiceUnitTest {

    @Test
    void checkUsesExactWindowAndBlocksOnlyAboveLimit() {
        JdbcClient jdbcClient = mock(JdbcClient.class);
        JdbcClient.StatementSpec deleteSpec = mock(JdbcClient.StatementSpec.class);
        JdbcClient.StatementSpec upsertSpec = mock(JdbcClient.StatementSpec.class);
        @SuppressWarnings("unchecked")
        JdbcClient.MappedQuerySpec<Integer> querySpec = mock(JdbcClient.MappedQuerySpec.class);

        when(jdbcClient.sql(startsWith("DELETE FROM rate_limits"))).thenReturn(deleteSpec);
        when(deleteSpec.param(anyString(), any())).thenReturn(deleteSpec);
        when(deleteSpec.update()).thenReturn(0);

        when(jdbcClient.sql(startsWith("INSERT INTO rate_limits"))).thenReturn(upsertSpec);
        when(upsertSpec.param(anyString(), any())).thenReturn(upsertSpec);
        when(upsertSpec.query(Integer.class)).thenReturn(querySpec);
        when(querySpec.single()).thenReturn(2, 3);

        RateLimitService service = new RateLimitService(jdbcClient);

        assertThatCode(() -> service.check("login", "user-1", 2, 60)).doesNotThrowAnyException();

        ArgumentCaptor<Object> nowCaptor = ArgumentCaptor.forClass(Object.class);
        ArgumentCaptor<Object> expiresAtCaptor = ArgumentCaptor.forClass(Object.class);
        ArgumentCaptor<Object> minWindowStartCaptor = ArgumentCaptor.forClass(Object.class);
        verify(upsertSpec).param(eq("now"), nowCaptor.capture());
        verify(upsertSpec).param(eq("expiresAt"), expiresAtCaptor.capture());
        verify(upsertSpec).param(eq("minWindowStart"), minWindowStartCaptor.capture());

        long now = (Long) nowCaptor.getValue();
        long expiresAt = (Long) expiresAtCaptor.getValue();
        long minWindowStart = (Long) minWindowStartCaptor.getValue();
        assertThat(expiresAt - now).isEqualTo(60);
        assertThat(now - minWindowStart).isEqualTo(60);

        assertThatThrownBy(() -> service.check("login", "user-1", 2, 60))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("429 TOO_MANY_REQUESTS");
    }

    @Test
    void checkAllowsRequestsWhenDatabaseReturnsNullCount() {
        JdbcClient jdbcClient = mock(JdbcClient.class);
        JdbcClient.StatementSpec deleteSpec = mock(JdbcClient.StatementSpec.class);
        JdbcClient.StatementSpec upsertSpec = mock(JdbcClient.StatementSpec.class);
        @SuppressWarnings("unchecked")
        JdbcClient.MappedQuerySpec<Integer> querySpec = mock(JdbcClient.MappedQuerySpec.class);

        when(jdbcClient.sql(startsWith("DELETE FROM rate_limits"))).thenReturn(deleteSpec);
        when(deleteSpec.param(anyString(), any())).thenReturn(deleteSpec);
        when(deleteSpec.update()).thenReturn(0);

        when(jdbcClient.sql(startsWith("INSERT INTO rate_limits"))).thenReturn(upsertSpec);
        when(upsertSpec.param(anyString(), any())).thenReturn(upsertSpec);
        when(upsertSpec.query(Integer.class)).thenReturn(querySpec);
        when(querySpec.single()).thenReturn(null);

        RateLimitService service = new RateLimitService(jdbcClient);

        assertThatCode(() -> service.check("login", "user-1", 2, 60)).doesNotThrowAnyException();
    }
}
