# -*- coding: utf-8 -*-
import sys, json, re
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

SESSION = Path("C:/Users/nissa/.claude/skills/monitor-concorrentes/session.json")
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        storage_state=str(SESSION) if SESSION.exists() else None,
        viewport={"width": 430, "height": 932},
        user_agent="Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    page = ctx.new_page()

    all_responses = []

    def on_response(response):
        ct = response.headers.get("content-type", "")
        url = response.url
        # Capturar tudo que seja JSON ou graphql
        if "json" in ct or "graphql" in url or "api/v1" in url:
            try:
                txt = response.text()
                all_responses.append({"url": url, "ct": ct, "len": len(txt), "sample": txt[:300]})
            except:
                all_responses.append({"url": url, "ct": ct, "len": 0, "sample": "erro"})

    page.on("response", on_response)
    page.goto("https://www.instagram.com/stories/gordinhomotos10/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    print(f"\nTotal respostas JSON/API: {len(all_responses)}")
    for r in all_responses[:30]:
        print(f"\n[{r['len']}] {r['url'][:120]}")
        if r['len'] > 0:
            print(f"  {r['sample'][:150]}")

    browser.close()
