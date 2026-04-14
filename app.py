"""
EInk Editor - Editor di testo Markdown ottimizzato per display e-ink.
Applicazione Flask a file singolo.

ARCHITETTURA:
  - L'INPUT del testo avviene nel TERMINALE del server (backend).
    Un thread dedicato cattura i tasti dalla console e costruisce il documento.
  - Il BROWSER (display e-ink) e' solo un VISUALIZZATORE read-only.
    Fa polling per ricevere il contenuto aggiornato e mostrarlo.
  - Salvataggio e caricamento file .md avvengono su disco lato server.
  - Anteprima Markdown renderizzata nel browser.

Comandi speciali nel terminale:
  Ctrl+W       -> salva su disco
  Ctrl+O       -> carica file da disco (prompt nel terminale)
  Ctrl+N       -> nuovo documento
  Ctrl+R       -> rinomina file (prompt nel terminale)
  Ctrl+Q       -> esci
  Ctrl+P       -> toggle anteprima nel browser
  Backspace    -> cancella carattere
  Enter        -> nuova riga
  Tab          -> inserisci tab
  Frecce su/giu -> muovi cursore tra le righe
"""

import os
import sys
import logging
import threading
import time
import socket
from collections import deque
from datetime import datetime

# Input da tastiera cross-platform
if sys.platform == "win32":
    import msvcrt
else:
    import tty
    import termios

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
)
import markdown

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload

# --------------------------------------------------------------------------- #
#  Directory documenti: dove vengono salvati e caricati i file .md
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "documents")
os.makedirs(DOCS_DIR, exist_ok=True)

# --------------------------------------------------------------------------- #
#  Logging: Werkzeug su file rotante (ultimi 20 messaggi), non sul terminale
# --------------------------------------------------------------------------- #
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")
MAX_LOG_LINES = 20

# Ottieni l'IP locale della macchina
try:
    hostname = socket.gethostname()
    ip_locale = socket.gethostbyname(hostname)
except Exception:
    ip_locale = "127.0.0.1"

class RotatingDequeHandler(logging.Handler):
    """Handler che scrive su file mantenendo solo le ultime N righe."""

    def __init__(self, filepath, maxlines=20):
        super().__init__()
        self.filepath = filepath
        self.maxlines = maxlines
        self._buffer = deque(maxlen=maxlines)
        # Carica righe esistenti se il file c'e' gia'
        if os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        self._buffer.append(line.rstrip("\n"))
            except Exception:
                pass

    def emit(self, record):
        try:
            msg = self.format(record)
            self._buffer.append(msg)
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(self._buffer) + "\n")
        except Exception:
            self.handleError(record)


def _setup_logging():
    """Redirige i log di Werkzeug e Flask su file, silenziando il terminale."""
    # Handler rotante su file
    handler = RotatingDequeHandler(LOG_FILE, maxlines=MAX_LOG_LINES)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s",
                                           datefmt="%Y-%m-%d %H:%M:%S"))

    # Werkzeug (le righe "GET /api/state ...")
    wlog = logging.getLogger("werkzeug")
    wlog.handlers.clear()
    wlog.addHandler(handler)
    wlog.setLevel(logging.INFO)

    # Flask app logger
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


_setup_logging()

# --------------------------------------------------------------------------- #
#  Stato globale del documento
# --------------------------------------------------------------------------- #
doc = {
    "lines": [""],           # contenuto come lista di righe
    "cursor_row": 0,         # riga corrente del cursore
    "cursor_col": 0,         # colonna corrente del cursore
    "filename": "untitled.md",
    "version": 0,            # incrementa ad ogni modifica (per il polling)
    "preview_mode": False,   # toggle anteprima nel browser
    "running": True,         # flag per terminare il thread
    "status_msg": "",        # messaggio di stato per il terminale
    "saved": True,           # documento salvato?
    "visible_lines": 5,     # numero di righe visibili nell'editor (configurabile)
}
doc_lock = threading.Lock()

