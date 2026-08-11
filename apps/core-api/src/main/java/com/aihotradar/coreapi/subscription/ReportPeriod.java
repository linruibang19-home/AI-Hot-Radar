package com.aihotradar.coreapi.subscription;

import java.util.Locale;

public enum ReportPeriod {
    DAILY("daily"),
    WEEKLY("weekly"),
    MONTHLY("monthly");

    private final String value;

    ReportPeriod(String value) {
        this.value = value;
    }

    public String value() {
        return value;
    }

    public static ReportPeriod parse(String raw) {
        String value = raw == null ? "" : raw.trim().toLowerCase(Locale.ROOT);
        return switch (value) {
            case "daily" -> DAILY;
            case "weekly" -> WEEKLY;
            case "monthly" -> MONTHLY;
            default -> throw new IllegalArgumentException("unsupported report period");
        };
    }
}
