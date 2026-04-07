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

    captured = []

    def on_response(response):
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        try:
            txt = response.text()
            if len(txt) < 200:
                return
            # Mostrar qualquer campo pk com valor longo (possivel story ID)
            pks = re.findall(r'"pk"\s*:\s*"?(\d{12,})"?', txt)
            if pks:
                fields = []
                for f in ["expiring_at", "story_pk", "product_type", "taken_at", "media_type"]:
                    if f'"{f}"' in txt:
                        fields.append(f)
                captured.append({
                    "url": response.url[:100],
                    "pks": pks[:10],
                    "fields": fields
                })
        except:
            pass

    page.on("response", on_response)
    page.goto("https://www.instagram.com/stories/gordinhomotos10/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    print(f"\nTotal respostas JSON com PKs longos: {len(captured)}")
    for c in captured:
        print(f"\nURL: {c['url']}")
        print(f"  PKs: {c['pks']}")
        print(f"  Campos: {c['fields']}")

    browser.close()
