FROM gradle:8.12-jdk21 AS build

WORKDIR /build

# Build context is the repository root, so every source path is repo-relative.
# Resolve dependencies before copying sources so source edits reuse this layer.
COPY apps/core-api/build.gradle.kts apps/core-api/settings.gradle.kts ./
RUN gradle --no-daemon dependencies --quiet || true

COPY apps/core-api/src ./src
# Flyway migrations live at the repository root so Java, CI and the docs share
# one canonical set.
COPY database/migrations ./src/main/resources/db/migration
RUN gradle --no-daemon bootJar --quiet

FROM eclipse-temurin:21-jre-jammy AS runtime

WORKDIR /app
COPY --from=build /build/build/libs/*.jar app.jar

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
    CMD ["sh", "-c", "wget -qO- http://localhost:8080/health/live > /dev/null || exit 1"]

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
