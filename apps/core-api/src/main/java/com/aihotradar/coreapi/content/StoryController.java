package com.aihotradar.coreapi.content;

import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** HTTP adapter for reader-facing Story queries. */
@RestController
@RequestMapping("/api/v1/stories")
public class StoryController {

    private final StoryService stories;

    public StoryController(StoryService stories) {
        this.stories = stories;
    }

    @GetMapping
    public List<StoryService.StorySummary> list(
            @RequestParam(required = false, defaultValue = "30") int limit) {
        return stories.list(limit);
    }

    @GetMapping("/{slug}")
    public ResponseEntity<StoryService.StoryDetail> detail(@PathVariable String slug) {
        return stories.detail(slug).map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
