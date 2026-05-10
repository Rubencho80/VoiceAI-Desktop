#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rubencho AI
Asistente de voz con IA local (Ollama) + Ejecución de comandos CMD
"""

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, filedialog
import threading
import queue
import json
import os
import sys
import re
import platform
import math
import time
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Tuple

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import speech_recognition as sr
    HAS_SR = True
except ImportError:
    HAS_SR = False

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    import pyttsx3
    HAS_PYTTSX3 = True
except ImportError:
    HAS_PYTTSX3 = False

try:
    from gtts import gTTS
    import io
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False

# ── Global TTS mute flag ──────────────────────────────────────────────────────
_TTS_MUTED: bool = False


# ══════════════════════════════════════════════════════════════════════════════
#  MÓDULO CMD – Ejecución de comandos del sistema
# ══════════════════════════════════════════════════════════════════════════════

# Tiempo máximo (segundos) que puede tardar un comando antes de cancelarse
CMD_TIMEOUT: int = 15

# Máximo de caracteres de salida que se devuelven a la IA
CMD_MAX_OUTPUT: int = 3000

# Si True, guarda cada comando ejecutado en ~/.voiceai/cmd_log.txt
CMD_LOG_ENABLED: bool = True

# Lista negra: estos comandos NUNCA se ejecutarán, independientemente de la config
CMD_BLOCKED: list = [
    "rm", "rmdir", "del", "rd", "format",
    "shutdown", "reboot", "halt", "poweroff",
    "sudo", "su", "runas",
    "reg",
]

# Patrón que detecta bloques <CMD>...</CMD> en la respuesta de la IA
_CMD_PATTERN = re.compile(r"<CMD>(.*?)</CMD>", re.DOTALL | re.IGNORECASE)

# Instrucciones que se añaden al system prompt cuando CMD está activado
_CMD_SYSTEM_ADDON = """
─── CAPACIDAD DE EJECUCIÓN DE COMANDOS ──────────────────────────────────────
Puedes ejecutar comandos reales en el sistema operativo del usuario.
Para hacerlo, incluye el comando en una etiqueta especial:

    <CMD>comando aquí</CMD>

REGLAS:
1. Usa <CMD>...</CMD> SOLO cuando sea necesario para obtener información
   real del sistema o realizar una tarea concreta pedida por el usuario.
2. Escribe UN SOLO bloque <CMD> por respuesta. Encadena con && si necesitas varios pasos.
3. Cuando recibas el resultado entre <RESULTADO>...</RESULTADO>, analízalo
   y responde al usuario de forma clara y natural. No incluyas más <CMD> en esa respuesta.
4. Nunca inventes resultados. Si el comando falla, explica el error con calma.
5. Antes del bloque <CMD>, indica brevemente qué vas a hacer.
6. NUNCA ejecutes comandos destructivos (borrar masivamente, formatear).

Ejemplos:
- "¿Cuánta RAM libre tengo?"
  → "Voy a consultar la memoria del sistema."
    <CMD>systeminfo | findstr /C:"Memoria física disponible"</CMD>

- "¿Cuál es mi IP local?"
  → "Consulto la configuración de red."
    <CMD>ipconfig</CMD>

- "¿Qué procesos consumen más CPU?"
  → "Reviso los procesos activos."
    <CMD>tasklist /fo list | findstr /i "nombre imagen uso mem"</CMD>

- "¿Qué archivos hay en el escritorio?"
  → "Listo el escritorio."
    <CMD>dir "%USERPROFILE%\\Desktop"</CMD>

- "Crea la carpeta Pruebas en el escritorio"
  → "Creo la carpeta."
    <CMD>mkdir "%USERPROFILE%\\Desktop\\Pruebas"</CMD>
─────────────────────────────────────────────────────────────────────────────
"""


def _cmd_log(cmd: str, output: str):
    """Registra el comando ejecutado en el log CMD."""
    if not CMD_LOG_ENABLED:
        return
    try:
        log_dir = Path.home() / ".voiceai"
        log_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_dir / "cmd_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] CMD: {cmd}\nOUT:\n{output}\n{'─'*50}\n")
    except Exception:
        pass


def _cmd_is_allowed(cmd: str) -> Tuple[bool, str]:
    """Comprueba si el comando está permitido. Devuelve (ok, motivo)."""
    tokens = cmd.strip().split()
    if not tokens:
        return False, "Comando vacío."
    root = tokens[0].lower().replace(".exe", "")
    for blocked in CMD_BLOCKED:
        if root == blocked.lower():
            return False, f"Comando '{blocked}' bloqueado por seguridad."
    return True, ""


def execute_command(cmd: str) -> str:
    """
    Ejecuta un comando de shell y devuelve su salida como string.
    Aplica lista negra, timeout y límite de caracteres.
    """
    cmd = cmd.strip()
    if not cmd:
        return "⚠️ Comando vacío."

    ok, reason = _cmd_is_allowed(cmd)
    if not ok:
        return f"🚫 Ejecución denegada: {reason}"

    try:
        if platform.system() == "Windows":
            proc = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, encoding="cp850", errors="replace",
                timeout=CMD_TIMEOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=CMD_TIMEOUT,
            )

        out = ""
        if proc.stdout:
            out += proc.stdout
        if proc.stderr:
            out += ("\n[STDERR]\n" if proc.stdout else "") + proc.stderr
        out = out.strip() or "(Sin salida — comando ejecutado sin errores)"

        if len(out) > CMD_MAX_OUTPUT:
            out = out[:CMD_MAX_OUTPUT] + f"\n… [truncado a {CMD_MAX_OUTPUT} chars]"

        _cmd_log(cmd, out)
        return out

    except subprocess.TimeoutExpired:
        msg = f"⏱️ Timeout: el comando superó {CMD_TIMEOUT}s y fue cancelado."
        _cmd_log(cmd, msg)
        return msg
    except FileNotFoundError:
        msg = f"❌ Comando no encontrado: '{cmd.split()[0]}'"
        _cmd_log(cmd, msg)
        return msg
    except Exception as e:
        msg = f"❌ Error al ejecutar: {e}"
        _cmd_log(cmd, msg)
        return msg


# ── Patrones de etiquetas especiales ─────────────────────────────────────────
_SEARCH_PATTERN = re.compile(r"<SEARCH>(.*?)</SEARCH>", re.DOTALL | re.IGNORECASE)
_FETCH_PATTERN  = re.compile(r"<FETCH>(.*?)</FETCH>",  re.DOTALL | re.IGNORECASE)

# ── Instrucciones adicionales para SEARCH/FETCH (se inyectan al addon CMD) ───
_WEB_SYSTEM_ADDON = """
─── BÚSQUEDA EN INTERNET (sin API, gratis) ───────────────────────────────────
También puedes buscar en internet y leer páginas web usando estas etiquetas:

    <SEARCH>tu consulta aquí</SEARCH>    → Busca en DuckDuckGo y devuelve resultados
    <FETCH>https://url.com</FETCH>       → Descarga y lee el contenido de esa URL

CUÁNDO USARLAS:
• Usa <SEARCH> cuando el usuario pregunte algo que requiera información actual,
  noticias, precios, datos recientes o que no tengas en tu contexto.
• Usa <FETCH> después de un <SEARCH> si necesitas leer el contenido completo
  de uno de los resultados para responder con más detalle.
• NUNCA hagas SEARCH o FETCH si ya tienes la información suficiente en contexto.
• Tras recibir <RESULTADO_WEB>...</RESULTADO_WEB>, sintetiza y responde al usuario.

Ejemplos:
- "¿Cuál es el precio del Bitcoin hoy?"
  → <SEARCH>precio Bitcoin hoy EUR</SEARCH>

- "¿Qué ha pasado hoy en las noticias?"
  → <SEARCH>noticias hoy España</SEARCH>

- "Investiga las características del iPhone 16"
  → <SEARCH>iPhone 16 características especificaciones</SEARCH>

- "¿Qué dice esta página?" + URL
  → <FETCH>https://esa-url.com</FETCH>
