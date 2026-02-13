use colored::*;
use sysinfo::System;

/// Detects system specs and recommends a safe thread count for the crawler.
pub struct SystemProfiler {
    pub cpu_physical: usize,
    pub cpu_logical: usize,
    pub cpu_usage: f32,
    pub total_ram_mb: u64,
    pub available_ram_mb: u64,
    pub os_name: String,
    pub os_version: String,
}

impl SystemProfiler {
    pub fn new() -> Self {
        let mut sys = System::new_all();
        sys.refresh_all();

        // Brief pause for accurate CPU usage
        std::thread::sleep(std::time::Duration::from_millis(300));
        sys.refresh_cpu_usage();

        let cpu_physical = sys.physical_core_count().unwrap_or(2);
        let cpu_logical = sys.cpus().len();
        let cpu_usage: f32 = sys.cpus().iter().map(|c| c.cpu_usage()).sum::<f32>() / cpu_logical as f32;
        let total_ram_mb = sys.total_memory() / (1024 * 1024);
        let available_ram_mb = sys.available_memory() / (1024 * 1024);
        let os_name = System::name().unwrap_or_else(|| "Unknown".into());
        let os_version = System::os_version().unwrap_or_else(|| "".into());

        Self {
            cpu_physical,
            cpu_logical,
            cpu_usage,
            total_ram_mb,
            available_ram_mb,
            os_name,
            os_version,
        }
    }

    /// Returns (recommended_threads, max_safe_threads)
    pub fn recommend_threads(&self) -> (usize, usize) {
        // Rust async tasks are much lighter than Python threads (~few KB each)
        // Base: 4x logical cores for I/O-bound async work
        let base = self.cpu_logical * 4;

        // RAM constraint: ~2 MB per task (much lighter than Python)
        // Use at most 60% of available RAM
        let ram_budget_mb = (self.available_ram_mb as f64 * 0.6) as usize;
        let ram_threads = (ram_budget_mb / 2).max(4);

        // CPU load scaling
        let cpu_factor = if self.cpu_usage > 80.0 {
            0.3
        } else if self.cpu_usage > 50.0 {
            0.6
        } else {
            1.0
        };

        let recommended = ((base.min(ram_threads) as f64) * cpu_factor) as usize;
        let recommended = recommended.clamp(4, 500);

        // Max safe ceiling
        let max_safe = ram_threads.min(self.cpu_logical * 16).min(1000).max(recommended);

        (recommended, max_safe)
    }

    pub fn print_report(&self) {
        let (rec, max_safe) = self.recommend_threads();

        println!("  {}", "System Profile".bold());
        println!("  ├─ OS:             {} {}", self.os_name, &self.os_version[..self.os_version.len().min(30)]);
        println!("  ├─ CPU cores:      {} physical / {} logical", self.cpu_physical, self.cpu_logical);

        let cpu_str = format!("{:.0}%", self.cpu_usage);
        let cpu_colored = if self.cpu_usage < 50.0 {
            cpu_str.green()
        } else if self.cpu_usage < 80.0 {
            cpu_str.yellow()
        } else {
            cpu_str.red()
        };
        println!("  ├─ CPU usage:      {}", cpu_colored);
        println!("  ├─ RAM total:      {} MB", self.total_ram_mb);

        let avail_str = format!("{} MB", self.available_ram_mb);
        let avail_colored = if self.available_ram_mb > 2048 {
            avail_str.green()
        } else if self.available_ram_mb > 512 {
            avail_str.yellow()
        } else {
            avail_str.red()
        };
        println!("  ├─ RAM available:  {}", avail_colored);

        let rec_str = format!("{} async tasks", rec);
        println!("  ├─ Recommended:    {}", rec_str.green().bold());
        let max_str = format!("{} async tasks", max_safe);
        println!("  └─ Max safe:       {}", max_str.yellow());
    }
}
