use clap::Parser;

/// Xue — High-performance continuous internet crawler with Tor support
#[derive(Parser, Debug)]
#[command(name = "xue", version, about, long_about = None)]
#[command(after_help = r#"EXAMPLES:
  xue -u https://example.com
  xue -u https://example.com --auto -d 0.2 -o urls.txt -r report.json
  xue -u https://example.com -t 50 -d 0.3
  xue -u http://something.onion -v --tor-proxy socks5h://127.0.0.1:9050
  xue -u https://example.com --domains-only --auto
"#)]
pub struct Args {
    /// Seed URL to start crawling
    #[arg(short, long)]
    pub url: String,

    /// Number of concurrent tasks
    #[arg(short, long, default_value_t = 20)]
    pub threads: usize,

    /// Auto-detect optimal thread count based on system specs
    #[arg(long)]
    pub auto_threads: bool,

    /// Delay between requests per task in seconds
    #[arg(short, long, default_value_t = 0.3)]
    pub delay: f64,

    /// File to append discovered URLs to
    #[arg(short, long)]
    pub output: Option<String>,

    /// Save aggregation report as JSON file
    #[arg(short, long)]
    pub report: Option<String>,

    /// Tor SOCKS5 proxy address
    #[arg(long, default_value = "socks5h://127.0.0.1:9050")]
    pub tor_proxy: String,

    /// Request timeout in seconds
    #[arg(long, default_value_t = 10)]
    pub timeout: u64,

    /// Max crawl depth (0 = unlimited)
    #[arg(long, default_value_t = 0)]
    pub max_depth: u32,

    /// Only crawl domains and subdomains, skip endpoints
    #[arg(long)]
    pub domains_only: bool,

    /// Verbose error output
    #[arg(short, long)]
    pub verbose: bool,
}
