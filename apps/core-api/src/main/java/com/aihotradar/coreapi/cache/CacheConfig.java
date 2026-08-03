package com.aihotradar.coreapi.cache;

import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.jsontype.BasicPolymorphicTypeValidator;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.time.Duration;
import java.util.Map;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext;
import org.springframework.data.redis.serializer.StringRedisSerializer;

/**
 * Read caching for the public feed.
 *
 * <p>TTLs follow AHR-ARCH-200 §7. They are short by design: content updates
 * continuously, and a stale homepage is worse than a slightly slower one.
 *
 * <p>ADR-005 keeps Redis strictly a cache. Nothing here is a source of truth —
 * a flushed Redis must only cost latency, never data, which is why every cached
 * method reads through to PostgreSQL on a miss.
 */
@Configuration
@EnableCaching
public class CacheConfig {

    public static final String SELECTED = "selected";
    public static final String TOPICS = "topics";
    public static final String STATS = "stats";
    public static final String REPORTS = "reports";

    /**
     * The serializer used for every cached value.
     *
     * <p>Exposed separately so it can be round-tripped in a test without a
     * Redis connection: the defect this guards against lived entirely in this
     * configuration, and was invisible from the outside until the second
     * request for a cached endpoint.
     */
    public static GenericJackson2JsonRedisSerializer valueSerializer() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.registerModule(new JavaTimeModule());
        mapper.setVisibility(PropertyAccessor.ALL, JsonAutoDetect.Visibility.ANY);
        // Records are deserialised back into concrete types, so the serializer
        // needs type information. The validator restricts that to our own
        // package: unrestricted polymorphic typing is a deserialisation risk.
        //
        // EVERYTHING, not NON_FINAL: every DTO here is a Java record, and
        // records are implicitly final. Under NON_FINAL the writer silently
        // omitted their type header, so the value landed in Redis as a bare
        // `{"items":878,...}` and the reader — which expects the wrapper array —
        // threw. The effect was invisible on a cache miss and a 500 on the very
        // next request, so /stats, /selected, /topics, /categories and /reports
        // all failed on their second call within the TTL. The homepage rendered
        // zeros because its client falls back to an empty payload on error.
        mapper.activateDefaultTyping(
                BasicPolymorphicTypeValidator.builder()
                        .allowIfSubType("com.aihotradar.coreapi")
                        .allowIfSubType("java.util")
                        .allowIfSubType("java.time")
                        .build(),
                ObjectMapper.DefaultTyping.EVERYTHING);

        return new GenericJackson2JsonRedisSerializer(mapper);
    }

    @Bean
    public RedisCacheManager cacheManager(RedisConnectionFactory connectionFactory) {
        RedisCacheConfiguration base =
                RedisCacheConfiguration.defaultCacheConfig()
                        .serializeKeysWith(
                                RedisSerializationContext.SerializationPair.fromSerializer(
                                        new StringRedisSerializer()))
                        .serializeValuesWith(
                                RedisSerializationContext.SerializationPair.fromSerializer(
                                        valueSerializer()))
                        // Caching a null would hide content that has just been
                        // published until the entry expires.
                        .disableCachingNullValues();

        return RedisCacheManager.builder(connectionFactory)
                .cacheDefaults(base.entryTtl(Duration.ofMinutes(5)))
                .withInitialCacheConfigurations(
                        Map.of(
                                SELECTED, base.entryTtl(Duration.ofMinutes(5)),
                                TOPICS, base.entryTtl(Duration.ofMinutes(10)),
                                STATS, base.entryTtl(Duration.ofMinutes(2)),
                                REPORTS, base.entryTtl(Duration.ofMinutes(10))))
                .build();
    }
}