# Tracciamento battute al secondo (KPS)
KPS_WINDOW = 5  # finestra di secondi per il calcolo
_keystroke_times = deque()  # timestamp dei tasti premuti (solo editing)


def record_keystroke():
    """Registra il timestamp di una battuta."""
    _keystroke_times.append(time.time())


def get_kps():
    """Calcola le battute al secondo nella finestra temporale."""
    now = time.time()
    # Rimuovi battute fuori dalla finestra
    while _keystroke_times and _keystroke_times[0] < now - KPS_WINDOW:
        _keystroke_times.popleft()
    count = len(_keystroke_times)
    if count == 0:
        return 0.0
    return round(count / KPS_WINDOW, 1)


def get_content():
    """Restituisce il contenuto completo come stringa."""
    with doc_lock:
        return "\n".join(doc["lines"])


def set_content(text, filename=None):
    """Imposta il contenuto da una stringa."""
    with doc_lock:
        doc["lines"] = text.split("\n")
        doc["cursor_row"] = len(doc["lines"]) - 1
        doc["cursor_col"] = len(doc["lines"][-1])
        doc["version"] += 1
        doc["saved"] = False
        if filename:
            doc["filename"] = filename


# --------------------------------------------------------------------------- #
#  Rendering del terminale (mostra cosa si sta scrivendo)
# --------------------------------------------------------------------------- #
def clear_terminal():
    os.system("cls" if sys.platform == "win32" else "clear")