─────────────────────────────────────────────────────────────────────────────
"""


class _DDGParser(HTMLParser):
    """Parser HTML mínimo para extraer resultados de DuckDuckGo HTML."""
    def __init__(self):
        super().__init__()
        self.results: list = []
        self._cur: dict    = {}
        self._in_title     = False
        self._in_snippet   = False
        self._in_url       = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._cur   = {"title": "", "url": a.get("href",""), "snippet": ""}
            self._in_title = True
        elif tag == "a" and "result__url" in cls:
            self._in_url = True
        elif tag == "div" and "result__snippet" in cls:
            self._in_snippet = True

    def handle_endtag(self, tag):
        if tag == "a":
            if self._in_title:
                self._in_title = False
                if self._cur.get("title"):
                    pass   # keep collecting snippet
            if self._in_url:
                self._in_url = False
        if tag == "div" and self._in_snippet:
            self._in_snippet = False
            if self._cur.get("title"):
                self.results.append(dict(self._cur))
                self._cur = {}

    def handle_data(self, data):
        if self._in_title:
            self._cur["title"] += data
        elif self._in_url:
            self._cur["url"] = data.strip()
        elif self._in_snippet:
            self._cur["snippet"] += data


def web_search(query: str, max_results: int = 5) -> str:
    """
    Busca en DuckDuckGo HTML (sin API, sin clave) y devuelve los resultados
    como texto para que la IA los analice.
    """
    query = query.strip()
    if not query:
        return "⚠️ Consulta vacía."
    try:
        url  = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req  = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/120 Safari/537.36"),
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        parser = _DDGParser()
        parser.feed(html)
        items  = parser.results[:max_results]

        if not items:
            # Fallback: extracción con regex si el parser no encontró nada
            titles   = re.findall(r'class="result__a"[^>]*>([^<]+)<', html)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</[^>]+>',
                                   html, re.DOTALL)
            urls     = re.findall(r'uddg=([^&"]+)', html)
            for i in range(min(max_results, len(titles))):
                items.append({
                    "title":   re.sub(r"<[^>]+>","",titles[i]).strip(),
                    "url":     urllib.parse.unquote(urls[i]) if i < len(urls) else "",
                    "snippet": re.sub(r"<[^>]+>","",snippets[i]).strip() if i < len(snippets) else "",
                })

        if not items:
            return f"No se encontraron resultados para: {query}"

        lines = [f"🔍 Resultados de búsqueda para: «{query}»\n"]
        for n, r in enumerate(items, 1):
            lines.append(f"{n}. {r.get('title','Sin título')}")
            if r.get('url'):
                lines.append(f"   🔗 {r['url']}")
            if r.get('snippet'):
                lines.append(f"   {r['snippet'].strip()}")
            lines.append("")
        return "\n".join(lines).strip()

    except Exception as e:
        return f"❌ Error al buscar: {e}"


def web_fetch(url: str, max_chars: int = 4000) -> str:
    """
    Descarga una URL y extrae su texto plano (elimina HTML/JS/CSS).
    Devuelve los primeros max_chars caracteres.
    """
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/120 Safari/537.36"),
            "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset("utf-8")
            html = raw.decode(enc, errors="replace")

        # Eliminar scripts, estilos y comentarios
        html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>",   " ", html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r"<!--.*?-->",                 " ", html, flags=re.DOTALL)
        # Convertir algunos tags a saltos de línea
        html = re.sub(r"<br\s*/?>|<p[^>]*>|</p>|<div[^>]*>|</div>|<li[^>]*>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"<h[1-6][^>]*>", "\n## ", html, flags=re.IGNORECASE)
        html = re.sub(r"</h[1-6]>",     "\n",    html, flags=re.IGNORECASE)
        # Quitar todos los demás tags
        text = re.sub(r"<[^>]+>", "", html)
        # Limpiar entidades HTML básicas
        for ent, ch in [("&amp;","&"),("&lt;","<"),("&gt;",">"),
                         ("&nbsp;"," "),("&quot;",'"'),("&#39;","'")]:
            text = text.replace(ent, ch)
        # Comprimir espacios
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        if not text:
            return "⚠️ No se pudo extraer texto de la página."
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n… [contenido truncado a {max_chars} chars]"
        return f"📄 Contenido de {url}:\n\n{text}"

    except Exception as e:
        return f"❌ Error al obtener la página: {e}"


def _build_system_prompt(base: str, cmd_enabled: bool) -> str:
    """Combina el system prompt base con fecha/hora actual e instrucciones CMD/SEARCH."""
    base = base.strip()
    now  = datetime.now().strftime("%A, %d de %B de %Y  –  %H:%M")
    date_line = f"🕐 Fecha y hora actual: {now}\n"
    if cmd_enabled:
        return date_line + base + "\n\n" + _CMD_SYSTEM_ADDON
    return date_line + base


# ── Markdown → tk.Text tags ──────────────────────────────────────────────────
def render_markdown(widget, text: str, colors: dict):
    """
    Inserta texto con formato markdown en un tk.Text widget.
    Soporta: **negrita**, *cursiva*, `código`, # Cabeceras, - listas, ---
    """
    widget.config(state='normal')
    widget.delete('1.0', 'end')

    bg      = colors.get("bg",     "#0d1117")
    fg      = colors.get("fg",     "#e2e8f0")
    acc     = colors.get("accent", "#4f8ef7")
    code_bg = colors.get("code_bg","#1e2530")

    widget.tag_configure("bold",    font=("Segoe UI", 10, "bold"), foreground=fg)
    widget.tag_configure("italic",  font=("Segoe UI", 10, "italic"), foreground=fg)
    widget.tag_configure("code",    font=("Consolas", 9), background=code_bg,
                         foreground="#7dd3fc")
    widget.tag_configure("h1",      font=("Segoe UI", 13, "bold"), foreground=acc)
    widget.tag_configure("h2",      font=("Segoe UI", 12, "bold"), foreground=acc)
    widget.tag_configure("h3",      font=("Segoe UI", 11, "bold"), foreground=acc)
    widget.tag_configure("bullet",  lmargin1=16, lmargin2=28, foreground=fg)
    widget.tag_configure("hr",      foreground=colors.get("muted","#333"))
    widget.tag_configure("normal",  foreground=fg)
    widget.tag_configure("muted",   foreground=colors.get("muted","#7d8590"))

    lines = text.split("\n")
    for line in lines:
        hm = re.match(r"^(#{1,3})\s+(.*)", line)
        if hm:
            level = len(hm.group(1))
            widget.insert("end", hm.group(2) + "\n", f"h{level}")
            continue
        if re.match(r"^-{3,}\s*$", line):
            widget.insert("end", "─" * 40 + "\n", "muted")
            continue
        bm = re.match(r"^[\-\*]\s+(.*)", line)
        if bm:
            _insert_inline(widget, "• " + bm.group(1) + "\n", "bullet", colors)
            continue
        _insert_inline(widget, line + "\n", "normal", colors)

    widget.config(state='disabled')


def _insert_inline(widget, line: str, base_tag: str, colors: dict):
    """Procesa **bold**, *italic* y `code` dentro de una línea."""
    pattern = re.compile(r"(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)")
    pos = 0
    for m in pattern.finditer(line):
        if m.start() > pos:
            widget.insert("end", line[pos:m.start()], base_tag)
        if m.group(2) is not None:
            widget.insert("end", m.group(2), "bold")
        elif m.group(3) is not None:
            widget.insert("end", m.group(3), "italic")
        elif m.group(4) is not None:
            widget.insert("end", m.group(4), "code")
        pos = m.end()
    if pos < len(line):
        widget.insert("end", line[pos:], base_tag)


# ── Config ────────────────────────────────────────────────────────────────────
APP_DIR     = Path.home() / ".voiceai"
CONFIG_FILE = APP_DIR / "config.json"

DEFAULT_CONFIG = {
    "autostart":            False,
    "minimize_to_tray":     True,
    "always_on_top_popup":  True,
    "sound_feedback":       False,
    "language":             "es-ES",
    "wake_word":            "jarvis",
    "custom_wake_word":     "",
    "use_custom_wake_word": False,
    "wake_words_presets": [
        "jarvis","nova","nexus","atlas","echo",
        "computer","asistente","despierta","oye","hola"
    ],
    "speech_engine":        "google",
    "command_engine":       "whisper",
    "whisper_model":        "small",
    "whisper_device":       "cpu",
    "whisper_language":     "es",
    "vosk_model_path":      "",
    "silence_timeout":      2.5,
    "phrase_time_limit":    15.0,
    "wake_phrase_limit":    3.0,
    "pause_threshold":          1.8,
    "phrase_threshold":         0.1,
    "non_speaking_duration":    0.4,
    "dynamic_energy_threshold": True,
    "energy_threshold":         300,
    "dynamic_energy_ratio":     1.5,
    "ollama_host":          "http://localhost:11434",
    "ollama_model":         "qwen2.5:3b",
    "ollama_no_think":      True,
    "conversation_memory":  True,
    "max_history_turns":    10,
    # CMD
    "cmd_enabled":          True,
    # Orbe
    "orb_size":             54,
    "orb_opacity":          0.88,
    "orb_opacity_min":      0.45,
    "orb_x":                -1,
    "orb_y":                -1,
    "orb_visible":          True,
    # Popup
    "popup_bg":             "#0d1117",
    "popup_opacity":        0.94,
    "popup_text_color":     "#e2e8f0",
    "popup_accent":         "#4f8ef7",
    "popup_width":          480,
    "popup_height":         340,
    "popup_position":       "bottom-right",
    "popup_custom_x":       100,
    "popup_custom_y":       100,
    "popup_auto_close":     30,
    "show_transcript":      True,
    "system_prompt":        "Eres un asistente de voz útil, conciso y amable. Responde siempre en el mismo idioma que el usuario.",
    "log_enabled":          False,
    "log_file_path":        "",
    "log_load_as_memory":   False,
    "tts_enabled":          False,
    "tts_engine":           "pyttsx3",
    "tts_rate":             180,
    "tts_volume":           1.0,
    "tts_voice_id":         "",
    "continuous_conv":              True,
    "continuous_timeout":           8.0,
    "continuous_stop_word":         "para",
    # Cerrar popup automáticamente tras TTS
    "popup_close_on_tts_end":       False,
    "popup_close_on_tts_end_delay": 2,
}


def load_config() -> dict:
    APP_DIR.mkdir(exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    APP_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def lerp_color(c1: str, c2: str, t: float) -> str:
    def h(c): return int(c[1:3],16), int(c[3:5],16), int(c[5:7],16)
    r1,g1,b1 = h(c1); r2,g2,b2 = h(c2)
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


# ── Orb Window ────────────────────────────────────────────────────────────────
class OrbWindow(tk.Toplevel):
    COLOR_A = "#2979ff"
    COLOR_B = "#9c27b0"

    def __init__(self, root, config: dict, on_open_settings, on_listen_now):
        super().__init__(root)
        self._cfg         = config
        self._on_settings = on_open_settings
        self._on_listen   = on_listen_now
        self._state       = "idle"
        self._phase       = 0.0
        self._alive       = True
        self._drag_offset = (0, 0)

        sz        = max(24, int(config.get("orb_size", 54)))
        self._sz  = sz

        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.configure(bg="black")
        try:    self.wm_attributes("-transparentcolor", "black")
        except Exception: pass
        try:    self.wm_attributes("-alpha", float(config.get("orb_opacity", 0.88)))
        except Exception: pass

        self._cv = tk.Canvas(self, width=sz, height=sz,
                              bg="black", highlightthickness=0)
        self._cv.pack()

        self._position_orb()

        self._cv.bind("<ButtonPress-1>",   self._drag_start)
        self._cv.bind("<B1-Motion>",       self._drag_move)
        self._cv.bind("<ButtonRelease-1>", self._drag_end)
        self._cv.bind("<Button-3>",        self._show_menu)

        self.withdraw()
        self._animate()

    def _position_orb(self):
        sz = self._sz
        ox = int(self._cfg.get("orb_x", -1))
        oy = int(self._cfg.get("orb_y", -1))
        if ox < 0 or oy < 0:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            ox = sw - sz - 28
            oy = sh - sz - 64
        self.geometry(f"{sz}x{sz}+{ox}+{oy}")

    def _animate(self):
        if not self._alive:
            return
        self._phase += 0.022
        self._draw()
        if self._alive:
            self.after(30, self._animate)

    def _draw(self):
        c  = self._cv
        c.delete("all")
        sz  = self._sz
        pad = 4
        st  = self._state
        ph  = self._phase

        if st == "continuous":
            pulse = 0.85 + 0.15 * math.sin(ph * 3)
            r2    = int((sz / 2 - pad) * pulse)
            cx    = sz // 2
            c.create_oval(cx-r2, cx-r2, cx+r2, cx+r2, fill="#00c853", outline="")
        elif st == "thinking":
            pulse = 0.75 + 0.25 * math.sin(ph * 4)
            r2    = int((sz / 2 - pad) * pulse)
            cx    = sz // 2
            c.create_oval(cx-r2, cx-r2, cx+r2, cx+r2, fill="#ff9800", outline="")
        else:
            color = "#2979ff"
            c.create_oval(pad, pad, sz - pad, sz - pad, fill=color, outline="")

    def _drag_start(self, e):
        self._drag_offset = (e.x_root - self.winfo_x(),
                              e.y_root - self.winfo_y())

    def _drag_move(self, e):
        ox, oy = self._drag_offset
        nx, ny = e.x_root - ox, e.y_root - oy
        self.geometry(f"+{nx}+{ny}")
        self._cfg["orb_x"] = nx
        self._cfg["orb_y"] = ny

    def _drag_end(self, _e):
        save_config(self._cfg)

    def _show_menu(self, e):
        m = tk.Menu(self, tearoff=0,
                    bg="#1a1a2e", fg="#c8e6ff",
                    activebackground="#0f3460", activeforeground="white",
                    font=("Segoe UI", 10), relief='flat', bd=0)
        m.add_command(label="🎙  Escuchar ahora",  command=self._on_listen)
        m.add_separator()
        m.add_command(label="👁  Ocultar orbe",    command=self.hide_orb)
        m.add_command(label="⚙️  Configuración",   command=self._on_settings)
        m.add_separator()
        m.add_command(label="✕  Salir",
                      command=lambda: self.event_generate("<<Quit>>"))
        try:   m.tk_popup(e.x_root, e.y_root)
        finally: m.grab_release()

    def set_state(self, state: str):
        self._state = state
        if state in ("listening", "thinking", "continuous"):
            self.deiconify()
        else:
            self.withdraw()

    def hide_orb(self):
        self.withdraw()
        self._cfg["orb_visible"] = False
        save_config(self._cfg)

    def show_orb(self):
        self.deiconify()
        self._cfg["orb_visible"] = True
        save_config(self._cfg)

    def safe_close(self):
        self._alive = False
        try: self.destroy()
        except Exception: pass


# ── Response Popup ────────────────────────────────────────────────────────────
class ResponsePopup(tk.Toplevel):
    RADIUS = 16

    def __init__(self, root, config: dict, transcript: str, response: str,
                 streaming: bool = False, on_send=None, on_mute=None):
        super().__init__(root)
        cfg            = config
        self._bg       = cfg.get("popup_bg",        "#0d1117")
        self._text     = cfg.get("popup_text_color", "#e2e8f0")
        self._accent   = cfg.get("popup_accent",     "#4f8ef7")
        w              = int(cfg.get("popup_width",  480))
        h              = int(cfg.get("popup_height", 340))
        opacity        = float(cfg.get("popup_opacity", 0.94))
        self._auto     = int(cfg.get("popup_auto_close", 30))
        self._paused   = False
        # Si está activado el cierre por TTS, desactivar el contador automático
        if bool(cfg.get("popup_close_on_tts_end", False)):
            self._cd = 99999   # nunca cierra solo; solo lo cerrará la señal close_popup
        else:
            self._cd = self._auto
        self._streaming= streaming
        self._rtxt     = None
        self._md_colors= {}
        self._full_buf = ""
        self._on_send  = on_send
        self._on_mute  = on_mute
        self._muted    = _TTS_MUTED   # estado inicial del icono
        self._full_response = response  # para copiar

        self.overrideredirect(True)
        self.wm_attributes("-topmost", bool(cfg.get("always_on_top_popup", True)))
        self.configure(bg="black")
        try:    self.wm_attributes("-transparentcolor", "black")
        except Exception: pass
        try:    self.wm_attributes("-alpha", opacity)
        except Exception: pass

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        pos    = cfg.get("popup_position", "bottom-right")
        pad    = 24
        if   pos == "center":       x, y = (sw-w)//2,    (sh-h)//2
        elif pos == "top-right":    x, y = sw-w-pad,      pad
        elif pos == "top-left":     x, y = pad,           pad
        elif pos == "bottom-right": x, y = sw-w-pad,      sh-h-72
        elif pos == "bottom-left":  x, y = pad,           sh-h-72
        else:
            x = int(cfg.get("popup_custom_x", 100))
            y = int(cfg.get("popup_custom_y", 100))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._pw, self._ph = w, h
        self._drag         = (0, 0)

        self._canvas = tk.Canvas(self, width=w, height=h,
                                  bg="black", highlightthickness=0)
        self._canvas.pack()

        self._draw_rounded_bg()
        self._build_content(transcript, response)

        self.bind("<Enter>", lambda _: setattr(self, "_paused", True))
        self.bind("<Leave>", lambda _: setattr(self, "_paused", False))
        self._canvas.bind("<ButtonPress-1>", self._ds)
        self._canvas.bind("<B1-Motion>",     self._dm)

        self._tick()

    def _draw_rounded_bg(self):
        c  = self._canvas
        w, h, r = self._pw, self._ph, self.RADIUS
        bg = self._bg

        c.create_arc(  0,     0,   r*2,   r*2, start=90,  extent=90, fill=bg, outline=bg)
        c.create_arc(w-r*2,   0,   w,     r*2, start=0,   extent=90, fill=bg, outline=bg)
        c.create_arc(  0,   h-r*2, r*2,   h,   start=180, extent=90, fill=bg, outline=bg)
        c.create_arc(w-r*2, h-r*2, w,     h,   start=270, extent=90, fill=bg, outline=bg)
        c.create_rectangle(r,   0,  w-r,  h,   fill=bg, outline=bg)
        c.create_rectangle(0,   r,  w,  h-r,   fill=bg, outline=bg)

        accent = self._accent
        c.create_arc(  0,  0, r*2, r*2, start=90, extent=90, fill=accent, outline=accent)
        c.create_arc(w-r*2, 0, w,  r*2, start=0,  extent=90, fill=accent, outline=accent)
        c.create_rectangle(r, 0, w-r, 3, fill=accent, outline=accent)

    def _build_content(self, transcript: str, response: str):
        c    = self._canvas
        w    = int(self._pw)
        h    = int(self._ph)
        bg   = self._bg
        acc  = self._accent
        txt  = self._text
        sub  = lerp_color(self._bg, self._text, 0.4)
        panel= lerp_color(bg, "#ffffff", 0.06)   # fondo del input
        PAD  = 18

        # ── Botón cerrar ──────────────────────────────────────────────────────
        close = tk.Label(c, text="×", bg=bg, fg=sub,
                          font=("Segoe UI", 14), cursor="hand2")
        close.place(x=w - PAD - 8, y=6)
        close.bind("<Button-1>", lambda _: self.destroy())
        close.bind("<Enter>",    lambda _: close.config(fg=txt))
        close.bind("<Leave>",    lambda _: close.config(fg=sub))

        # ── Botón silenciar ───────────────────────────────────────────────────
        mute_icon  = "🔇" if self._muted else "🔊"
        mute_color = "#ff5566" if self._muted else sub
        self._mute_lbl = tk.Label(c, text=mute_icon, bg=bg, fg=mute_color,
                                   font=("Segoe UI", 11), cursor="hand2")
        self._mute_lbl.place(x=w - PAD - 34, y=6)

        def toggle_mute(_e=None):
            if self._on_mute:
                self._muted = self._on_mute()
            else:
                global _TTS_MUTED
                _TTS_MUTED = not _TTS_MUTED
                self._muted = _TTS_MUTED
            icon  = "🔇" if self._muted else "🔊"
            color = "#ff5566" if self._muted else sub
            try: self._mute_lbl.config(text=icon, fg=color)
            except Exception: pass

        self._mute_lbl.bind("<Button-1>", toggle_mute)

        y = int(PAD) + 2

        # ── Badge ─────────────────────────────────────────────────────────────
        badge = tk.Label(c, text=" 🐢  Rubencho AI ", bg=acc, fg="white",
                          font=("Segoe UI", 8, "bold"), padx=6, pady=2)
        badge.place(x=PAD, y=y)
        y += 26

        # ── Transcripción ─────────────────────────────────────────────────────
        if transcript:
            tl = tk.Label(c, text=f"\u201c{transcript}\u201d",
                           bg=bg, fg=sub,
                           font=("Segoe UI", 9, "italic"),
                           wraplength=w - PAD * 2 - 20,
                           justify='left', anchor='w')
            tl.place(x=PAD, y=y, width=w - PAD * 2 - 20)
            y += 20 + 8

        sep_color = lerp_color(bg, acc, 0.2)
        tk.Frame(c, bg=sep_color, height=1).place(x=PAD, y=y, width=w - PAD * 2)
        y += 10

        # ── Área de respuesta ─────────────────────────────────────────────────
        # Reservamos espacio: 24px (footer) + 36px (input) + 4px (gap) = 64px
        FOOTER_H = 64
        avail_h  = max(60, int(h) - int(y) - FOOTER_H)

        vsb = tk.Scrollbar(c, orient='vertical',
                           bg=lerp_color(bg, "#ffffff", 0.07),
                           troughcolor=bg, relief='flat', bd=0, width=5)
        rtxt = tk.Text(c, bg=bg, fg=txt,
                        font=("Segoe UI", 10), wrap='word',
                        relief='flat', bd=0, padx=0, pady=2,
                        yscrollcommand=vsb.set,
                        cursor="arrow",
                        selectbackground=lerp_color(bg, acc, 0.35),
                        highlightthickness=0)
        vsb.config(command=rtxt.yview)
        vsb.place(x=w - PAD - 3, y=y, height=avail_h)
        rtxt.place(x=PAD, y=y, width=w - PAD * 2 - 10, height=avail_h)

        md_colors = {
            "bg":      bg,
            "fg":      txt,
            "accent":  acc,
            "code_bg": lerp_color(bg, "#2979ff", 0.12),
            "muted":   lerp_color(bg, txt, 0.35),
        }
        self._rtxt     = rtxt
        self._md_colors= md_colors

        if self._streaming:
            rtxt.config(state="normal")
        else:
            render_markdown(rtxt, str(response), md_colors)

        # ── Footer: contador + copiar ─────────────────────────────────────────
        footer_y = h - FOOTER_H

        self._cd_lbl = tk.Label(c, text=f"{self._cd}s",
                                 bg=bg, fg=sub, font=("Segoe UI", 8))
        self._cd_lbl.place(x=PAD, y=footer_y + 4)

        full_resp_ref = [response]   # lista mutable para captura en closure

        def copy_it(_e=None):
            try:
                self.clipboard_clear()
                self.clipboard_append(self._full_response or full_resp_ref[0])
                cb.config(text="✓")
                self.after(1500, lambda: cb.config(text="⎘"))
            except Exception: pass

        cb = tk.Label(c, text="⎘", bg=bg, fg=sub,
                       font=("Segoe UI", 10), cursor="hand2")
        cb.place(x=w - PAD - 16, y=footer_y + 2)
        cb.bind("<Button-1>", copy_it)
        cb.bind("<Enter>",    lambda _: cb.config(fg=acc))
        cb.bind("<Leave>",    lambda _: cb.config(fg=sub))

        # ── Input de texto ────────────────────────────────────────────────────
        input_y = footer_y + 26
        input_h = 28
        btn_w   = 32

        input_bg = lerp_color(bg, "#ffffff", 0.09)
        input_frame = tk.Frame(c, bg=input_bg,
                                highlightbackground=lerp_color(bg, acc, 0.3),
                                highlightthickness=1, bd=0)
        input_frame.place(x=PAD, y=input_y,
                          width=w - PAD * 2 - btn_w - 4, height=input_h)

        entry_var = tk.StringVar()
        entry = tk.Entry(input_frame, textvariable=entry_var,
                         bg=input_bg, fg=txt,
                         font=("Segoe UI", 9), relief='flat', bd=4,
                         insertbackground=acc,
                         highlightthickness=0)
        entry.pack(fill='both', expand=True)
        entry.insert(0, "Escribe un mensaje…")
        entry.config(fg=sub)

        def _on_focus_in(_e):
            if entry_var.get() == "Escribe un mensaje…":
                entry.delete(0, 'end')
                entry.config(fg=txt)
        def _on_focus_out(_e):
            if not entry_var.get():
                entry.insert(0, "Escribe un mensaje…")
                entry.config(fg=sub)

        entry.bind("<FocusIn>",  _on_focus_in)
        entry.bind("<FocusOut>", _on_focus_out)

        def _send(_e=None):
            text = entry_var.get().strip()
            if not text or text == "Escribe un mensaje…":
                return
            entry.delete(0, 'end')
            entry.config(fg=sub)
            entry.insert(0, "Escribe un mensaje…")
            if self._on_send:
                self._on_send(text)

        entry.bind("<Return>", _send)
        # Evitar que el clic en entry pause el contador accidentalmente
        entry.bind("<Button-1>", lambda e: (entry.focus_set(), "break"))

        send_btn = tk.Label(c, text="➤", bg=acc, fg="white",
                             font=("Segoe UI", 11, "bold"), cursor="hand2",
                             width=2)
        send_btn.place(x=w - PAD - btn_w + 2, y=input_y, height=input_h)
        send_btn.bind("<Button-1>", _send)
        send_btn.bind("<Enter>",    lambda _: send_btn.config(bg=lerp_color(acc,"#ffffff",0.15)))
        send_btn.bind("<Leave>",    lambda _: send_btn.config(bg=acc))

        # Pausar el countdown cuando el usuario escribe en el entry
        entry.bind("<FocusIn>",  lambda e: (setattr(self, "_paused", True),  _on_focus_in(e)))
        entry.bind("<FocusOut>", lambda e: (setattr(self, "_paused", False), _on_focus_out(e)))

    def append_chunk(self, chunk: str):
        if self._rtxt is None:
            return
        try:
            self._full_buf += chunk
            self._full_response = self._full_buf
            self._rtxt.config(state="normal")
            self._rtxt.insert("end", chunk, "normal")
            self._rtxt.see("end")
        except Exception:
            pass

    def finalize(self, full_response: str):
        if self._rtxt is None:
            return
        try:
            self._full_response = full_response
            render_markdown(self._rtxt, full_response, self._md_colors)
            self._rtxt.see("1.0")
            self._streaming = False
        except Exception:
            pass

    def _ds(self, e):
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _dm(self, e):
        ox, oy = self._drag
        self.geometry(f"+{e.x_root-ox}+{e.y_root-oy}")

    def _tick(self):
        if not self._paused:
            self._cd -= 1
            if self._cd <= 0:
                try:   self.destroy()
                except Exception: pass
                return
            try:   self._cd_lbl.config(text=f"{self._cd}s")
            except Exception: pass
        try:   self.after(1000, self._tick)
        except Exception: pass


# ── Settings Window ───────────────────────────────────────────────────────────
class SettingsWindow(tk.Toplevel):
    C = {
        "bg":     "#0d1117",
        "panel":  "#161b22",
        "deep":   "#21262d",
        "accent": "#4f8ef7",
        "text":   "#e2e8f0",
        "muted":  "#7d8590",
    }
    LANGS = [
        ("es-ES","Español (España)"), ("es-MX","Español (México)"),
        ("es-AR","Español (Argentina)"), ("es-CO","Español (Colombia)"),
        ("en-US","English (US)"), ("en-GB","English (UK)"),
        ("fr-FR","Français"), ("de-DE","Deutsch"),
        ("it-IT","Italiano"), ("pt-BR","Português (Brasil)"),
        ("ca-ES","Català"), ("gl-ES","Galego"),
        ("ja-JP","日本語"), ("zh-CN","中文 (简体)"),
    ]

    def __init__(self, root, config: dict, on_save):
        super().__init__(root)
        self._cfg     = config.copy()
        self._on_save = on_save
        self._vars: dict = {}
        self.title("⚙️  Rubencho AI – Configuración")
        self.geometry("740x680")
        self.resizable(True, True)
        self.configure(bg=self.C["bg"])
        self.grab_set()
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"740x680+{(sw-740)//2}+{(sh-680)//2}")
        self._init_styles()
        self._build()

    def _init_styles(self):
        s = ttk.Style()
        s.theme_use('clam')
        bg, panel, deep, accent, text, muted = (
            self.C["bg"], self.C["panel"], self.C["deep"],
            self.C["accent"], self.C["text"], self.C["muted"])
        s.configure("TNotebook",     background=bg, borderwidth=0)
        s.configure("TNotebook.Tab", background=panel, foreground=muted,
                    padding=[14,7], font=("Segoe UI",10))
        s.map("TNotebook.Tab",
              background=[("selected", deep)],
              foreground=[("selected", accent)])
        for cls in ("TFrame","TLabelframe"):
            s.configure(cls, background=bg)
        s.configure("TLabelframe.Label", background=bg,
                    foreground=accent, font=("Segoe UI",10,"bold"))
        s.configure("TLabel",       background=bg, foreground=text, font=("Segoe UI",10))
        s.configure("TCheckbutton", background=bg, foreground=text, font=("Segoe UI",10))
        s.map("TCheckbutton", background=[("active", bg)])
        s.configure("TCombobox",    fieldbackground=panel, background=panel,
                    foreground=text, selectbackground=deep, font=("Segoe UI",10))

    def _build(self):
        bg, deep, accent = self.C["bg"], self.C["deep"], self.C["accent"]
        hdr = tk.Frame(self, bg=deep, height=54)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(hdr, text="⚙️   Configuración de Rubencho AI",
                 bg=deep, fg=accent,
                 font=("Segoe UI",14,"bold")).pack(side='left', padx=20)

        foot = tk.Frame(self, bg=deep, height=54)
        foot.pack(fill='x', side='bottom')
        foot.pack_propagate(False)
        tk.Button(foot, text="💾  Guardar",
                  bg=accent, fg="white",
                  font=("Segoe UI",11,"bold"),
                  relief='flat', padx=24, pady=10, cursor="hand2",
                  activebackground="#2563eb",
                  command=self._save).pack(side='right', padx=10, pady=8)
        tk.Button(foot, text="✕  Cancelar",
                  bg=self.C["panel"], fg=self.C["muted"],
                  font=("Segoe UI",10),
                  relief='flat', padx=16, pady=10, cursor="hand2",
                  activebackground=self.C["deep"],
                  command=self.destroy).pack(side='right', padx=4, pady=8)

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=12, pady=(12, 4))
        for title, builder in [
            ("  General  ",        self._tab_general),
            ("  Palabra Clave  ",  self._tab_wakeword),
            ("  Reconocimiento  ", self._tab_voice),
            ("  IA / Ollama  ",    self._tab_ai),
            ("  Orbe  ",           self._tab_orb),
            ("  Popup  ",          self._tab_popup),
            ("  Log  ",            self._tab_log),
            ("  Voz IA  ",         self._tab_tts),
        ]:
            inner = self._scrollable_tab(nb, title)
            builder(inner)

    def _scrollable_tab(self, nb: ttk.Notebook, title: str) -> tk.Frame:
        bg = self.C["bg"]
        outer = ttk.Frame(nb)
        nb.add(outer, text=title)
        canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, bd=0)
        vsb    = tk.Scrollbar(outer, orient="vertical",
                              command=canvas.yview,
                              bg=self.C["panel"],
                              troughcolor=self.C["bg"],
                              relief='flat', bd=0, width=8)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(canvas, bg=bg, padx=14, pady=10)
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def on_canvas_configure(event):
            canvas.itemconfig(win_id, width=event.width)

        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        def _on_mousewheel(event):
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>",   _on_mousewheel)
        canvas.bind_all("<Button-5>",   _on_mousewheel)
        return inner

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _v(self, key, typ='str'):
        val = self._cfg.get(key, DEFAULT_CONFIG.get(key,""))
        if   typ=='bool':   v = tk.BooleanVar(value=bool(val))
        elif typ=='int':    v = tk.IntVar(value=int(float(val)))
        elif typ=='double': v = tk.DoubleVar(value=float(val))
        else:               v = tk.StringVar(value=str(val))
        self._vars[key] = v
        return v

    def _entry(self, p, key, row, col=1, w=28):
        var = self._v(key)
        tk.Entry(p, textvariable=var,
                 bg=self.C["panel"], fg=self.C["text"],
                 font=("Segoe UI",10), relief='flat', width=w,
                 insertbackground=self.C["accent"]
                 ).grid(row=row, column=col, sticky='ew', padx=8, pady=5)
        return var

    def _check(self, p, key, text, row, col=0):
        v = self._v(key,'bool')
        ttk.Checkbutton(p, text=text, variable=v).grid(
            row=row, column=col, columnspan=2, sticky='w', padx=8, pady=5)
        return v

    def _scale(self, p, key, row, frm=0.0, to=1.0, res=0.01, col=1):
        v  = self._v(key,'double')
        fr = tk.Frame(p, bg=self.C["bg"])
        fr.grid(row=row, column=col, sticky='ew', padx=8, pady=5)
        tk.Scale(fr, variable=v, from_=frm, to=to, resolution=res,
                 orient='horizontal', bg=self.C["bg"], fg=self.C["text"],
                 troughcolor=self.C["panel"], highlightthickness=0,
                 length=200, showvalue=False).pack(side='left')
        tk.Label(fr, textvariable=v, bg=self.C["bg"], fg=self.C["accent"],
                 font=("Segoe UI",9,"bold"), width=5).pack(side='left', padx=4)
        return v

    def _color_btn(self, p, key, row, col=1):
        v    = tk.StringVar(value=self._cfg.get(key,"#4f8ef7"))
        self._vars[key] = v
        fr   = tk.Frame(p, bg=self.C["bg"])
        fr.grid(row=row, column=col, sticky='w', padx=8, pady=5)
        prev = tk.Label(fr, bg=v.get(), width=3, height=1, relief='groove', bd=2)
        prev.pack(side='left', padx=(0,6))
        tk.Entry(fr, textvariable=v, bg=self.C["panel"], fg=self.C["text"],
                 font=("Segoe UI",10), relief='flat', width=9,
                 insertbackground=self.C["accent"]).pack(side='left')
        def pick():
            res = colorchooser.askcolor(color=v.get(), parent=self)
            if res[1]: v.set(res[1]); prev.config(bg=res[1])
        def sync(*_):
            try: prev.config(bg=v.get())
            except Exception: pass
        v.trace_add('write', sync)
        tk.Button(fr, text="🎨", bg=self.C["deep"], fg="white",
                  relief='flat', cursor="hand2", command=pick, padx=4
                  ).pack(side='left', padx=4)
        return v

    def _lbl(self, p, text, row, col=0):
        ttk.Label(p, text=text).grid(row=row, column=col, sticky='w', padx=8, pady=5)

    def _info(self, p, lines):
        box = tk.Frame(p, bg=self.C["deep"], padx=12, pady=10)
        box.pack(fill='x', pady=8)
        for ln in lines:
            tk.Label(box, text=ln, bg=self.C["deep"], fg=self.C["muted"],
                     font=("Segoe UI",9), anchor='w').pack(fill='x', pady=1)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    def _tab_general(self, p):
        p.columnconfigure(1, weight=1)
        sf = ttk.LabelFrame(p, text="Sistema", padding=10)
        sf.pack(fill='x', pady=8)
        self._check(sf, "autostart",           "🚀  Iniciar con el sistema operativo", 0)
        self._check(sf, "minimize_to_tray",     "📌  Minimizar a bandeja al cerrar",    1)
        self._check(sf, "always_on_top_popup",  "🔝  Popup siempre encima",             2)
        self._check(sf, "sound_feedback",       "🔔  Pitido al detectar la palabra",    3)
        cf = ttk.LabelFrame(p, text="💬  Conversación continua", padding=10)
        cf.pack(fill='x', pady=8)
        cf.columnconfigure(1, weight=1)
        self._check(cf, "continuous_conv",
                    "🔁  Seguir escuchando tras responder (sin repetir la palabra clave)", 0)
        self._lbl(cf, "Silencio para parar (s):", 1)
        self._scale(cf, "continuous_timeout", 1, frm=2.0, to=30.0, res=0.5)
        self._lbl(cf, "Palabra de parada:", 2)
        self._entry(cf, "continuous_stop_word", 2, w=14)
        tk.Label(cf,
                 text="Di la palabra de parada para volver al modo wake word.\nEl orbe se vuelve verde mientras estás en modo continuo.",
                 bg=self.C["bg"], fg=self.C["muted"],
                 font=("Segoe UI", 8), justify='left'
                 ).grid(row=3, column=0, columnspan=2, sticky='w', padx=8, pady=4)

        lf = ttk.LabelFrame(p, text="Idioma de reconocimiento de voz", padding=10)
        lf.pack(fill='x', pady=8)
        lf.columnconfigure(1, weight=1)
        names = [f"{c}  –  {n}" for c,n in self.LANGS]
        codes = [c for c,_ in self.LANGS]
        cur   = self._cfg.get("language","es-ES")
        cur_n = next((f"{c}  –  {n}" for c,n in self.LANGS if c==cur), names[0])
        lv    = tk.StringVar(value=cur_n)
        self._vars["_lang_display"] = lv
        self._lang_codes = codes
        self._lang_names = names
        ttk.Label(lf, text="Idioma:").grid(row=0, column=0, sticky='w', padx=8, pady=5)
        ttk.Combobox(lf, textvariable=lv, values=names, state='readonly', width=38
                     ).grid(row=0, column=1, sticky='ew', padx=8, pady=5)

    def _tab_wakeword(self, p):
        p.columnconfigure(1, weight=1)
        pf = ttk.LabelFrame(p, text="Palabra de activación", padding=12)
        pf.pack(fill='x', pady=8)
        ttk.Label(pf, text="Pronuncia esta palabra para activar Rubencho AI:"
                  ).pack(anchor='w', pady=(0,10))
        cur     = self._cfg.get("wake_word","jarvis")
        wv      = tk.StringVar(value=cur)
        self._vars["wake_word"] = wv
        presets = self._cfg.get("wake_words_presets", DEFAULT_CONFIG["wake_words_presets"])
        grid    = tk.Frame(pf, bg=self.C["bg"])
        grid.pack(fill='x')
        cols = 4
        for i, word in enumerate(presets):
            tk.Radiobutton(grid, text=f"  {word.capitalize()}  ",
                           variable=wv, value=word,
                           bg=self.C["bg"], fg=self.C["text"],
                           selectcolor=self.C["deep"],
                           activebackground=self.C["bg"],
                           font=("Segoe UI",10), indicatoron=0,
                           relief='groove', padx=8, pady=5, cursor="hand2"
                           ).grid(row=i//cols, column=i%cols, padx=4, pady=4, sticky='ew')
        cf = ttk.LabelFrame(p, text="Palabra personalizada", padding=10)
        cf.pack(fill='x', pady=8)
        cf.columnconfigure(1, weight=1)
        ttk.Label(cf, text="Palabra:").grid(row=0, column=0, sticky='w', padx=8)
        self._entry(cf, "custom_wake_word", 0, w=22)
        self._check(cf, "use_custom_wake_word",
                    "Usar esta palabra en vez de la lista", 1)
        self._info(p, [
            "💡  Palabras de 2-3 sílabas con consonantes fuertes funcionan mejor",
            "💡  'Jarvis' y 'Nova' tienen el mejor equilibrio precisión/comodidad",
        ])

    def _tab_voice(self, p):
        p.columnconfigure(1, weight=1)
        ef = ttk.LabelFrame(p, text="Motor de reconocimiento", padding=12)
        ef.pack(fill='x', pady=8)
        ev = self._v("speech_engine")
        for val, txt in [
            ("google","🌐  Google Speech  (online, gratis, sin API key)"),
            ("vosk",  "💻  Vosk           (offline, sin internet)"),
        ]:
            tk.Radiobutton(ef, text=txt, variable=ev, value=val,
                           bg=self.C["bg"], fg=self.C["text"],
                           selectcolor=self.C["deep"], activebackground=self.C["bg"],
                           font=("Segoe UI",10)).pack(anchor='w', pady=4)
        vf = ttk.LabelFrame(p, text="Modelo Vosk  (solo si usas Vosk)", padding=10)
        vf.pack(fill='x', pady=8)
        vf.columnconfigure(1, weight=1)
        ttk.Label(vf, text="Carpeta:").grid(row=0, column=0, sticky='w', padx=8)
        vp = self._entry(vf, "vosk_model_path", 0, w=26)
        def browse():
            d = filedialog.askdirectory(parent=self)
            if d: vp.set(d)
        tk.Button(vf, text="📁", bg=self.C["deep"], fg="white",
                  relief='flat', cursor="hand2", command=browse
                  ).grid(row=0, column=2, padx=4)
        tk.Label(vf, text="Descarga: https://alphacephei.com/vosk/models  →  vosk-model-es-0.42",
                 bg=self.C["bg"], fg=self.C["muted"], font=("Segoe UI",9)
                 ).grid(row=1, column=0, columnspan=3, sticky='w', padx=8, pady=4)
        tf = ttk.LabelFrame(p, text="⏱  Tiempos de grabación", padding=10)
        tf.pack(fill='x', pady=6)
        tf.columnconfigure(1, weight=1)
        for i,(key,lbl,frm,to,res) in enumerate([
            ("phrase_time_limit", "Tiempo máx. escucha (s):",    5.0, 30.0, 1.0),
            ("wake_phrase_limit", "Límite frase activación (s):", 2.0,  6.0, 0.5),
            ("silence_timeout",   "Timeout si no hay voz (s):",   0.5,  8.0, 0.5),
        ]):
            self._lbl(tf, lbl, i)
            self._scale(tf, key, i, frm=frm, to=to, res=res)
        self._check(tf, "show_transcript", "Mostrar lo que dijiste en el popup", 3)

        vf2 = ttk.LabelFrame(p, text="🎤  Detección de fin de frase (VAD)", padding=10)
        vf2.pack(fill='x', pady=6)
        vf2.columnconfigure(1, weight=1)
        for i,(key,lbl,frm,to,res) in enumerate([
            ("pause_threshold",       "⭐ Pausa para terminar frase (s):", 0.5, 5.0, 0.1),
            ("phrase_threshold",      "Voz mínima para empezar (s):",      0.05, 1.0, 0.05),
            ("non_speaking_duration", "Silencio a mantener al final (s):",  0.05, 1.5, 0.05),
            ("dynamic_energy_ratio",  "Ratio voz/ambiente:",                1.0,  4.0, 0.1),
        ]):
            self._lbl(vf2, lbl, i)
            self._scale(vf2, key, i, frm=frm, to=to, res=res)

        ef2 = ttk.LabelFrame(p, text="🔊  Umbral de energía", padding=10)
        ef2.pack(fill='x', pady=6)
        ef2.columnconfigure(1, weight=1)
        self._check(ef2, "dynamic_energy_threshold",
                    "Ajustar umbral automáticamente (recomendado)", 0)
        self._lbl(ef2, "Umbral manual:", 1)
        self._scale(ef2, "energy_threshold", 1, frm=50, to=4000, res=50)

        cf = ttk.LabelFrame(p, text="🤖  Motor de transcripción del comando", padding=12)
        cf.pack(fill='x', pady=6)
        cf.columnconfigure(1, weight=1)
        cv = self._v("command_engine")
        for val, txt2 in [
            ("whisper","⭐  faster-whisper  (muy preciso, offline, recomendado)"),
            ("google", "🌐  Google Speech  (online, ligero, sin descarga)"),
            ("vosk",   "💻  Vosk           (offline, modelo pequeño)"),
        ]:
            tk.Radiobutton(cf, text=txt2, variable=cv, value=val,
                           bg=self.C["bg"], fg=self.C["text"],
                           selectcolor=self.C["deep"], activebackground=self.C["bg"],
                           font=("Segoe UI",10)).pack(anchor='w', pady=2)

        wf = ttk.LabelFrame(p, text="⚙️  Opciones de faster-whisper", padding=10)
        wf.pack(fill='x', pady=6)
        wf.columnconfigure(1, weight=1)

        self._lbl(wf, "Modelo:", 0)
        wm = self._v("whisper_model")
        ttk.Combobox(wf, textvariable=wm,
                     values=["tiny","base","small","medium","large-v2","large-v3"],
                     state='readonly', width=14
                     ).grid(row=0, column=1, sticky='w', padx=8, pady=4)

        self._lbl(wf, "Dispositivo:", 1)
        wd = self._v("whisper_device")
        ttk.Combobox(wf, textvariable=wd,
                     values=["cpu","cuda"],
                     state='readonly', width=8
                     ).grid(row=1, column=1, sticky='w', padx=8, pady=4)

        self._lbl(wf, "Idioma:", 2)
        wl = self._v("whisper_language")
        ttk.Combobox(wf, textvariable=wl,
                     values=["es","en","fr","de","it","pt","ca","gl","ja","zh"],
                     width=8).grid(row=2, column=1, sticky='w', padx=8, pady=4)

        tk.Label(wf,
                 text=("Instalar:  pip install faster-whisper\n"
                       "tiny≈39MB · base≈74MB · small≈244MB · medium≈769MB · large≈1.5GB\n"
                       "El modelo se descarga automáticamente la primera vez que se usa."),
                 bg=self.C["bg"], fg=self.C["muted"], font=("Segoe UI",8), justify='left'
                 ).grid(row=3, column=0, columnspan=2, sticky='w', padx=8, pady=4)

        self._info(p, [
            "⭐  'Pausa para terminar frase' sigue siendo el ajuste más importante para el VAD",
            "⭐  faster-whisper small: mejor relación velocidad/precisión en español",
            "💡  La palabra de activación siempre usa Google SR (más rápido para bucle continuo)",
        ])

    def _tab_ai(self, p):
        p.columnconfigure(1, weight=1)

        # ── Ollama conexión ──────────────────────────────────────────────────
        of = ttk.LabelFrame(p, text="Ollama", padding=12)
        of.pack(fill='x', pady=6)
        of.columnconfigure(1, weight=1)
        self._lbl(of, "Host:", 0)
        self._entry(of, "ollama_host", 0)
        self._lbl(of, "Modelo:", 1)
        mv  = self._v("ollama_model")
        mcb = ttk.Combobox(of, textvariable=mv, width=30, font=("Segoe UI",10))
        mcb.grid(row=1, column=1, sticky='ew', padx=8, pady=5)
        sl  = tk.Label(of, text="", bg=self.C["bg"], fg=self.C["muted"], font=("Segoe UI",9))
        sl.grid(row=3, column=0, columnspan=2, sticky='w', padx=8, pady=4)
        def refresh():
            sl.config(text="⏳  Conectando...", fg=self.C["muted"])
            host = self._vars.get("ollama_host",
                   tk.StringVar(value=self._cfg.get("ollama_host",""))).get()
            try:
                r = requests.get(f"{host}/api/tags", timeout=5)
                models = [m["name"] for m in r.json().get("models",[])]
                if models:
                    mcb["values"] = models
                    sl.config(text=f"✅  {len(models)} modelo(s)", fg="#44ff88")
                else:
                    sl.config(text="⚠️  Sin modelos", fg="#ffaa44")
            except Exception as e:
                sl.config(text=f"❌  {e}", fg="#ff5566")
        tk.Button(of, text="🔄  Detectar modelos",
                  bg=self.C["deep"], fg="white", relief='flat', cursor="hand2",
                  font=("Segoe UI",9), padx=10, pady=6,
                  command=lambda: threading.Thread(target=refresh, daemon=True).start()
                  ).grid(row=2, column=0, columnspan=2, sticky='w', padx=8, pady=4)

        # ── Opciones IA ──────────────────────────────────────────────────────
        opt = ttk.LabelFrame(p, text="Comportamiento", padding=12)
        opt.pack(fill='x', pady=6)
        opt.columnconfigure(1, weight=1)
        self._check(opt, "ollama_no_think",
                    "⚡  Sin razonamiento interno  (respuestas más rápidas)", 0)
        self._check(opt, "conversation_memory",
                    "🧠  Recordar historial de conversación (sesión)", 1)
        self._lbl(opt, "Turnos a recordar:", 2)
        self._scale(opt, "max_history_turns", 2, frm=2, to=30, res=1)

        # ── CMD ──────────────────────────────────────────────────────────────
        cmd_f = ttk.LabelFrame(p, text="⚙️  Ejecución de comandos CMD", padding=12)
        cmd_f.pack(fill='x', pady=6)
        cmd_f.columnconfigure(1, weight=1)
        self._check(cmd_f, "cmd_enabled",
                    "🖥️  Permitir que la IA ejecute comandos del sistema", 0)
        tk.Label(cmd_f,
                 text=(
                     "Cuando está activado, la IA puede ejecutar comandos reales\n"
                     "en tu consola para obtener información del sistema (IP, RAM,\n"
                     "archivos, procesos…) o realizar tareas concretas que pidas.\n\n"
                     f"⏱  Timeout por comando: {CMD_TIMEOUT}s     "
                     f"📄  Log: ~/.voiceai/cmd_log.txt"
                 ),
                 bg=self.C["bg"], fg=self.C["muted"],
                 font=("Segoe UI", 8), justify='left'
                 ).grid(row=1, column=0, columnspan=2, sticky='w', padx=8, pady=(4,2))
        # Botón para ver log de comandos
        def open_cmd_log():
            log_path = Path.home() / ".voiceai" / "cmd_log.txt"
            if log_path.exists():
                if platform.system() == "Windows":
                    os.startfile(str(log_path))
                else:
                    os.system(f"xdg-open '{log_path}'")
            else:
                messagebox.showinfo("Log CMD",
                    "Todavía no se ha ejecutado ningún comando.", parent=self)
        tk.Button(cmd_f, text="📋  Ver log de comandos",
                  bg=self.C["deep"], fg=self.C["text"],
                  font=("Segoe UI",9), relief='flat', cursor="hand2",
                  padx=10, pady=5,
                  command=open_cmd_log
                  ).grid(row=2, column=0, sticky='w', padx=8, pady=6)

        # ── Prompt de sistema ────────────────────────────────────────────────
        sf = ttk.LabelFrame(p, text="📝  Prompt de sistema  (instrucciones iniciales a la IA)", padding=12)
        sf.pack(fill='x', pady=6)
        sf.columnconfigure(0, weight=1)
        tk.Label(sf, text="La IA recibirá este texto antes de cada conversación:",
                 bg=self.C["bg"], fg=self.C["muted"], font=("Segoe UI",9)
                 ).grid(row=0, column=0, sticky='w', pady=(0,4))
        sp_var = tk.StringVar(value=self._cfg.get("system_prompt",""))
        self._vars["system_prompt"] = sp_var
        sp_txt = tk.Text(sf, height=4, bg=self.C["panel"], fg=self.C["text"],
                         font=("Segoe UI",10), relief='flat',
                         insertbackground=self.C["accent"], wrap='word')
        sp_txt.insert("1.0", sp_var.get())
        sp_txt.grid(row=1, column=0, sticky='ew', pady=2)
        self._sp_text_widget = sp_txt

    def _tab_orb(self, p):
        p.columnconfigure(1, weight=1)
        bf = ttk.LabelFrame(p, text="Orbe flotante", padding=12)
        bf.pack(fill='x', pady=8)
        bf.columnconfigure(1, weight=1)
        self._check(bf, "orb_visible",    "👁  Mostrar orbe al iniciar", 0)
        self._lbl(bf, "Opacidad máxima:", 1)
        self._scale(bf, "orb_opacity",    1, frm=0.3, to=1.0,  res=0.05)
        self._lbl(bf, "Opacidad mínima:", 2)
        self._scale(bf, "orb_opacity_min",2, frm=0.05, to=0.8, res=0.05)
        self._lbl(bf, "Tamaño (px):",     3)
        self._scale(bf, "orb_size",       3, frm=24, to=120,   res=4)
        pf = ttk.LabelFrame(p, text="Posición  (-1 = esquina inferior derecha)", padding=12)
        pf.pack(fill='x', pady=8)
        pf.columnconfigure(1, weight=1)
        self._lbl(pf, "X:", 0); self._entry(pf, "orb_x", 0, w=8)
        self._lbl(pf, "Y:", 1); self._entry(pf, "orb_y", 1, w=8)
        self._info(p, [
            "💡  Arrastra el orbe con el ratón — la posición se guarda automáticamente",
            "💡  Click derecho → menú rápido (escuchar / ocultar / configuración)",
            "💡  Si lo ocultas, recupéralo desde la bandeja del sistema",
        ])

    def _tab_popup(self, p):
        p.columnconfigure(1, weight=1)
        cf = ttk.LabelFrame(p, text="Colores", padding=12)
        cf.pack(fill='x', pady=8)
        cf.columnconfigure(1, weight=1)
        for i,(lbl,key) in enumerate([
            ("Fondo:",   "popup_bg"),
            ("Texto:",   "popup_text_color"),
            ("Acento:",  "popup_accent"),
        ]):
            self._lbl(cf, lbl, i)
            self._color_btn(cf, key, i)
        self._lbl(cf, "Opacidad:", 3)
        self._scale(cf, "popup_opacity", 3, frm=0.3, to=1.0, res=0.05)
        sf = ttk.LabelFrame(p, text="Tamaño, posición y tiempo", padding=12)
        sf.pack(fill='x', pady=8)
        sf.columnconfigure(1, weight=1)
        for i,(lbl,key,frm,to,res) in enumerate([
            ("Ancho (px):",      "popup_width",     280, 900, 10),
            ("Alto (px):",       "popup_height",    180, 700, 10),
            ("Cierre auto (s):", "popup_auto_close",  -1, 120,  5),
        ]):
            self._lbl(sf, lbl, i)
            self._scale(sf, key, i, frm=frm, to=to, res=res)
        self._lbl(sf, "Posición:", 3)
        pv = self._v("popup_position")
        ttk.Combobox(sf, textvariable=pv,
                     values=["center","top-right","top-left",
                             "bottom-right","bottom-left","custom"],
                     state='readonly', width=18
                     ).grid(row=3, column=1, sticky='w', padx=8, pady=5)
        for i,(lbl,key) in enumerate([("X custom:","popup_custom_x"),
                                       ("Y custom:","popup_custom_y")], start=4):
            self._lbl(sf, lbl, i)
            self._entry(sf, key, i, w=8)

        tf = ttk.LabelFrame(p, text="🔊  Cierre automático tras TTS", padding=12)
        tf.pack(fill='x', pady=8)
        tf.columnconfigure(1, weight=1)
        self._check(tf, "popup_close_on_tts_end",
                    "⏹️  Cerrar el popup cuando la IA termina de hablar", 0)
        self._lbl(tf, "Espera tras TTS (s):", 1)
        self._scale(tf, "popup_close_on_tts_end_delay", 1, frm=0, to=15, res=1)
        tk.Label(tf, text="Si el TTS está desactivado, el cierre automático usa el contador normal de arriba.",
                 bg=self.C["bg"], fg=self.C["muted"], font=("Segoe UI",8), justify='left'
                 ).grid(row=2, column=0, columnspan=2, sticky='w', padx=8, pady=2)

    def _tab_log(self, p):
        p.columnconfigure(1, weight=1)
        lf = ttk.LabelFrame(p, text="📋  Registro de conversaciones", padding=12)
        lf.pack(fill='x', pady=6)
        lf.columnconfigure(1, weight=1)
        self._check(lf, "log_enabled",
                    "💾  Guardar todas las conversaciones en un fichero .txt", 0)
        self._check(lf, "log_load_as_memory",
                    "🧠  Cargar el log como memoria al iniciar  (recuerda días anteriores)", 1)
        tk.Label(lf, text="⚠️  Cargar el log puede aumentar mucho el tiempo de respuesta si es muy largo.",
                 bg=self.C["bg"], fg=self.C["muted"], font=("Segoe UI",8), justify='left'
                 ).grid(row=2, column=0, columnspan=2, sticky='w', padx=8, pady=2)
        pf = ttk.LabelFrame(p, text="Ruta del fichero .txt", padding=12)
        pf.pack(fill='x', pady=6)
        pf.columnconfigure(1, weight=1)
        lp = self._entry(pf, "log_file_path", 0, w=34)
        def browse_log():
            f = filedialog.asksaveasfilename(
                parent=self, defaultextension=".txt",
                filetypes=[("Texto","*.txt"),("Todos","*.*")],
                initialfile="voiceai_log.txt")
            if f: lp.set(f)
        tk.Button(pf, text="📁", bg=self.C["deep"], fg="white",
                  relief='flat', cursor="hand2", command=browse_log
                  ).grid(row=0, column=2, padx=4)
        def open_log():
            path = self._vars["log_file_path"].get()
            if path and os.path.exists(path):
                os.startfile(path) if platform.system()=="Windows" else os.system(f"xdg-open '{path}'")
            else:
                messagebox.showwarning("Fichero no encontrado", "El fichero de log no existe aún.", parent=self)
        def clear_log():
            path = self._vars["log_file_path"].get()
            if path and os.path.exists(path):
                if messagebox.askyesno("Borrar log", "¿Borrar el contenido del log?", parent=self):
                    open(path,'w').close()
            else:
                messagebox.showinfo("Log", "No hay fichero de log.", parent=self)
        bf = tk.Frame(p, bg=self.C["bg"])
        bf.pack(fill='x', pady=4)
        for txt, cmd in [("📂  Abrir log", open_log), ("🗑  Borrar log", clear_log)]:
            tk.Button(bf, text=txt, bg=self.C["deep"], fg=self.C["text"],
                      relief='flat', cursor="hand2", font=("Segoe UI",9),
                      padx=12, pady=6, command=cmd).pack(side='left', padx=4)
        self._info(p, [
            "ℹ️  Formato del log:  fecha | tú dijiste → IA respondió",
            "ℹ️  'Cargar como memoria' inyecta el log completo como contexto al inicio",
            "ℹ️  Si el log es muy largo, recorta las entradas antiguas para mantener velocidad",
        ])

    def _tab_tts(self, p):
        p.columnconfigure(1, weight=1)
        ef = ttk.LabelFrame(p, text="🔊  Voz de la IA  (Text-to-Speech)", padding=12)
        ef.pack(fill='x', pady=6)
        ef.columnconfigure(1, weight=1)
        self._check(ef, "tts_enabled", "🔊  Leer la respuesta en voz alta", 0)
        self._lbl(ef, "Motor:", 1)
        tv = self._v("tts_engine")
        ttk.Combobox(ef, textvariable=tv,
                     values=["pyttsx3  (offline, sin internet)",
                             "gtts     (Google, requiere internet)"],
                     state='readonly', width=32
                     ).grid(row=1, column=1, sticky='w', padx=8, pady=5)
        self._lbl(ef, "Velocidad:", 2)
        self._scale(ef, "tts_rate",   2, frm=80,  to=300, res=10)
        self._lbl(ef, "Volumen:",     3)
        self._scale(ef, "tts_volume", 3, frm=0.1, to=1.0, res=0.05)

        vf = ttk.LabelFrame(p, text="🎤  Voz del sistema  (solo pyttsx3)", padding=12)
        vf.pack(fill='x', pady=6)
        vf.columnconfigure(1, weight=1)
        self._voice_map: dict = {}
        cur_id  = self._cfg.get("tts_voice_id","")
        voice_v = tk.StringVar(value=cur_id)
        self._vars["tts_voice_id"] = voice_v
        voice_cb = ttk.Combobox(vf, state='readonly', width=42, font=("Segoe UI",9))
        voice_cb.grid(row=0, column=0, columnspan=2, sticky='ew', padx=8, pady=4)
        status_lbl = tk.Label(vf, text="Pulsa 'Detectar voces' para ver las disponibles",
                               bg=self.C["bg"], fg=self.C["muted"], font=("Segoe UI",8))
        status_lbl.grid(row=1, column=0, columnspan=2, sticky='w', padx=8)

        def on_voice_select(event=None):
            name = voice_cb.get()
            vid  = self._voice_map.get(name, "")
            voice_v.set(vid)
        voice_cb.bind("<<ComboboxSelected>>", on_voice_select)

        def _get_all_voices():
            import pyttsx3 as _p
            eng    = _p.init()
            voices = list(eng.getProperty("voices"))
            eng.stop()
            if platform.system() == "Windows":
                try:
                    import winreg
                    ONECORE_KEY = r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
                    seen_ids = {v.id for v in voices}
                    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                        try:
                            reg = winreg.OpenKey(hive, ONECORE_KEY)
                        except FileNotFoundError:
                            continue
                        i = 0
                        while True:
                            try:
                                token_name = winreg.EnumKey(reg, i); i += 1
                            except OSError:
                                break
                            token_path = ONECORE_KEY + "\\" + token_name
                            try:
                                tok      = winreg.OpenKey(hive, token_path)
                                name_val = winreg.QueryValue(tok, "")
                                full_id  = (f"HKEY_LOCAL_MACHINE\\{token_path}"
                                            if hive == winreg.HKEY_LOCAL_MACHINE
                                            else f"HKEY_CURRENT_USER\\{token_path}")
                                if full_id in seen_ids:
                                    continue
                                seen_ids.add(full_id)
                                class _FakeVoice: pass
                                fv = _FakeVoice()
                                fv.id   = full_id
                                fv.name = name_val or token_name
                                fv.languages = []; fv.age = ""; fv.gender = ""
                                try:
                                    attr = winreg.OpenKey(hive, token_path + "\\Attributes")
                                    for aname in ("Language","Gender","Age"):
                                        try:
                                            val, _ = winreg.QueryValueEx(attr, aname)
                                            if aname == "Language": fv.languages = [val]
                                            elif aname == "Gender": fv.gender = val
                                            elif aname == "Age":    fv.age = val
                                        except Exception: pass
                                except Exception: pass
                                voices.append(fv)
                            except Exception: pass
                except Exception as e:
                    print(f"[TTS] OneCore scan error: {e}")
            return voices

        def detect_voices():
            status_lbl.config(text="⏳  Detectando voces (incluyendo OneCore)...", fg=self.C["muted"])
            try:
                voices = _get_all_voices()
                self._voice_map.clear()
                names = []; cur_name = ""
                FEMALE_NAMES = {"zira","helena","sabina","laura","lucia","eva","monica","paula","maria","rosa"}
                MALE_NAMES   = {"david","mark","pablo","jorge","carlos","antonio","miguel","juan","pedro","raul"}
                for v in voices:
                    lang = ""
                    if getattr(v,"languages",[]):
                        try:
                            raw = v.languages[0]
                            lang = raw.decode() if isinstance(raw, bytes) else str(raw)
                            try:
                                import locale
                                code = int(lang, 16)
                                lang = locale.windows_locale.get(code, lang)
                            except Exception: pass
                        except Exception: pass
                    gender_attr = getattr(v, "gender", "").lower()
                    vname_low   = v.name.lower()
                    if gender_attr == "female" or any(x in vname_low for x in FEMALE_NAMES):
                        gender = " ♀"
                    elif gender_attr == "male" or any(x in vname_low for x in MALE_NAMES):
                        gender = " ♂"
                    else:
                        gender = ""
                    onecore = " [OneCore]" if "Speech_OneCore" in str(v.id) else ""
                    display = f"{v.name}{gender}{onecore}  {lang}".strip()
                    self._voice_map[display] = v.id
                    names.append(display)
                    if v.id == cur_id:
                        cur_name = display
                voice_cb["values"] = names
                if cur_name:   voice_cb.set(cur_name)
                elif names:    voice_cb.set(names[0]); voice_v.set(self._voice_map[names[0]])
                n_oc = sum(1 for n in names if "OneCore" in n)
                status_lbl.config(text=f"✅  {len(names)} voces  ({n_oc} OneCore)  —  ♂ masc  ♀ fem", fg="#44ff88")
            except ImportError:
                status_lbl.config(text="❌  pyttsx3 no instalado: pip install pyttsx3", fg="#ff5566")
            except Exception as e:
                status_lbl.config(text=f"❌  Error: {e}", fg="#ff5566")

        tk.Button(vf, text="🔍  Detectar voces",
                  bg=self.C["deep"], fg="white", relief='flat', cursor="hand2",
                  font=("Segoe UI",9), padx=10, pady=5,
                  command=lambda: threading.Thread(target=detect_voices,daemon=True).start()
                  ).grid(row=2, column=0, sticky='w', padx=8, pady=6)

        def test_tts():
            engine_raw = self._vars.get("tts_engine", tv).get()
            engine     = "gtts" if "gtts" in engine_raw else "pyttsx3"
            rate       = float(self._vars["tts_rate"].get())
            vol        = float(self._vars["tts_volume"].get())
            vid        = voice_v.get()
            threading.Thread(
                target=speak,
                args=("Hola, soy tu asistente de voz Rubencho AI.", engine, rate, vol, vid),
                daemon=True).start()

        tk.Button(vf, text="🔊  Probar voz seleccionada",
                  bg=self.C["accent"], fg="white", relief='flat', cursor="hand2",
                  font=("Segoe UI",9,"bold"), padx=12, pady=5, command=test_tts
                  ).grid(row=2, column=1, sticky='w', padx=8, pady=6)

        self._info(p, [
            "ℹ️  pyttsx3 usa las voces instaladas en tu sistema operativo",
            "ℹ️  Windows: Panel de control → Voz → instalar paquetes de idioma adicionales",
            "ℹ️  Las voces ♂ masculinas suelen llevar nombres como 'David' o 'Pablo'",
            "ℹ️  gtts siempre usa la voz de Google — no permite elegir género",
        ])

    # ── Guardar ───────────────────────────────────────────────────────────────
    def _save(self):
        if hasattr(self, "_sp_text_widget"):
            self._vars["system_prompt"].set(
                self._sp_text_widget.get("1.0", "end-1c").strip())
        if "tts_engine" in self._vars:
            raw = self._vars["tts_engine"].get()
            self._vars["tts_engine"].set("gtts" if "gtts" in raw else "pyttsx3")
        for key, var in self._vars.items():
            if not key.startswith("_"):
                self._cfg[key] = var.get()
        if "_lang_display" in self._vars:
            display = self._vars["_lang_display"].get()
            try:
                idx = self._lang_names.index(display)
                self._cfg["language"] = self._lang_codes[idx]
            except ValueError: pass
        for key in ("orb_size","popup_width","popup_height",
                    "popup_custom_x","popup_custom_y","popup_auto_close",
                    "orb_x","orb_y","max_history_turns","energy_threshold","tts_rate",
                    "popup_close_on_tts_end_delay"):
            try: self._cfg[key] = int(float(self._cfg.get(key, DEFAULT_CONFIG.get(key,0))))
            except Exception: pass
        for key in ("orb_opacity","orb_opacity_min","popup_opacity",
                    "silence_timeout","phrase_time_limit","wake_phrase_limit",
                    "pause_threshold","phrase_threshold","non_speaking_duration",
                    "dynamic_energy_ratio","tts_volume"):
            try: self._cfg[key] = round(float(self._cfg.get(key,1.0)), 3)
            except Exception: pass
        save_config(self._cfg)
        self._on_save(self._cfg)
        messagebox.showinfo("✅ Guardado",
            "Configuración guardada.\nLos cambios se aplican en la próxima activación.",
            parent=self)
        self.destroy()


# ── TTS ───────────────────────────────────────────────────────────────────────
def speak(text: str, engine: str = "pyttsx3", rate: int = 180, volume: float = 1.0, voice_id: str = ""):
    global _TTS_MUTED
    if _TTS_MUTED:
        return
    clean = re.sub(r"#{1,6}\s*", "", text)
    clean = re.sub(r"[*_`>]", "", clean)
    clean = re.sub(r"-{3,}", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return

    if engine == "gtts":
        try:
            from gtts import gTTS
            import io as _io
            tts = gTTS(text=clean, lang="es", slow=False)
            buf = _io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(buf, "mp3")
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                return
            except Exception:
                pass
            import tempfile
            buf.seek(0)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(buf.read()); tmp = f.name
            if platform.system() == "Windows":
                os.startfile(tmp)
            elif platform.system() == "Darwin":
                subprocess.Popen(["afplay", tmp])
            else:
                subprocess.Popen(["mpg123", tmp])
        except ImportError:
            print("[TTS] gtts no instalado. Ejecuta:  pip install gtts")
        except Exception as e:
            print(f"[TTS] gtts error: {e}")
    else:
        try:
            import pyttsx3 as _pyttsx3
            is_onecore = "Speech_OneCore" in str(voice_id)
            if is_onecore and platform.system() == "Windows":
                try:
                    import win32com.client
                    sapi = win32com.client.Dispatch("SAPI.SpVoice")
                    cat = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
                    cat.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", False)
                    tokens = cat.EnumerateTokens()
                    for tok in tokens:
                        if tok.Id.lower() == voice_id.lower().replace("\\\\", "\\"):
                            sapi.Voice = tok
                            break
                    sapi.Rate   = max(-10, min(10, int((int(rate) - 180) / 18)))
                    sapi.Volume = int(float(volume) * 100)
                    sapi.Speak(clean)
                except Exception as e_oc:
                    print(f"[TTS] OneCore via win32com error: {e_oc}")
                    eng = _pyttsx3.init()
                    eng.setProperty("rate",   int(rate))
                    eng.setProperty("volume", float(volume))
                    eng.say(clean)
                    eng.runAndWait()
            else:
                eng = _pyttsx3.init()
                eng.setProperty("rate",   int(rate))
                eng.setProperty("volume", float(volume))
                if voice_id:
                    eng.setProperty("voice", voice_id)
                eng.say(clean)
                eng.runAndWait()
        except ImportError:
            print("[TTS] pyttsx3 no instalado. Ejecuta:  pip install pyttsx3")
        except Exception as e:
            print(f"[TTS] pyttsx3 error: {e}")


# ── Log helpers ───────────────────────────────────────────────────────────────
def append_log(path: str, user_msg: str, ai_msg: str):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M")
        entry = f"[{ts}]\nTú: {user_msg}\nIA:  {ai_msg}\n{'─'*60}\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print(f"[Log] Error al escribir: {e}")


def load_log_as_context(path: str) -> list:
    if not path or not os.path.exists(path):
        return []
    try:
        raw     = open(path, encoding="utf-8").read()
        blocks  = re.split(r"─{10,}", raw)
        history = []
        for block in blocks:
            um = re.search(r"^Tú:\s*(.+)$", block, re.MULTILINE)
            am = re.search(r"^IA:\s*(.+)", block, re.MULTILINE | re.DOTALL)
            if um and am:
                history.append({"role":"user",      "content": um.group(1).strip()})
                history.append({"role":"assistant",  "content": am.group(1).strip()})
        return history
    except Exception as e:
        print(f"[Log] Error al leer: {e}")
        return []


# ── Main Application ──────────────────────────────────────────────────────────
class VoiceAIApp:

    def __init__(self):
        self.config   = load_config()
        self.root     = tk.Tk()
        self.root.withdraw()
        self._ui_q    = queue.Queue()
        self._listening = False
        self._orb     = None
        self._popup   = None
        self._whisper_model    = None
        self._tts_playing      = False
        self._continuous_active= False

        self._history: list = []
        if (self.config.get("log_load_as_memory") and
                self.config.get("log_enabled") and
                self.config.get("log_file_path")):
            self._history = load_log_as_context(self.config["log_file_path"])
            print(f"📖  Log cargado: {len(self._history)//2} turnos anteriores")

        self._create_orb()
        self._setup_tray()
        self._start_listener()
        self.root.after(50, self._process_queue)

        if "--settings" in sys.argv:
            self.root.after(400, self.open_settings)

        self.root.mainloop()

    def _create_orb(self):
        try:
            self._orb = OrbWindow(
                self.root, self.config,
                on_open_settings=lambda: self._ui_q.put(("settings",      None)),
                on_listen_now=   lambda: self._ui_q.put(("manual_listen", None))
            )
            self._orb.bind("<<Quit>>", lambda _: self._ui_q.put(("quit", None)))
        except Exception as e:
            print(f"[Orb] {e}")

    def _setup_tray(self):
        if not HAS_TRAY:
            self._setup_fallback_window()
            return
        img = Image.new('RGBA', (64,64), (0,0,0,0))
        d   = ImageDraw.Draw(img)
        d.ellipse([4,4,60,60],  fill=(79,142,247,230))
        d.ellipse([12,12,28,28],fill=(200,220,255,140))
        menu = pystray.Menu(
            pystray.MenuItem("🐢  Rubencho AI", None, enabled=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🎙  Escuchar ahora",
                             lambda *_: self._ui_q.put(("manual_listen", None))),
            pystray.MenuItem("👁  Mostrar orbe",
                             lambda *_: self._ui_q.put(("show_orb",      None))),
            pystray.MenuItem("🗑  Limpiar historial",
                             lambda *_: self._ui_q.put(("clear_history", None))),
            pystray.MenuItem("⚙️  Configuración",
                             lambda *_: self._ui_q.put(("settings",      None))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌  Salir",
                             lambda *_: self._ui_q.put(("quit",          None))),
        )
        self._tray = pystray.Icon("VoiceAI", img, "Rubencho AI", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _setup_fallback_window(self):
        bg = "#0d1117"
        self.root.deiconify()
        self.root.title("🐢  Rubencho AI")
        self.root.geometry("300x90")
        self.root.resizable(False, False)
        self.root.configure(bg=bg)
        self.root.protocol("WM_DELETE_WINDOW", self.root.iconify)
        tk.Label(self.root, text="🐢  Rubencho AI  —  escuchando...",
                 bg=bg, fg="#4f8ef7",
                 font=("Segoe UI",12,"bold")).pack(expand=True, pady=6)
        fr = tk.Frame(self.root, bg=bg)
        fr.pack(pady=4)
        for txt, cmd in [
            ("⚙️", self.open_settings),
            ("🎙", self._manual_listen_trigger),
            ("🗑", lambda: self._history.clear()),
            ("✕", self.root.quit),
        ]:
            tk.Button(fr, text=txt, bg="#21262d", fg="white",
                      relief='flat', cursor="hand2", padx=8,
                      command=cmd).pack(side='left', padx=3)

    def _process_queue(self):
        try:
            while True:
                cmd, data = self._ui_q.get_nowait()
                if   cmd == "orb_state":        self._orb and self._orb.set_state(data)
                elif cmd == "show_popup":        self._show_popup(*data)
                elif cmd == "open_popup_stream": self._open_stream_popup(data)
                elif cmd == "popup_chunk":       self._append_popup_chunk(data)
                elif cmd == "popup_stream_done": self._finalize_popup(data)
                elif cmd == "show_orb":          self._orb and self._orb.show_orb()
                elif cmd == "settings":          self.open_settings()
                elif cmd == "manual_listen":     self._manual_listen_trigger()
                elif cmd == "clear_history":
                    self._history.clear()
                    messagebox.showinfo("🗑  Historial",
                        "Historial de conversación borrado.", parent=self.root)
                elif cmd == "close_popup":
                    if self._popup:
                        try: self._popup.destroy()
                        except Exception: pass
                        self._popup = None
                elif cmd == "quit":              self._quit()
        except queue.Empty:
            pass
        self.root.after(40, self._process_queue)

    def _show_popup(self, transcript: str, response: str):
        if self._popup:
            try: self._popup.destroy()
            except Exception: pass
        try:
            self._popup = ResponsePopup(
                self.root, self.config, transcript, response,
                on_send=self._handle_text_input,
                on_mute=self._toggle_mute)
        except Exception as e:
            import traceback
            print(f"[Popup] {e}")
            traceback.print_exc()

    def _open_stream_popup(self, transcript: str):
        if self._popup:
            try: self._popup.destroy()
            except Exception: pass
        try:
            self._popup = ResponsePopup(
                self.root, self.config, transcript, "",
                streaming=True,
                on_send=self._handle_text_input,
                on_mute=self._toggle_mute)
        except Exception as e:
            import traceback
            print(f"[Popup-stream] {e}")
            traceback.print_exc()

    def _append_popup_chunk(self, chunk: str):
        if self._popup and hasattr(self._popup, "append_chunk"):
            try:
                self._popup.append_chunk(chunk)
            except Exception:
                pass

    def _finalize_popup(self, full_response: str):
        if self._popup and hasattr(self._popup, "finalize"):
            try:
                self._popup.finalize(full_response)
            except Exception:
                pass

    def _toggle_mute(self) -> bool:
        """Alterna el silencio del TTS. Devuelve el nuevo estado (True=silenciado).
        Al silenciar, libera _tts_playing para que el bucle de conversación continua
        pueda escuchar en cuanto termine la frase actual."""
        global _TTS_MUTED
        _TTS_MUTED = not _TTS_MUTED
        if _TTS_MUTED:
            # Liberar el flag inmediatamente: la frase en curso terminará sola
            # (pyttsx3 es bloqueante por frase), pero la siguiente no sonará
            # y el bucle continuo no se quedará esperando indefinidamente.
            self._tts_playing = False
        print(f"🔇 TTS {'silenciado' if _TTS_MUTED else 'activado'}")
        return _TTS_MUTED

    def _handle_text_input(self, text: str):
        """Envía un mensaje de texto desde el input del popup a la IA."""
        text = text.strip()
        if not text:
            return
        # Abrir nuevo popup de streaming con el texto como transcripción
        self._ui_q.put(("open_popup_stream", text))
        self._ui_q.put(("orb_state", "thinking"))
        threading.Thread(
            target=self._stream_ollama,
            args=(text,),
            daemon=True
        ).start()

    def _start_listener(self):
        if not HAS_SR:
            print("⚠️  SpeechRecognition no instalado.")
            return
        threading.Thread(target=self._listener_loop, daemon=True).start()

    def _apply_vad(self, r):
        cfg = self.config
        r.pause_threshold         = float(cfg.get("pause_threshold",         1.8))
        r.phrase_threshold        = float(cfg.get("phrase_threshold",        0.1))
        r.non_speaking_duration   = float(cfg.get("non_speaking_duration",   0.4))
        r.dynamic_energy_threshold= bool(cfg.get("dynamic_energy_threshold", True))
        r.dynamic_energy_ratio    = float(cfg.get("dynamic_energy_ratio",    1.5))
        if not r.dynamic_energy_threshold:
            r.energy_threshold    = float(cfg.get("energy_threshold",        300))

    def _listener_loop(self):
        print("🐢  Rubencho AI iniciado — esperando palabra clave...")
        r = sr.Recognizer()
        r.energy_threshold = float(self.config.get("energy_threshold", 300))
        self._apply_vad(r)
        try:
            mic = sr.Microphone()
            with mic as src:
                r.adjust_for_ambient_noise(src, duration=1.5)
            print(f"✅  Calibrado. Umbral: {r.energy_threshold:.0f}  |  pausa: {r.pause_threshold}s")
        except Exception as e:
            print(f"⚠️  Error calibrando: {e}")
            mic = sr.Microphone()

        while True:
            try:
                cfg  = self.config
                wake = (cfg.get("custom_wake_word","").strip().lower()
                        if cfg.get("use_custom_wake_word") and cfg.get("custom_wake_word")
                        else cfg.get("wake_word","jarvis").lower())

                phrase = self._sr_listen(r, mic,
                    phrase_time_limit=float(cfg.get("wake_phrase_limit", 3.0)))
                if not phrase or wake not in phrase.lower():
                    continue
                if self._listening:
                    continue
                self._listening = True

                print(f"✅  '{wake}' detectado → escuchando comando...")
                self._ui_q.put(("orb_state", "listening"))
                self._apply_vad(r)

                cmd_engine = cfg.get("command_engine", "whisper")

                if cmd_engine == "whisper":
                    audio = self._record_raw_audio(
                        r, mic,
                        phrase_time_limit=float(cfg.get("phrase_time_limit", 15.0)),
                        timeout=float(cfg.get("silence_timeout", 2.5)))
                    command = self._whisper_transcribe(audio) if audio else ""
                else:
                    command = self._sr_listen(
                        r, mic,
                        phrase_time_limit=float(cfg.get("phrase_time_limit", 15.0)),
                        timeout=float(cfg.get("silence_timeout", 2.5)))

                if not command:
                    print("⚠️  Sin comando.")
                    self._ui_q.put(("orb_state","idle"))
                    self._listening = False
                    continue

                print(f"📝  Comando ({cmd_engine}): {command}")
                self._ui_q.put(("orb_state","thinking"))
                self._ui_q.put(("open_popup_stream", command))

                threading.Thread(
                    target=self._stream_ollama,
                    args=(command,),
                    daemon=True).start()

            except Exception as e:
                print(f"[Listener] {e}")
                time.sleep(1)
            finally:
                self._listening = False

    # ── Whisper ──────────────────────────────────────────────────────────────
    def _ensure_whisper(self):
        if hasattr(self, "_whisper_model") and self._whisper_model is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            cfg   = self.config
            msize = cfg.get("whisper_model",  "small")
            dev   = cfg.get("whisper_device", "cpu")
            ctype = "int8" if dev == "cpu" else "float16"
            print(f"⏳  Cargando faster-whisper '{msize}' en {dev}...")
            self._whisper_model = WhisperModel(msize, device=dev, compute_type=ctype)
            print("✅  Whisper listo")
            return True
        except ImportError:
            print("❌  faster-whisper no instalado: pip install faster-whisper")
            self._whisper_model = None
            return False
        except Exception as e:
            print(f"❌  Error cargando whisper: {e}")
            self._whisper_model = None
            return False

    def _record_raw_audio(self, r, mic, phrase_time_limit, timeout=None):
        try:
            with mic as src:
                audio = r.listen(src, timeout=timeout, phrase_time_limit=phrase_time_limit)
            return audio
        except sr.WaitTimeoutError:
            return None
        except Exception as e:
            print(f"[Record] {e}")
            return None

    def _whisper_transcribe(self, audio) -> str:
        if not self._ensure_whisper() or audio is None:
            return ""
        import io, wave
        try:
            raw  = audio.get_wav_data()
            buf  = io.BytesIO(raw)
            lang = self.config.get("whisper_language", "es")
            segs, _ = self._whisper_model.transcribe(
                buf, language=lang, beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500})
            return " ".join(s.text.strip() for s in segs).strip()
        except Exception as e:
            print(f"[Whisper] Error: {e}")
            return ""

    def _sr_listen(self, r, mic, phrase_time_limit, timeout=None):
        try:
            with mic as src:
                audio = r.listen(src, timeout=timeout, phrase_time_limit=phrase_time_limit)
            lang   = self.config.get("language","es-ES")
            engine = self.config.get("speech_engine","google")

            if engine == "vosk":
                model_path = self.config.get("vosk_model_path","")
                if model_path and os.path.exists(model_path):
                    try:
                        from vosk import Model, KaldiRecognizer
                        model = Model(model_path)
                        rec   = KaldiRecognizer(model, 16000)
                        raw   = audio.get_raw_data(convert_rate=16000, convert_width=2)
                        rec.AcceptWaveform(raw)
                        return json.loads(rec.FinalResult()).get("text","")
                    except Exception as ve:
                        print(f"[Vosk] fallback Google: {ve}")

            return r.recognize_google(audio, language=lang)

        except sr.WaitTimeoutError:  return None
        except sr.UnknownValueError: return ""
        except sr.RequestError as e:
            print(f"[SR] {e}"); time.sleep(2); return None
        except Exception as e:
            print(f"[SR] {e}"); return None

    # ── Ollama helpers (sin stream) ───────────────────────────────────────────
    def _ollama_chat(self, messages: list, no_think: bool, host: str, model: str) -> str:
        """Llama a Ollama sin streaming y devuelve el texto de respuesta."""
        body = {
            "model":    model,
            "messages": messages,
            "stream":   False,
            "think":    False if no_think else True,
        }
        resp = requests.post(f"{host}/api/chat", json=body, timeout=120)
        resp.raise_for_status()
        text = resp.json().get("message", {}).get("content", "Sin respuesta")
        return re.sub(r"<think>.*?</think>", "", text,
                      flags=re.DOTALL | re.IGNORECASE).strip()

    def _run_cmd_turn(self, first_response: str, messages: list,
                      host: str, model: str, no_think: bool) -> str:
        """
        Detecta <CMD>...</CMD> en first_response, ejecuta cada comando,
        construye el mensaje de seguimiento con los resultados y hace una
        segunda llamada a Ollama para obtener la respuesta final limpia.
        """
        cmd_matches = _CMD_PATTERN.findall(first_response)
        if not cmd_matches:
            return first_response

        # Ejecutar todos los comandos
        results_text = ""
        for cmd in cmd_matches:
            cmd = cmd.strip()
            print(f"⚙️  Ejecutando CMD: {cmd}")
            self._ui_q.put(("popup_chunk", f"\n⚙️  Ejecutando: `{cmd}`\n"))
            result = execute_command(cmd)
            results_text += f"<CMD>{cmd}</CMD>\n<RESULTADO>\n{result}\n</RESULTADO>\n\n"
            print(f"📋  Resultado:\n{result[:200]}{'…' if len(result)>200 else ''}")

        # Segundo turno: dar resultados a la IA y pedir respuesta final
        followup = (
            "He ejecutado los comandos que pediste. "
            "Aquí están los resultados reales del sistema:\n\n"
            + results_text
            + "\nAnaliza estos resultados y responde al usuario de forma clara, "
              "concisa y en lenguaje natural. "
              "No incluyas más bloques <CMD> en tu respuesta."
        )
        new_messages = list(messages)
        new_messages.append({"role": "assistant", "content": first_response})
        new_messages.append({"role": "user",      "content": followup})

        final = self._ollama_chat(new_messages, no_think, host, model)
        return final

    # ── _query_ollama (sin streaming) ─────────────────────────────────────────
    def _query_ollama(self, prompt: str) -> str:
        cfg       = self.config
        host      = cfg.get("ollama_host","http://localhost:11434")
        model     = cfg.get("ollama_model","qwen2.5:3b")
        no_think  = bool(cfg.get("ollama_no_think", True))
        use_mem   = bool(cfg.get("conversation_memory", True))
        max_hist  = int(cfg.get("max_history_turns", 10))
        cmd_on    = bool(cfg.get("cmd_enabled", True))
        sys_prompt = _build_system_prompt(
            cfg.get("system_prompt","Eres un asistente de voz útil, conciso y amable."),
            cmd_on
        )

        if use_mem:
            self._history.append({"role":"user","content": prompt})
            while len(self._history) > max_hist * 2:
                self._history.pop(0)
            messages = self._history.copy()
        else:
            messages = [{"role":"user","content": prompt}]

        if sys_prompt:
            messages = [{"role":"system","content": sys_prompt}] + messages

        try:
            first_response = self._ollama_chat(messages, no_think, host, model)

            # ── CMD turn ──────────────────────────────────────────────────
            if cmd_on and _CMD_PATTERN.search(first_response):
                response = self._run_cmd_turn(first_response, messages, host, model, no_think)
            else:
                response = first_response

            if use_mem:
                self._history.append({"role":"assistant","content": response})

            if cfg.get("log_enabled") and cfg.get("log_file_path"):
                threading.Thread(
                    target=append_log,
                    args=(cfg["log_file_path"], prompt, response),
                    daemon=True).start()

            if cfg.get("tts_enabled"):
                threading.Thread(
                    target=speak,
                    args=(response,
                          cfg.get("tts_engine","pyttsx3"),
                          int(cfg.get("tts_rate",180)),
                          float(cfg.get("tts_volume",1.0)),
                          cfg.get("tts_voice_id","")),
                    daemon=True).start()

            return response

        except requests.exceptions.ConnectionError:
            return "❌  No puedo conectar con Ollama.\n\n¿Está en ejecución?  →  ollama serve"
        except requests.exceptions.Timeout:
            return "❌  Ollama tardó demasiado. Prueba con un modelo más pequeño."
        except Exception as e:
            return f"❌  Error: {e}"

    def _manual_listen_trigger(self):
        if not self._listening:
            self._listening = True
            self._ui_q.put(("orb_state","listening"))
            threading.Thread(target=self._manual_listen_thread, daemon=True).start()

    def _manual_listen_thread(self):
        try:
            r   = sr.Recognizer()
            r.energy_threshold = float(self.config.get("energy_threshold", 300))
            self._apply_vad(r)
            mic         = sr.Microphone()
            cmd_engine  = self.config.get("command_engine","whisper")

            if cmd_engine == "whisper":
                audio = self._record_raw_audio(
                    r, mic,
                    phrase_time_limit=float(self.config.get("phrase_time_limit",15.0)),
                    timeout=float(self.config.get("silence_timeout",2.5)))
                cmd = self._whisper_transcribe(audio) if audio else ""
            else:
                cmd = self._sr_listen(r, mic,
                    phrase_time_limit=float(self.config.get("phrase_time_limit",15.0)),
                    timeout=float(self.config.get("silence_timeout",2.5)))

            if not cmd:
                self._ui_q.put(("orb_state","idle")); return
            self._ui_q.put(("orb_state","thinking"))
            self._ui_q.put(("open_popup_stream", cmd))
            self._stream_ollama(cmd)
        except Exception as e:
            print(f"[Manual] {e}")
            self._ui_q.put(("orb_state","idle"))
        finally:
            self._listening = False

    # ── _stream_ollama (con soporte CMD) ──────────────────────────────────────
    def _stream_ollama(self, prompt: str):
        """
        Llama a Ollama con stream=True.
        Si la respuesta contiene <CMD>...</CMD>:
          1. Termina de recopilar el stream.
          2. Ejecuta los comandos.
          3. Hace una segunda llamada (sin stream) para obtener la respuesta final.
          4. Muestra la respuesta final en el popup.
        """
        cfg       = self.config
        host      = cfg.get("ollama_host","http://localhost:11434")
        model     = cfg.get("ollama_model","qwen2.5:3b")
        no_think  = bool(cfg.get("ollama_no_think", True))
        use_mem   = bool(cfg.get("conversation_memory", True))
        max_hist  = int(cfg.get("max_history_turns", 10))
        cmd_on    = bool(cfg.get("cmd_enabled", True))
        tts_on    = bool(cfg.get("tts_enabled", False))
        close_on_tts = bool(cfg.get("popup_close_on_tts_end", False))
        close_delay  = int(cfg.get("popup_close_on_tts_end_delay", 2))
        sys_prompt = _build_system_prompt(
            cfg.get("system_prompt","Eres un asistente de voz útil, conciso y amable."),
            cmd_on
        )

        if use_mem:
            self._history.append({"role":"user","content": prompt})
            while len(self._history) > max_hist * 2:
                self._history.pop(0)
            messages = self._history.copy()
        else:
            messages = [{"role":"user","content": prompt}]
        if sys_prompt:
            messages = [{"role":"system","content": sys_prompt}] + messages

        full_response = ""

        # ── TTS helper ────────────────────────────────────────────────────────
        def _make_tts_worker(tts_q: queue.Queue):
            """Crea e inicia un hilo consumidor de TTS sobre la cola dada."""
            engine   = cfg.get("tts_engine","pyttsx3")
            rate     = int(cfg.get("tts_rate", 180))
            vol      = float(cfg.get("tts_volume", 1.0))
            voice_id = cfg.get("tts_voice_id","")

            def _consumer():
                while True:
                    sentence = tts_q.get()
                    if sentence is None:
                        tts_q.task_done()
                        break
                    if not _TTS_MUTED:          # solo bloquea el bucle si no está silenciado
                        self._tts_playing = True
                    speak(sentence, engine, rate, vol, voice_id)
                    self._tts_playing = False   # siempre liberar al terminar
                    tts_q.task_done()

            t = threading.Thread(target=_consumer, daemon=True)
            t.start()
            return t

        sentence_buf = ""
        SENT_END = set(".!?。！？\n")

        def _flush_tts(tts_q: queue.Queue, text: str = "", force: bool = False):
            """Acumula texto en sentence_buf y envía frases completas a la cola TTS."""
            nonlocal sentence_buf
            if not tts_on or tts_q is None:
                return
            sentence_buf += text
            while True:
                idx = -1
                for i, ch in enumerate(sentence_buf):
                    if ch in SENT_END:
                        idx = i
                        break
                if idx == -1:
                    if force and sentence_buf.strip():
                        tts_q.put(sentence_buf.strip())
                        sentence_buf = ""
                    break
                sentence = sentence_buf[:idx + 1].strip()
                sentence_buf = sentence_buf[idx + 1:]
                clean = re.sub(r"#{1,6}\s*|[*_`>]|-{3,}", "", sentence).strip()
                if clean:
                    tts_q.put(clean)

        # Crear cola y worker TTS para el stream inicial
        tts_q1     = queue.Queue() if tts_on else None
        tts_worker1 = _make_tts_worker(tts_q1) if tts_on else None

        # ── Petición streaming a Ollama ───────────────────────────────────────
        try:
            body = {
                "model":    model,
                "messages": messages,
                "stream":   True,
                "think":    False if no_think else True,
            }
            with requests.post(f"{host}/api/chat", json=body,
                               timeout=120, stream=True) as resp:
                resp.raise_for_status()
                in_think = False

                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        data  = json.loads(raw_line)
                        chunk = data.get("message", {}).get("content", "")
                        if not chunk:
                            continue

                        if "<think>" in chunk:
                            in_think = True
                        if in_think:
                            if "</think>" in chunk:
                                in_think = False
                                chunk = chunk.split("</think>", 1)[-1]
                            else:
                                continue
                        if not chunk:
                            continue

                        full_response += chunk
                        self._ui_q.put(("popup_chunk", chunk))
                        # No hablar si hay un bloque CMD pendiente
                        if not cmd_on or "<CMD>" not in full_response:
                            _flush_tts(tts_q1, chunk)

                    except Exception:
                        continue

        except requests.exceptions.ConnectionError:
            err = "❌  No puedo conectar con Ollama.\n\n¿Está en ejecución?  →  ollama serve"
            self._ui_q.put(("popup_chunk", err))
            full_response = err
        except Exception as e:
            err = f"❌  Error: {e}"
            self._ui_q.put(("popup_chunk", err))
            full_response = err

        # ── ¿Hay comandos CMD en la respuesta? ───────────────────────────────
        if cmd_on and _CMD_PATTERN.search(full_response):
            # Detener TTS del stream (no queremos hablar el bloque <CMD>)
            if tts_on and tts_q1 is not None:
                tts_q1.put(None)
            if tts_worker1 is not None:
                tts_worker1.join()
            self._tts_playing = False

            # Ejecutar comandos y obtener respuesta definitiva
            final_response = self._run_cmd_turn(
                full_response, messages, host, model, no_think)

            # ── Actualizar popup con la respuesta limpia ──────────────────
            self._ui_q.put(("popup_stream_done", final_response))
            # ── Orbe a idle/continuous ANTES de esperar el TTS ────────────
            self._ui_q.put(("orb_state", "continuous" if self._continuous_active else "idle"))
            full_response = final_response

            # TTS de la respuesta final (cola separada, sin raza de datos)
            if tts_on:
                tts_q2      = queue.Queue()
                tts_worker2 = _make_tts_worker(tts_q2)
                _flush_tts(tts_q2, final_response, force=True)
                tts_q2.put(None)
                tts_worker2.join()
                self._tts_playing = False

        else:
            # Flujo normal sin CMD
            _flush_tts(tts_q1, "", force=True)
            if tts_on and tts_q1 is not None:
                tts_q1.put(None)
            self._ui_q.put(("popup_stream_done", full_response))
            # ── Orbe a idle/continuous ANTES de esperar el TTS ────────────
            self._ui_q.put(("orb_state", "continuous" if self._continuous_active else "idle"))
            if tts_worker1 is not None:
                tts_worker1.join()
            self._tts_playing = False

        # ── Cerrar popup al terminar TTS (si está configurado) ────────────────
        if tts_on and close_on_tts:
            def _close_after_delay():
                time.sleep(max(0, close_delay))
                self._ui_q.put(("close_popup", None))
            threading.Thread(target=_close_after_delay, daemon=True).start()

        # Historial
        if use_mem and full_response:
            self._history.append({"role": "assistant", "content": full_response})

        # Log
        if cfg.get("log_enabled") and cfg.get("log_file_path") and full_response:
            threading.Thread(
                target=append_log,
                args=(cfg["log_file_path"], prompt, full_response),
                daemon=True).start()

        # Conversación continua
        if cfg.get("continuous_conv", True) and full_response and not full_response.startswith("❌"):
            if not self._continuous_active:
                self._continuous_active = True
                threading.Thread(
                    target=self._continuous_conv_loop,
                    daemon=True).start()

        self._listening = False

    def _continuous_conv_loop(self):
        cfg       = self.config
        timeout_s = float(cfg.get("continuous_timeout",   8.0))
        stop_word = cfg.get("continuous_stop_word", "para").lower().strip()
        cmd_engine= cfg.get("command_engine", "whisper")

        print(f"🔁  Conversación continua activa (timeout {timeout_s}s)")
        self._ui_q.put(("orb_state", "continuous"))

        try:
            r   = sr.Recognizer()
            r.energy_threshold = float(cfg.get("energy_threshold", 300))
            self._apply_vad(r)
            mic = sr.Microphone()
        except Exception as e:
            print(f"[ContConv] Mic error: {e}")
            self._continuous_active = False
            self._ui_q.put(("orb_state", "idle"))
            return

        deadline = None

        while self._continuous_active:
            if self._tts_playing:
                time.sleep(0.15)
                deadline = None
                self._ui_q.put(("orb_state", "continuous"))
                continue

            if deadline is None:
                deadline = time.time() + timeout_s
                print(f"🕐  Escuchando {timeout_s}s más...")
                self._ui_q.put(("orb_state", "listening"))

            remaining = deadline - time.time()
            if remaining <= 0:
                print("⏹️  Timeout conversación continua")
                break

            listen_t = min(remaining, 4.0)
            audio = self._record_raw_audio(
                r, mic,
                phrase_time_limit=float(cfg.get("phrase_time_limit", 15.0)),
                timeout=listen_t)

            if audio is None:
                continue

            if cmd_engine == "whisper":
                command = self._whisper_transcribe(audio)
            else:
                try:
                    command = r.recognize_google(
                        audio, language=cfg.get("language","es-ES"))
                except Exception:
                    command = ""

            if not command or not command.strip():
                continue

            command = command.strip()
            print(f"📝  Follow-up: {command}")

            if stop_word and stop_word in command.lower():
                print(f"🛑  Palabra de parada '{stop_word}'")
                break

            self._listening = True
            self._ui_q.put(("orb_state", "thinking"))
            self._ui_q.put(("open_popup_stream", command))
            self._stream_ollama(command)
            deadline = None
            self._ui_q.put(("orb_state", "continuous"))
            print("🔁  Esperando siguiente follow-up...")

        self._continuous_active = False
        self._listening         = False
        self._ui_q.put(("orb_state", "idle"))
        print("✅  Volviendo al modo wake word")

    def open_settings(self):
        def on_save(new_cfg):
            self.config = new_cfg
            self._apply_autostart(new_cfg.get("autostart", False))
        SettingsWindow(self.root, self.config, on_save)

    def _apply_autostart(self, enable: bool):
        system = platform.system()
        exe    = sys.executable
        script = os.path.abspath(__file__)
        if system == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE)
                if enable:
                    winreg.SetValueEx(key,"VoiceAI",0,winreg.REG_SZ,
                        f'"{exe}" "{script}" --tray')
                else:
                    try: winreg.DeleteValue(key,"VoiceAI")
                    except FileNotFoundError: pass
                winreg.CloseKey(key)
            except Exception as e: print(f"[Autostart] {e}")
        elif system == "Darwin":
            plist = Path.home()/"Library/LaunchAgents/com.voiceai.desktop.plist"
            if enable:
                plist.write_text(
                    f'<?xml version="1.0"?><plist version="1.0"><dict>'
                    f'<key>Label</key><string>com.voiceai.desktop</string>'
                    f'<key>ProgramArguments</key><array>'
                    f'<string>{exe}</string><string>{script}</string></array>'
                    f'<key>RunAtLoad</key><true/></dict></plist>')
            elif plist.exists(): plist.unlink()
        elif system == "Linux":
            dst = Path.home()/".config/autostart/voiceai.desktop"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if enable:
                dst.write_text(
                    "[Desktop Entry]\nType=Application\nName=Rubencho AI\n"
                    f"Exec={exe} {script} --tray\n"
                    "Hidden=false\nNoDisplay=false\n"
                    "X-GNOME-Autostart-enabled=true\n")
            elif dst.exists(): dst.unlink()

    def _quit(self):
        if HAS_TRAY and hasattr(self, '_tray'):
            try: self._tray.stop()
            except Exception: pass
        self.root.quit()


if __name__ == "__main__":
    missing = []
    if not HAS_REQUESTS: missing.append("requests")
    if not HAS_SR:       missing.append("SpeechRecognition")
    if missing:
        print(f"\n⚠️  Instala: pip install {' '.join(missing)} pyaudio\n")
    if not HAS_TRAY:
        print("ℹ️  Para bandeja del sistema: pip install pystray pillow\n")
    VoiceAIApp()
