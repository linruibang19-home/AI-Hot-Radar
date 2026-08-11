package com.aihotradar.coreapi.admin;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The audit trail, readable by any authenticated principal including {@code VIEWER}.
 *
 * <p>This is the endpoint that makes {@code VIEWER} worth having: something to read that is not
 * public. It is also the most sensitive read on the service — it lists failed authentication
 * attempts — which is why it lives under {@code /admin} and behind {@link AdminAuthFilter} rather
 * than beside the public source health view.
 */
@RestController
@RequestMapping("/api/v1/admin/audit")
public class AdminAuditController {

    private final AdminAudit audit;

    public AdminAuditController(AdminAudit audit) {
        this.audit = audit;
    }

    @GetMapping
    public List<Map<String, Object>> recent(@RequestParam(defaultValue = "50") int limit) {
        return audit.recent(limit);
    }
}
