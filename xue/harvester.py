import re
import threading


class DataHarvester:
    EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    PHONE_RE = re.compile(r'\+?[0-9]{1,4}?[-.\s]?\(?[0-9]{1,3}?\)?[-.\s]?[0-9]{1,4}[-.\s]?[0-9]{1,4}[-.\s]?[0-9]{1,9}')
    SOCIAL_PATTERNS = {
        "Twitter": re.compile(r'twitter\.com/([A-Za-z0-9_]{1,15})'),
        "GitHub": re.compile(r'github\.com/([A-Za-z0-9_-]{1,39})'),
        "LinkedIn": re.compile(r'linkedin\.com/in/([A-Za-z0-9_-]+)'),
        "Facebook": re.compile(r'facebook\.com/([A-Za-z0-9.]+)'),
        "Instagram": re.compile(r'instagram\.com/([A-Za-z0-9_.]+)'),
        "YouTube": re.compile(r'youtube\.com/@?([A-Za-z0-9_.-]+)'),
        "Telegram": re.compile(r't\.me/([A-Za-z0-9_]{5,32})'),
    }

    def __init__(self):
        self.emails = set()
        self.phones = set()
        self.social = {}
        self._lock = threading.Lock()

    def harvest(self, text):
        emails = set(self.EMAIL_RE.findall(text))
        phones = set(self.PHONE_RE.findall(text))
        social = {}
        for platform, pattern in self.SOCIAL_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                social[platform] = list(set(matches))
        with self._lock:
            self.emails.update(emails)
            self.phones.update(phones)
            for platform, handles in social.items():
                if platform not in self.social:
                    self.social[platform] = set()
                self.social[platform].update(handles)
        return {"emails": emails, "phones": phones, "social": social}

    def get_report(self):
        with self._lock:
            return {
                "emails": sorted(self.emails),
                "phones": sorted(self.phones),
                "social": {k: sorted(v) for k, v in self.social.items()},
                "total_emails": len(self.emails),
                "total_phones": len(self.phones),
                "total_social": sum(len(v) for v in self.social.values()),
            }