def render_terminal():
    """Ridisegna il terminale con interfaccia retrò stile anni 80."""
    clear_terminal()
    
    width = 80  # larghezza totale dell'interfaccia
    visible = doc["visible_lines"]  # numero di righe visibili
    
    # === MENU IN TESTA ===
    menu = f"http://{ip_locale}:5000 - EInk Editor"
    menu_line = menu
    print(menu_line)
    
    # === BORDO SUPERIORE ===
    print("|" + "-" * (width - 2) + "|")
    
    # === AREA EDITOR CON SCROLL ===
    total = len(doc["lines"])
    # Finestra di righe visibili attorno al cursore
    start = max(0, doc["cursor_row"] - visible // 2)
    end = min(total, start + visible)
    if end - start < visible:
        start = max(0, end - visible)
    
    # Riempie le righe fino a 'visible' linee
    displayed_lines = list(range(start, end))
    while len(displayed_lines) < visible:
        if end < total:
            displayed_lines.append(end)
            end += 1
        else:
            displayed_lines.append(-1)  # linea vuota
    
    for line_idx in displayed_lines[:visible]:
        if line_idx == -1:
            # Linea vuota
            display = ""
        else:
            line = doc["lines"][line_idx]
            line_num = f"{line_idx+1:3d}"
            
            # Mostra cursore nella riga corrente
            if line_idx == doc["cursor_row"]:
                col = doc["cursor_col"]
                char_at = line[col] if col < len(line) else " "
                display_content = line[:col] + "[" + char_at + "]" + line[col+1:]  # cursore
            else:
                display_content = line
            
            # Limita la larghezza della riga visualizzata
            max_content_width = width - 8  # 3 cifre + 2 spazi + | + | + |
            if len(display_content) > max_content_width:
                display_content = display_content[:max_content_width]
            
            display = f" {line_num} | {display_content}"
        
        # Riempie il resto della riga con spazi
        display = display.ljust(width - 2)
        print("|" + display + "|")
    
    # === BORDO INFERIORE ===
    print("|" + "-" * (width - 2) + "|")
    
    # === BARRA DI STATO ===
    saved_indicator = "" if doc['saved'] else "*"
    status_left = f"Riga {doc['cursor_row']+1}/{total} Col {doc['cursor_col']+1} {saved_indicator}"
    
    if doc["status_msg"]:
        status_right = f"[ {doc['status_msg']} ]"
        doc["status_msg"] = ""
    else:
        status_right = doc["filename"]
    
    status_line = status_left + " " * (width - len(status_left) - len(status_right)) + status_right
    print(status_line)
    
    # === INFO COMANDI ===
    help_line = "Ctrl+W=Save  Ctrl+O=Open  Ctrl+N=New  Ctrl+R=Rename  Ctrl+P=Preview  Ctrl+Q=Quit"
    print(help_line)


# --------------------------------------------------------------------------- #
#  Lettura tasti dal terminale (thread dedicato)
# --------------------------------------------------------------------------- #
def read_key_windows():
    """Legge un tasto su Windows. Restituisce (key_str, is_special)."""
    if not msvcrt.kbhit():
        return None, False

    ch = msvcrt.getwch()

    # Ctrl+combinations
    if ch == "\x17":  # Ctrl+W
        return "CTRL_W", True
    if ch == "\x0f":  # Ctrl+O
        return "CTRL_O", True
    if ch == "\x0e":  # Ctrl+N
        return "CTRL_N", True
    if ch == "\x11":  # Ctrl+Q
        return "CTRL_Q", True
    if ch == "\x10":  # Ctrl+P
        return "CTRL_P", True
    if ch == "\x12":  # Ctrl+R
        return "CTRL_R", True

    # Backspace
    if ch == "\x08":
        return "BACKSPACE", True

    # Enter
    if ch == "\r":
        return "ENTER", True

    # Tab
    if ch == "\t":
        return "TAB", True

    # Escape / special keys (arrows, function keys)
    if ch == "\x00" or ch == "\xe0":
        ch2 = msvcrt.getwch()
        if ch2 == "H":
            return "UP", True
        if ch2 == "P":
            return "DOWN", True
        if ch2 == "K":
            return "LEFT", True
        if ch2 == "M":
            return "RIGHT", True
        if ch2 == "S":
            return "DELETE", True
        if ch2 == "G":
            return "HOME", True
        if ch2 == "O":
            return "END", True
        return None, False

    # Escape
    if ch == "\x1b":
        return "ESC", True

    # Carattere normale
    return ch, False


def read_key_unix():
    """Legge un tasto su Linux/Mac. Restituisce (key_str, is_special)."""
    import select
    if not select.select([sys.stdin], [], [], 0.05)[0]:
        return None, False

    ch = sys.stdin.read(1)

    if ch == "\x17":
        return "CTRL_W", True
    if ch == "\x0f":
        return "CTRL_O", True
    if ch == "\x0e":
        return "CTRL_N", True
    if ch == "\x11":
        return "CTRL_Q", True
    if ch == "\x10":
        return "CTRL_P", True
    if ch == "\x12":
        return "CTRL_R", True

    if ch == "\x7f" or ch == "\x08":
        return "BACKSPACE", True
    if ch == "\r" or ch == "\n":
        return "ENTER", True
    if ch == "\t":
        return "TAB", True
    if ch == "\x1b":
        # Escape sequence (arrows)
        ch2 = sys.stdin.read(1) if select.select([sys.stdin], [], [], 0.05)[0] else ""
        if ch2 == "[":
            ch3 = sys.stdin.read(1) if select.select([sys.stdin], [], [], 0.05)[0] else ""
            if ch3 == "A":
                return "UP", True
            if ch3 == "B":
                return "DOWN", True
            if ch3 == "D":
                return "LEFT", True
            if ch3 == "C":
                return "RIGHT", True
            if ch3 == "3":
                sys.stdin.read(1)  # consume ~
                return "DELETE", True
            if ch3 == "H":
                return "HOME", True
            if ch3 == "F":
                return "END", True
        return "ESC", True

    return ch, False


def save_to_disk(filename=None):
    """Salva il documento su disco nella cartella documents/."""
    content = get_content()
    if filename is None:
        filename = doc["filename"]
    # Assicura estensione .md
    if not filename.endswith(".md"):
        filename += ".md"
    filepath = os.path.join(DOCS_DIR, os.path.basename(filename))
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        with doc_lock:
            doc["filename"] = os.path.basename(filename)
            doc["saved"] = True
            doc["version"] += 1
            doc["status_msg"] = f"Salvato: {filename} ({len(content)} car.)"
    except Exception as e:
        with doc_lock:
            doc["status_msg"] = f"Errore salvataggio: {e}"


def load_from_disk(filepath=None):
    """Carica un file da disco. Se filepath e' None, chiede nel terminale."""
    if filepath is None:
        # Prompt interattivo nel terminale
        clear_terminal()
        print("=" * 60)
        print("  Carica file Markdown")
        print("  Directory:", DOCS_DIR)
        print("-" * 60)
        # Mostra file disponibili
        files = sorted(f for f in os.listdir(DOCS_DIR)
                       if f.endswith((".md", ".markdown", ".txt")))
        if files:
            for i, f in enumerate(files, 1):
                print(f"  {i}. {f}")
        else:
            print("  (nessun file trovato)")
        print("=" * 60)
        try:
            choice = input("  Nome file o numero: ").strip()
        except EOFError:
            return
        if not choice:
            with doc_lock:
                doc["status_msg"] = "Caricamento annullato"
            return
        # Se e' un numero, seleziona dalla lista
        if choice.isdigit() and files:
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                filepath = os.path.join(DOCS_DIR, files[idx])
            else:
                with doc_lock:
                    doc["status_msg"] = f"Indice non valido: {choice}"
                return
        else:
            # Prova prima nella cartella documents, poi come percorso assoluto
            candidate = os.path.join(DOCS_DIR, choice)
            if os.path.isfile(candidate):
                filepath = candidate
            elif os.path.isfile(choice):
                filepath = choice
            else:
                with doc_lock:
                    doc["status_msg"] = f"File non trovato: {choice}"
                return
    else:
        # filepath fornito direttamente (es. dalla API)
        if not os.path.isfile(filepath):
            return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="latin-1") as f:
            content = f.read()

    set_content(content, filename=os.path.basename(filepath))
    with doc_lock:
        doc["saved"] = True
        doc["status_msg"] = f"Caricato: {os.path.basename(filepath)}"
    return True


