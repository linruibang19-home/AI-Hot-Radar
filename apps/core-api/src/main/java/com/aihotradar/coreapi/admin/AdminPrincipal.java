package com.aihotradar.coreapi.admin;

import java.util.UUID;

/**
 * An authenticated admin credential.
 *
 * <p>Deliberately carries no token, hashed or otherwise. Once authentication has happened the token
 * has no further use, and an object that holds it is an object that can leak it into a log line, a
 * stack trace or an error response.
 */
public record AdminPrincipal(UUID id, String label, AdminRole role) {

    public static final String ATTRIBUTE = "ahr.admin.principal";
}
