use colored::*;
use dashmap::DashMap;
use serde::Serialize;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Mutex;
use std::time::Instant;
use std::collections::HashMap;
use url::Url;

/// Thread-safe aggregator using atomic counters and DashMap.
/// No heavy locks — designed for high-concurrency access.
pub struct Aggregator {
    start_time: Instant,

    // Domain tracking (lock-free concurrent map)
    pub domains: DashMap<String, usize>,

    // Status code distribution
    pub status_codes: DashMap<u16, usize>,

    // Content types
    pub content_types: DashMap<String, usize>,

    // Atomic counters (no locks needed)
    pub onion_count: AtomicUsize,
    pub clearnet_count: AtomicUsize,
    pub total_links_found: AtomicUsize,
    pub total_size_bytes: AtomicU64,
    pub total_errors: AtomicUsize,

    // Error tracking (bounded, needs a lock)
    pub errors: DashMap<String, usize>,
    pub error_urls: Mutex<Vec<(String, String)>>,

    // Largest pages
    pub largest_pages: Mutex<Vec<(String, u64)>>,
}

impl Aggregator {
    pub fn new() -> Self {
        Self {
            start_time: Instant::now(),
            domains: DashMap::new(),
            status_codes: DashMap::new(),
            content_types: DashMap::new(),
            onion_count: AtomicUsize::new(0),
            clearnet_count: AtomicUsize::new(0),
            total_links_found: AtomicUsize::new(0),
            total_size_bytes: AtomicU64::new(0),
            total_errors: AtomicUsize::new(0),
            errors: DashMap::new(),
            error_urls: Mutex::new(Vec::new()),
            largest_pages: Mutex::new(Vec::new()),
        }
    }

    pub fn record_page(
        &self,
        url: &str,
        status_code: u16,
        content_type: &str,
        links_found: usize,
        size_bytes: u64,
    ) {
        // Domain
        if let Ok(parsed) = Url::parse(url) {
            if let Some(host) = parsed.host_str() {
                *self.domains.entry(host.to_string()).or_insert(0) += 1;

                if host.contains(".onion") {
                    self.onion_count.fetch_add(1, Ordering::Relaxed);
                } else {
                    self.clearnet_count.fetch_add(1, Ordering::Relaxed);
                }
            }
        }

        // Status code
        *self.status_codes.entry(status_code).or_insert(0) += 1;

        // Content type
        let ct = content_type.split(';').next().unwrap_or("unknown").trim().to_string();
        *self.content_types.entry(ct).or_insert(0) += 1;

        // Counters
        self.total_links_found.fetch_add(links_found, Ordering::Relaxed);
        self.total_size_bytes.fetch_add(size_bytes, Ordering::Relaxed);

        // Largest pages
        if let Ok(mut pages) = self.largest_pages.lock() {
            pages.push((url.to_string(), size_bytes));
            if pages.len() > 20 {
                pages.sort_by(|a, b| b.1.cmp(&a.1));
                pages.truncate(10);
            }
        }
    }

    pub fn record_error(&self, url: &str, error: &str) {
        self.total_errors.fetch_add(1, Ordering::Relaxed);

        let error_type = error.split(':').next().unwrap_or("Unknown").to_string();
        *self.errors.entry(error_type).or_insert(0) += 1;

        if let Ok(mut urls) = self.error_urls.lock() {
            urls.push((url.to_string(), error.to_string()));
            if urls.len() > 200 {
                urls.drain(0..100);
            }
        }
    }

    pub fn total_pages(&self) -> usize {
        self.onion_count.load(Ordering::Relaxed) + self.clearnet_count.load(Ordering::Relaxed)
    }

    pub fn total_domains(&self) -> usize {
        self.domains.len()
    }

    pub fn elapsed_secs(&self) -> f64 {
        self.start_time.elapsed().as_secs_f64()
    }

    pub fn pages_per_sec(&self) -> f64 {
        let elapsed = self.elapsed_secs();
        if elapsed > 0.0 {
            self.total_pages() as f64 / elapsed
        } else {
            0.0
        }
    }

    pub fn format_elapsed(&self) -> String {
        let secs = self.start_time.elapsed().as_secs();
        let h = secs / 3600;
        let m = (secs % 3600) / 60;
        let s = secs % 60;
        if h > 0 {
            format!("{}:{:02}:{:02}", h, m, s)
        } else {
            format!("{}:{:02}", m, s)
        }
    }

    pub fn live_stats_line(&self) -> String {
        format!(
            "{} crawled / {} domains / {:.1}/s / {}",
            self.total_pages(),
            self.total_domains(),
            self.pages_per_sec(),
            self.format_elapsed(),
        )
    }

