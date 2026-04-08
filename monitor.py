# -*- coding: utf-8 -*-
"""
Monitor de Concorrentes - Loja Jhow Motos
Captura Stories + Posts dos 5 concorrentes e gera relatorio HTML.
Roda 2x por dia via Agendador de Tarefas do Windows (09:00 e 17:00).
"""

import sys, json, shutil, subprocess, hashlib, re, os
from datetime import datetime
from pathlib import Path

# Compatibilidade Windows/Linux (GitHub Actions)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CONCORRENTES = {
    "Gordinho Motos": "gordinhomotos10",
    "Prado Motos":    "prado_motos",
    "Robson Motos":   "_robsonsmotos",
    "Rodolfo Motos":  "rodolfomotosvotorantim",
    "Start Motos":    "startmotosoficial",
}

SCRIPT_DIR   = Path(__file__).parent
SESSION_FILE = SCRIPT_DIR / "session.json"
COOKIES_FILE = SCRIPT_DIR / "cookies.txt"
ENV_FILE     = SCRIPT_DIR / ".env"

# JHOW_DIR: usa env var para suportar GitHub Actions (Linux) e Windows
JHOW_DIR = Path(os.environ.get("JHOW_DIR", "C:/jhow"))
JHOW_DIR.mkdir(parents=True, exist_ok=True)


# ── Credenciais ───────────────────────────────────────────────────────────────
def carregar_credenciais():
    creds = {}
    if ENV_FILE.exists():
        for linha in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.startswith("#"):
                k, v = linha.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds.get("IG_USER", ""), creds.get("IG_PASS", "")


# ── Sessao ────────────────────────────────────────────────────────────────────
def salvar_sessao(context):
    cookies = context.cookies()
    SESSION_FILE.write_text(json.dumps(cookies), encoding="utf-8")
    # Salvar tambem em formato Netscape para yt-dlp
    with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in cookies:
            domain = c.get('domain', '')
            if domain and not domain.startswith('.'):
                domain = '.' + domain
            path  = c.get('path', '/')
            secure = 'TRUE' if c.get('secure') else 'FALSE'
            exp_raw = c.get('expires', 2147483647)
            exp = str(int(exp_raw)) if exp_raw and int(exp_raw) > 0 else str(2147483647)
            f.write(f"{domain}\tTRUE\t{path}\t{secure}\t{exp}\t{c['name']}\t{c['value']}\n")

def restaurar_sessao(context):
    if SESSION_FILE.exists():
        try:
            context.add_cookies(json.loads(SESSION_FILE.read_text(encoding="utf-8")))
            return True
        except Exception:
            pass
    return False


# ── Login ─────────────────────────────────────────────────────────────────────
def fazer_login(page, usuario, senha):
    print("  Fazendo login no Instagram...")
    page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(3000)

    for texto in ["Allow all cookies", "Aceitar todos os cookies", "Accept All"]:
        try:
            btn = page.get_by_text(texto, exact=False).first
            if btn.is_visible(timeout=1500):
                btn.click()
                page.wait_for_timeout(1000)
                break
        except Exception:
            pass

    seletores = ["input[name='username']", "input[aria-label*='usuário']",
                 "input[aria-label*='username']", "input[type='text']"]
    campo_user = None
    for sel in seletores:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=6000)
            campo_user = loc
            break
        except Exception:
            continue

    if not campo_user:
        print("  Erro: campo de usuario nao encontrado")
        return False

    campo_user.fill(usuario)
    page.wait_for_timeout(600)
    page.locator("input[name='password'], input[type='password']").first.fill(senha)
    page.wait_for_timeout(600)
    page.locator("input[name='password'], input[type='password']").first.press("Enter")
    page.wait_for_timeout(7000)

    if "login" not in page.url:
        print("  Login OK!")
        return True
    print("  Falha no login")
    return False


# ── Classificacao de story com IA (opcional) ─────────────────────────────────
def _carregar_api_key():
    creds = {}
    if ENV_FILE.exists():
        for linha in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.startswith("#"):
                k, v = linha.split("=", 1)
                creds[k.strip()] = v.strip()
    return creds.get("ANTHROPIC_API_KEY", "")

_ANTHROPIC_KEY = None  # cache

def classificar_story_ia(arq_path: Path) -> str:
    """Classifica o story como 'venda' ou 'outro' usando Claude Haiku.
    Retorna 'venda', 'outro', ou 'nd' (nao disponivel) se sem chave."""
    global _ANTHROPIC_KEY
    if _ANTHROPIC_KEY is None:
        _ANTHROPIC_KEY = _carregar_api_key()
    if not _ANTHROPIC_KEY:
        return "nd"
    # Apenas imagens (nao envia MP4)
    if arq_path.suffix.lower() == ".mp4":
        return "venda"  # videos de motos costumam ser entregas/vendas
    try:
        import anthropic, base64
        img_bytes = arq_path.read_bytes()
        img_b64   = base64.standard_b64encode(img_bytes).decode()
        ext = arq_path.suffix.lower().lstrip(".")
        media_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        client = anthropic.Anthropic(api_key=_ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_b64}},
                    {"type": "text", "text": (
                        "Story do Instagram de loja de motos. Responda APENAS com uma palavra:\n"
                        "venda — entrega de moto, cliente com moto nova, negocio realizado, parabens pela moto\n"
                        "outro — motivacional, feriado, horario, pessoal, nao relacionado a venda\n"
                        "Palavra:"
                    )},
                ],
            }],
        )
        resposta = msg.content[0].text.strip().lower()
        return "venda" if "venda" in resposta else "outro"
    except Exception:
        return "nd"


# ── Stories via yt-dlp (video real + imagem real) ────────────────────────────
def baixar_stories_ytdlp(username, nome, ts):
    """Baixa todos os stories com yt-dlp: video como .mp4, foto como .jpg."""
    if not COOKIES_FILE.exists():
        return []

    import yt_dlp as _ytdlp

    pasta = ASSETS_DIR / username / "stories"
    pasta.mkdir(parents=True, exist_ok=True)

    url = f"https://www.instagram.com/stories/{username}/"
    prefixo = f"ytdlp_{ts}_"

    ydl_opts = {
        "outtmpl":      str(pasta / f"{prefixo}%(autonumber)03d.%(ext)s"),
        "format":       "best[ext=mp4]/best",
        "cookiefile":   str(COOKIES_FILE),
        "quiet":        True,
        "no_warnings":  True,
        "ignoreerrors": True,
        "autonumber_start": 1,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    }

    try:
        with _ytdlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        pass  # ignoreerrors ja trata a maioria; log detalhado desnecessario

    # Coletar arquivos baixados e renomear para padrao story_N_ts.ext
    baixados = sorted(pasta.glob(f"{prefixo}*"), key=lambda x: x.name)
    stories = []
    for i, arq in enumerate(baixados):
        novo = pasta / f"story_{i+1}_{ts}{arq.suffix}"
        arq.rename(novo)
        tipo = "video" if novo.suffix.lower() in (".mp4", ".mkv", ".webm") else "imagem"
        stories.append({
            "arquivo": str(novo.relative_to(BASE_DIR)).replace("\\", "/"),
            "indice":  i + 1,
            "tipo":    tipo,
        })

    if stories:
        qtd_v = sum(1 for s in stories if s["tipo"] == "video")
        qtd_i = len(stories) - qtd_v
        print(f"  {nome} (@{username}): {len(stories)} story(ies) [{qtd_v} video(s), {qtd_i} foto(s)]")
    else:
        print(f"  {nome}: sem stories ativos")

    return stories


