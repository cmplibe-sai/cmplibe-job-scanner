import time
import random
import logging
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from job_pulse.config import USER_AGENTS, DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES, DEFAULT_RETRY_BACKOFF

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False

logger = logging.getLogger("job_pulse.network")


class StealthClient:
    """
    Resilient HTTP client with TLS fingerprint impersonation,
    User-Agent rotation, request jitter, and retry backoff.
    """

    def __init__(
        self,
        impersonate: str = "chrome124",
        timeout: int = DEFAULT_TIMEOUT,
        proxy: Optional[str] = None
    ):
        self.impersonate = impersonate
        self.timeout = timeout
        self.proxy = proxy
        self.session = self._create_session()

    def _create_session(self):
        if HAS_CURL_CFFI:
            session = cffi_requests.Session(impersonate=self.impersonate)
        else:
            session = cffi_requests.Session()
        return session

    def _get_headers(self, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        if custom_headers:
            headers.update(custom_headers)
        return headers

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        delay_range: tuple = (0.5, 1.5)
    ):
        """Perform GET request with stealth headers, jitter and exponential retries."""
        # Jitter delay
        if delay_range and delay_range[1] > 0:
            time.sleep(random.uniform(delay_range[0], delay_range[1]))

        req_headers = self._get_headers(headers)
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None

        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=req_headers,
                    timeout=self.timeout,
                    proxies=proxies
                )
                if response.status_code in (200, 201, 206):
                    return response
                elif response.status_code in (403, 429):
                    wait_time = (DEFAULT_RETRY_BACKOFF ** attempt) + random.uniform(1.0, 3.0)
                    logger.warning(
                        f"Rate limit / Bot check [{response.status_code}] on {url}. Retrying in {wait_time:.1f}s (Attempt {attempt}/{max_retries})"
                    )
                    # Rotate session and headers
                    req_headers["User-Agent"] = random.choice(USER_AGENTS)
                    time.sleep(wait_time)
                else:
                    logger.warning(f"HTTP {response.status_code} for {url}")
                    return response
            except Exception as e:
                wait_time = (DEFAULT_RETRY_BACKOFF ** attempt) + random.uniform(0.5, 1.5)
                logger.warning(f"Request error on {url}: {e}. Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)

        logger.error(f"Failed to fetch {url} after {max_retries} attempts.")
        return None

    def post(
        self,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = DEFAULT_MAX_RETRIES
    ):
        """Perform POST request with stealth headers."""
        req_headers = self._get_headers(headers)
        if json_data is not None:
            req_headers["Content-Type"] = "application/json"

        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None

        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.post(
                    url,
                    params=params,
                    json=json_data,
                    data=data,
                    headers=req_headers,
                    timeout=self.timeout,
                    proxies=proxies
                )
                if response.status_code in (200, 201):
                    return response
                else:
                    logger.warning(f"HTTP {response.status_code} for POST {url}")
                    return response
            except Exception as e:
                time.sleep(DEFAULT_RETRY_BACKOFF ** attempt)
        return None

    def get_soup(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Optional[BeautifulSoup]:
        """Fetch and return parsed BeautifulSoup object."""
        resp = self.get(url, params=params, headers=headers)
        if resp and resp.text:
            return BeautifulSoup(resp.text, "lxml")
        return None
