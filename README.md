# wfs_catasto_download_particelle_bbox

Questo progetto fornisce uno script Python con interfaccia grafica per scaricare particelle catastali tramite servizi WFS, utilizzando una bounding box (BBOX) come filtro geografico.

![](./screen.png)

## Funzionalità principali
- Download delle particelle catastali da servizi WFS
- Selezione dell'area di interesse tramite BBOX
- Interfaccia grafica semplice e intuitiva

## Requisiti
- Python 3.x
- Librerie: PyQt5, requests, xml, ecc. (vedi codice per dettagli)

## Utilizzo
1. Clona il repository:
   ```bash
   git clone https://github.com/pigreco/wfs_catasto_download_particelle_bbox.git
   ```
2. Installa le dipendenze necessarie.
3. Avvia lo script `wfs_catasto_gui.py` **dalla console Python di QGIS**.

> ⚠️ **Nota importante:**
> Questo script è pensato per essere eseguito dalla console Python di QGIS, non da una normale shell Python.

## Licenza
Questo progetto è distribuito con licenza MIT.

---

## Ringraziamenti
Un sentito grazie ad Andrea Borruso per l'idea e l'ispirazione.

## Avviso
Io non sono un developer, ma uso molto l'AI. Questo repository è interamente creato con l'aiuto di Claude AI.
