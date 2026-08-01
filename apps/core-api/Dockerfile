FROM gradle:8.12-jdk21 AS build

WORKDIR /build

# Resolve dependencies before copying sources so source edits reuse this layer.
COPY build.gradle.kts settings.gradle.kts ./
RUN gradle --no-daemon dependencies --quiet || true

COPY src ./src
# Flyway migrations live at the repository root (database/migrations) and are
# copied in by the Compose build context so Java ships one canonical set.
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
