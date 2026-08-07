package com.aihotradar.coreapi.admin;

import java.util.Optional;

/**
 * The two things a credential may be allowed to do.
 *
 * <p>AHR-QSO-700 §3 requires least-privilege RBAC on the admin surface. Two roles rather than one
 * because least privilege is only a real property if reading does not imply writing: a single
 * {@code ADMIN} role would satisfy the word and none of the meaning.
 *
 * <p>The split is read versus mutate rather than by resource. Resource-scoped roles would be
 * speculative — there is one operator and the resources they touch (sources, jobs, stories) are all
 * operational rather than separable by trust.
 */
public enum AdminRole {

    /** May read the admin views, including the audit log. May not change anything. */
    VIEWER,

    /** May read, and may perform operational mutations. */
    OPERATOR;

    public boolean canMutate() {
        return this == OPERATOR;
    }

    /**
     * Parses a stored role, treating anything unrecognised as absent rather than as a default.
     *
     * <p>A row whose role has been edited to something the code does not know about must fail
     * closed. Defaulting to {@code VIEWER} would be the safer-looking choice and still wrong: it
     * would silently grant read access on a value nobody intended.
     */
    public static Optional<AdminRole> parse(String raw) {
        if (raw == null) {
            return Optional.empty();
        }
        for (AdminRole role : values()) {
            if (role.name().equals(raw)) {
                return Optional.of(role);
            }
        }
        return Optional.empty();
    }
}
