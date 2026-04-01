"""
CODEY-V2 GUI Server  —  uses only aiohttp (already in requirements.txt)
Run:  python gui/server.py [port]
Then: open http://localhost:8888 in your browser
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Set

from aiohttp import web, WSMsgType

CODEY_DIR = Path(__file__).parent.parent
GUI_DIR   = Path(__file__).parent

# ─── ANSI / metric parsers ────────────────────────────────────────────────────

ANSI_RE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\r')
TPS_RE  = re.compile(r'([\d]+\.?[\d]*)\s*t/s')
CTX_RE  = re.compile(r'(\d{2,})/(\d{4,})')


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub('', text)


def parse_tps(text: str) -> Optional[float]:
    m = TPS_RE.search(text)
    return float(m.group(1)) if m else None


def parse_ctx(text: str) -> Optional[Dict]:
    for m in CTX_RE.finditer(text):
        used, total = int(m.group(1)), int(m.group(2))
        if 1000 <= total <= 200_000:
            return {'ctx_used': used, 'ctx_max': total}
    return None


# ─── System metrics ───────────────────────────────────────────────────────────

async def get_ram() -> Dict:
    try:
        data: Dict[str, int] = {}
        with open('/proc/meminfo') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    data[parts[0].rstrip(':')] = int(parts[1]) * 1024
        total     = data.get('MemTotal', 0)
        available = data.get('MemAvailable', 0)
        return {'used': total - available, 'total': total}
    except Exception:
        return {'used': 0, 'total': 1}


async def probe_port(port: int) -> bool:
    """Check whether a llama-server is answering on the given port."""
    import aiohttp as _aio
    for path in ('/health', '/v1/models'):
        try:
            async with _aio.ClientSession() as s:
                async with s.get(
                    f'http://127.0.0.1:{port}{path}',
                    timeout=_aio.ClientTimeout(total=2),
                ) as resp:
                    if resp.status < 500:
                        return True
        except Exception:
            pass
    return False


async def get_model_status() -> Dict:
    backend   = os.environ.get('CODEY_BACKEND',   'local')
    backend_p = os.environ.get('CODEY_BACKEND_P', backend)

    async def maybe_probe(port: int, be: str) -> bool:
        return (await probe_port(port)) if be == 'local' else False

    a_ok, p_ok, e_ok = await asyncio.gather(
        maybe_probe(8080, backend),
        maybe_probe(8081, backend_p),
        probe_port(8082),
    )

    def info(ok: bool, name: str, port: int, be: str) -> Dict:
        if be != 'local':
            return {'name': name, 'status': 'remote', 'backend': be, 'port': port}
        return {'name': name,
                'status': 'online' if ok else 'offline',
                'backend': 'local', 'port': port}

    return {
        'agent':   info(a_ok, 'Qwen2.5-Coder-7B',  8080, backend),
        'planner': info(p_ok, 'Qwen2.5-0.5B',       8081, backend_p),
        'embed':   info(e_ok, 'nomic-embed-text',    8082, 'local'),
    }


# ─── WebSocket hub ────────────────────────────────────────────────────────────

clients: Set[web.WebSocketResponse] = set()


async def broadcast(msg: dict) -> None:
    payload = json.dumps(msg)
    dead: Set[web.WebSocketResponse] = set()
    for ws in list(clients):
        try:
            await ws.send_str(payload)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


# ─── Codey task runner ────────────────────────────────────────────────────────

active_proc: Optional[asyncio.subprocess.Process] = None


async def run_codey(prompt: str) -> None:
    global active_proc

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    try:
        active_proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(CODEY_DIR / 'main.py'),
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CODEY_DIR),
            env=env,
        )

        await broadcast({'type': 'task_start'})

        last_tps: Optional[float] = None
        last_ctx: Optional[Dict]  = None

        async for raw_line in active_proc.stdout:
            raw   = raw_line.decode('utf-8', errors='replace')
            clean = strip_ansi(raw).rstrip('\n').rstrip()
            if not clean.strip():
                continue

            tps = parse_tps(clean)
            ctx = parse_ctx(clean)
            if tps is not None: last_tps = tps
            if ctx:              last_ctx = ctx

            msg: Dict = {'type': 'output', 'text': clean}
            if tps is not None: msg['tps'] = tps
            if ctx:             msg.update(ctx)
            await broadcast(msg)

        await active_proc.wait()

        done: Dict = {'type': 'task_done'}
        if last_tps is not None: done['tps'] = last_tps
        if last_ctx:             done.update(last_ctx)
        await broadcast(done)

    except Exception as exc:
        await broadcast({'type': 'error', 'text': str(exc)})
    finally:
        active_proc = None


# ─── Background metrics loop ──────────────────────────────────────────────────

async def metrics_loop() -> None:
    while True:
        try:
            ram, models = await asyncio.gather(get_ram(), get_model_status())
            await broadcast({'type': 'metrics', 'ram': ram, 'models': models})
        except Exception:
            pass
        await asyncio.sleep(5)


# ─── HTTP routes ──────────────────────────────────────────────────────────────

async def handle_index(request: web.Request) -> web.Response:
    html = (GUI_DIR / 'index.html').read_text(encoding='utf-8')
    return web.Response(text=html, content_type='text/html')


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    clients.add(ws)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue
                kind = data.get('type')
                if kind == 'command':
                    prompt = data.get('prompt', '').strip()
                    if prompt and active_proc is None:
                        asyncio.create_task(run_codey(prompt))
                elif kind == 'cancel':
                    if active_proc:
                        try: active_proc.terminate()
                        except Exception: pass
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        clients.discard(ws)

    return ws


# ─── App factory & startup ────────────────────────────────────────────────────

async def on_startup(app: web.Application) -> None:
    asyncio.create_task(metrics_loop())


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/ws', handle_ws)
    app.on_startup.append(on_startup)
    return app


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get('CODEY_GUI_PORT', '8888'))
    host = os.environ.get('CODEY_GUI_HOST', '0.0.0.0')
    print(f'\n  CODEY-V2 GUI  →  http://localhost:{port}\n')
    web.run_app(make_app(), host=host, port=port, print=lambda *_: None)