# ── Stories via Instagram ─────────────────────────────────────────────────────
def dispensar_overlay(page):
    """Dispensa o overlay 'Ver como rastreavel?' antes de capturar stories."""
    textos = ["Ver story", "Ver stories", "Assistir ao story", "Tudo bem",
              "OK", "Continuar", "Assistir", "Ver"]
    for texto in textos:
        try:
            el = page.get_by_text(texto, exact=True).first
            if el.is_visible(timeout=1200):
                el.click()
                page.wait_for_timeout(2000)
                return True
        except Exception:
            pass
    # Tentar por role button com texto parcial
    for texto in ["Ver story", "Assistir"]:
        try:
            btn = page.get_by_role("button", name=texto, exact=False).first
            if btn.is_visible(timeout=1000):
                btn.click()
                page.wait_for_timeout(2000)
                return True
        except Exception:
            pass
    return False


def _pass1_coletar_ids(page, username, nome, espera_inicial=4000):
    """
    Pass 1: navega para os stories e coleta todos os IDs via tap.
    Retorna (story_ids, ids_set, story1_url_generica).
    """
    story_ids = []
    ids_set   = set()
    story1_url_generica = None
    sid0 = None

    page.goto(f"https://www.instagram.com/stories/{username}/",
              timeout=35000, wait_until="domcontentloaded")
    page.wait_for_timeout(espera_inicial)

    if "stories" not in page.url or username not in page.url:
        return story_ids, ids_set, story1_url_generica

    # Pausar video e dispensar overlays
    page.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")
    dispensar_overlay(page)
    page.wait_for_timeout(500)
    page.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")

    # Aguardar video ou imagem de story aparecer (confirma que app Bloks carregou)
    for _ in range(20):
        tem_midia = page.evaluate("""() => {
            return document.querySelector('video') !== null
                || document.querySelector('img[decoding]') !== null;
        }""")
        if tem_midia:
            break
        page.wait_for_timeout(300)

    # Story 1: verificar se URL ja tem ID ou e URL generica
    m0 = re.search(r'/stories/' + re.escape(username) + r'/(\d+)/', page.url)
    if m0:
        sid0 = m0.group(1)
        ids_set.add(sid0)
        story_ids.append(sid0)
    else:
        story1_url_generica = f"https://www.instagram.com/stories/{username}/"

    # Loop de tap para coletar IDs dos stories 2, 3, 4...
    ads_consecutivos = 0
    dup_consecutivos  = 0
    ultimo_sid        = sid0

    for _ in range(80):
        page.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")
        cur = page.url

        if "stories" not in cur:
            break
        if username not in cur:
            ads_consecutivos += 1
            dup_consecutivos = 0
            if ads_consecutivos >= 5:
                break
        else:
            ads_consecutivos = 0
            m = re.search(r'/stories/' + re.escape(username) + r'/(\d+)/', cur)
            if m:
                sid = m.group(1)
                if sid in ids_set:
                    if sid == ultimo_sid:
                        dup_consecutivos += 1
                        if dup_consecutivos >= 10:
                            break
                    else:
                        break  # voltou ao inicio
                else:
                    dup_consecutivos = 0
                    ids_set.add(sid)
                    story_ids.append(sid)
                ultimo_sid = sid

        # TAP lado direito da tela
        vp = page.viewport_size or {"width": 430, "height": 932}
        page.touchscreen.tap(int(vp["width"] * 0.82), int(vp["height"] * 0.45))

        # Aguardar mudanca de URL ate 9s
        for _ in range(60):
            page.wait_for_timeout(150)
            if page.url != cur:
                page.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")
                break

    return story_ids, ids_set, story1_url_generica


