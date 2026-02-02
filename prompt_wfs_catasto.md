# Prompt per generare lo script PyQGIS - Download WFS Catasto

> Copia e incolla il testo seguente in un LLM per rigenerare lo script completo.

---

Agisci come esperto PyQGIS. Crea uno script Python da eseguire nella **Console Python di QGIS** per scaricare le particelle catastali italiane dal servizio WFS dell'Agenzia delle Entrate.

## Servizio WFS

```
URL base: https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php
Servizio: WFS versione 2.0.0
TypeName: CP:CadastralParcel
CRS richiesto: EPSG:6706 (ETRS89 geografico Italia)
Formato bbox nella request: min_lat,min_lon,max_lat,max_lon,urn:ogc:def:crs:EPSG::6706
```

## GUI - Dialogo scelta modalità

All'avvio mostra un `QDialog` con titolo "Download Particelle Catastali WFS" che offre tre modalità:

1. **Disegna BBox** (pulsante blu) — l'utente disegna un rettangolo sulla mappa
2. **Seleziona Poligono** (pulsante verde) — l'utente clicca su un poligono esistente
3. **Seleziona Asse Stradale** (pulsante arancione) — l'utente clicca su una linea, viene creato un buffer e scaricate solo le particelle che intersecano il buffer. Include un `QSpinBox` per impostare la distanza del buffer (range 0-100m, default 50m).

Il dialogo deve avere anche un pulsante "Annulla". Usa `QGroupBox` per raggruppare ogni modalità con una breve descrizione. Applica stili CSS ai pulsanti (colori, hover, border-radius).

## Modalità A — Disegna BBox

Implementa un `QgsMapTool` personalizzato (`BBoxDrawTool`):

- **Primo click**: registra il primo angolo del rettangolo.
- **Movimento mouse**: mostra un'anteprima in tempo reale con un `QgsRubberBand` tratteggiato blu (`Qt.DashLine`, fill semi-trasparente).
- **Secondo click**: conferma il secondo angolo, rimuove l'anteprima, disegna il rettangolo definitivo con RubberBand rosso, poi avvia il download.
- Dopo il download, ripristina lo strumento Pan (`iface.actionPan().trigger()`).

## Modalità B — Seleziona Poligono

Implementa un `QgsMapTool` personalizzato (`PolySelectTool`):

- Al click, itera tutti i layer poligonali del progetto.
- Per determinare se un layer è poligonale, usa `Qgis.GeometryType.Polygon` con fallback al valore numerico `2` per compatibilità con versioni QGIS diverse.
- **Trasforma le coordinate del click** dal CRS del progetto al CRS del layer prima di fare la ricerca spaziale.
- Usa `QgsFeatureRequest().setFilterRect()` con tolleranza adattiva, poi verifica con `geom.contains(click_geom)` che il click sia effettivamente dentro il poligono.
- Estratto il bbox della geometria, disegnalo con RubberBand verde.
- Trasforma il bbox dal CRS del layer a EPSG:6706 per la chiamata WFS.
- Stampa nella console: layer name, feature ID, CRS del layer, bbox.

## Modalità C — Seleziona Asse Stradale

Implementa un `QgsMapTool` personalizzato (`LineSelectTool`):

- Al click, itera tutti i layer lineari del progetto.
- Per determinare se un layer è lineare, usa `Qgis.GeometryType.Line` con fallback al valore numerico `1` per compatibilità con versioni QGIS diverse.
- **Controlla che il CRS del layer sia proiettato** (non geografico). Usa `layer.crs().isGeographic()`:
  - Se il CRS è geografico, mostra un `QMessageBox.warning` che spiega all'utente di riproiettare il layer in un CRS proiettato (es. EPSG:3857, UTM) per calcolare correttamente il buffer in metri.
  - Blocca l'operazione e non procedere con il download.
- Trova la linea più vicina al punto cliccato usando `geom.distance(click_geom)`.
- **Crea un buffer** sulla linea selezionata: `line_geom.buffer(buffer_distance, 8)` dove `buffer_distance` è il valore scelto dall'utente nella GUI (default 50m, range 0-100m).
- **Visualizza il buffer** sulla mappa con un `QgsRubberBand` arancione (fill: 255,140,0,60 — bordo: 255,100,0,200).
- Estrai il bbox dal buffer e trasformalo in EPSG:6706 per la chiamata WFS.
- **Trasforma anche la geometria del buffer** in EPSG:6706 per usarla come filtro spaziale.
- Passa il buffer trasformato come parametro `filter_geom` alla funzione `esegui_download_e_caricamento()`.
- Stampa nella console: layer name, feature ID, CRS del layer, area del buffer, bbox.

## Trasformazione CRS

Crea una funzione `trasforma_bbox_a_wfs(rect, source_crs)` che:

