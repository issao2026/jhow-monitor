# -*- coding: utf-8 -*-
"""
Servidor HTTP para o Monitor Jhow Motos — porta 8642.
- Serve arquivos de C:/jhow normalmente
- GET /run    -> dispara monitor.py em background (nao bloqueia)
- GET /status -> retorna JSON com estado atual
Acesso local:   http://localhost:8642
Acesso publico: via cloudflared (URL salvo em C:/jhow/tunnel_url.txt)
"""
import http.server, socketserver, os, json, subprocess, sys, threading, re, shutil
from pathlib import Path
from datetime import datetime

PASTA      = Path("C:/jhow")
PORTA      = 8642
MONITOR_PY = Path(__file__).parent / "monitor.py"
TUNNEL_FILE = PASTA / "tunnel_url.txt"
CLOUDFLARED = Path("C:/jhow/cloudflared.exe")

os.chdir(PASTA)

# Estado compartilhado entre threads
_estado = {
    "rodando":    False,
    "ultimo_run": None,
    "pid":        None,
    "tunnel_url": None,
}
_lock = threading.Lock()


def iniciar_cloudflared():
    """Lanca cloudflared tunnel e extrai o URL publico do output."""
    if not CLOUDFLARED.exists():
        print("  cloudflared.exe nao encontrado em C:/jhow — acesso remoto indisponivel")
        return

    def _run():
        proc = subprocess.Popen(
            [str(CLOUDFLARED), "tunnel", "--url", f"http://localhost:{PORTA}", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",
        )
        for line in proc.stdout:
            line = line.strip()
            m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
            if m:
                url = m.group(0)
                with _lock:
                    _estado["tunnel_url"] = url
                TUNNEL_FILE.write_text(url, encoding="utf-8")
                print(f"\n  Acesso remoto: {url}/run\n")
                break
        proc.wait()

    threading.Thread(target=_run, daemon=True).start()


def iniciar_monitor():
    """Inicia monitor.py em background se nao estiver rodando."""
    with _lock:
        if _estado["rodando"]:
            return False
        _estado["rodando"] = True
        _estado["ultimo_run"] = datetime.now().isoformat()

    def _run():
        proc = subprocess.Popen(
            [sys.executable, str(MONITOR_PY)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        with _lock:
            _estado["pid"] = proc.pid
        proc.wait()
        with _lock:
            _estado["rodando"] = False
            _estado["pid"]     = None

    threading.Thread(target=_run, daemon=True).start()
    return True


class Handler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/run", "/run/"):
            iniciou = iniciar_monitor()
            body = json.dumps({
                "ok":      True,
                "iniciou": iniciou,
                "estado":  _estado.copy(),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        elif self.path in ("/status", "/status/"):
            with _lock:
                estado = _estado.copy()
            body = json.dumps(estado).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        else:
            super().do_GET()

    def log_message(self, format, *args):
        pass  # silenciar logs


print(f"  Servidor rodando em http://localhost:{PORTA}")
print(f"  Pasta: {PASTA}")
print(f"  /run    -> dispara coleta")
print(f"  /status -> estado atual")
print(f"  Iniciando tunnel cloudflared...")

iniciar_cloudflared()

print(f"  Ctrl+C para parar\n")

with socketserver.TCPServer(("", PORTA), Handler) as httpd:
    httpd.serve_forever()
