package com.aihotradar.coreapi;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Core API entry point.
 *
 * <p>Scope per AHR-ARCH-200 §3: content queries, stories, reports, users,
 * subscriptions, permissions, audit and task status. This service must not
 * perform web body extraction or embedding computation — those belong to the
 * Python AI service.
 */
@SpringBootApplication
public class CoreApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(CoreApiApplication.class, args);
    }
}
