# -*- coding: utf-8 -*-
import sys, re
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
    page.goto("https://www.instagram.com/stories/gordinhomotos10/", timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    print("URL atual:", page.url)

    # 1) IDs na URL e no HTML completo
    html = page.content()
    ids_html = set(re.findall(r'/stories/gordinhomotos10/(\d{10,})/', html))
    print(f"\nStory IDs no HTML: {ids_html}")

    # 2) Atributos href com story IDs
    hrefs = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a[href*="/stories/"]'))
               .map(a => a.href).slice(0, 20);
    }""")
    print(f"\nHREFs com /stories/: {hrefs}")

    # 3) Contar segmentos da barra de progresso
    segs = page.evaluate("""() => {
        const sels = [
            '[role="progressbar"]',
            '[class*="progress"]',
            '[class*="Progress"]',
            '[class*="segment"]',
            '[class*="Segment"]',
            '[class*="story-tray"]',
            'div[style*="transform"]'
        ];
        const results = {};
        for (const s of sels) {
            results[s] = document.querySelectorAll(s).length;
        }
        return results;
    }""")
    print(f"\nSegmentos de progresso: {segs}")

    # 4) window.__additionalData ou __initialData
    keys = page.evaluate("""() => {
        const wKeys = Object.keys(window).filter(k => k.startsWith('__'));
        const result = {};
        for (const k of wKeys.slice(0, 20)) {
            try { result[k] = typeof window[k]; } catch(e) {}
        }
        return result;
    }""")
    print(f"\nChaves window.__*: {keys}")

    browser.close()