- Prende un `QgsRectangle` e il CRS sorgente.
- Se il CRS sorgente è già EPSG:6706, restituisce le coordinate direttamente.
- Altrimenti usa `QgsCoordinateTransform` e `transformBoundingBox()` per riproiettare a EPSG:6706.
- Restituisce `(min_lat, min_lon, max_lat, max_lon)`.

## Tiling automatico per aree grandi

Il server WFS ha un limite di feature per chiamata. Per gestire aree grandi:

- Crea una funzione `stima_area_km2()` che calcola l'area approssimativa del bbox in km² usando la latitudine media (1° lat ≈ 111 km, 1° lon ≈ 111 × cos(lat) km).
- Crea una funzione `calcola_griglia_tile()` che, se l'area supera la soglia `MAX_TILE_KM2 = 2.0` km², suddivide il bbox in una griglia quasi quadrata di tile più piccoli. Il numero di righe e colonne viene calcolato automaticamente con `math.ceil(math.sqrt(n_tiles_necessari))`.
- Se servono più tile, mostra un `QMessageBox.question` con il numero di tile e il tempo stimato, e chiedi conferma all'utente.

## Download con Progress Bar

Crea una funzione `esegui_download_e_caricamento(min_lat, min_lon, max_lat, max_lon, filter_geom=None)` che:

- Calcola la griglia tile.
- **Ottimizzazione tile (se `filter_geom` è presente)**: prima di scaricare, filtra le tile che intersecano effettivamente il buffer. Per ogni tile, crea un `QgsGeometry.fromRect()` e verifica `tile_geom.intersects(filter_geom)`. Salta le tile che non intersecano. Stampa quante tile sono state saltate.
- Mostra un `QProgressDialog` modale con pulsante "Annulla".
- Per ogni tile:
  - Aggiorna la label della progress bar con: tile corrente, feature scaricate, errori.
  - Scarica il GML in un file temporaneo con `urllib.request.urlretrieve`.
  - Verifica che il contenuto non sia un `ExceptionReport`.
  - Carica con `QgsVectorLayer(tmp_path, "tile_tmp", "ogr")` e estrai le feature.
  - Elimina i file temporanei (.gml e .xsd).
  - Attendi `PAUSA_SECONDI = 5` secondi tra una chiamata e l'altra, mostrando il countdown nella progress bar (controlla `wasCanceled()` ogni secondo).
- Se l'utente annulla a metà, chiedi se vuole caricare le feature scaricate finora.

## Deduplicazione in due fasi

### Fase 1 — Per attributo

Rimuovi le feature con lo stesso valore nel campo `gml_id` (oppure `inspireid` o `nationalCadastralReference` come fallback). Queste sono feature identiche restituite da tile adiacenti.

### Fase 2 — Per geometria (segnalazione, NON rimozione)

- Confronta le geometrie usando `geom.asWkt(precision=6)`.
- Le feature con geometria identica ma ID diverso vanno **mantenute tutte** nel layer finale.
- Aggiungi due campi attributo al layer:
  - `geom_duplicata` (String): `"si"` o `"no"`
  - `gruppo_duplicato` (Int): numero progressivo del gruppo (stesso numero = stessa geometria), `NULL` se non è duplicata.
- Stampa nella console un report dettagliato: numero di gruppi, e per i primi 10 gruppi mostra gli ID delle feature coinvolte e il bbox.

### Fase 3 — Filtro spaziale (opzionale, per asse stradale)

Se `filter_geom` è presente (modalità asse stradale):

- Dopo la deduplicazione, filtra le feature che **intersecano** effettivamente il buffer usando `geom.intersects(filter_geom)`.
- Mantieni la mappatura dei duplicati aggiornando gli indici.
- Stampa nella console quante feature sono state escluse perché non intersecano il buffer.
- Il layer finale conterrà **solo** le particelle che toccano il buffer dell'asse stradale.

## Creazione layer temporaneo in memoria

- NON salvare nulla su disco. Crea un layer memory: `QgsVectorLayer("GeomType?crs=EPSG:...", "nome", "memory")`.
- Nome del layer:
  - `"Particelle Catastali WFS"` per le modalità BBox e Poligono
  - `"Particelle Catastali WFS (buffer asse)"` per la modalità Asse Stradale
- Copia i campi originali dal GML più i due campi aggiunti (`geom_duplicata`, `gruppo_duplicato`).
- Copia le feature una per una impostando gli attributi originali e quelli di segnalazione.
- Aggiungi il layer al progetto con `QgsProject.instance().addMapLayer()`.

## Zoom sul layer caricato

Dopo aver aggiunto il layer, fai zoom sull'extent **trasformando le coordinate dal CRS del layer (EPSG:6706) al CRS del progetto** con `QgsCoordinateTransform` e `transformBoundingBox()`. Aggiungi un margine del 5% con `extent.scale(1.05)`. Questo è fondamentale: senza la trasformazione lo zoom va in una zona sbagliata se il progetto usa un CRS diverso da EPSG:6706.