def capturar_stories_instagram(page, username, nome, run_dir):
    """2 passos:
    1. Ciclar rapidamente pelos stories coletando IDs (sem capturar) — com retry
    2. Navegar diretamente em cada story_id e capturar com video pausado
    """
    stories = []
    pasta = run_dir / username
    pasta.mkdir(parents=True, exist_ok=True)

    # ── PASSO 1: coletar IDs — tenta ate 3 vezes se captura < 2 IDs ─────────
    story_ids = []
    ids_set   = set()
    story1_url_generica = None

    MAX_TENTATIVAS = 3
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        espera = 4000 + (tentativa - 1) * 2000  # 4s / 6s / 8s
        try:
            s_ids, s_set, s_url = _pass1_coletar_ids(page, username, nome, espera)
        except Exception as e:
            print(f"  {nome}: Pass1 tentativa {tentativa} erro — {e}")
            s_ids, s_set, s_url = [], set(), None

        total_tap = len(s_ids) + (1 if s_url else 0)
        print(f"  {nome}: Pass1 tentativa {tentativa} — {len(s_ids)} IDs tap + {'URL generica' if s_url else 'sem URL generica'}")

        # Se nao tem stories: confirmar com tentativa extra so se tentativa 1
        if total_tap == 0 and tentativa == 1:
            continue

        # Se capturou mais que na tentativa anterior, usar esses IDs
        if len(s_ids) > len(story_ids):
            story_ids = s_ids
            ids_set   = s_set
            story1_url_generica = s_url

        # Se capturou > 1 ID via tap (tem mais de 1 story com ID), confiar
        if len(s_ids) >= 1:
            break

        # Se so tem URL generica (1 story) e nao ha IDs, pode ser que realmente
        # so tem 1 story — mas fazer mais 1 tentativa para confirmar
        if tentativa < MAX_TENTATIVAS:
            page.wait_for_timeout(3000)

    print(f"  {nome}: Pass1 final — {len(story_ids)} IDs + {'URL generica' if story1_url_generica else 'sem generica'}")

    # Se nao ha stories e nao temos URL generica para capturar, sair
    if not story_ids and not story1_url_generica:
        print(f"  {nome}: sem stories ativos")
        return stories

    # ── PASSO 2: capturar cada story via URL direta ───────────────────────────
    foto_buffer = []
    video_urls  = []

    def capturar_resposta(response):
        url_r = response.url
        ct    = response.headers.get("content-type", "")
        if "json" in ct and ("stories" in url_r or "graphql" in url_r or "api/v1" in url_r):
            try:
                txt = response.text()
                for m in re.findall(r'"video_url"\s*:\s*"([^"]+)"', txt):
                    clean = m.replace("\\u0026", "&").replace("\\/", "/")
                    if clean and ("cdninstagram" in clean or "fbcdn" in clean or "scontent" in clean):
                        if clean not in video_urls:
                            video_urls.insert(0, clean)
            except Exception:
                pass
        cdn = ("cdninstagram" in url_r or "fbcdn" in url_r or "scontent" in url_r)
        if not cdn:
            return
        if "video" in ct:
            if url_r not in video_urls:
                video_urls.append(url_r)
        elif "image/jpeg" in ct or "image/jpg" in ct:
            try:
                data = response.body()
                if len(data) >= 30_000:
                    foto_buffer.append({"ext": "jpg", "data": data})
            except Exception:
                pass

    page.on("response", capturar_resposta)

    # Montar lista completa de URLs: story 1 via URL generica + stories 2..N via ID
    story_urls_pass2 = []
    if story1_url_generica:
        story_urls_pass2.append(story1_url_generica)  # story 1 (sem ID)
    for sid in story_ids:
        story_urls_pass2.append(f"https://www.instagram.com/stories/{username}/{sid}/")

    try:
        for idx, story_url in enumerate(story_urls_pass2):
            foto_buffer.clear()
            video_urls.clear()
            try:
                page.goto(story_url, timeout=30000, wait_until="domcontentloaded")
            except Exception:
                continue
            page.wait_for_timeout(1500)
            dispensar_overlay(page)  # dispensar overlay em cada story navegado diretamente
            page.wait_for_timeout(800)

            # Classificacao via rede (mais confiavel que canvas/DOM):
            # se Instagram serviu URL de video CDN, e definitivamente um video
            is_video = len(video_urls) > 0
            if not is_video:
                is_video = page.evaluate("""() => {
                    for (const v of document.querySelectorAll('video')) {
                        if (v.duration > 0 || v.videoWidth > 0) return true;
                    }
                    return false;
                }""")

            arq_path   = None
            tipo_salvo = "imagem"
            thumb_path = None

            # Tirar screenshot (serve como thumb para video ou fallback para foto)
            shot = pasta / f"story_{idx+1}.png"
            try:
                page.screenshot(path=str(shot))
                if shot.exists() and shot.stat().st_size > 5_000:
                    thumb_path = shot
            except Exception:
                pass

            if is_video:
                # Tentar baixar video real da URL interceptada
                if video_urls:
                    try:
                        resp = page.request.get(video_urls[0], timeout=30_000)
                        if resp.ok and len(resp.body()) > 50_000:
                            arq_path   = pasta / f"story_{idx+1}.mp4"
                            arq_path.write_bytes(resp.body())
                            tipo_salvo = "video"
                    except Exception:
                        pass
                if arq_path is None and thumb_path:
                    arq_path   = thumb_path
                    tipo_salvo = "video"
            else:
                # Story de foto: tentar baixar imagem de alta qualidade
                img_src = page.evaluate("""() => {
                    const sels = [
                        'img[style*="object-fit: cover"]',
                        'section img[src*="cdninstagram"]','section img[src*="fbcdn"]',
                        'section img[src*="scontent"]',
                        'img[src*="cdninstagram"]','img[src*="fbcdn"]','img[src*="scontent"]',
                    ];
                    for (const s of sels) {
                        const el = document.querySelector(s);
                        if (el && el.src && el.naturalWidth > 100) return el.src;
                    }
                    return null;
                }""")
                if img_src:
                    try:
                        resp = page.request.get(img_src, timeout=30_000)
                        if resp.ok and len(resp.body()) > 20_000:
                            arq_path   = pasta / f"story_{idx+1}.jpg"
                            arq_path.write_bytes(resp.body())
                            tipo_salvo = "imagem"
                    except Exception:
                        pass
                if arq_path is None and foto_buffer:
                    item       = foto_buffer.pop(0)
                    arq_path   = pasta / f"story_{idx+1}.{item['ext']}"
                    arq_path.write_bytes(item["data"])
                    tipo_salvo = "imagem"
                if arq_path is None and thumb_path:
                    arq_path   = thumb_path
                    tipo_salvo = "imagem"

            if arq_path is None:
                arq_path = pasta / f"story_{idx+1}.png"
                try:
                    page.screenshot(path=str(arq_path))
                except Exception:
                    continue
                tipo_salvo = "imagem"

            categoria    = classificar_story_ia(arq_path)
            ig_story_url = None
            if tipo_salvo == "video":
                ig_story_url = story_url

            stories.append({
                "arquivo":      str(arq_path.relative_to(run_dir)).replace("\\", "/"),
                "indice":       idx + 1,
                "tipo":         tipo_salvo,
                "categoria":    categoria,
                "thumb":        str(thumb_path.relative_to(run_dir)).replace("\\", "/") if thumb_path and thumb_path.exists() else None,
                "ig_story_url": ig_story_url,
            })

    except Exception as e:
        print(f"  {nome}: erro ao capturar stories — {e}")
    finally:
        try:
            page.remove_listener("response", capturar_resposta)
        except Exception:
            pass

    if stories:
        qtd_v = sum(1 for s in stories if s["tipo"] == "video")
        qtd_i = len(stories) - qtd_v
        print(f"  {nome} (@{username}): {len(stories)} story(ies) [{qtd_v} video(s), {qtd_i} foto(s)]")

    return stories


