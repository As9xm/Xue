use crate::aggregator::Aggregator;
use colored::*;
use dashmap::DashSet;
use reqwest::Client;
use scraper::{Html, Selector};
use std::collections::VecDeque;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::AsyncWriteExt;
use tokio::sync::{Mutex, Notify, Semaphore};
use url::Url;

/// Skip these file extensions (binary/media/docs)
const SKIP_EXTENSIONS: &[&str] = &[
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mkv",
    ".zip", ".rar", ".tar", ".gz", ".7z", ".bz2",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".msi", ".dmg", ".deb", ".rpm", ".iso",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".css", ".map",
];

pub struct CrawlerConfig {
    pub seed_url: String,
    pub threads: usize,
    pub delay_ms: u64,
    pub timeout_secs: u64,
    pub tor_proxy: String,
    pub output_file: Option<String>,
    pub report_file: Option<String>,
    pub max_depth: u32,
    pub verbose: bool,
    pub domains_only: bool,
}

struct QueueItem {
    url: String,
    depth: u32,
}

pub struct CrawlerEngine {
    config: CrawlerConfig,
    shutdown: Arc<Notify>,
}

impl CrawlerEngine {
    pub fn new(config: CrawlerConfig, shutdown: Arc<Notify>) -> Self {
        Self { config, shutdown }
    }

    fn build_client(&self, use_proxy: bool) -> Result<Client, reqwest::Error> {
        let mut builder = Client::builder()
            .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            .timeout(Duration::from_secs(self.config.timeout_secs))
            .connect_timeout(Duration::from_secs(self.config.timeout_secs))
            .pool_max_idle_per_host(self.config.threads)
            .pool_idle_timeout(Duration::from_secs(30))
            .redirect(reqwest::redirect::Policy::limited(10))
            .danger_accept_invalid_certs(true)
            .gzip(true)
            .deflate(true);

        if use_proxy {
            let proxy = reqwest::Proxy::all(&self.config.tor_proxy)
                .expect("Invalid Tor proxy URL");
            builder = builder.proxy(proxy);
        }

        builder.build()
    }

    fn is_onion(url: &str) -> bool {
        if let Ok(parsed) = Url::parse(url) {
            parsed.host_str().map_or(false, |h| h.contains(".onion"))
        } else {
            false
        }
    }

    fn should_skip(url: &str) -> bool {
        if let Ok(parsed) = Url::parse(url) {
            match parsed.scheme() {
                "http" | "https" => {}
                _ => return true,
            }
            if parsed.host_str().is_none() {
                return true;
            }
            let path = parsed.path().to_lowercase();
            for ext in SKIP_EXTENSIONS {
                if path.ends_with(ext) {
                    return true;
                }
            }
            false
        } else {
            true
        }
    }

    fn normalize_url(url: &str) -> String {
        // Remove fragment
        let without_fragment = url.split('#').next().unwrap_or(url);
        let mut s = without_fragment.to_string();
        // Strip trailing slash if not root
        if s.ends_with('/') && s.matches('/').count() > 3 {
            s.pop();
        }
        s
    }

    fn extract_links(html: &str, base_url: &str) -> Vec<String> {
        let mut links = Vec::new();
        let document = Html::parse_document(html);
        let selector = Selector::parse("a[href]").unwrap();

        let base = match Url::parse(base_url) {
            Ok(u) => u,
            Err(_) => return links,
        };

        for element in document.select(&selector) {
            if let Some(href) = element.value().attr("href") {
                let href = href.trim();
                if href.is_empty()
                    || href.starts_with('#')
                    || href.starts_with("javascript:")
                    || href.starts_with("mailto:")
                    || href.starts_with("tel:")
                    || href.starts_with("data:")
                {
                    continue;
                }

                let full_url = match base.join(href) {
                    Ok(u) => u.to_string(),
                    Err(_) => continue,
                };

                let normalized = Self::normalize_url(&full_url);

                if !Self::should_skip(&normalized) {
                    links.push(normalized);
                }
            }
        }

        links
    }

    async fn test_tor(&self, client: &Client) {
        print!("  {} Testing Tor connection... ", "[*]".dimmed());
        match client.get("http://check.torproject.org/api/ip").send().await {
            Ok(resp) => {
                if let Ok(data) = resp.json::<serde_json::Value>().await {
                    if data.get("IsTor").and_then(|v| v.as_bool()) == Some(true) {
                        let ip = data.get("IP").and_then(|v| v.as_str()).unwrap_or("unknown");
                        println!("{} (IP: {})", "OK".green(), ip);
                    } else {
                        println!("{} — connected but Tor not detected", "WARNING".yellow());
                    }
                }
            }
            Err(e) => {
                println!("{}", "FAILED".red());
                println!("  {} Could not connect to Tor: {}", "[!]".red(), e);
                println!("  {}    Make sure Tor is running on {}", "".dimmed(), self.config.tor_proxy);
            }
        }
    }

