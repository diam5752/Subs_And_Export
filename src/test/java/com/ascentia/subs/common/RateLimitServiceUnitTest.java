package com.ascentia.subs.common;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class RateLimitServiceUnitTest {

    @Test
    void checkAllowsRequestsWhenCountIsWithinLimit() {
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
        when(querySpec.single()).thenReturn(1);

        RateLimitService service = new RateLimitService(jdbcClient);

        assertThatCode(() -> service.check("login", "user-1", 2, 60)).doesNotThrowAnyException();
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