def new_document():
    """Crea un nuovo documento vuoto."""
    set_content("")
    with doc_lock:
        doc["filename"] = "untitled.md"
        doc["cursor_row"] = 0
        doc["cursor_col"] = 0
        doc["saved"] = True
        doc["status_msg"] = "Nuovo documento"


def rename_file():
    """Rinomina il file corrente. Prompt interattivo nel terminale."""
    clear_terminal()
    print("=" * 60)
    print("  Rinomina file")
    print(f"  Nome attuale: {doc['filename']}")
    print("-" * 60)
    print("  Inserisci il nuovo nome (vuoto = annulla)")
    print("  L'estensione .md viene aggiunta automaticamente")
    print("=" * 60)
    try:
        new_name = input("  Nuovo nome: ").strip()
    except EOFError:
        return

    if not new_name:
        with doc_lock:
            doc["status_msg"] = "Rinomina annullata"
        return

    # Assicura estensione .md
    if not new_name.endswith(".md"):
        new_name += ".md"

    # Sicurezza: solo il nome del file, niente percorsi
    new_name = os.path.basename(new_name)

    old_name = doc["filename"]
    old_path = os.path.join(DOCS_DIR, old_name)
    new_path = os.path.join(DOCS_DIR, new_name)

    # Controlla se esiste gia' un file con il nuovo nome
    if os.path.isfile(new_path) and new_name != old_name:
        with doc_lock:
            doc["status_msg"] = f"Errore: '{new_name}' esiste gia'"
        return

    # Se il file vecchio esiste su disco, rinominalo
    if os.path.isfile(old_path):
        try:
            os.rename(old_path, new_path)
            with doc_lock:
                doc["filename"] = new_name
                doc["version"] += 1
                doc["status_msg"] = f"Rinominato: {old_name} -> {new_name}"
        except Exception as e:
            with doc_lock:
                doc["status_msg"] = f"Errore rinomina: {e}"
    else:
        # Il file non era ancora salvato su disco, cambia solo il nome in memoria
        with doc_lock:
            doc["filename"] = new_name
            doc["version"] += 1
            doc["status_msg"] = f"Nome cambiato: {new_name}"