# ── Stories via instanonimo.com.br (fallback) ─────────────────────────────────
def capturar_stories_instanonimo(page, username, nome, run_dir):
    """Baixa stories via instanonimo.com.br — extrai imagens e videos reais."""
    stories = []
    pasta = run_dir / username
    pasta.mkdir(parents=True, exist_ok=True)

    try:
        page.goto("https://instanonimo.com.br/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Preencher campo com o username (sem URL completa)
        preencheu = False
        for seletor in [
            "input[type='text']", "input[type='url']",
            "input[placeholder*='instagram' i]", "input[placeholder*='usuário' i]",
            "input[placeholder*='username' i]", "input[placeholder*='URL' i]",
            "input[name*='user' i]", "input[name*='search' i]", "input",
        ]:
            try:
                campo = page.locator(seletor).first
                if campo.is_visible(timeout=2000):
                    campo.clear()
                    campo.fill(username)
                    page.wait_for_timeout(600)
                    campo.press("Enter")
                    page.wait_for_timeout(7000)
                    preencheu = True
                    break
            except Exception:
                continue

        if not preencheu:
            print(f"  {nome}: instanonimo — campo de busca nao encontrado")
            return stories

        # Clicar botao de busca se ainda nao carregou
        for texto in ["Ver stories", "Ver Stories", "Buscar", "Search", "Ver"]:
            try:
                btn = page.get_by_role("button", name=texto, exact=False).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(6000)
                    break
            except Exception:
                pass

        # 1. Tentar extrair videos (stories em video)
        videos = page.eval_on_selector_all(
            "video source[src], video[src]",
            "els => els.map(e => e.src || e.getAttribute('src')).filter(Boolean)"
        )
        for i, src in enumerate(videos[:10]):
            if not src:
                continue
            try:
                resp = page.request.get(src, timeout=20000)
                if resp.ok:
                    arq = pasta / f"story_{i+1}.mp4"
                    arq.write_bytes(resp.body())
                    stories.append({
                        "arquivo": str(arq.relative_to(run_dir)).replace("\\", "/"),
                        "indice": i + 1,
                        "fonte": "instanonimo",
                        "tipo": "video",
                    })
            except Exception:
                pass

        offset = len(stories)

        # 2. Tentar extrair imagens (stories em foto)
        imgs = page.eval_on_selector_all(
            "img[src*='cdninstagram'], img[src*='fbcdn'], img[src*='scontent']",
            "els => els.map(e => e.src).filter(Boolean)"
        )
        for i, src in enumerate(imgs[:10]):
            if not src:
                continue
            try:
                resp = page.request.get(src, timeout=10000)
                if resp.ok:
                    ct = resp.headers.get("content-type", "")
                    ext = "jpg" if "jpeg" in ct else "png"
                    arq = pasta / f"story_{offset+i+1}.{ext}"
                    arq.write_bytes(resp.body())
                    stories.append({
                        "arquivo": str(arq.relative_to(run_dir)).replace("\\", "/"),
                        "indice": offset + i + 1,
                        "fonte": "instanonimo",
                        "tipo": "imagem",
                    })
            except Exception:
                pass

        # 3. Tentar botoes de download (intercepta arquivo baixado)
        if not stories:
            try:
                dl_sels = ["a[download]", "a[href*='.mp4']", "a[href*='download']",
                           "button[class*='download' i]", "a[class*='download' i]"]
                for sel in dl_sels:
                    btns = page.locator(sel)
                    count = btns.count()
                    for j in range(min(count, 5)):
                        try:
                            with page.expect_download(timeout=15000) as dl_info:
                                btns.nth(j).click()
                            dl = dl_info.value
                            suf = Path(dl.suggested_filename).suffix or ".mp4"
                            arq = pasta / f"story_{j+1}{suf}"
                            dl.save_as(str(arq))
                            tipo = "video" if suf == ".mp4" else "imagem"
                            stories.append({
                                "arquivo": str(arq.relative_to(run_dir)).replace("\\", "/"),
                                "indice": j + 1,
                                "fonte": "instanonimo",
                                "tipo": tipo,
                            })
                        except Exception:
                            pass
                    if stories:
                        break
            except Exception:
                pass

        if stories:
            print(f"  {nome}: {len(stories)} story(ies) via instanonimo")
        else:
            print(f"  {nome}: instanonimo sem midia (perfil sem stories ativos)")

    except Exception as e:
        print(f"  {nome}: erro instanonimo — {e}")

    return stories


# ── Posts do feed ─────────────────────────────────────────────────────────────
def _dispensar_dialogs(page):
    """Dispensa dialogs de 'Salvar informações', 'Agora não', cookies, notificacoes, etc."""
    textos_nao = ["Agora não", "Agora nao", "Not Now", "Not now",
                  "Recusar tudo", "Recusar", "Fechar", "Cancelar"]
    for texto in textos_nao:
        try:
            el = page.get_by_text(texto, exact=True).first
            if el.is_visible(timeout=800):
                el.click()
                page.wait_for_timeout(600)
        except Exception:
            pass
    # Botao "Agora não" por role
    for texto in textos_nao:
        try:
            btn = page.get_by_role("button", name=texto, exact=False).first
            if btn.is_visible(timeout=600):
                btn.click()
                page.wait_for_timeout(600)
        except Exception:
            pass


def capturar_posts(page, username, nome, run_dir):
    url = f"https://www.instagram.com/{username}/"
    posts = []
    screenshot = None

    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Dispensar popups de "Salvar informacoes", notificacoes, cookies
        _dispensar_dialogs(page)
        page.wait_for_timeout(1500)

        # Rolar um pouco para carregar o grid de posts
        page.evaluate("window.scrollBy(0, 400)")
        page.wait_for_timeout(2000)

        # Dispensar novamente caso algum popup apareca apos scroll
        _dispensar_dialogs(page)
        page.wait_for_timeout(800)

        shot = run_dir / username / "perfil.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot))
        screenshot = str(shot.relative_to(run_dir)).replace("\\", "/")

        # Capturar links /p/ (posts do feed)
        links = page.eval_on_selector_all(
            "a[href*='/p/']",
            "els => els.map(el => ({ href: el.href, src: el.querySelector('img') ? el.querySelector('img').src : '' }))"
        )
        vistos = set()
        for l in links:
            href = l.get("href", "")
            if "/p/" not in href:
                continue
            sc = href.split("/p/")[-1].rstrip("/")
            if sc and sc not in vistos:
                vistos.add(sc)
                posts.append({"url": href, "shortcode": sc, "thumb": l.get("src", "")})
            if len(posts) >= 9:
                break

        print(f"  {nome} (@{username}): {len(posts)} post(s) no feed")

    except Exception as e:
        print(f"  {nome}: erro feed — {e}")

    return posts, screenshot


# ── HTML ──────────────────────────────────────────────────────────────────────
def gerar_html(resultados, timestamp):
    secoes = ""
    total_stories = sum(len(r["stories"]) for r in resultados)
    total_posts   = sum(len(r["posts"])   for r in resultados)
    total_ok      = sum(1 for r in resultados if not r.get("erro"))

    tem_ia = any(s.get("categoria") not in ("nd", None)
                 for r in resultados for s in r["stories"])

    for r in resultados:
        # Stories
        html_stories = ""
        if r["stories"]:
            qtd_venda = sum(1 for s in r["stories"] if s.get("categoria") == "venda")
            qtd_outro = sum(1 for s in r["stories"] if s.get("categoria") == "outro")
            qtd_nd    = len(r["stories"]) - qtd_venda - qtd_outro

            for s in r["stories"]:
                tipo      = s.get("tipo", "imagem")
                cat       = s.get("categoria", "nd")
                arq       = s["arquivo"]
                # Badge de categoria
                if cat == "venda":
                    cat_badge = '<span class="cat-badge venda">&#128994; Venda</span>'
                elif cat == "outro":
                    cat_badge = '<span class="cat-badge outro">&#128308; Outro</span>'
                else:
                    cat_badge = ""
                num = s["indice"]
                if tipo == "video":
                    thumb = s.get("thumb") or arq
                    ig_url = s.get("ig_story_url") or f"https://www.instagram.com/stories/{r['username']}/"
                    midia = f'<a href="{ig_url}" target="_blank" title="Clique para ver o story no Instagram"><img src="{thumb}" alt="Video {num}"><div class="play-icon">&#9654;</div></a>'
                else:
                    midia = f'<a href="{arq}" target="_blank" title="Clique para ampliar"><img src="{arq}" alt="Story {num}"></a>'
                css_venda = " destaque" if cat == "venda" else ""
                html_stories += f"""
                <div class="story-card{css_venda}">
                  {cat_badge}
                  {midia}
                  <div class="story-num">#{s["indice"]}</div>
                </div>"""
        else:
            qtd_venda = qtd_outro = qtd_nd = 0
            html_stories = '<p class="sem">Nenhum story ativo no momento</p>'

        # Posts feed
        html_posts = ""
        for p in r["posts"]:
            html_posts += f"""
            <a href="{p['url']}" target="_blank" class="post-thumb">
              <img src="{p['thumb']}" onerror="this.style.display='none'">
              <div class="post-overlay">Ver post</div>
            </a>"""
        if not html_posts:
            html_posts = '<p class="sem">Nenhum post detectado</p>'

        # Screenshot perfil
        shot_tag = f'<img src="{r["screenshot"]}" class="perfil-shot">' if r.get("screenshot") else ""

        legenda_cat = ""
        if qtd_venda > 0:
            legenda_cat = f'<span style="font-size:11px;color:#166534;font-weight:600;margin-left:8px;">&#128994; {qtd_venda} venda(s) destacada(s)</span>'

        secoes += f"""
        <section class="card">
          <div class="card-header">
            <div>
              <h2>@{r['username']}</h2>
              <span class="nome-loja">{r['nome']}</span>
            </div>
            <div class="card-actions">
              <button class="btn-pdf" onclick="gerarPDF('{r['username']}')" title="Gerar PDF com grade 3x3 dos stories">&#128437; PDF Stories</button>
              <a href="https://www.instagram.com/{r['username']}/" target="_blank" class="ver-ig">Abrir no Instagram &rarr;</a>
            </div>
          </div>

          <div class="bloco">
            <div class="bloco-titulo">
              <span class="icone">&#128247;</span> Stories ({len(r['stories'])}){legenda_cat}
            </div>
            <div class="stories-grid">{html_stories}</div>
          </div>

          <div class="bloco">
            <div class="bloco-titulo">
              <span class="icone">&#128248;</span> Posts recentes ({len(r['posts'])})
            </div>
            <div class="perfil-wrap">{shot_tag}</div>
            <div class="posts-grid">{html_posts}</div>
          </div>
        </section>"""

    # Dados de stories por usuario como JSON para o JS de PDF
    import json as _json
    stories_json = _json.dumps({
        r["username"]: {
            "nome": r["nome"],
            "stories": [
                {
                    "indice": s["indice"],
                    "tipo":   s.get("tipo", "imagem"),
                    "src":    s.get("thumb") or s["arquivo"],
                    "cat":    s.get("categoria", "nd"),
                }
                for s in r["stories"]
            ]
        }
        for r in resultados
    }, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor Concorrentes - {timestamp}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',sans-serif; background:#f0f4ff; color:#0f172a; }}
  header {{ background:linear-gradient(135deg,#1e3a8a,#1a56db); color:#fff; padding:28px 40px; }}
  header h1 {{ font-size:24px; font-weight:800; }}
  .header-sub {{ display:flex; align-items:center; gap:18px; margin-top:6px; flex-wrap:wrap; }}
  .header-sub p {{ font-size:13px; opacity:.7; }}
  .header-datetime {{ font-size:20px; font-weight:800; color:#fff; letter-spacing:.5px; }}
  .header-datetime span {{ font-size:13px; font-weight:400; opacity:.7; margin-right:6px; }}
  .badges {{ display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }}
  .badge {{ background:rgba(255,255,255,.18); border-radius:20px; padding:4px 14px; font-size:12px; font-weight:600; cursor:pointer; text-decoration:none; color:#fff; transition:background .15s; }}
  .badge:hover {{ background:rgba(255,255,255,.32); }}
  .btn-imprimir {{ background:#fff; color:#1a56db; border:none; border-radius:20px; padding:6px 18px; font-size:13px; font-weight:800; cursor:pointer; display:flex; align-items:center; gap:6px; transition:opacity .15s; }}
  .btn-imprimir:hover {{ opacity:.85; }}
  .container {{ max-width:1200px; margin:0 auto; padding:32px 20px; display:flex; flex-direction:column; gap:28px; }}
  .card {{ background:#fff; border-radius:16px; overflow:hidden; box-shadow:0 2px 16px rgba(0,0,0,.08); }}
  .card-header {{ display:flex; justify-content:space-between; align-items:center; padding:18px 28px; border-bottom:2px solid #e2e8f0; background:#f8faff; flex-wrap:wrap; gap:10px; }}
  .card-header h2 {{ font-size:18px; color:#1a56db; font-weight:800; }}
  .nome-loja {{ font-size:12px; color:#64748b; display:block; }}
  .card-actions {{ display:flex; gap:10px; align-items:center; }}
  .ver-ig {{ font-size:12px; font-weight:700; color:#1a56db; text-decoration:none; }}
  .ver-ig:hover {{ text-decoration:underline; }}
  .btn-pdf {{ font-size:12px; font-weight:700; color:#fff; background:#e11d48;
    border:none; border-radius:8px; padding:6px 14px; cursor:pointer;
    display:flex; align-items:center; gap:5px; transition:background .15s; }}
  .btn-pdf:hover {{ background:#be123c; }}
  .bloco {{ padding:20px 28px; border-bottom:1px solid #e2e8f0; }}
  .bloco:last-child {{ border-bottom:none; }}
  .bloco-titulo {{ font-size:13px; font-weight:700; color:#374151; margin-bottom:14px; display:flex; align-items:center; gap:6px; }}
  .icone {{ font-size:16px; }}
  .stories-grid {{ display:flex; gap:14px; flex-wrap:wrap; }}
  .story-card {{ position:relative; width:120px; }}
  .story-card a {{ display:block; position:relative; text-decoration:none; }}
  .story-card img {{ width:120px; height:213px; object-fit:cover; border-radius:10px; border:2px solid #dbeafe; display:block; }}
  .story-card a:hover img {{ border-color:#1a56db; opacity:.92; }}
  .play-icon {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
    background:rgba(0,0,0,.55); color:#fff; font-size:28px; width:48px; height:48px;
    border-radius:50%; display:flex; align-items:center; justify-content:center;
    pointer-events:none; padding-left:4px; }}
  .story-num {{ font-size:11px; color:#94a3b8; text-align:center; margin-top:4px; }}
  .story-card.destaque img {{ border:3px solid #f59e0b !important; box-shadow:0 0 12px rgba(245,158,11,.55); border-radius:10px; }}
  .story-card.destaque .story-num {{ color:#b45309; font-weight:700; }}
  .cat-badge {{ font-size:10px; font-weight:700; padding:2px 7px; border-radius:20px; margin-bottom:5px; display:inline-block; }}
  .cat-badge.venda {{ background:#fef3c7; color:#92400e; }}
  .cat-badge.outro {{ background:#f1f5f9; color:#64748b; }}
  .perfil-shot {{ width:100%; max-height:280px; object-fit:cover; border-radius:10px; border:1px solid #e2e8f0; margin-bottom:12px; }}
  .perfil-wrap {{ margin-bottom:12px; }}
  .posts-grid {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .post-thumb {{ position:relative; width:90px; height:90px; overflow:hidden; border-radius:8px; border:1px solid #e2e8f0; display:block; }}
  .post-thumb img {{ width:100%; height:100%; object-fit:cover; }}
  .post-overlay {{ position:absolute; inset:0; background:rgba(26,86,219,.75); color:#fff; font-size:11px; font-weight:700; display:flex; align-items:center; justify-content:center; opacity:0; transition:.2s; }}
  .post-thumb:hover .post-overlay {{ opacity:1; }}
  .sem {{ color:#94a3b8; font-size:13px; padding:8px 0; }}
  footer {{ text-align:center; color:#94a3b8; font-size:12px; padding:28px; }}
</style>
</head>
<body>
<header>
  <h1>&#128202; Monitor de Concorrentes</h1>
  <div class="header-sub">
    <p>Loja Jhow Motos &mdash; Votorantim, SP</p>
    <div class="header-datetime"><span>&#128197;</span>{timestamp}</div>
  </div>
  <div class="badges">
    <a class="badge" onclick="abrirTodos()" title="Abrir todos os perfis no Instagram">&#9989; {total_ok}/5 perfis &rarr;</a>
    <span class="badge">&#127897; {total_stories} stories</span>
    <span class="badge">&#128248; {total_posts} posts</span>
    <button class="btn-imprimir" onclick="window.print()" title="Imprimir / Salvar como PDF">&#128438; Imprimir</button>
  </div>
</header>
<div class="container">
{secoes}
</div>
<footer>Monitor automatico 2x/dia &mdash; Jhow Motos {datetime.now().year}</footer>

<script>
const STORIES_DATA = {stories_json};
const TIMESTAMP = "{timestamp}";
const USERNAMES = Object.keys(STORIES_DATA);

function abrirTodos() {{
  USERNAMES.forEach(u => window.open('https://www.instagram.com/' + u + '/', '_blank'));
}}

function gerarPDF(username) {{
  const d = STORIES_DATA[username];
  if (!d || !d.stories.length) {{ alert('Nenhum story disponivel para ' + username); return; }}

  // Agrupar stories em pares (2 por pagina)
  const paginas = [];
  for (let i = 0; i < d.stories.length; i += 2) paginas.push(d.stories.slice(i, i + 2));

  function storyCard(s) {{
    const isVideo = s.tipo === 'video';
    const tipoLabel = isVideo
      ? '<div style="display:inline-flex;align-items:center;gap:4px;background:#1e3a8a;color:#fff;font-size:10px;font-weight:700;border-radius:6px;padding:2px 8px;margin-bottom:5px;">&#9654; VIDEO</div>'
      : '<div style="display:inline-flex;align-items:center;gap:4px;background:#0f766e;color:#fff;font-size:10px;font-weight:700;border-radius:6px;padding:2px 8px;margin-bottom:5px;">&#128247; FOTO</div>';
    const cat = s.cat === 'venda' ? '<div style="font-size:10px;color:#92400e;background:#fef3c7;border-radius:6px;padding:2px 8px;display:inline-block;margin-left:4px;font-weight:700;">VENDA</div>' : '';
    const badge = isVideo ? '<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(0,0,0,.6);color:#fff;font-size:36px;width:64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;padding-left:6px;pointer-events:none;">&#9654;</div>' : '';
    return `<div class="story-wrap">
      <div style="display:flex;align-items:center;gap:2px;margin-bottom:4px;">${{tipoLabel}}${{cat}}</div>
      <div style="position:relative;flex:1;display:flex;align-items:center;justify-content:center;">
        <img class="story-img" src="${{s.src}}" onerror="this.style.background='#e2e8f0';this.alt='Imagem indisponivel';">
        ${{badge}}
      </div>
      <div style="font-size:11px;color:#64748b;margin-top:5px;text-align:center;">Story #${{s.indice}}</div>
    </div>`;
  }}

  const pagHtml = paginas.map((par, pi) => {{
    const cards = par.map(storyCard).join('');
    const pb = pi < paginas.length - 1 ? 'page-break-after:always;' : '';
    return `<div class="page-row" style="${{pb}}">${{cards}}</div>`;
  }}).join('');

  const html = `<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Stories ${{d.nome}} - ${{TIMESTAMP}}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ height:100%; }}
  body {{ font-family:'Segoe UI',sans-serif; color:#0f172a; display:flex; flex-direction:column; }}
  .header {{ padding:8px 16px 6px; border-bottom:2px solid #dbeafe; flex-shrink:0; }}
  h2 {{ font-size:15px; color:#1a56db; }}
  .sub {{ font-size:10px; color:#64748b; }}
  .page-row {{
    display:flex; flex-direction:row; gap:16px;
    justify-content:center; align-items:stretch;
    flex:1; padding:12px 16px; min-height:0;
  }}
  .story-wrap {{
    display:flex; flex-direction:column; align-items:center;
    flex:1; min-width:0; max-width:48%;
  }}
  .story-img {{
    max-height:calc(100vh - 80px); max-width:100%;
    width:auto; height:auto;
    object-fit:contain;
    border-radius:10px;
    border:2px solid #dbeafe;
    display:block;
  }}
  @media print {{
    @page {{ margin:6mm; size:A4 landscape; }}
    body {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; height:100vh; }}
    .page-row {{ page-break-after:always; height:calc(100vh - 52px); }}
    .story-img {{ max-height:calc(100vh - 80px); }}
  }}
</style>
</head><body>
<div class="header">
  <h2>&#128247; ${{d.nome}} &mdash; @${{username}}</h2>
  <div class="sub">Gerado em ${{TIMESTAMP}} &middot; ${{d.stories.length}} story(ies)</div>
</div>
${{pagHtml}}
<script>window.onload = function() {{ window.print(); }};<\\/script>
</body></html>`;

  const w = window.open('', '_blank');
  w.document.open();
  w.document.write(html);
  w.document.close();
}}
</script>
</body>
</html>"""


# ── Netlify ───────────────────────────────────────────────────────────────────
def _img_base64(path: Path, max_width: int = 320, quality: int = 52) -> str:
    """Converte imagem em data URI base64 com compressao (Pillow se disponivel)."""
    import base64, io as _io
    raw = path.read_bytes()
    try:
        from PIL import Image as _Img
        img = _Img.open(_io.BytesIO(raw)).convert("RGB")
        # Redimensionar mantendo proporcao (max_width px de largura)
        w, h = img.size
        if w > max_width:
            img = img.resize((max_width, int(h * max_width / w)), _Img.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
    except Exception:
        # Sem Pillow: embute raw sem compressao
        ext = path.suffix.lower().lstrip(".")
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

def gerar_html_standalone(resultados, timestamp, run_dir):
    """Gera HTML auto-contido com imagens embutidas em base64."""
    import re as _re
    html = gerar_html(resultados, timestamp)

    # Substituir src="caminho/relativo.ext" por data URI (atributos HTML)
    def substituir(m):
        src = m.group(1)
        caminho = run_dir / src
        if caminho.exists() and caminho.stat().st_size > 0:
            return f'src="{_img_base64(caminho)}"'
        return m.group(0)
    html = _re.sub(r'src="([^"]+\.(png|jpg|jpeg))"', substituir, html)

    # Substituir "src":"caminho/relativo.ext" dentro do STORIES_DATA JSON
    # (PDF popup usa esses caminhos — precisam ser base64 para funcionar offline)
    def substituir_json_src(m):
        src = m.group(1)
        caminho = run_dir / src
        if caminho.exists() and caminho.stat().st_size > 0:
            return f'"src":"{_img_base64(caminho)}"'
        # fallback: tentar .png com mesmo nome base (thumb do video)
        thumb = caminho.with_suffix(".png")
        if thumb.exists() and thumb.stat().st_size > 0:
            return f'"src":"{_img_base64(thumb)}"'
        return m.group(0)
    # json.dumps gera "src": "path" com espaco apos os dois-pontos
    html = _re.sub(r'"src":\s*"([^"]+\.(png|jpg|jpeg|mp4))"', substituir_json_src, html)

    return html

def gerar_zip_netlify(run_dir, timestamp, resultados):
    """Gera C:/jhow/para_netlify.zip — arraste no Netlify para publicar."""
    try:
        import zipfile, io as _io
        html_standalone = gerar_html_standalone(resultados, timestamp, run_dir)
        saida = JHOW_DIR / "para_netlify.zip"
        with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
            # index.html = relatorio diretamente (https://jhow-analise.netlify.app/ mostra o relatorio)
            zf.writestr("index.html", html_standalone)
        mb = saida.stat().st_size / 1_048_576
        print(f"  ZIP Netlify: {saida}  ({mb:.1f} MB)")
    except Exception as e:
        print(f"  ZIP: erro — {e}")


def publicar_surge(run_dir, timestamp, resultados):
    """Publica relatorio standalone em jhow-motos.surge.sh automaticamente."""
    try:
        import zipfile as _zf, re as _re2
        SURGE_DIR  = JHOW_DIR / "surge_publish"
        SURGE_DIR.mkdir(exist_ok=True)
        html_standalone = gerar_html_standalone(resultados, timestamp, run_dir)

        # Injetar script de auto-atualizacao via GitHub Actions
        # Token lido de env var (nao hardcoded no codigo)
        GH_TOKEN  = os.environ.get("WORKFLOW_TOKEN", "")
        GH_OWNER  = "issao2026"
        GH_REPO   = "jhow-monitor"
        GH_WF     = "monitor.yml"
        auto_script = f"""<script>
(async function autoAtualizar() {{
  var OWNER = '{GH_OWNER}', REPO = '{GH_REPO}', WF = '{GH_WF}';
  var TOKEN = '{GH_TOKEN}';
  var HDR = {{'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}};
  var banner = document.createElement('div');
  banner.style = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#1a56db;color:#fff;font-size:14px;font-weight:700;padding:12px 24px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.2)';
  function showBanner(msg, cor) {{ banner.textContent = msg; banner.style.background = cor||'#1a56db'; if(!banner.parentNode) document.body.prepend(banner); }}
  try {{
    // Verificar runs recentes
    var r = await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/actions/runs?per_page=5',{{headers:HDR}});
    var d = await r.json();
    var runs = d.workflow_runs||[];
    var emAndamento = runs.find(function(x){{return x.status==='in_progress'||x.status==='queued';}});
    var ultimo = runs.find(function(x){{return x.status==='completed';}});
    // Se dados sao recentes (< 4 min), nao disparar novo run
    if (!emAndamento && ultimo) {{
      var diff = (Date.now() - new Date(ultimo.updated_at).getTime()) / 60000;
      if (diff < 4) return; // ja esta atualizado
    }}
    if (!emAndamento) {{
      // Disparar novo run
      await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/actions/workflows/'+WF+'/dispatches',
        {{method:'POST',headers:HDR,body:JSON.stringify({{ref:'main'}})}});
      showBanner('Buscando stories... aguarde ~2 minutos');
    }} else {{
      showBanner('Coletando stories em andamento...');
    }}
    // Aguardar 15s antes de comecar a verificar
    await new Promise(function(res){{setTimeout(res,15000);}});
    var poll = setInterval(async function() {{
      try {{
        var pr = await fetch('https://api.github.com/repos/'+OWNER+'/'+REPO+'/actions/runs?per_page=1',{{headers:HDR}});
        var pd = await pr.json();
        var run = pd.workflow_runs&&pd.workflow_runs[0];
        if (run && run.status==='completed') {{
          clearInterval(poll);
          showBanner('Stories atualizados! Recarregando...', '#16a34a');
          setTimeout(function(){{location.reload(true);}}, 1500);
        }}
      }} catch(e) {{}}
    }}, 12000);
  }} catch(e) {{ console.log('auto-update erro:', e); }}
}})();
</script>"""
        html_standalone = html_standalone.replace("</body>", auto_script + "\n</body>", 1)

        (SURGE_DIR / "index.html").write_text(html_standalone, encoding="utf-8")
        # Localizar surge: PATH ou caminho fixo do npm global
        surge_exe = (shutil.which("surge")
                     or shutil.which("surge.cmd")
                     or str(Path.home() / "AppData/Roaming/npm/surge.cmd"))
        cmd = [surge_exe, str(SURGE_DIR), "jhow-motos.surge.sh"]
        # Suporte a token via env var (necessario no GitHub Actions)
        surge_token = os.environ.get("SURGE_TOKEN", "")
        if surge_token:
            cmd += ["--token", surge_token]
        proc = subprocess.run(
            cmd, capture_output=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        saida = (proc.stdout or "") + (proc.stderr or "")
        if "Success" in saida or "success" in saida.lower():
            print("  Surge: publicado em https://jhow-motos.surge.sh")
        else:
            print(f"  Surge: erro — {saida[-300:]}")
    except Exception as e:
        print(f"  Surge: erro — {e}")


def publicar_netlify(run_dir, timestamp, resultados):
    """Publica relatorio standalone no Netlify via API."""
    creds = {}
    if ENV_FILE.exists():
        for linha in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.startswith("#"):
                k, v = linha.split("=", 1)
                creds[k.strip()] = v.strip()

    token   = creds.get("NETLIFY_TOKEN", "")
    site_id = creds.get("NETLIFY_SITE_ID", "")
    if not token or not site_id:
        return  # Sem credenciais, pular silenciosamente

    try:
        import urllib.request, urllib.error, zipfile, io, json as _json

        print("  Publicando no Netlify...")

        # Gerar HTML standalone
        html_standalone = gerar_html_standalone(resultados, timestamp, run_dir)

        # Gerar index standalone
        index_html = (JHOW_DIR / "index.html").read_text(encoding="utf-8")

        # Criar ZIP com index.html + relatorio.html (sem imagens externas)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html",     index_html)
            zf.writestr("relatorio.html", html_standalone)
        buf.seek(0)

        req = urllib.request.Request(
            f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
            data=buf.read(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/zip",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            deploy = _json.loads(resp.read())
            url = deploy.get("ssl_url") or deploy.get("url", "")
            print(f"  Publicado: {url}")

    except Exception as e:
        print(f"  Netlify: erro ao publicar — {e}")


# ── Index ─────────────────────────────────────────────────────────────────────
def atualizar_index():
    """Gera C:/jhow/index.html listando todos os runs em ordem cronologica reversa."""
    runs = sorted(
        [d for d in JHOW_DIR.iterdir() if d.is_dir() and (d / "relatorio.html").exists()],
        key=lambda d: d.stat().st_mtime,
        reverse=True
    )
    linhas = ""
    for i, run in enumerate(runs):
        ts_raw = run.name  # ex: 06-04-2026_09h20
        try:
            dt = datetime.strptime(ts_raw, "%d-%m-%Y_%Hh%M")
            data  = dt.strftime("%d/%m/%Y")
            hora  = dt.strftime("%H:%M")
        except Exception:
            # fallback para formato antigo
            try:
                dt = datetime.strptime(ts_raw, "%Y%m%d_%H%M")
                data  = dt.strftime("%d/%m/%Y")
                hora  = dt.strftime("%H:%M")
            except Exception:
                data = hora = ts_raw
        # Contar stories salvos
        total_imgs = sum(1 for f in run.rglob("story_*.jpg") ) + \
                     sum(1 for f in run.rglob("story_*.png") if "perfil" not in f.name)
        destaque = ' class="ultima"' if i == 0 else ""
        badge_novo = '<span class="badge-novo">NOVO</span>' if i == 0 else ""
        linhas += f"""
        <tr{destaque}>
          <td>{badge_novo}<strong>{data}</strong></td>
          <td>{hora}</td>
          <td>{total_imgs}</td>
          <td><a href="{run.name}/relatorio.html" target="_blank">Abrir Relatório &rarr;</a></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor Concorrentes — Jhow Motos</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',sans-serif; background:#f0f4ff; color:#0f172a; min-height:100vh; }}
  header {{ background:linear-gradient(135deg,#1e3a8a,#1a56db); color:#fff; padding:32px 40px; }}
  header h1 {{ font-size:26px; font-weight:800; }}
  header p  {{ font-size:14px; opacity:.75; margin-top:6px; }}
  .container {{ max-width:800px; margin:40px auto; padding:0 20px; }}
  .card {{ background:#fff; border-radius:16px; box-shadow:0 2px 16px rgba(0,0,0,.08); overflow:hidden; }}
  table {{ width:100%; border-collapse:collapse; }}
  thead {{ background:#f8faff; }}
  th {{ padding:14px 20px; font-size:12px; font-weight:700; color:#64748b; text-align:left; border-bottom:2px solid #e2e8f0; }}
  td {{ padding:14px 20px; font-size:14px; border-bottom:1px solid #f1f5f9; }}
  tr:last-child td {{ border-bottom:none; }}
  tr.ultima td {{ background:#eff6ff; }}
  tr:hover td {{ background:#f8faff; }}
  td a {{ color:#1a56db; font-weight:700; text-decoration:none; }}
  td a:hover {{ text-decoration:underline; }}
  .badge-novo {{ background:#1a56db; color:#fff; font-size:10px; font-weight:800;
    padding:2px 7px; border-radius:20px; margin-right:8px; vertical-align:middle; }}
  .footer {{ text-align:center; color:#94a3b8; font-size:12px; padding:24px; }}
  #banner {{ display:none; position:fixed; top:0; left:0; right:0; z-index:999;
    background:#1a56db; color:#fff; font-size:14px; font-weight:700;
    padding:12px 24px; text-align:center; box-shadow:0 2px 12px rgba(0,0,0,.2); }}
  #banner.erro {{ background:#dc2626; }}
  .btn-run {{ background:#fff; color:#1a56db; border:none; border-radius:20px;
    padding:8px 20px; font-size:13px; font-weight:800; cursor:pointer;
    margin-left:16px; transition:opacity .15s; }}
  .btn-run:hover {{ opacity:.85; }}
  .btn-run:disabled {{ opacity:.5; cursor:default; }}
</style>
</head>
<body>
<div id="banner">
  <span id="banner-txt"></span>
</div>
<header>
  <h1>&#128202; Monitor de Concorrentes</h1>
  <p>Loja Jhow Motos &mdash; Votorantim, SP &mdash; {len(runs)} relatório(s) disponíveis
    <button class="btn-run" id="btn-run" onclick="rodar()">&#9654; Atualizar agora</button>
  </p>
</header>
<div class="container">
  <div class="card">
    <table>
      <thead>
        <tr>
          <th>Data</th>
          <th>Horário</th>
          <th>Stories</th>
          <th>Relatório</th>
        </tr>
      </thead>
      <tbody>
        {linhas}
      </tbody>
    </table>
  </div>
  <p class="footer">Jhow Motos {datetime.now().year}</p>
</div>
<script>
let _rodando = false;
let _poll = null;

function banner(msg, erro) {{
  const b = document.getElementById('banner');
  b.className = erro ? 'erro' : '';
  document.getElementById('banner-txt').textContent = msg;
  b.style.display = 'block';
}}

function esconderBanner() {{
  document.getElementById('banner').style.display = 'none';
}}

function rodar() {{
  if (_rodando) return;
  fetch('/run').then(r => r.json()).then(d => {{
    if (d.iniciou) {{
      _rodando = true;
      document.getElementById('btn-run').disabled = true;
      banner('🔄 Coletando stories... aguarde ~2 minutos');
      _poll = setInterval(verificar, 8000);
    }} else {{
      banner('⏳ Coleta já em andamento...');
    }}
  }}).catch(() => {{
    banner('⚠️ Servidor local não encontrado (inicie servidor.py)', true);
  }});
}}

function verificar() {{
  fetch('/status').then(r => r.json()).then(d => {{
    if (!d.rodando && _rodando) {{
      clearInterval(_poll);
      _rodando = false;
      banner('✅ Concluído! Recarregando...');
      setTimeout(() => {{ sessionStorage.setItem('auto_reload','1'); location.reload(); }}, 1500);
    }}
  }}).catch(() => {{ clearInterval(_poll); }});
}}

// Ao abrir/recarregar a página:
// - F5 manual → nova coleta
// - reload automático pós-coleta → só exibir dados (sem novo run)
window.addEventListener('load', () => {{
  const foiAutoReload = sessionStorage.getItem('auto_reload');
  sessionStorage.removeItem('auto_reload');
  if (foiAutoReload) return;  // reload após coleta: não disparar de novo

  fetch('/run').then(r => r.json()).then(d => {{
    _rodando = true;
    document.getElementById('btn-run').disabled = true;
    if (d.iniciou) {{
      banner('🔄 Coletando stories... aguarde ~2 minutos');
    }} else {{
      banner('⏳ Coleta já em andamento... aguarde');
    }}
    _poll = setInterval(verificar, 8000);
  }}).catch(() => {{
    // Servidor local nao disponivel — apenas exibir dados existentes
  }});
}});
</script>
</body>
</html>"""
    (JHOW_DIR / "index.html").write_text(html, encoding="utf-8")
    print("  Index atualizado: C:/jhow/index.html")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    agora = datetime.now()
    timestamp = agora.strftime("%d/%m/%Y %H:%M")
    ts        = agora.strftime("%d-%m-%Y_%Hh%M")
    run_dir   = JHOW_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print(f"  Monitor de Concorrentes - {timestamp}")
    print("=" * 50)

    usuario, senha = carregar_credenciais()
    if not usuario:
        print("  ERRO: credenciais nao encontradas em .env")
        return

    from playwright.sync_api import sync_playwright

    resultados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 430, "height": 932},
            user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
            locale="pt-BR",
            has_touch=True,
        )
        page = context.new_page()

        # Login
        sessao_ok = restaurar_sessao(context)
        if sessao_ok:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            try:
                if "login" in page.url or page.locator("input[name='username']").is_visible(timeout=2000):
                    sessao_ok = False
            except Exception:
                sessao_ok = False

        if not sessao_ok:
            if not fazer_login(page, usuario, senha):
                browser.close()
                return
            salvar_sessao(context)
        else:
            # Sessao restaurada — salvar cookies.txt para yt-dlp
            salvar_sessao(context)

        print("\n  Coletando Stories...")
        print("-" * 40)

        for nome, username in CONCORRENTES.items():
            # 1. Playwright com interceptacao de rede (foto .jpg + video screenshot + fallback)
            stories = capturar_stories_instagram(page, username, nome, run_dir)

            # 2. Fallback final: instanonimo
            if not stories:
                stories = capturar_stories_instanonimo(page, username, nome, run_dir)

            # 3. Posts do feed + screenshot do perfil
            posts, screenshot = capturar_posts(page, username, nome, run_dir)

            resultados.append({
                "username":   username,
                "nome":       nome,
                "stories":    stories,
                "posts":      posts,
                "screenshot": screenshot,
            })

        browser.close()

    # Gerar relatorio dentro do run_dir (paths relativos funcionam corretamente)
    relatorio_path = run_dir / "relatorio.html"
    relatorio_path.write_text(gerar_html(resultados, timestamp), encoding="utf-8")

    # ultimo.html = redirect para o relatorio atual (nao copia — paths relativos ficariam errados)
    (JHOW_DIR / "ultimo.html").write_text(
        f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
        f'<meta http-equiv="refresh" content="0; url={ts}/relatorio.html">'
        f'</head><body></body></html>',
        encoding="utf-8"
    )

    ultimo = str(relatorio_path)
    print(f"\n  Relatorio: {ultimo}")

    total_s = sum(len(r["stories"]) for r in resultados)
    total_p = sum(len(r["posts"])   for r in resultados)
    print(f"  Total: {total_s} stories + {total_p} posts\n")

    # Atualizar index.html com todos os runs
    atualizar_index()

    # Salvar resultado.json para regeneracao posterior do ZIP
    (run_dir / "resultado.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Gerar ZIP (backup local)
    gerar_zip_netlify(run_dir, timestamp, resultados)

    # Publicar no surge.sh automaticamente
    publicar_surge(run_dir, timestamp, resultados)

    # Abrir relatorio no browser (somente Windows local, nao no CI)
    if sys.platform == "win32" and ultimo:
        subprocess.Popen(["cmd", "/c", "start", "", ultimo])


if __name__ == "__main__":
    main()
