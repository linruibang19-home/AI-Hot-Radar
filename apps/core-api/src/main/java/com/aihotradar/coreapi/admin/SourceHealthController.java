package com.aihotradar.coreapi.admin;

import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Authenticated HTTP adapter for the source health projection. */
@RestController
@RequestMapping("/api/v1/admin")
public class SourceHealthController {

    private final SourceRepository sources;

    public SourceHealthController(SourceRepository sources) {
        this.sources = sources;
    }

    @GetMapping("/sources")
    public List<SourceRepository.SourceHealth> sources() {
        return sources.findEnabledHealth();
    }

    @GetMapping("/sources/summary")
    public SourceRepository.SourceSummary summary() {
        return sources.findSummary();
    }
}
