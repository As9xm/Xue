import re
import threading


class SecretDetector:
    PATTERNS = {
        "AWS Access Key": r'AKIA[0-9A-Z]{16}',
        "AWS Secret Key": r'(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*[:=]\s*["\']?[A-Za-z0-9/+=]{40}',
        "Private Key": r'-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----',
        "GitHub Token": r'gh[pousr]_[A-Za-z0-9_]{36,}',
        "Slack Token": r'xox[baprs]-[0-9a-zA-Z]{10,48}',
        "Google API Key": r'AIza[0-9A-Za-z\-_]{35}',
        "Stripe Key": r'(sk|pk)_(test|live)_[0-9a-zA-Z]{24,}',
        "Generic Password": r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?[^\s"\']{4,}',
        "JWT Token": r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
        "Bearer Token": r'(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*',
    }

    def __init__(self):
        self._compiled = {name: re.compile(pattern) for name, pattern in self.PATTERNS.items()}
        self.findings = []
        self._lock = threading.Lock()

    def scan(self, url, text):
        results = []
        for name, pattern in self._compiled.items():
            matches = pattern.findall(text)
            if matches:
                for match in matches[:5]:
                    masked = match[:4] + "***" + match[-2:] if len(match) > 6 else "***"
                    results.append({"type": name, "value": masked, "url": url})
        if results:
            with self._lock:
                self.findings.extend(results)
        return results
