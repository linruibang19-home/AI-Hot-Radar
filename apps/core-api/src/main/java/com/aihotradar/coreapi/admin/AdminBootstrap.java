package com.aihotradar.coreapi.admin;

import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/**
 * Registers the configured bootstrap credential once the schema is in place.
 *
 * <p>Runs on {@code ApplicationReadyEvent} rather than at construction so it happens after Flyway
 * has created {@code admin_principal}. It is idempotent, so a restart is harmless and a rotation is
 * "change the variable, revoke the old row".
 */
@Component
public class AdminBootstrap {

    private final AdminTokens tokens;

    public AdminBootstrap(AdminTokens tokens) {
        this.tokens = tokens;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void register() {
        tokens.bootstrap();
    }
}
