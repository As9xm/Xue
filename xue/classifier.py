import re


class DomainClassifier:
    CATEGORIES = {
        "Pornography / Adult": {
            "domains": ["porn", "xxx", "sex", "adult", "nsfw", "hentai", "xvideo",
                        "xhamster", "redtube", "youporn", "brazzers", "onlyfans",
                        "chaturbate", "livejasmin", "cam4", "stripchat", "xnxx",
                        "spankbang", "eporner", "tube8", "pornhub", "fapello",
                        "rule34", "e621", "nhentai", "hanime", "livehdcams"],
            "titles": ["porn", "xxx", "adult", "nsfw", "hentai"],
        },
        "Social Media": {
            "domains": ["facebook", "twitter", "instagram", "tiktok", "snapchat",
                        "linkedin", "reddit", "tumblr", "pinterest", "mastodon",
                        "threads.net", "bsky", "bluesky", "discord", "telegram",
                        "whatsapp", "wechat", "weibo", "vk.com", "ok.ru"],
            "titles": ["social", "feed", "timeline", "connect with"],
        },
        "Gaming": {
            "domains": ["steam", "epicgames", "gog.com", "itch.io", "roblox",
                        "minecraft", "twitch", "xbox", "playstation", "nintendo",
                        "ea.com", "ubisoft", "riot", "blizzard", "activision",
                        "igdb", "rawg", "gamespot", "ign.com", "kotaku",
                        "pcgamer", "gamefaqs", "nexusmods", "moddb", "curseforge"],
            "titles": ["gaming", "video game", "esport", "gameplay", "gamer"],
        },
        "Game Store / Marketplace": {
            "domains": ["store.steampowered", "store.epicgames", "store.playstation",
                        "marketplace.xbox", "humblebundle", "greenmangaming",
                        "kinguin", "g2a.com", "cdkeys", "fanatical"],
            "titles": ["game store", "buy game", "game deal"],
        },
        "Technology": {
            "domains": ["github", "gitlab", "stackoverflow", "hackernews",
                        "techcrunch", "theverge", "arstechnica", "wired.com",
                        "engadget", "tomshardware", "anandtech", "slashdot",
                        "dev.to", "medium.com", "hashnode", "replit", "codepen",
                        "npmjs", "pypi", "crates.io", "docker", "kubernetes",
                        "aws.amazon", "azure.microsoft", "cloud.google",
                        "digitalocean", "heroku", "vercel", "netlify", "render"],
            "titles": ["developer", "programming", "software", "open source",
                       "code", "api", "framework", "devops"],
        },
        "News / Media": {
            "domains": ["cnn.com", "bbc.com", "bbc.co.uk", "nytimes", "reuters",
                        "apnews", "theguardian", "washingtonpost", "foxnews",
                        "nbcnews", "abcnews", "aljazeera", "bloomberg",
                        "cnbc.com", "forbes.com", "businessinsider", "vice.com",
                        "huffpost", "buzzfeed", "dailymail", "news.yahoo"],
            "titles": ["news", "breaking", "headline", "journalist"],
        },
        "Forums / Community": {
            "domains": ["forum", "community", "discuss", "discourse", "phpbb",
                        "vbulletin", "xenforo", "stackexchange", "quora",
                        "answers.yahoo", "4chan", "8chan", "kiwifarms",
                        "somethingawful", "resetera", "neogaf", "voat"],
            "titles": ["forum", "community", "discussion", "board", "thread"],
        },
        "Shopping / E-Commerce": {
            "domains": ["amazon", "ebay", "aliexpress", "alibaba", "walmart",
                        "etsy", "shopify", "target", "bestbuy", "newegg",
                        "wish.com", "temu", "shein", "asos", "zalando",
                        "rakuten", "mercadolibre", "flipkart", "lazada"],
            "titles": ["shop", "buy", "store", "cart", "checkout", "deals"],
        },
        "Streaming / Entertainment": {
            "domains": ["youtube", "youtu.be", "netflix", "hulu", "disneyplus",
                        "hbomax", "primevideo", "peacock", "crunchyroll",
                        "funimation", "spotify", "soundcloud", "deezer",
                        "tidal", "bandcamp", "vimeo", "dailymotion",
                        "twitch", "kick.com", "rumble", "bitchute"],
            "titles": ["stream", "watch", "listen", "movie", "music", "video"],
        },
        "Education": {
            "domains": [".edu", "coursera", "udemy", "edx.org", "khanacademy",
                        "skillshare", "academia.edu", "researchgate",
                        "scholar.google", "jstor", "arxiv", "wikipedia",
                        "wikimedia", "britannica", "w3schools", "freecodecamp"],
            "titles": ["learn", "course", "education", "university", "tutorial",
                       "academy", "school"],
        },
        "Government": {
            "domains": [".gov", ".mil", "government", "whitehouse",
                        "congress.gov", "senate.gov", "europa.eu"],
            "titles": ["government", "federal", "official"],
        },
        "Finance / Crypto": {
            "domains": ["paypal", "stripe", "coinbase", "binance", "kraken",
                        "blockchain", "crypto", "bitcoin", "ethereum",
                        "robinhood", "etrade", "fidelity", "schwab",
                        "bankofamerica", "chase", "wellsfargo", "revolut",
                        "wise.com", "venmo"],
            "titles": ["bank", "finance", "crypto", "trading", "invest",
                       "wallet", "exchange"],
        },
        "AI / Machine Learning": {
            "domains": ["openai", "anthropic", "huggingface", "midjourney",
                        "stability.ai", "replicate", "ollama", "perplexity",
                        "chatgpt", "claude", "gemini", "copilot",
                        "theresanaiforthat", "aitools"],
            "titles": [" ai ", "artificial intelligence", "machine learning",
                       "neural", "llm", "chatbot", "generative"],
        },
        "Search Engine": {
            "domains": ["google.com", "bing.com", "duckduckgo", "yahoo.com",
                        "yandex", "baidu", "brave.com/search", "startpage",
                        "searx", "ecosia"],
            "titles": ["search engine"],
        },
        "Advertising / Tracking": {
            "domains": ["doubleclick", "googlesyndication", "googleadservices",
                        "adnxs", "criteo", "taboola", "outbrain", "trafficjunky",
                        "adtng", "exoclick", "juicyads", "clickadilla",
                        "analytics", "hotjar", "mouseflow", "newrelic"],
            "titles": ["advertising", "ad network", "analytics"],
        },
    }

    def __init__(self):
        self._compiled = {}
        for category, rules in self.CATEGORIES.items():
            self._compiled[category] = {
                "domains": [kw.lower() for kw in rules["domains"]],
                "titles": [re.compile(re.escape(kw), re.IGNORECASE) for kw in rules["titles"]],
            }

    def classify(self, domain, title=""):
        domain_lower = domain.lower()
        for category, rules in self._compiled.items():
            for kw in rules["domains"]:
                if kw in domain_lower:
                    return category
        title_lower = (title or "").lower()
        if title_lower:
            for category, rules in self._compiled.items():
                for pattern in rules["titles"]:
                    if pattern.search(title_lower):
                        return category
        return "Uncategorized"
