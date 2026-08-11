package com.aihotradar.coreapi.subscription;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1/subscriptions")
public class ReportSubscriptionController {
    private final ReportSubscriptionService subscriptions;

    public ReportSubscriptionController(ReportSubscriptionService subscriptions) {
        this.subscriptions = subscriptions;
    }

    @PostMapping
    public ResponseEntity<SubscriptionResponse> request(
            @Valid @RequestBody SubscriptionRequest request) {
        subscriptions.request(request.email(), request.periods(), request.timezone());
        return ResponseEntity.accepted().body(new SubscriptionResponse(
                "PENDING_CONFIRMATION",
                "如果该地址可以接收邮件，确认链接将在稍后送达。",
                List.of()));
    }

    @PostMapping("/confirm")
    public SubscriptionResponse confirm(@Valid @RequestBody TokenRequest request) {
        ReportSubscriptionService.SubscriptionState state = subscriptions.confirm(request.token());
        return new SubscriptionResponse(state.status(), "订阅已确认。", state.periods());
    }

    @PostMapping("/unsubscribe")
    public SubscriptionResponse unsubscribe(@Valid @RequestBody TokenRequest request) {
        ReportSubscriptionService.SubscriptionState state = subscriptions.unsubscribe(request.token());
        return new SubscriptionResponse(state.status(), "已取消后续邮件。", state.periods());
    }

    @ExceptionHandler({InvalidSubscriptionTokenException.class, IllegalArgumentException.class})
    public ResponseEntity<Map<String, Object>> invalidRequest(RuntimeException exception) {
        return ResponseEntity.badRequest().body(Map.of(
                "type", "https://aihotradar.online/problems/subscription-invalid",
                "title", "Subscription request is invalid",
                "status", 400,
                "detail", exception.getMessage()));
    }

    @ExceptionHandler(SubscriptionMailUnavailableException.class)
    public ResponseEntity<Map<String, Object>> mailUnavailable() {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(Map.of(
                "type", "https://aihotradar.online/problems/subscription-mail-unavailable",
                "title", "Subscription email is temporarily unavailable",
                "status", 503,
                "detail", "确认邮件暂时无法发送，请稍后重试。"));
    }

    public record SubscriptionRequest(
            @NotBlank @Email @Size(max = 320) String email,
            @NotEmpty @Size(max = 3) Set<@NotBlank String> periods,
            @NotBlank @Size(max = 64) String timezone) {}

    public record TokenRequest(@NotBlank @Size(max = 2048) String token) {}

    public record SubscriptionResponse(String status, String message, List<String> periods) {}
}