## RubberBand visivi

Crea una funzione riutilizzabile `disegna_rubberband_da_rect(canvas, rect, colore_fill, colore_bordo)`:

- Colori come tuple RGBA.
- Prima di disegnare, rimuovi eventuali RubberBand precedenti (`pulisci_rubberband(canvas)`).
- Salva il riferimento in `canvas._wfs_rubberband`.

Colori usati:
- Anteprima disegno: blu tratteggiato (fill: 0,120,255,40 — bordo: 0,120,255,180)
- BBox definitivo disegnato: rosso (fill: 255,50,50,50 — bordo: 255,0,0,220)
- BBox poligono selezionato: verde (fill: 50,200,50,50 — bordo: 0,180,0,220)
- Buffer asse stradale: arancione (fill: 255,140,0,60 — bordo: 255,100,0,200)

## Log nella console

Ogni operazione significativa deve stampare informazioni nella console Python di QGIS con tag tra parentesi quadre: `[CRS]`, `[BBOX]`, `[BBOX WFS]`, `[TILING]`, `[WFS]`, `[POLIGONO]`, `[ASSE STRADALE]`, `[BUFFER]`, `[OTTIMIZZAZIONE]`, `[DEBUG]`, `[OK]`, `[ERRORE]`, `[AVVISO]`, `[INFO]`.

Il riepilogo finale deve mostrare: feature caricate, tile scaricati, tile saltate (se ottimizzazione buffer attiva), tile con errori, duplicati per attributo rimossi, geometrie duplicate segnalate, numero di gruppi duplicati, feature escluse dal filtro buffer, e suggerire il filtro `"geom_duplicata" = 'si'`.

## Costanti di configurazione

Metti all'inizio del file come costanti modificabili:

```python
WFS_CRS_ID = "EPSG:6706"
WFS_BASE_URL = "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?service=WFS&request=GetFeature&version=2.0.0&typeNames=CP:CadastralParcel"
MAX_TILE_KM2 = 4.0
PAUSA_SECONDI = 5
BUFFER_DISTANCE_M = 50  # Distanza buffer di default (utente può scegliere 0-100m nella GUI)
```

## Struttura del codice

Lo script deve essere un singolo file .py con questa struttura:

1. Docstring e import
2. Costanti di configurazione
3. Funzioni comuni: `pulisci_rubberband`, `disegna_rubberband_da_rect`, `trasforma_bbox_a_wfs`, `stima_area_km2`, `calcola_griglia_tile`, `scarica_singolo_tile`, `esegui_download_e_caricamento`
4. Classe `BBoxDrawTool(QgsMapTool)` — disegno interattivo
5. Classe `PolySelectTool(QgsMapTool)` — selezione poligono
6. Classe `LineSelectTool(QgsMapTool)` — selezione asse stradale con buffer
7. Classe `SceltaModalitaDialog(QDialog)` — GUI
8. Funzione `avvia()` e chiamata `avvia()`

## Import necessari

Usa solo moduli della libreria standard Python e dell'API PyQGIS/Qt già disponibili in QGIS:

```
math, os, re, tempfile, time, urllib.request
qgis.core: Qgis, QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem,
            QgsCoordinateTransform, QgsRectangle, QgsPointXY, QgsWkbTypes,
            QgsFeatureRequest, QgsGeometry, QgsFeature, QgsField, QgsFields
qgis.gui: QgsMapTool, QgsRubberBand
PyQt: Qt, QVariant, QTimer, QColor, QFont, QDialog, QVBoxLayout, QHBoxLayout,
      QLabel, QPushButton, QGroupBox, QSizePolicy, QMessageBox,
      QProgressDialog, QApplication, QSpinBox
qgis.utils: iface
```

## Note importanti

- Lo script viene eseguito nella Console Python di QGIS, non come plugin.
- Non salvare file su disco: tutto in memoria (layer memory + tempfile per il download GML che viene cancellato subito dopo).
- Compatibilità: `geometryType()` può restituire `Qgis.GeometryType.Polygon`/`Line` oppure i valori numerici `2`/`1` a seconda della versione di QGIS. Gestisci entrambi i casi.
- **Modalità Asse Stradale**: il layer lineare deve avere un CRS proiettato (metri) per calcolare correttamente il buffer. Se il CRS è geografico (gradi), mostra un errore e blocca l'operazione.
- **Ottimizzazione tile**: quando si usa il buffer, scarica solo le tile che intersecano effettivamente il buffer, non tutte quelle del bbox rettangolare. Questo riduce significativamente il tempo di download per assi obliqui o curvi.
- Commenta il codice in italiano.
