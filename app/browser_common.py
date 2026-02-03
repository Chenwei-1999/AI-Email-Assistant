from typing import List


def create_browser_context(p, profile_dir, headless: bool, cdp_url: str):
    if cdp_url:
        browser = p.chromium.connect_over_cdp(cdp_url)
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context()
        return browser, context, False
    context = p.chromium.launch_persistent_context(str(profile_dir), headless=headless)
    return None, context, True


def get_page_by_url(context, url_substrings: List[str], fallback_url: str):
    for page in context.pages:
        if any(sub in page.url for sub in url_substrings):
            try:
                page.bring_to_front()
            except Exception:
                pass
            return page
    page = context.new_page()
    page.goto(fallback_url)
    return page
