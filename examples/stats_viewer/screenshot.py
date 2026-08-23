"""Render the optional viewer with Selenium for visual regression review."""

from __future__ import annotations

from pathlib import Path
import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support.ui import WebDriverWait


def cached_driver(driver_name: str) -> Path | None:
    cache = Path.home() / ".cache" / "selenium" / driver_name
    candidates = tuple(cache.glob("**/*.exe")) if cache.is_dir() else ()
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def open_browser() -> webdriver.Remote:
    errors: list[str] = []
    for browser_name, driver_type, options_type, service_type, driver_name in (
        ("Edge", webdriver.Edge, webdriver.EdgeOptions, EdgeService, "msedgedriver"),
        ("Chrome", webdriver.Chrome, webdriver.ChromeOptions, ChromeService, "chromedriver"),
    ):
        options = options_type()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--hide-scrollbars")
        driver = cached_driver(driver_name)
        try:
            if driver is not None:
                return driver_type(options=options, service=service_type(executable_path=str(driver)))
            return driver_type(options=options)
        except Exception as exc:  # Selenium reports platform-specific driver failures.
            errors.append(f"{browser_name}: {exc}")
    raise RuntimeError("No Selenium browser could start:\n" + "\n".join(errors))


def capture(url: str, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    browser = open_browser()
    try:
        for name, width, minimum_height in (
            ("desktop", 1440, 1000),
            ("mobile", 430, 900),
        ):
            browser.set_window_size(width, minimum_height)
            browser.get(url)
            WebDriverWait(browser, 10).until(
                lambda current: current.find_element(By.ID, "histograms").text.strip()
            )
            height = max(
                minimum_height,
                int(browser.execute_script("return document.documentElement.scrollHeight")),
            )
            browser.set_window_size(width, height)
            time.sleep(0.2)
            if not browser.save_screenshot(str(output_directory / f"{name}.png")):
                raise RuntimeError(f"Selenium did not save the {name} screenshot")
    finally:
        browser.quit()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
    capture(target, Path(__file__).with_name("screenshots"))
