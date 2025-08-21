# config.py
import os
from typing import List

# Any number of domains; we’ll probe and pick the first that responds OK.
HIANIME_DOMAIN_POOL: List[str] = [
    "https://hianimez.is",
    "https://hianimez.to",
    "https://hianime.is",
    "https://hianime.bz",
    "https://hianimez.bz",
]

# Number of seconds to wait for HTTP requests
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
RETRIES      = int(os.getenv("HTTP_RETRIES", "2"))

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
