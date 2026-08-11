package com.aihotradar.coreapi.subscription;

public final class InvalidSubscriptionTokenException extends RuntimeException {
    public InvalidSubscriptionTokenException() {
        super("subscription token is invalid or expired");
    }
}
