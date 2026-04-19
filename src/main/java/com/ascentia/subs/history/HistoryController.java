package com.ascentia.subs.history;

import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.auth.CurrentUserAccess;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import java.util.List;
import java.util.Map;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/history")
public class HistoryController {

    private final HistoryStore historyStore;

    public HistoryController(HistoryStore historyStore) {
        this.historyStore = historyStore;
    }

    @GetMapping({"", "/"})
    List<HistoryEventResponse> readHistory(
            @RequestParam(name = "limit", defaultValue = "50") @Min(1) @Max(200) int limit,
            Authentication authentication
    ) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        return historyStore.recentForUser(currentUser.id(), limit).stream().map(HistoryEventResponse::from).toList();
    }

    public record HistoryEventResponse(String ts, String user_id, String email, String kind, String summary, Map<String, Object> data) {
        static HistoryEventResponse from(HistoryStore.HistoryEvent event) {
            return new HistoryEventResponse(event.ts(), event.userId(), event.email(), event.kind(), event.summary(), event.data());
        }
    }
}
