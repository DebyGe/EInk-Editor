"""
EInk Editor - Editor di testo Markdown ottimizzato per display e-ink.
Applicazione Flask a file singolo.

ARCHITETTURA:
  - L'INPUT del testo avviene nel TERMINALE del server (backend).
    Un thread dedicato cattura i tasti dalla console e costruisce il documento.
  - Il BROWSER (display e-ink) e' solo un VISUALIZZATORE read-only.
    Fa polling per ricevere il contenuto aggiornato e mostrarlo.
  - Upload/download di file .md avviene dal browser.
  - Anteprima Markdown renderizzata nel browser.

Comandi speciali nel terminale:
  Ctrl+S       -> salva su disco
  Ctrl+O       -> carica file da disco (prompt nel terminale)
  Ctrl+N       -> nuovo documento
  Ctrl+Q       -> esci
  Ctrl+P       -> toggle anteprima nel browser
  Backspace    -> cancella carattere
  Enter        -> nuova riga
  Tab          -> inserisci tab
  Frecce su/giu -> muovi cursore tra le righe
"""

import os
import sys
import threading
import tempfile
import time
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
    send_file,
    Response,
)
import markdown

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload

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
}
doc_lock = threading.Lock()


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
    """Ridisegna il terminale con il contenuto e il cursore."""
    clear_terminal()
    print("=" * 60)
    print(f"  EInk Editor  |  {doc['filename']}"
          f"{'  [modificato]' if not doc['saved'] else ''}")
    print(f"  Riga {doc['cursor_row']+1}/{len(doc['lines'])}"
          f"  Col {doc['cursor_col']+1}")
    print("-" * 60)
    print("  Ctrl+S=Salva  Ctrl+O=Apri  Ctrl+N=Nuovo  Ctrl+Q=Esci")
    print("  Ctrl+P=Toggle anteprima browser")
    print("=" * 60)

    # Mostra le righe con indicatore cursore
    total = len(doc["lines"])
    # Finestra di righe visibili attorno al cursore
    visible = 20
    start = max(0, doc["cursor_row"] - visible // 2)
    end = min(total, start + visible)
    if end - start < visible:
        start = max(0, end - visible)

    for i in range(start, end):
        line = doc["lines"][i]
        prefix = ">" if i == doc["cursor_row"] else " "
        line_num = f"{i+1:4d}"
        # Mostra cursore nella riga corrente
        if i == doc["cursor_row"]:
            col = doc["cursor_col"]
            char_at = line[col] if col < len(line) else " "
            display = line[:col] + "[" + char_at + "]" + line[col+1:]  # cursore
        else:
            display = line
        print(f" {prefix} {line_num} | {display}")

    if doc["status_msg"]:
        print()
        print(f"  [{doc['status_msg']}]")
        doc["status_msg"] = ""


# --------------------------------------------------------------------------- #
#  Lettura tasti dal terminale (thread dedicato)
# --------------------------------------------------------------------------- #
def read_key_windows():
    """Legge un tasto su Windows. Restituisce (key_str, is_special)."""
    if not msvcrt.kbhit():
        return None, False

    ch = msvcrt.getwch()

    # Ctrl+combinations
    if ch == "\x13":  # Ctrl+S
        return "CTRL_S", True
    if ch == "\x0f":  # Ctrl+O
        return "CTRL_O", True
    if ch == "\x0e":  # Ctrl+N
        return "CTRL_N", True
    if ch == "\x11":  # Ctrl+Q
        return "CTRL_Q", True
    if ch == "\x10":  # Ctrl+P
        return "CTRL_P", True

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

    if ch == "\x13":
        return "CTRL_S", True
    if ch == "\x0f":
        return "CTRL_O", True
    if ch == "\x0e":
        return "CTRL_N", True
    if ch == "\x11":
        return "CTRL_Q", True
    if ch == "\x10":
        return "CTRL_P", True

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


def save_to_disk():
    """Salva il documento su disco."""
    content = get_content()
    filename = doc["filename"]
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        with doc_lock:
            doc["saved"] = True
            doc["status_msg"] = f"Salvato: {filename} ({len(content)} car.)"
    except Exception as e:
        with doc_lock:
            doc["status_msg"] = f"Errore salvataggio: {e}"


def load_from_disk():
    """Carica un file da disco (prompt nel terminale)."""
    clear_terminal()
    print("=" * 60)
    print("  Carica file Markdown")
    print("=" * 60)

    # Su Windows serve input() standard per leggere percorso file
    # Temporaneamente usiamo input bloccante
    try:
        path = input("  Percorso file: ").strip()
    except EOFError:
        return

    if not path:
        with doc_lock:
            doc["status_msg"] = "Caricamento annullato"
        return

    if not os.path.isfile(path):
        with doc_lock:
            doc["status_msg"] = f"File non trovato: {path}"
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1") as f:
            content = f.read()

    set_content(content, filename=os.path.basename(path))
    with doc_lock:
        doc["saved"] = True
        doc["status_msg"] = f"Caricato: {path}"


def new_document():
    """Crea un nuovo documento vuoto."""
    set_content("")
    with doc_lock:
        doc["filename"] = "untitled.md"
        doc["cursor_row"] = 0
        doc["cursor_col"] = 0
        doc["saved"] = True
        doc["status_msg"] = "Nuovo documento"


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

                    elif key == "CTRL_S":
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

                    elif key == "DELETE":
                        if col < len(lines[row]):
                            lines[row] = lines[row][:col] + lines[row][col+1:]
                        elif row < len(lines) - 1:
                            lines[row] += lines[row + 1]
                            lines.pop(row + 1)
                        doc["version"] += 1
                        doc["saved"] = False

                    elif key == "ENTER":
                        # Spezza la riga
                        rest = lines[row][col:]
                        lines[row] = lines[row][:col]
                        lines.insert(row + 1, rest)
                        doc["cursor_row"] = row + 1
                        doc["cursor_col"] = 0
                        doc["version"] += 1
                        doc["saved"] = False

                    elif key == "TAB":
                        lines[row] = lines[row][:col] + "    " + lines[row][col:]
                        doc["cursor_col"] = col + 4
                        doc["version"] += 1
                        doc["saved"] = False

                    elif key == "UP":
                        if row > 0:
                            doc["cursor_row"] = row - 1
                            doc["cursor_col"] = min(col, len(lines[row - 1]))

                    elif key == "DOWN":
                        if row < len(lines) - 1:
                            doc["cursor_row"] = row + 1
                            doc["cursor_col"] = min(col, len(lines[row + 1]))

                    elif key == "LEFT":
                        if col > 0:
                            doc["cursor_col"] = col - 1
                        elif row > 0:
                            doc["cursor_row"] = row - 1
                            doc["cursor_col"] = len(lines[row - 1])

                    elif key == "RIGHT":
                        if col < len(lines[row]):
                            doc["cursor_col"] = col + 1
                        elif row < len(lines) - 1:
                            doc["cursor_row"] = row + 1
                            doc["cursor_col"] = 0

                    elif key == "HOME":
                        doc["cursor_col"] = 0

                    elif key == "END":
                        doc["cursor_col"] = len(lines[row])

                else:
                    # Carattere normale -> inserisci
                    lines[row] = lines[row][:col] + key + lines[row][col:]
                    doc["cursor_col"] = col + len(key)
                    doc["version"] += 1
                    doc["saved"] = False

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


@app.route("/api/upload", methods=["POST"])
def upload():
    """Riceve un file .md dal browser e lo carica nel documento."""
    if "file" not in request.files:
        return jsonify({"error": "Nessun file ricevuto"}), 400

    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "Nome file vuoto"}), 400

    try:
        content = f.read().decode("utf-8")
    except UnicodeDecodeError:
        f.seek(0)
        try:
            content = f.read().decode("latin-1")
        except Exception:
            return jsonify({"error": "Impossibile decodificare il file"}), 400

    filename = f.filename or "uploaded.md"
    set_content(content, filename=filename)
    with doc_lock:
        doc["saved"] = True
        doc["status_msg"] = f"Caricato dal browser: {filename}"

    return jsonify({"ok": True, "filename": filename})


@app.route("/api/download")
def download():
    """Invia il documento corrente come file .md al browser."""
    content = get_content()
    filename = doc["filename"]

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name=filename,
        mimetype="text/markdown",
    )


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("=" * 60)
    print("  EInk Editor")
    print("  Browser: http://localhost:5000 (solo visualizzazione)")
    print("  Input:   digita in questo terminale")
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
