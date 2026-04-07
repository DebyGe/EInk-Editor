# EInk Editor

Editor di testo Markdown con interfaccia web ottimizzata per display e-ink.

## Architettura

L'applicazione separa input e visualizzazione:

- **Input** -- si digita nel **terminale** dove gira il server Python. Un thread dedicato cattura ogni tasto e costruisce il documento in memoria.
- **Visualizzazione** -- il **browser** (pensato per un display e-ink) mostra il contenuto in sola lettura, aggiornandosi tramite polling ogni 300 ms.
- **File** -- salvataggio e caricamento dei file `.md` avvengono su disco lato server, nella cartella `documents/`. Il browser comanda le operazioni tramite API, ma i file non transitano mai nel browser.

```
Tastiera --> Terminale Python (input) --> Flask (stato) --> Browser e-ink (visualizzazione)
                                            |
                                       documents/  (salvataggio e caricamento file .md)
```

Questo approccio permette di collegare un display e-ink come monitor secondario che mostra solo la pagina web, mentre si scrive da una tastiera collegata al server.

## Struttura del progetto

```
EInk-Editor/
  app.py               # Backend Flask + logica di input da tastiera
  requirements.txt     # Dipendenze Python
  server.log           # Log delle richieste HTTP (creato automaticamente)
  documents/           # Cartella dove vengono salvati/caricati i file .md
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

Al primo avvio viene creata automaticamente la cartella `documents/` dove risiedono tutti i file Markdown.

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
| `Ctrl+S` | Salva il documento nella cartella `documents/` |
| `Ctrl+O` | Apri un file dalla cartella `documents/` (con lista nel terminale) |
| `Ctrl+N` | Nuovo documento vuoto |
| `Ctrl+R` | Rinomina il file corrente (prompt nel terminale) |
| `Ctrl+P` | Mostra/nascondi anteprima Markdown nel browser |
| `Ctrl+Q` | Esci dall'applicazione |

## Funzioni disponibili dal browser

- **Salva** -- salva il documento corrente nella cartella `documents/` sul server (chiede il nome del file).
- **Apri** -- mostra la lista dei file `.md` presenti nella cartella `documents/` sul server e permette di sceglierne uno da caricare.
- **Selettore font** -- cambia la dimensione del testo (14--24 px) per adattarsi al display.

## Gestione file

Tutti i file vengono salvati e caricati dalla cartella `documents/` nella directory del progetto. Questa cartella viene creata automaticamente al primo avvio.

- Dal **terminale**: `Ctrl+S` salva, `Ctrl+O` mostra la lista dei file disponibili con un menu numerato, `Ctrl+R` rinomina il file corrente (se esiste su disco viene rinominato anche il file fisico).
- Dal **browser**: il bottone "Salva" scrive su disco nel server, il bottone "Apri" mostra un dialog con la lista dei file sul server.
- I file non vengono mai scaricati o caricati nel browser. Tutto resta sul server.

## API endpoints

| Route | Metodo | Descrizione |
|---|---|---|
| `/` | GET | Pagina principale (visualizzatore) |
| `/api/state` | GET | Stato corrente del documento (polling) |
| `/api/render` | POST | Converte Markdown in HTML |
| `/api/files` | GET | Lista dei file .md nella cartella `documents/` |
| `/api/save` | POST | Salva il documento su disco nel server |
| `/api/load` | POST | Carica un file .md dal disco del server |

## Ottimizzazioni per e-ink

- Bianco e nero puro, nessun colore.
- `transition: none` e `animation: none` su tutti gli elementi.
- Font serif (Georgia) per l'interfaccia, monospace (Courier New) per il codice.
- Bordi netti, nessuna ombra o gradiente.
- Aggiornamento del browser solo quando il contenuto cambia (confronto versione), per ridurre i refresh del display.

## Logging

I log delle richieste HTTP (Werkzeug) non vengono stampati nel terminale per non interferire con l'editor. Vengono scritti nel file `server.log` nella directory del progetto, mantenendo solo le **ultime 20 righe** (rotazione automatica).

Per consultare il log:

```bash
# Windows
type server.log

# Linux / macOS
cat server.log
```

## Compatibilita

- **Windows** -- input da tastiera tramite `msvcrt`.
- **Linux / macOS** -- input da tastiera tramite `tty` + `termios` (raw mode).

## Licenza

Uso libero.