    pub async fn run(self) {
        let is_seed_onion = Self::is_onion(&self.config.seed_url);

        // Build HTTP clients
        let clearnet_client = self.build_client(false).expect("Failed to build HTTP client");
        let tor_client = self.build_client(true).expect("Failed to build Tor HTTP client");

        // Tor check
        if is_seed_onion {
            println!("  {} Tor mode — routing through {}", "[*]".magenta(), self.config.tor_proxy);
            self.test_tor(&tor_client).await;
        } else {
            println!("  {} Clearnet mode (Tor available for .onion links)", "[*]".blue());
        }

        // Config summary
        println!("\n  {} Seed:    {}", "[*]".dimmed(), self.config.seed_url);
        println!("  {} Tasks:   {}", "[*]".dimmed(), format!("{}", self.config.threads).bold());
        println!("  {} Delay:   {}ms", "[*]".dimmed(), self.config.delay_ms);
        println!("  {} Timeout: {}s", "[*]".dimmed(), self.config.timeout_secs);
        if self.config.domains_only {
            println!("  {} Mode:    {}", "[*]".cyan(), "DOMAINS ONLY".bold());
        }
        if self.config.max_depth > 0 {
            println!("  {} Max depth: {}", "[*]".dimmed(), self.config.max_depth);
        }
        if let Some(ref f) = self.config.output_file {
            println!("  {} Output:  {}", "[*]".dimmed(), f);
        }
        if let Some(ref f) = self.config.report_file {
            println!("  {} Report:  {}", "[*]".dimmed(), f);
        }
        println!("\n  {}\n", "Press CTRL+C to stop and view aggregation report".yellow());

        // Shared state
        let aggregator = Arc::new(Aggregator::new());
        let visited: Arc<DashSet<String>> = Arc::new(DashSet::new());
        let discovered_domains: Arc<DashSet<String>> = Arc::new(DashSet::new());
        let queue: Arc<Mutex<VecDeque<QueueItem>>> = Arc::new(Mutex::new(VecDeque::new()));
        let total_discovered = Arc::new(std::sync::atomic::AtomicUsize::new(0));

        // Semaphore to limit concurrency
        let semaphore = Arc::new(Semaphore::new(self.config.threads));

        // Output file
        let output_file: Arc<Option<Mutex<tokio::fs::File>>> = if let Some(ref path) = self.config.output_file {
            let f = tokio::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)
                .await
                .expect("Failed to open output file");
            Arc::new(Some(Mutex::new(f)))
        } else {
            Arc::new(None)
        };

        // Seed the queue
        let seed_normalized = Self::normalize_url(&self.config.seed_url);
        visited.insert(seed_normalized.clone());
        total_discovered.fetch_add(1, std::sync::atomic::Ordering::Relaxed);

        if let Ok(parsed) = Url::parse(&seed_normalized) {
            if let Some(host) = parsed.host_str() {
                discovered_domains.insert(host.to_string());
            }
        }

        {
            let mut q = queue.lock().await;
            q.push_back(QueueItem { url: seed_normalized, depth: 0 });
        }

        let clearnet_client = Arc::new(clearnet_client);
        let tor_client = Arc::new(tor_client);
        let shutdown = self.shutdown.clone();
        let config = Arc::new(self.config);

        // Spawn the task dispatcher
        let agg = aggregator.clone();
        let vis = visited.clone();
        let dd = discovered_domains.clone();
        let q = queue.clone();
        let td = total_discovered.clone();
        let sem = semaphore.clone();
        let sd = shutdown.clone();
        let cc = clearnet_client.clone();
        let tc = tor_client.clone();
        let of = output_file.clone();
        let cfg = config.clone();