    pub fn generate_report(&self) -> Report {
        let total = self.total_pages();
        let elapsed = self.elapsed_secs();

        let mut top_domains: Vec<(String, usize)> = self
            .domains
            .iter()
            .map(|e| (e.key().clone(), *e.value()))
            .collect();
        top_domains.sort_by(|a, b| b.1.cmp(&a.1));
        top_domains.truncate(30);

        let mut status_dist: Vec<(u16, usize)> = self
            .status_codes
            .iter()
            .map(|e| (*e.key(), *e.value()))
            .collect();
        status_dist.sort_by_key(|e| e.0);

        let mut ct_dist: Vec<(String, usize)> = self
            .content_types
            .iter()
            .map(|e| (e.key().clone(), *e.value()))
            .collect();
        ct_dist.sort_by(|a, b| b.1.cmp(&a.1));
        ct_dist.truncate(10);

        let mut error_dist: Vec<(String, usize)> = self
            .errors
            .iter()
            .map(|e| (e.key().clone(), *e.value()))
            .collect();
        error_dist.sort_by(|a, b| b.1.cmp(&a.1));

        let largest = self
            .largest_pages
            .lock()
            .map(|p| {
                let mut sorted = p.clone();
                sorted.sort_by(|a, b| b.1.cmp(&a.1));
                sorted.truncate(10);
                sorted
            })
            .unwrap_or_default();

        Report {
            summary: ReportSummary {
                total_pages_crawled: total,
                total_unique_domains: self.total_domains(),
                total_errors: self.total_errors.load(Ordering::Relaxed),
                onion_pages: self.onion_count.load(Ordering::Relaxed),
                clearnet_pages: self.clearnet_count.load(Ordering::Relaxed),
                crawl_duration: self.format_elapsed(),
                pages_per_second: if elapsed > 0.0 { total as f64 / elapsed } else { 0.0 },
                total_data_downloaded_mb: self.total_size_bytes.load(Ordering::Relaxed) as f64 / (1024.0 * 1024.0),
                total_links_found: self.total_links_found.load(Ordering::Relaxed),
            },
            top_domains,
            status_code_distribution: status_dist.into_iter().collect(),
            content_type_distribution: ct_dist.into_iter().collect(),
            error_distribution: error_dist.into_iter().collect(),
            largest_pages: largest.into_iter().map(|(u, s)| LargestPage { url: u, size_bytes: s }).collect(),
        }
    }

    pub fn save_report(&self, path: &str) -> std::io::Result<()> {
        let report = self.generate_report();
        let json = serde_json::to_string_pretty(&report)?;
        std::fs::write(path, json)?;
        Ok(())
    }

    pub fn print_summary(&self) {
        let report = self.generate_report();
        let s = &report.summary;

        println!("\n{}", "=".repeat(60));
        println!("  {}", "AGGREGATION REPORT".cyan().bold());
        println!("{}", "=".repeat(60));

        println!("\n  {}", "Overview".bold());
        println!("  ├─ Pages crawled:    {}", format!("{}", s.total_pages_crawled).green());
        println!("  ├─ Unique domains:   {}", format!("{}", s.total_unique_domains).blue());
        println!("  ├─ Clearnet pages:   {}", s.clearnet_pages);
        println!("  ├─ Onion pages:      {}", format!("{}", s.onion_pages).magenta());
        println!("  ├─ Errors:           {}", format!("{}", s.total_errors).red());
        println!("  ├─ Data downloaded:  {:.1} MB", s.total_data_downloaded_mb);
        println!("  ├─ Links found:      {}", s.total_links_found);
        println!("  ├─ Duration:         {}", s.crawl_duration);
        println!("  └─ Speed:            {:.1} pages/sec", s.pages_per_second);

        // Status codes
        if !report.status_code_distribution.is_empty() {
            println!("\n  {}", "Status Codes".bold());
            for (code, count) in &report.status_code_distribution {
                let code_str = format!("{}", code);
                let colored = if *code >= 200 && *code < 300 {
                    code_str.green()
                } else if *code >= 300 && *code < 400 {
                    code_str.yellow()
                } else {
                    code_str.red()
                };
                println!("    {}: {}", colored, count);
            }
        }

        // Top domains
        if !report.top_domains.is_empty() {
            println!("\n  {}", "Top Domains (by pages)".bold());
            for (i, (domain, count)) in report.top_domains.iter().take(15).enumerate() {
                let marker = if domain.contains(".onion") {
                    "[TOR] ".magenta().to_string()
                } else {
                    String::new()
                };
                println!(
                    "    {:>3}. {}{} — {} pages",
                    (i + 1).to_string().dimmed(),
                    marker,
                    domain,
                    format!("{}", count).cyan()
                );
            }
        }

        // Content types
        if !report.content_type_distribution.is_empty() {
            println!("\n  {}", "Content Types".bold());
            for (ct, count) in &report.content_type_distribution {
                println!("    {} {}: {}", "•".dimmed(), ct, count);
            }
        }

        // Errors
        if !report.error_distribution.is_empty() {
            println!("\n  {}", "Error Types".bold());
            for (err, count) in &report.error_distribution {
                println!("    {} {}: {}", "•".red(), err, count);
            }
        }

        // Largest
        if !report.largest_pages.is_empty() {
            println!("\n  {}", "Largest Pages".bold());
            for p in report.largest_pages.iter().take(5) {
                let kb = p.size_bytes as f64 / 1024.0;
                let url_short = if p.url.len() > 80 { &p.url[..80] } else { &p.url };
                println!("    {} {:.1} KB — {}", "•".dimmed(), kb, url_short);
            }
        }

        println!("\n{}\n", "=".repeat(60));
    }
}

// ─── Serializable Report Structs ────────────────────────────────────────────────

#[derive(Serialize)]
pub struct Report {
    pub summary: ReportSummary,
    pub top_domains: Vec<(String, usize)>,
    pub status_code_distribution: Vec<(u16, usize)>,
    pub content_type_distribution: Vec<(String, usize)>,
    pub error_distribution: Vec<(String, usize)>,
    pub largest_pages: Vec<LargestPage>,
}

#[derive(Serialize)]
pub struct ReportSummary {
    pub total_pages_crawled: usize,
    pub total_unique_domains: usize,
    pub total_errors: usize,
    pub onion_pages: usize,
    pub clearnet_pages: usize,
    pub crawl_duration: String,
    pub pages_per_second: f64,
    pub total_data_downloaded_mb: f64,
    pub total_links_found: usize,
}

#[derive(Serialize)]
pub struct LargestPage {
    pub url: String,
    pub size_bytes: u64,
}
