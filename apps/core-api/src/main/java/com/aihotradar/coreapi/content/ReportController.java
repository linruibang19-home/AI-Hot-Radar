package com.aihotradar.coreapi.content;

import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** HTTP adapter for daily, weekly and monthly report reads. */
@RestController
@RequestMapping("/api/v1/reports")
public class ReportController {

    private final ReportService reports;

    public ReportController(ReportService reports) {
        this.reports = reports;
    }

    @GetMapping
    public List<ReportService.ReportSummary> list(
            @RequestParam(required = false, defaultValue = "daily") String period,
            @RequestParam(required = false, defaultValue = "30") int limit) {
        return reports.list(period, limit);
    }

    @GetMapping("/{period}/{key}")
    public ResponseEntity<ReportService.ReportDetail> detail(
            @PathVariable String period, @PathVariable String key) {
        return reports.detail(period, key).map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