def keyboard_thread():
    """Thread principale di input da tastiera."""
    read_key = read_key_windows if sys.platform == "win32" else read_key_unix

    # Su Unix, metti il terminale in raw mode
    old_settings = None
    if sys.platform != "win32":
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin.fileno())

    try:
        render_terminal()
        while doc["running"]:
            key, is_special = read_key()
            if key is None:
                time.sleep(0.02)
                continue

            needs_redraw = True

            with doc_lock:
                row = doc["cursor_row"]
                col = doc["cursor_col"]
                lines = doc["lines"]

                if is_special:
                    if key == "CTRL_Q":
                        doc["running"] = False
                        break

                    elif key == "CTRL_W":
                        # Salva in un thread separato per non bloccare
                        needs_redraw = False
                        threading.Thread(target=_save_and_redraw, daemon=True).start()
                        continue

                    elif key == "CTRL_O":
                        doc_lock.release()
                        try:
                            if sys.platform != "win32" and old_settings:
                                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                            load_from_disk()
                            if sys.platform != "win32":
                                tty.setraw(sys.stdin.fileno())
                        finally:
                            doc_lock.acquire()
                        render_terminal()
                        continue

                    elif key == "CTRL_N":
                        doc_lock.release()
                        new_document()
                        doc_lock.acquire()

                    elif key == "CTRL_R":
                        doc_lock.release()
                        try:
                            if sys.platform != "win32" and old_settings:
                                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                            rename_file()
                            if sys.platform != "win32":
                                tty.setraw(sys.stdin.fileno())
                        finally:
                            doc_lock.acquire()
                        render_terminal()
                        continue

                    elif key == "CTRL_P":
                        doc["preview_mode"] = not doc["preview_mode"]
                        state = "ON" if doc["preview_mode"] else "OFF"
                        doc["status_msg"] = f"Anteprima browser: {state}"
                        doc["version"] += 1

                    elif key == "BACKSPACE":
                        if col > 0:
                            lines[row] = lines[row][:col-1] + lines[row][col:]
                            doc["cursor_col"] = col - 1
                        elif row > 0:
                            # Unisci con la riga precedente
                            prev_len = len(lines[row - 1])
                            lines[row - 1] += lines[row]
                            lines.pop(row)
                            doc["cursor_row"] = row - 1
                            doc["cursor_col"] = prev_len
                        doc["version"] += 1
                        doc["saved"] = False
                        record_keystroke()

                    elif key == "DELETE":
                        if col < len(lines[row]):
                            lines[row] = lines[row][:col] + lines[row][col+1:]
                        elif row < len(lines) - 1:
                            lines[row] += lines[row + 1]
                            lines.pop(row + 1)
                        doc["version"] += 1
                        doc["saved"] = False
                        record_keystroke()

                    elif key == "ENTER":
                        # Spezza la riga
                        rest = lines[row][col:]
                        lines[row] = lines[row][:col]
                        lines.insert(row + 1, rest)
                        doc["cursor_row"] = row + 1
                        doc["cursor_col"] = 0
                        doc["version"] += 1
                        doc["saved"] = False
                        record_keystroke()

                    elif key == "TAB":
                        lines[row] = lines[row][:col] + "    " + lines[row][col:]
                        doc["cursor_col"] = col + 4
                        doc["version"] += 1
                        doc["saved"] = False
                        record_keystroke()

                    elif key == "UP":
                        if row > 0:
                            doc["cursor_row"] = row - 1
                            doc["cursor_col"] = min(col, len(lines[row - 1]))
                        doc["version"] += 1

                    elif key == "DOWN":
                        if row < len(lines) - 1:
                            doc["cursor_row"] = row + 1
                            doc["cursor_col"] = min(col, len(lines[row + 1]))
                        doc["version"] += 1

                    elif key == "LEFT":
                        if col > 0:
                            doc["cursor_col"] = col - 1
                        elif row > 0:
                            doc["cursor_row"] = row - 1
                            doc["cursor_col"] = len(lines[row - 1])
                        doc["version"] += 1

                    elif key == "RIGHT":
                        if col < len(lines[row]):
                            doc["cursor_col"] = col + 1
                        elif row < len(lines) - 1:
                            doc["cursor_row"] = row + 1
                            doc["cursor_col"] = 0
                        doc["version"] += 1

                    elif key == "HOME":
                        doc["cursor_col"] = 0
                        doc["version"] += 1

                    elif key == "END":
                        doc["cursor_col"] = len(lines[row])
                        doc["version"] += 1

                else:
                    # Carattere normale -> inserisci
                    lines[row] = lines[row][:col] + key + lines[row][col:]
                    doc["cursor_col"] = col + len(key)
                    doc["version"] += 1
                    doc["saved"] = False
                    record_keystroke()

            if needs_redraw:
                render_terminal()

    finally:
        if sys.platform != "win32" and old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def _save_and_redraw():
    save_to_disk()
    render_terminal()


