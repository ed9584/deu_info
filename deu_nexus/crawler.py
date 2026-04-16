from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium import webdriver
from dataclasses import dataclass

DEFAULT_BASE = "https://dess.deu.ac.kr/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

@dataclass
class ArticleRow:
    list_no: str
    title: str
    url: str
    document_srl: str | None
    author: str
    posted: str
    views: str
    is_notice: bool

def build_driver(*, headless: bool = True) -> WebDriver:
    """Chrome 드라이버를 설정하고 반환."""
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(f"user-agent={DEFAULT_USER_AGENT}")
    
    try:
        driver = webdriver.Chrome(options=opts)
        return driver
    except Exception as e:
        raise RuntimeError(f"Failed to initialize WebDriver: {e}")