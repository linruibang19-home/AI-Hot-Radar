FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /build

# Build context is the repository root, so every source path is repo-relative.
# Resolve dependencies before copying sources so source edits reuse this layer.
COPY apps/core-api/pom.xml ./
RUN mvn -B -q dependency:go-offline

COPY apps/core-api/src ./src
# Flyway migrations live at the repository root so Java, CI and the docs share
# one canonical set.
COPY database/migrations ./src/main/resources/db/migration
RUN mvn -B -q clean package -DskipTests

FROM eclipse-temurin:21-jre-jammy AS runtime

WORKDIR /app
COPY --from=build /build/target/*.jar app.jar

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
    CMD ["sh", "-c", "wget -qO- http://127.0.0.1:8080/health/live > /dev/null || exit 1"]

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
