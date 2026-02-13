mod crawler;
mod aggregator;
mod profiler;
mod cli;

use cli::Args;
use clap::Parser;
use colored::*;
use std::sync::Arc;
use tokio::sync::Notify;

const BANNER: &str = r#"
  ██╗  ██╗██╗   ██╗███████╗
  ╚██╗██╔╝██║   ██║██╔════╝
   ╚███╔╝ ██║   ██║█████╗  
   ██╔██╗ ██║   ██║██╔══╝  
  ██╔╝ ██╗╚██████╔╝███████╗
  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
"#;

#[tokio::main]
async fn main() {
    let args = Args::parse();

    // Banner
    println!("{}", BANNER.cyan().bold());
    println!("  {}", "Continuous Internet Crawler · Tor Enabled · Rust".dimmed());
    println!();

    // Validate URL
    if let Err(e) = url::Url::parse(&args.url) {
        eprintln!("  {} Invalid URL: {}", "[!]".red(), e);
        std::process::exit(1);
    }

    // System profiler
    let profiler = profiler::SystemProfiler::new();
    profiler.print_report();

    let (recommended, max_safe) = profiler.recommend_threads();

    // Determine thread count
    let threads = if args.auto_threads {
        println!(
            "\n  {} Auto-threads: using {}",
            "[*]".green(),
            format!("{} threads", recommended).bold()
        );
        recommended
    } else if args.threads > max_safe {
        println!(
            "\n  {} {} threads exceeds safe limit ({}). Using recommended: {}",
            "[!]".yellow().bold(),
            args.threads,
            max_safe,
            recommended
        );
        recommended
    } else {
        args.threads
    };

    // Setup shutdown signal
    let shutdown = Arc::new(Notify::new());
    let shutdown_clone = shutdown.clone();
    ctrlc::set_handler(move || {
        println!("\n\n  {} CTRL+C received — stopping crawler...\n", "[!]".yellow());
        shutdown_clone.notify_waiters();
    })
    .expect("Error setting Ctrl-C handler");

    // Build and run crawler
    let mut crawler_config = crawler::CrawlerConfig {
        seed_url: args.url,
        threads,
        delay_ms: (args.delay * 1000.0) as u64,
        timeout_secs: args.timeout,
        tor_proxy: args.tor_proxy,
        output_file: args.output,
        report_file: args.report,
        max_depth: args.max_depth,
        verbose: args.verbose,
        domains_only: args.domains_only,
    };

    let engine = crawler::CrawlerEngine::new(crawler_config, shutdown);
    engine.run().await;
}