        let dispatcher = tokio::spawn(async move {
            loop {
                // Check shutdown
                if sd.notified().now_or_never().is_some() {
                    break;
                }

                // Try to get an item from the queue
                let item = {
                    let mut q_lock = q.lock().await;
                    q_lock.pop_front()
                };

                let item = match item {
                    Some(item) => item,
                    None => {
                        // Queue empty, wait a bit
                        tokio::time::sleep(Duration::from_millis(100)).await;
                        continue;
                    }
                };

                // Acquire semaphore permit (limits concurrency)
                let permit = sem.clone().acquire_owned().await.unwrap();

                let agg = agg.clone();
                let vis = vis.clone();
                let dd = dd.clone();
                let q = q.clone();
                let td = td.clone();
                let cc = cc.clone();
                let tc = tc.clone();
                let of = of.clone();
                let cfg = cfg.clone();

                tokio::spawn(async move {
                    let _permit = permit; // held until task completes

                    let url = item.url;
                    let depth = item.depth;
                    let is_onion = Self::is_onion(&url);
                    let client = if is_onion { &*tc } else { &*cc };

                    // Fetch
                    match client.get(&url).send().await {
                        Ok(resp) => {
                            let status = resp.status().as_u16();
                            let content_type = resp
                                .headers()
                                .get("content-type")
                                .and_then(|v| v.to_str().ok())
                                .unwrap_or("")
                                .to_string();

                            let mut links = Vec::new();
                            let size_bytes;

                            if content_type.contains("text/html") {
                                // Read body with 10 MB limit
                                let body = match resp.bytes().await {
                                    Ok(b) => b,
                                    Err(_) => {
                                        agg.record_error(&url, "BodyReadError");
                                        return;
                                    }
                                };
                                size_bytes = body.len().min(10 * 1024 * 1024) as u64;
                                let text = String::from_utf8_lossy(
                                    &body[..body.len().min(10 * 1024 * 1024)]
                                );
                                links = Self::extract_links(&text, &url);
                            } else {
                                size_bytes = resp
                                    .content_length()
                                    .unwrap_or(0);
                                // Don't download non-HTML bodies
                            }

                            agg.record_page(&url, status, &content_type, links.len(), size_bytes);

                            // Print
                            let tag = if is_onion {
                                "[TOR]".magenta().to_string()
                            } else {
                                "[WEB]".blue().to_string()
                            };
                            let sc = if status >= 200 && status < 300 {
                                format!("{}", status).green().to_string()
                            } else if status >= 300 && status < 400 {
                                format!("{}", status).yellow().to_string()
                            } else {
                                format!("{}", status).red().to_string()
                            };
                            let url_display = if url.len() > 100 { &url[..97] } else { &url };
                            let dots = if url.len() > 100 { "..." } else { "" };

                            println!(
                                "  {} {} {} {} {}{} {}",
                                tag,
                                sc,
                                format!("d={}", depth).dimmed(),
                                format!("[{} links]", links.len()).dimmed(),
                                url_display,
                                dots,
                                format!("| {}", agg.live_stats_line()).truecolor(100, 100, 100),
                            );

                            // Write to output file
                            if let Some(ref of_mutex) = *of {
                                let mut f = of_mutex.lock().await;
                                let _ = f.write_all(format!("{}\n", url).as_bytes()).await;
                            }

                            // Enqueue new links
                            if cfg.max_depth > 0 && depth + 1 > cfg.max_depth {
                                return;
                            }

                            if cfg.domains_only {
                                for link in &links {
                                    if let Ok(parsed) = Url::parse(link) {
                                        if let Some(host) = parsed.host_str() {
                                            if !dd.contains(host) {
                                                dd.insert(host.to_string());
                                                let root = format!("{}://{}", parsed.scheme(), host);
                                                if !vis.contains(&root) {
                                                    vis.insert(root.clone());
                                                    let mut q_lock = q.lock().await;
                                                    q_lock.push_back(QueueItem {
                                                        url: root,
                                                        depth: depth + 1,
                                                    });
                                                    td.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                                                }
                                            }
                                        }
                                    }
                                }
                            } else {
                                let mut new_items = Vec::new();
                                for link in links {
                                    if !vis.contains(&link) {
                                        vis.insert(link.clone());
                                        new_items.push(QueueItem {
                                            url: link,
                                            depth: depth + 1,
                                        });
                                    }
                                }
                                if !new_items.is_empty() {
                                    td.fetch_add(new_items.len(), std::sync::atomic::Ordering::Relaxed);
                                    let mut q_lock = q.lock().await;
                                    for item in new_items {
                                        q_lock.push_back(item);
                                    }
                                }
                            }

                            // Delay
                            if cfg.delay_ms > 0 {
                                tokio::time::sleep(Duration::from_millis(cfg.delay_ms)).await;
                            }
                        }
                        Err(e) => {
                            if cfg.verbose {
                                let url_short = if url.len() > 80 { &url[..80] } else { &url };
                                println!("  {} {}: {}", "[ERR]".red(), e.to_string().split(':').next().unwrap_or("Error"), url_short);
                            }
                            agg.record_error(&url, &e.to_string());
                        }
                    }
                });
            }
        });

        // Wait for shutdown signal
        shutdown.notified().await;

        // Give workers a moment to finish current tasks
        tokio::time::sleep(Duration::from_secs(2)).await;
        dispatcher.abort();

        // Print report
        aggregator.print_summary();

        // Save JSON report
        if let Some(ref path) = config.report_file {
            match aggregator.save_report(path) {
                Ok(_) => println!("  {} Aggregation report saved to {}", "[+]".green(), path),
                Err(e) => println!("  {} Failed to save report: {}", "[!]".red(), e),
            }
        }

        // Flush output file
        if let Some(ref of_mutex) = *output_file {
            let mut f = of_mutex.lock().await;
            let _ = f.flush().await;
            if let Some(ref path) = config.output_file {
                println!("  {} URL list saved to {}", "[+]".green(), path);
            }
        }

        println!(
            "  {} Done. Total discovered: {}",
            "[*]".cyan(),
            total_discovered.load(std::sync::atomic::Ordering::Relaxed)
        );
    }
}
