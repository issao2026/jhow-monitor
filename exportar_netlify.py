# -*- coding: utf-8 -*-
"""
Gera C:\jhow\para_netlify.zip — arraste no site Netlify para publicar.
Uso: python exportar_netlify.py
"""
import base64, re, io, zipfile, subprocess
from pathlib import Path
from datetime import datetime

JHOW_DIR = Path("C:/jhow")

def img_base64(path: Path) -> str:
    ext  = path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"

def embed_imagens(html: str, run_dir: Path) -> str:
    def sub(m):
        src     = m.group(1)
        caminho = run_dir / src
        if caminho.exists() and caminho.stat().st_size > 0:
            return f'src="{img_base64(caminho)}"'
        return m.group(0)
    return re.sub(r'src="([^"]+\.(png|jpg|jpeg))"', sub, html)

def main():
    # Encontrar o run mais recente
    runs = sorted(
        [d for d in JHOW_DIR.iterdir() if d.is_dir() and (d / "relatorio.html").exists()],
        key=lambda d: d.stat().st_mtime,
        reverse=True
    )
    if not runs:
        print("Nenhum relatorio encontrado em C:\\jhow")
        return

    run_dir = runs[0]
    print(f"Usando: {run_dir.name}")

    # Gerar relatorio standalone (imagens embutidas)
    relatorio_html = (run_dir / "relatorio.html").read_text(encoding="utf-8")
    relatorio_standalone = embed_imagens(relatorio_html, run_dir)

    # Index — usa links relativos para os outros runs (so funciona localmente)
    # Para Netlify: gerar index simples que redireciona para relatorio.html
    index_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=relatorio.html">
<title>Monitor Jhow Motos</title>
</head>
<body>
<p>Redirecionando... <a href="relatorio.html">clique aqui</a></p>
</body>
</html>"""

    # Criar ZIP
    saida = JHOW_DIR / "para_netlify.zip"
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html",     index_html)
        zf.writestr("relatorio.html", relatorio_standalone)

    tamanho_mb = saida.stat().st_size / 1_048_576
    print(f"ZIP criado: {saida}  ({tamanho_mb:.1f} MB)")
    print()
    print("Proximos passos:")
    print("  1. Abra  https://app.netlify.com/sites/jhow-analise/deploys")
    print("  2. Arraste o arquivo ZIP para a area de deploy")
    print("  3. Aguarde ~30s e o link estara disponivel")
    print()

    # Abrir a pasta C:\jhow no Explorer
    subprocess.Popen(["explorer", str(JHOW_DIR)])

if __name__ == "__main__":
    main()
