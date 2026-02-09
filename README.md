# WFS Catasto Download Particelle BBox

Plugin per QGIS che consente di scaricare le particelle catastali dal servizio WFS dell'Agenzia delle Entrate (INSPIRE).

![Panoramica del plugin in QGIS](./screen.png)

## Funzionalità

Tre modalità di selezione dell'area di interesse:

1. **Disegna BBox** - Clicca due punti sulla mappa per disegnare un rettangolo che definisce l'area di download.
2. **Seleziona Poligono** - Clicca su un poligono esistente in mappa per estrarne automaticamente il bounding box. Se l'area è grande, viene suddivisa in tile automaticamente.
3. **Seleziona Linea** - Clicca su una linea nella mappa e crea un buffer personalizzabile (0-100m) per scaricare le particelle che lo intersecano. Il layer deve avere un CRS proiettato (metri).

### Opzione: Espandi riferimento catastale (v1.1.0)

Nella sezione **Opzioni** della finestra di scelta modalità è disponibile il checkbox **"Espandi riferimento catastale"**. Quando attivato, il plugin analizza il campo `NATIONALCADASTRALREFERENCE` e ne estrae 4 nuovi attributi nel layer di output:

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `sezione` | String | Sezione censuaria (lettera, es. A, B; vuoto se assente) |
| `foglio` | Integer | Numero del foglio catastale |
| `allegato` | String | Codice allegato (0 = nessuno, Q = quadro d'unione) |
| `sviluppo` | String | Codice sviluppo (0 = nessuno, U = quadro d'unione) |

Il parsing segue il formato ufficiale dell'Agenzia delle Entrate `CCCCZFFFFAS`, dove:
- **CCCC** = codice nazionale del comune (già presente nel campo `ADMINISTRATIVEUNIT`)
- **Z** = sezione censuaria (`_` se assente)
- **FFFF** = numero foglio (4 cifre, con zeri a sinistra)
- **A** = codice allegato
- **S** = codice sviluppo

Per ulteriori dettagli sulla codifica, consultare il file [test/decodifica.md](test/decodifica.md).

### Caratteristiche tecniche

- Download multi-tile con progress bar per aree estese
- Deduplicazione automatica delle feature
- Filtro spaziale per la modalità linea con buffer
- Espansione opzionale del riferimento catastale nazionale
- Compatibile con QGIS 3 (Qt5) e QGIS 4 (Qt6)

## Interfaccia

Al primo avvio per sessione QGIS viene mostrato un avviso obbligatorio sull'uso responsabile del plugin. Dopo l'accettazione si accede alla finestra di scelta modalità, che resta in primo piano permettendo di navigare la mappa prima di selezionare la modalità.

![Finestra di avviso e scelta modalità](./screen2.png)

## Installazione

### Da cartella plugin

1. Copia la cartella `wfs_catasto_download_particelle_bbox` nella directory dei plugin di QGIS:
   - **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - **macOS**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
2. Riavvia QGIS.
3. Attiva il plugin dal menu **Plugin > Gestisci e installa plugin**.

### Da repository GitHub

```bash
cd <cartella_plugin_qgis>
git clone https://github.com/pigreco/wfs_catasto_download_particelle_bbox.git
```

## Avviso importante

Si raccomanda un uso **responsabile** e **moderato** del plugin. Il download massivo o ripetuto di grandi quantità di dati potrebbe compromettere la disponibilità del servizio WFS dell'Agenzia delle Entrate, arrecando disservizio a tutti gli utenti.

L'autore invita al rispetto dell'**etica professionale** e delle buone pratiche nell'utilizzo delle risorse pubbliche condivise: il servizio WFS è messo a disposizione dalla pubblica amministrazione per finalità istituzionali e professionali, non per lo scaricamento indiscriminato dei dati.

L'autore declina ogni responsabilità per eventuali usi impropri del plugin o per conseguenze derivanti da un utilizzo non conforme alle condizioni del servizio WFS dell'Agenzia delle Entrate.

## Licenza

Questo progetto è distribuito con licenza MIT.

## Ringraziamenti

Un sentito grazie ad [Andrea Borruso](https://github.com/aborruso) per l'idea e l'ispirazione.

---

> Questo repository è interamente creato con l'aiuto di [Claude Code](https://claude.ai/claude-code).

## Video Demo

[![Video Demo del Plugin](https://img.youtube.com/vi/iEFLlQq_9hY/maxresdefault.jpg)](https://youtu.be/iEFLlQq_9hY)

## Autore

**Salvatore Fiandaca** - [pigrecoinfinito@gmail.com](mailto:pigrecoinfinito@gmail.com)
