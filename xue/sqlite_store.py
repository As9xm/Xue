import sqlite3


class SqliteStore:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS visited (
                url TEXT PRIMARY KEY,
                depth INTEGER NOT NULL,
                crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                url TEXT PRIMARY KEY,
                depth INTEGER NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS domains (
                domain TEXT PRIMARY KEY,
                discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                source TEXT,
                target TEXT,
                PRIMARY KEY (source, target)
            )
        """)
        self.conn.commit()

    def is_visited(self, url):
        cur = self.conn.execute("SELECT 1 FROM visited WHERE url = ?", (url,))
        return cur.fetchone() is not None

    def mark_visited(self, url, depth):
        self.conn.execute("INSERT OR IGNORE INTO visited (url, depth) VALUES (?, ?)", (url, depth))
        self.conn.commit()

    def queue_url(self, url, depth):
        self.conn.execute("INSERT OR IGNORE INTO queue (url, depth) VALUES (?, ?)", (url, depth))
        self.conn.commit()

    def dequeue(self):
        cur = self.conn.execute("SELECT url, depth FROM queue LIMIT 1")
        row = cur.fetchone()
        if row:
            self.conn.execute("DELETE FROM queue WHERE url = ?", (row[0],))
            self.conn.commit()
            return (row[0], row[1])
        return None

    def add_domain(self, domain):
        self.conn.execute("INSERT OR IGNORE INTO domains (domain) VALUES (?)", (domain,))
        self.conn.commit()

    def is_domain_known(self, domain):
        cur = self.conn.execute("SELECT 1 FROM domains WHERE domain = ?", (domain,))
        return cur.fetchone() is not None

    def add_graph_edge(self, source, target):
        self.conn.execute("INSERT OR IGNORE INTO graph_edges (source, target) VALUES (?, ?)", (source, target))
        self.conn.commit()

    def load_all_visited(self):
        cur = self.conn.execute("SELECT url FROM visited")
        return [row[0] for row in cur.fetchall()]

    def load_queue(self):
        cur = self.conn.execute("SELECT url, depth FROM queue ORDER BY rowid")
        return [(row[0], row[1]) for row in cur.fetchall()]

    def load_domains(self):
        cur = self.conn.execute("SELECT domain FROM domains")
        return [row[0] for row in cur.fetchall()]

    def close(self):
        self.conn.close()
