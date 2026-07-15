import hashlib
import re
import threading


class SimHash:
    @staticmethod
    def compute(text, bits=64):
        if not text:
            return 0
        words = re.findall(r'\w+', text.lower())
        if not words:
            return 0
        v = [0] * bits
        for word in words:
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            for i in range(bits):
                if h & (1 << i):
                    v[i] += 1
                else:
                    v[i] -= 1
        fingerprint = 0
        for i in range(bits):
            if v[i] > 0:
                fingerprint |= (1 << i)
        return fingerprint

    @staticmethod
    def hamming_distance(a, b):
        return bin(a ^ b).count('1')

    @staticmethod
    def is_similar(a, b, threshold=3):
        return SimHash.hamming_distance(a, b) <= threshold


class FingerprintDedup:
    def __init__(self):
        self.fingerprints = {}
        self._lock = threading.Lock()
        self.duplicate_count = 0

    def is_duplicate(self, url, text):
        fp = SimHash.compute(text)
        with self._lock:
            for existing_url, existing_fp in self.fingerprints.items():
                if SimHash.is_similar(fp, existing_fp):
                    self.duplicate_count += 1
                    return True
            self.fingerprints[url] = fp
            return False
