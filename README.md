# EInk Editor

Editor di testo Markdown con interfaccia web ottimizzata per display e-ink.

## Architettura

L'applicazione separa input e visualizzazione:

- **Input** -- si digita nel **terminale** dove gira il server Python. Un thread dedicato cattura ogni tasto e costruisce il documento in memoria.
- **Visualizzazione** -- il **browser** (pensato per un display e-ink) mostra il contenuto in sola lettura, aggiornandosi tramite polling ogni 300 ms.

```
Tastiera --> Terminale Python (input) --> Flask (stato) --> Browser e-ink (visualizzazione)
```

Questo approccio permette di collegare un display e-ink come monitor secondario che mostra solo la pagina web, mentre si scrive da una tastiera collegata al server.

## Struttura del progetto

```
EInk-Editor/
  app.py               # Backend Flask + logica di input da tastiera
  requirements.txt     # Dipendenze Python
  templates/
    index.html         # Frontend HTML/CSS/JS (visualizzatore read-only)
```

## Requisiti

- Python 3.10+
- Flask >= 3.0
- Markdown >= 3.5

## Installazione

```bash
# Clona o copia il progetto, poi:
cd EInk-Editor
pip install -r requirements.txt
```

## Avvio

```bash
python app.py
```

Il server si avvia su `http://localhost:5000`.

- **Terminale** -- qui si digita il testo. Compare un mini-editor con numeri di riga e cursore.
- **Browser** -- aprire `http://localhost:5000` sul display e-ink (o qualsiasi browser). Mostra il documento in sola lettura.

## Comandi da tastiera (nel terminale)

| Tasto | Azione |
|---|---|
| Caratteri | Inserimento testo |
| `Enter` | Nuova riga |
| `Backspace` | Cancella carattere a sinistra |
| `Delete` | Cancella carattere a destra |
| `Tab` | Inserisce 4 spazi |
| Frecce | Muovi cursore |
| `Home` / `End` | Inizio / fine riga |
| `Ctrl+S` | Salva il documento su disco |
| `Ctrl+O` | Apri un file da disco (prompt nel terminale) |
| `Ctrl+N` | Nuovo documento vuoto |
| `Ctrl+P` | Mostra/nascondi anteprima Markdown nel browser |
| `Ctrl+Q` | Esci dall'applicazione |

## Funzioni disponibili dal browser

- **Carica .md** -- carica un file Markdown dal filesystem locale nel documento corrente.
- **Scarica .md** -- scarica il documento corrente come file `.md`.
- **Selettore font** -- cambia la dimensione del testo (14--24 px) per adattarsi al display.

## API endpoints

| Route | Metodo | Descrizione |
|---|---|---|
| `/` | GET | Pagina principale (visualizzatore) |
| `/api/state` | GET | Stato corrente del documento (polling) |
| `/api/render` | POST | Converte Markdown in HTML |
| `/api/upload` | POST | Carica un file .md nel documento |
| `/api/download` | GET | Scarica il documento come file .md |

## Ottimizzazioni per e-ink

- Bianco e nero puro, nessun colore.
- `transition: none` e `animation: none` su tutti gli elementi.
- Font serif (Georgia) per l'interfaccia, monospace (Courier New) per il codice.
- Bordi netti, nessuna ombra o gradiente.
- Aggiornamento del browser solo quando il contenuto cambia (confronto versione), per ridurre i refresh del display.

## Compatibilita

- **Windows** -- input da tastiera tramite `msvcrt`.
- **Linux / macOS** -- input da tastiera tramite `tty` + `termios` (raw mode).

## Licenza

Uso libero.
