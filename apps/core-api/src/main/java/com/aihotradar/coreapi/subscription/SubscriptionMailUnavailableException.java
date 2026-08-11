package com.aihotradar.coreapi.subscription;

public final class SubscriptionMailUnavailableException extends RuntimeException {
    public SubscriptionMailUnavailableException(Throwable cause) {
        super("subscription email could not be sent", cause);
    }

    public SubscriptionMailUnavailableException() {
        super("subscription email is not configured");
    }
}