# --------------------------------------------------------------------------- #
#  Flask Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def state():
    """Restituisce lo stato corrente del documento per il polling del browser."""
    with doc_lock:
        return jsonify({
            "lines":        doc["lines"],
            "cursor_row":   doc["cursor_row"],
            "cursor_col":   doc["cursor_col"],
            "filename":     doc["filename"],
            "version":      doc["version"],
            "preview_mode": doc["preview_mode"],
            "saved":        doc["saved"],
            "kps":          get_kps(),
        })


@app.route("/api/render", methods=["POST"])
def render_md():
    """Converte Markdown in HTML."""
    data = request.get_json(silent=True) or {}
    md_content = data.get("content", "")
    html = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "codehilite", "toc", "nl2br"],
    )
    return jsonify({"html": html})


@app.route("/api/files")
def list_files():
    """Restituisce la lista dei file .md disponibili nella cartella documents/."""
    files = []
    for f in sorted(os.listdir(DOCS_DIR)):
        if f.lower().endswith((".md", ".markdown", ".txt")):
            filepath = os.path.join(DOCS_DIR, f)
            stat = os.stat(filepath)
            files.append({
                "name": f,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return jsonify({"files": files, "directory": DOCS_DIR})


@app.route("/api/save", methods=["POST"])
def save():
    """Salva il documento corrente su disco nel server (cartella documents/)."""
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", doc["filename"])
    # Assicura estensione .md
    if not filename.endswith(".md"):
        filename += ".md"
    save_to_disk(filename=filename)
    return jsonify({"ok": True, "filename": doc["filename"]})


@app.route("/api/load", methods=["POST"])
def load():
    """Carica un file .md dal disco del server nel documento corrente."""
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "Nome file mancante"}), 400
    # Sicurezza: solo il nome del file, niente percorsi relativi
    safe_name = os.path.basename(filename)
    filepath = os.path.join(DOCS_DIR, safe_name)
    if not os.path.isfile(filepath):
        return jsonify({"error": f"File non trovato: {safe_name}"}), 404
    result = load_from_disk(filepath)
    if result:
        return jsonify({"ok": True, "filename": safe_name})
    return jsonify({"error": "Impossibile caricare il file"}), 500


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("=" * 60)
    print("  EInk Editor")
    print("  Browser (localhost): http://localhost:5000")
    print(f"  Browser (IP):        http://{ip_locale}:5000")
    print("  Input:               digita in questo terminale")
    print("=" * 60)
    print("  Avvio server Flask...")
    print()

    # Avvia il thread di input da tastiera
    kb_thread = threading.Thread(target=keyboard_thread, daemon=True)
    kb_thread.start()

    # Avvia Flask (use_reloader=False per non interferire col thread)
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
