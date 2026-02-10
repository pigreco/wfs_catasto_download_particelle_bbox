"""
WFS Catasto Download Particelle BBox - Plugin Logic
====================================================
Logica principale del plugin: classe plugin, map tools, download WFS,
tiling, deduplicazione e filtro spaziale.

Compatibile con QGIS 3 (Qt5) e QGIS 4 (Qt6).

Autore: Salvatore Fiandaca
Email: pigrecoinfinito@gmail.com
"""

import math
import os
import tempfile
import time
import urllib.request
from datetime import datetime

from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsRectangle,
    QgsPointXY,
    QgsWkbTypes,
    QgsFeatureRequest,
    QgsGeometry,
    QgsFeature,
    QgsField,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, QVariant, QTimer
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QMessageBox,
    QProgressDialog,
    QApplication,
)
from qgis.utils import iface as qgis_iface

from .wfs_catasto_download_particelle_bbox_d import AvvisoDialog, SceltaModalitaDialog


# =============================================================================
# COMPATIBILITÀ QGIS 3 / QGIS 4 (Qt5 / Qt6)
# =============================================================================

# Tipo geometria per QgsRubberBand e controlli layer
try:
    _GEOM_POLYGON = Qgis.GeometryType.Polygon
    _GEOM_LINE = Qgis.GeometryType.Line
except AttributeError:
    _GEOM_POLYGON = QgsWkbTypes.PolygonGeometry
    _GEOM_LINE = QgsWkbTypes.LineGeometry


def _exec_dialog(dialog):
    """Esegue un dialog in modo compatibile con Qt5 e Qt6."""
    try:
        return dialog.exec()
    except AttributeError:
        return dialog.exec_()


def _wkb_display_string(wkb_type):
    """Restituisce il nome del tipo WKB, compatibile QGIS 3/4."""
    try:
        return QgsWkbTypes.displayString(wkb_type)
    except AttributeError:
        return str(wkb_type)


def _is_polygon_layer(layer):
    """Verifica se il layer è poligonale (compatibile QGIS 3/4)."""
    try:
        return layer.geometryType() == Qgis.GeometryType.Polygon
    except AttributeError:
        return layer.geometryType() == 2


def _is_line_layer(layer):
    """Verifica se il layer è lineare (compatibile QGIS 3/4)."""
    try:
        return layer.geometryType() == Qgis.GeometryType.Line
    except AttributeError:
        return layer.geometryType() == 1


# Qt enum scoped (Qt6) vs flat (Qt5)
try:
    _WindowModal = Qt.WindowModality.WindowModal
    _DashLine = Qt.PenStyle.DashLine
    _DialogAccepted = QDialog.DialogCode.Accepted
except AttributeError:
    _WindowModal = Qt.WindowModal
    _DashLine = Qt.DashLine
    _DialogAccepted = QDialog.Accepted


# =============================================================================
# CONFIGURAZIONE
# =============================================================================
WFS_CRS_ID = "EPSG:6706"
WFS_BASE_URL = (
    "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?"
    "service=WFS&request=GetFeature&version=2.0.0"
    "&typeNames=CP:CadastralParcel"
)
# Area massima per singola tile in km² (soglia sicurezza WFS)
MAX_TILE_KM2 = 4.0
# Pausa tra le chiamate WFS in secondi
PAUSA_SECONDI = 5
# Distanza buffer in metri di default
BUFFER_DISTANCE_M = 50


# =============================================================================
# FUNZIONI COMUNI
# =============================================================================

def pulisci_rubberband(canvas):
    """Rimuove eventuali rubber band precedenti dal canvas."""
    if hasattr(canvas, '_wfs_rubberband') and canvas._wfs_rubberband:
        canvas.scene().removeItem(canvas._wfs_rubberband)
        canvas._wfs_rubberband = None


def disegna_rubberband_da_rect(canvas, rect, colore_fill, colore_bordo):
    """Disegna un QgsRubberBand rettangolare sul canvas."""
    pulisci_rubberband(canvas)
    rb = QgsRubberBand(canvas, _GEOM_POLYGON)
    rb.setColor(QColor(*colore_fill))
    rb.setStrokeColor(QColor(*colore_bordo))
    rb.setWidth(2)
    rb.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()))
    rb.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()))
    rb.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()))
    rb.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()))
    rb.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()))
    rb.show()
    canvas._wfs_rubberband = rb
    return rb


def trasforma_bbox_a_wfs(rect, source_crs):
    """
    Trasforma un QgsRectangle dal CRS sorgente a EPSG:6706.
    Restituisce (min_lat, min_lon, max_lat, max_lon).
    """
    wfs_crs = QgsCoordinateReferenceSystem(WFS_CRS_ID)

    if source_crs.authid() == wfs_crs.authid():
        print(f"[CRS] Il CRS sorgente è già {WFS_CRS_ID}, nessuna riproiezione necessaria.")
        min_lon = rect.xMinimum()
        max_lon = rect.xMaximum()
        min_lat = rect.yMinimum()
        max_lat = rect.yMaximum()
    else:
        print(f"[CRS] Riproiezione da {source_crs.authid()} a {WFS_CRS_ID}...")
        transform = QgsCoordinateTransform(source_crs, wfs_crs, QgsProject.instance())
        rect_wfs = transform.transformBoundingBox(rect)
        min_lon = rect_wfs.xMinimum()
        max_lon = rect_wfs.xMaximum()
        min_lat = rect_wfs.yMinimum()
        max_lat = rect_wfs.yMaximum()

    print(f"[BBOX WFS] min_lat={min_lat:.7f}, min_lon={min_lon:.7f}")
    print(f"           max_lat={max_lat:.7f}, max_lon={max_lon:.7f}")
    return min_lat, min_lon, max_lat, max_lon


def stima_area_km2(min_lat, min_lon, max_lat, max_lon):
    """Stima approssimativa dell'area del bbox in km²."""
    delta_lat = max_lat - min_lat
    delta_lon = max_lon - min_lon
    lat_media = (min_lat + max_lat) / 2.0
    km_per_lat = 111.0
    km_per_lon = 111.0 * math.cos(math.radians(lat_media))
    return (delta_lat * km_per_lat) * (delta_lon * km_per_lon)


def calcola_griglia_tile(min_lat, min_lon, max_lat, max_lon, max_tile_km2):
    """
    Suddivide il bbox in una griglia di tile, ciascuna con area <= max_tile_km2.
    Restituisce una lista di tuple (min_lat, min_lon, max_lat, max_lon) per ogni tile.
    """
    area_totale = stima_area_km2(min_lat, min_lon, max_lat, max_lon)

    if area_totale <= max_tile_km2:
        return [(min_lat, min_lon, max_lat, max_lon)]

    # Calcola quanti tile servono
    n_tiles_necessari = math.ceil(area_totale / max_tile_km2)
    # Distribuisci su righe e colonne (griglia ~quadrata)
    n_cols = math.ceil(math.sqrt(n_tiles_necessari))
    n_rows = math.ceil(n_tiles_necessari / n_cols)

    delta_lat = (max_lat - min_lat) / n_rows
    delta_lon = (max_lon - min_lon) / n_cols

    tiles = []
    for r in range(n_rows):
        for c in range(n_cols):
            t_min_lat = min_lat + r * delta_lat
            t_max_lat = min_lat + (r + 1) * delta_lat
            t_min_lon = min_lon + c * delta_lon
            t_max_lon = min_lon + (c + 1) * delta_lon
            tiles.append((t_min_lat, t_min_lon, t_max_lat, t_max_lon))

    print(f"\n[TILING] Area totale: ~{area_totale:.1f} km²")
    print(f"[TILING] Griglia: {n_rows} righe x {n_cols} colonne = {len(tiles)} tile")
    print(f"[TILING] Area per tile: ~{area_totale / len(tiles):.2f} km²")

    return tiles


def scarica_singolo_tile(min_lat, min_lon, max_lat, max_lon):
    """
    Scarica un singolo tile WFS.
    Restituisce (lista_feature, info_dict) oppure (None, None) in caso di errore.
    """
    bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon},urn:ogc:def:crs:EPSG::6706"
    wfs_url = f"{WFS_BASE_URL}&bbox={bbox_str}"

    try:
        tmp_file = tempfile.NamedTemporaryFile(
            suffix=".gml", prefix="wfs_tile_", delete=False
        )
        tmp_path = tmp_file.name
        tmp_file.close()

        if not wfs_url.startswith("https://"):
            raise ValueError(f"Schema URL non permesso: {wfs_url}")
        urllib.request.urlretrieve(wfs_url, tmp_path)  # noqa: S310

        # Verifica errori nel contenuto
        with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
            contenuto = f.read(2048)
        if '<ExceptionReport' in contenuto or '<ows:ExceptionReport' in contenuto:
            print("  [ERRORE] Il server ha restituito un errore per questo tile")
            os.remove(tmp_path)
            return None, None

        # Carica con OGR
        tmp_layer = QgsVectorLayer(tmp_path, "tile_tmp", "ogr")
        if not tmp_layer.isValid():
            os.remove(tmp_path)
            return None, None

        features = list(tmp_layer.getFeatures())
        fields = tmp_layer.fields()
        wkb_type = tmp_layer.wkbType()
        crs = tmp_layer.crs()

        # Pulizia
        del tmp_layer
        try:
            os.remove(tmp_path)
            xsd_path = tmp_path.replace('.gml', '.xsd')
            if os.path.exists(xsd_path):
                os.remove(xsd_path)
        except Exception:
            pass

        return features, {"fields": fields, "wkb_type": wkb_type, "crs": crs}

    except Exception as e:
        print(f"  [ERRORE] Download tile fallito: {e}")
        return None, None


def esegui_download_e_caricamento(min_lat, min_lon, max_lat, max_lon, filter_geom=None,
                                  layer_name="Particelle WFS",
                                  espandi_catastale=False):
    """
    Gestisce il download WFS: singolo o multi-tile con progress bar.

    Args:
        min_lat, min_lon, max_lat, max_lon: Coordinate bbox in EPSG:6706
        filter_geom: (opzionale) QgsGeometry in EPSG:6706 per filtrare le feature
        layer_name: (opzionale) Nome del layer di output
                     che intersecano questa geometria (es. buffer asse stradale)
    """
    area_km2 = stima_area_km2(min_lat, min_lon, max_lat, max_lon)
    print(f"\n[BBOX] Dimensione stimata: ~{area_km2:.1f} km²")

    # --- Calcola griglia tile ---
    tiles = calcola_griglia_tile(min_lat, min_lon, max_lat, max_lon, MAX_TILE_KM2)
    n_tiles_totali = len(tiles)

    # --- Filtra tile che intersecano il buffer (ottimizzazione per asse stradale) ---
    tiles_saltate = 0
    if filter_geom is not None and n_tiles_totali > 1:
        tiles_filtrate = []
        for tile in tiles:
            t_min_lat, t_min_lon, t_max_lat, t_max_lon = tile
            # Crea geometria rettangolare della tile (in coordinate WFS/EPSG:6706)
            tile_rect = QgsRectangle(t_min_lon, t_min_lat, t_max_lon, t_max_lat)
            tile_geom = QgsGeometry.fromRect(tile_rect)
            # Verifica intersezione con il buffer
            if tile_geom.intersects(filter_geom):
                tiles_filtrate.append(tile)
            else:
                tiles_saltate += 1

        if tiles_saltate > 0:
            print(f"\n[OTTIMIZZAZIONE] Tile nel bbox totale: {n_tiles_totali}")
            print(f"[OTTIMIZZAZIONE] Tile che intersecano il buffer: {len(tiles_filtrate)}")
            print(f"[OTTIMIZZAZIONE] Tile saltate: {tiles_saltate}")

        tiles = tiles_filtrate

    n_tiles = len(tiles)

    if n_tiles > 1:
        # Chiedi conferma per download multiplo
        tempo_stimato = n_tiles * PAUSA_SECONDI
        minuti = tempo_stimato // 60
        secondi = tempo_stimato % 60
        tempo_str = f"{minuti} min {secondi} sec" if minuti > 0 else f"{secondi} sec"

        # Messaggio diverso se ci sono tile saltate (ottimizzazione buffer)
        if tiles_saltate > 0:
            msg = (
                f"L'area selezionata (~{area_km2:.1f} km²) richiede {n_tiles_totali} tile,\n"
                f"ma solo {n_tiles} intersecano il buffer dell'asse stradale.\n\n"
                f"Tile da scaricare: {n_tiles} (saltate: {tiles_saltate})\n"
                f"Tempo stimato: ~{tempo_str}\n"
                f"(pausa di {PAUSA_SECONDI} sec tra ogni chiamata)\n\n"
                f"Vuoi procedere?"
            )
        else:
            msg = (
                f"L'area selezionata (~{area_km2:.1f} km²) verrà suddivisa\n"
                f"in {n_tiles} tile per rispettare i limiti del server WFS.\n\n"
                f"Tempo stimato: ~{tempo_str}\n"
                f"(pausa di {PAUSA_SECONDI} sec tra ogni chiamata)\n\n"
                f"Vuoi procedere?"
            )
        risposta = QMessageBox.question(
            qgis_iface.mainWindow(),
            f"Download multi-tile ({n_tiles} tile)",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if risposta == QMessageBox.No:
            print("[INFO] Download annullato dall'utente.")
            return
    else:
        print("[TILING] Area piccola, download singolo (1 tile)")

    # --- Progress Dialog ---
    progress = QProgressDialog(
        "Download particelle catastali...",
        "Annulla",
        0,
        n_tiles,
        qgis_iface.mainWindow(),
    )
    progress.setWindowTitle("WFS Catasto - Download")
    progress.setWindowModality(_WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.show()
    QApplication.processEvents()

    # --- Download tile per tile ---
    all_features = []
    layer_info = None
    errori = 0
    annullato = False

    for i, (t_min_lat, t_min_lon, t_max_lat, t_max_lon) in enumerate(tiles):
        if progress.wasCanceled():
            annullato = True
            print("[INFO] Download annullato dall'utente.")
            break

        tile_label = f"Tile {i + 1}/{n_tiles}"
        progress.setLabelText(
            f"{tile_label}\n"
            f"Feature scaricate: {len(all_features)}\n"
            f"Errori: {errori}"
        )
        progress.setValue(i)
        QApplication.processEvents()

        tile_area = stima_area_km2(t_min_lat, t_min_lon, t_max_lat, t_max_lon)
        print(f"\n--- {tile_label} (~{tile_area:.2f} km²) ---")
        print(f"    bbox: {t_min_lat:.7f},{t_min_lon:.7f},{t_max_lat:.7f},{t_max_lon:.7f}")

        features, info = scarica_singolo_tile(t_min_lat, t_min_lon, t_max_lat, t_max_lon)

        if features is not None:
            print(f"    [OK] {len(features)} feature(s)")
            all_features.extend(features)
            if layer_info is None and info is not None:
                layer_info = info
        else:
            errori += 1
            print("    [ERRORE] Tile fallito")

        # Pausa tra le chiamate (non dopo l'ultimo tile)
        if i < n_tiles - 1 and not progress.wasCanceled():
            for sec in range(PAUSA_SECONDI):
                if progress.wasCanceled():
                    annullato = True
                    break
                progress.setLabelText(
                    f"{tile_label} completato\n"
                    f"Feature scaricate: {len(all_features)}\n"
                    f"Attesa: {PAUSA_SECONDI - sec} sec..."
                )
                QApplication.processEvents()
                time.sleep(1)

    progress.setValue(n_tiles)
    QApplication.processEvents()

    if annullato:
        progress.close()
        if len(all_features) == 0:
            print("[INFO] Nessuna feature scaricata.")
            return
        risposta = QMessageBox.question(
            qgis_iface.mainWindow(),
            "Download interrotto",
            f"Download annullato.\n\n"
            f"Sono state scaricate {len(all_features)} feature.\n"
            f"Vuoi caricarle comunque?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if risposta == QMessageBox.No:
            return

    progress.close()

    # --- Verifica risultati ---
    if len(all_features) == 0:
        print("[AVVISO] Nessuna feature scaricata.")
        QMessageBox.warning(
            qgis_iface.mainWindow(),
            "Nessuna feature",
            "Il download non ha prodotto risultati.\n\n"
            "Possibili cause:\n"
            "- Non ci sono particelle catastali in quest'area\n"
            "- Il server WFS non è raggiungibile",
        )
        return

    if layer_info is None:
        print("[ERRORE] Impossibile determinare la struttura del layer.")
        return

    # --- Deduplicazione feature ---
    print("\n--- Deduplicazione ---")
    print(f"    Feature totali scaricate: {len(all_features)}")

    # FASE 1: Deduplicazione per attributo (gml_id, inspireid, ecc.)
    campo_id_usato = None
    for campo in ['gml_id', 'inspireid', 'nationalCadastralReference']:
        idx = layer_info["fields"].indexOf(campo)
        if idx >= 0:
            campo_id_usato = campo
            break

    seen_ids = set()
    dopo_dedup_id = []
    duplicati_id = 0

    if campo_id_usato:
        idx_campo = layer_info["fields"].indexOf(campo_id_usato)
        print(f"    Campo chiave per dedup: '{campo_id_usato}'")
        for feat in all_features:
            fid = feat.attribute(idx_campo)
            if fid not in seen_ids:
                seen_ids.add(fid)
                dopo_dedup_id.append(feat)
            else:
                duplicati_id += 1
    else:
        print("    [AVVISO] Nessun campo ID trovato, salto dedup per attributo")
        dopo_dedup_id = list(all_features)

    if duplicati_id > 0:
        print(f"    Duplicati per attributo rimossi: {duplicati_id}")
    else:
        print("    Nessun duplicato per attributo")

    # FASE 2: Verifica geometrie duplicate (stessa geometria, ID diverso)
    # Le feature vengono MANTENUTE tutte, ma segnalate con un campo attributo
    print("\n--- Verifica geometrie duplicate ---")
    seen_geom = {}  # wkt -> lista di indici in dopo_dedup_id

    for i, feat in enumerate(dopo_dedup_id):
        geom = feat.geometry()
        if geom.isNull() or geom.isEmpty():
            continue
        wkt = geom.asWkt(precision=6)
        if wkt in seen_geom:
            seen_geom[wkt].append(i)
        else:
            seen_geom[wkt] = [i]

    # Mappa indice feature -> (è_duplicata, numero_gruppo)
    geom_dup_map = {}
    geom_duplicati_gruppi = []
    duplicati_geom = 0
    gruppo_num = 0

    for wkt, indici in seen_geom.items():
        if len(indici) > 1:
            gruppo_num += 1
            duplicati_geom += len(indici)
            geom_duplicati_gruppi.append(indici)
            for idx in indici:
                geom_dup_map[idx] = (True, gruppo_num)
        else:
            geom_dup_map[indici[0]] = (False, 0)

    if duplicati_geom > 0:
        print(f"    [ATTENZIONE] {duplicati_geom} feature con geometria duplicata!")
        print(f"    Gruppi di geometrie identiche: {len(geom_duplicati_gruppi)}")
        for g_idx, indici in enumerate(geom_duplicati_gruppi[:10]):
            ids_nel_gruppo = []
            for idx in indici:
                f = dopo_dedup_id[idx]
                if campo_id_usato:
                    idx_campo = layer_info["fields"].indexOf(campo_id_usato)
                    ids_nel_gruppo.append(str(f.attribute(idx_campo)))
                else:
                    ids_nel_gruppo.append(str(f.id()))
            bbox_g = dopo_dedup_id[indici[0]].geometry().boundingBox()
            print(f"      Gruppo {g_idx + 1}: {len(indici)} feature "
                  f"(IDs: {', '.join(ids_nel_gruppo)}) "
                  f"bbox: [{bbox_g.xMinimum():.5f},{bbox_g.yMinimum():.5f}]")
        if len(geom_duplicati_gruppi) > 10:
            print(f"      ... e altri {len(geom_duplicati_gruppi) - 10} gruppi")
    else:
        print("    Nessuna geometria duplicata trovata")

    # Riepilogo deduplicazione
    print("\n    --- Riepilogo ---")
    print(f"    Feature iniziali:              {len(all_features)}")
    print(f"    Duplicati per attributo:        {duplicati_id} (rimossi)")
    print(f"    Geometrie duplicate:            {duplicati_geom} (mantenute, segnalate)")
    print(f"    Feature finali:                 {len(dopo_dedup_id)}")

    # --- FASE 3: Filtro spaziale (opzionale, per asse stradale) ---
    filtrate_spaziale = 0
    if filter_geom is not None:
        print("\n--- Filtro spaziale (intersezione con buffer) ---")
        features_filtrate = []
        nuova_geom_dup_map = {}

        for i, feat in enumerate(dopo_dedup_id):
            geom = feat.geometry()
            if geom.isNull() or geom.isEmpty():
                continue
            if geom.intersects(filter_geom):
                nuovo_idx = len(features_filtrate)
                features_filtrate.append(feat)
                # Mantieni info duplicati con nuovo indice
                if i in geom_dup_map:
                    nuova_geom_dup_map[nuovo_idx] = geom_dup_map[i]

        filtrate_spaziale = len(dopo_dedup_id) - len(features_filtrate)
        print(f"    Feature nel bbox:              {len(dopo_dedup_id)}")
        print(f"    Feature che intersecano buffer: {len(features_filtrate)}")
        print(f"    Feature escluse:               {filtrate_spaziale}")

        dopo_dedup_id = features_filtrate
        geom_dup_map = nuova_geom_dup_map

    # Tutte le feature vengono mantenute
    unique_features = dopo_dedup_id

    # --- Crea layer temporaneo in memoria ---
    print("\n--- Creazione layer temporaneo ---")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    layer_name = f"{layer_name}_{timestamp}"
    geom_type_str = _wkb_display_string(layer_info["wkb_type"])
    crs = layer_info["crs"]
    mem_uri = f"{geom_type_str}?crs={crs.authid()}"

    mem_layer = QgsVectorLayer(mem_uri, layer_name, "memory")
    mem_provider = mem_layer.dataProvider()

    # Copia campi originali + aggiungi campi segnalazione duplicati
    original_fields = layer_info["fields"].toList()
    original_fields.append(QgsField("geom_duplicata", QVariant.String))
    original_fields.append(QgsField("gruppo_duplicato", QVariant.Int))
    if espandi_catastale:
        original_fields.append(QgsField("sezione", QVariant.String))
        original_fields.append(QgsField("foglio", QVariant.Int))
        original_fields.append(QgsField("allegato", QVariant.String))
        original_fields.append(QgsField("sviluppo", QVariant.String))
    mem_provider.addAttributes(original_fields)
    mem_layer.updateFields()

    # Indici dei nuovi campi
    idx_geom_dup = mem_layer.fields().indexOf("geom_duplicata")
    idx_gruppo_dup = mem_layer.fields().indexOf("gruppo_duplicato")
    if espandi_catastale:
        idx_sezione = mem_layer.fields().indexOf("sezione")
        idx_foglio = mem_layer.fields().indexOf("foglio")
        idx_allegato = mem_layer.fields().indexOf("allegato")
        idx_sviluppo = mem_layer.fields().indexOf("sviluppo")
        idx_ncr = layer_info["fields"].indexOf("NATIONALCADASTRALREFERENCE")

    # Copia feature con attributi di segnalazione
    new_features = []
    for i, feat in enumerate(unique_features):
        new_feat = QgsFeature(mem_layer.fields())
        new_feat.setGeometry(feat.geometry())

        # Copia attributi originali
        for field_idx in range(layer_info["fields"].count()):
            field_name = layer_info["fields"].field(field_idx).name()
            new_field_idx = mem_layer.fields().indexOf(field_name)
            if new_field_idx >= 0:
                new_feat.setAttribute(new_field_idx, feat.attribute(field_idx))

        # Imposta segnalazione duplicato
        is_dup, grp = geom_dup_map.get(i, (False, 0))
        new_feat.setAttribute(idx_geom_dup, "si" if is_dup else "no")
        new_feat.setAttribute(idx_gruppo_dup, grp if is_dup else None)

        # Parsing NATIONALCADASTRALREFERENCE (formato CCCCZFFFFAS.particella)
        if espandi_catastale and idx_ncr >= 0:
            ncr = feat.attribute(idx_ncr)
            if ncr and isinstance(ncr, str):
                codice = ncr.split(".")[0]  # parte prima del punto
                if len(codice) == 11:  # CCCCZFFFFAS = 11 caratteri
                    sez = codice[4]  # Z: sezione censuaria
                    new_feat.setAttribute(idx_sezione, "" if sez == "_" else sez)
                    try:
                        new_feat.setAttribute(idx_foglio, int(codice[5:9]))
                    except ValueError:
                        new_feat.setAttribute(idx_foglio, None)
                    new_feat.setAttribute(idx_allegato, codice[9])
                    new_feat.setAttribute(idx_sviluppo, codice[10])

        new_features.append(new_feat)

    mem_provider.addFeatures(new_features)
    mem_layer.updateExtents()

    # Aggiungi al progetto
    QgsProject.instance().addMapLayer(mem_layer)
    feat_count = mem_layer.featureCount()

    print(f"[OK] Layer temporaneo caricato con {feat_count} feature(s)")
    print(f"     CRS: {crs.authid()}")
    print(f"     Geometria: {geom_type_str}")
    print("     Campi aggiunti: 'geom_duplicata' (si/no), 'gruppo_duplicato' (n. gruppo)")
    if espandi_catastale:
        print("     Campi catastali: 'sezione', 'foglio', 'allegato', 'sviluppo'")

    # Zoom sul layer (trasforma extent nel CRS del progetto)
    canvas = qgis_iface.mapCanvas()
    project_crs = QgsProject.instance().crs()
    layer_extent = mem_layer.extent()

    if crs.authid() != project_crs.authid():
        transform_to_project = QgsCoordinateTransform(
            crs, project_crs, QgsProject.instance()
        )
        extent_proj = transform_to_project.transformBoundingBox(layer_extent)
    else:
        extent_proj = layer_extent

    extent_proj.scale(1.05)  # margine del 5%
    canvas.setExtent(extent_proj)
    canvas.refresh()

    # Riepilogo finale
    print("\n" + "=" * 60)
    print("  COMPLETATO!")
    print(f"  Feature caricate:         {feat_count}")
    print(f"  Tile scaricati:           {n_tiles - errori}/{n_tiles}")
    if tiles_saltate > 0:
        print(f"  Tile saltate (no inters.): {tiles_saltate}")
    if errori > 0:
        print(f"  Tile con errori:          {errori}")
    if duplicati_id > 0:
        print(f"  Duplicati (attributo):    {duplicati_id} rimossi")
    if duplicati_geom > 0:
        print(f"  Geometrie duplicate:      {duplicati_geom} segnalate")
        print(f"  Gruppi duplicati:         {len(geom_duplicati_gruppi)}")
        print("  Filtra con: \"geom_duplicata\" = 'si'")
    if filtrate_spaziale > 0:
        print(f"  Filtro buffer:            {filtrate_spaziale} escluse (non intersecano)")
    print("=" * 60)


# =============================================================================
# TOOL 1: DISEGNA BBOX (due click)
# =============================================================================

class BBoxDrawTool(QgsMapTool):
    """
    Tool interattivo: clicca il primo angolo, anteprima in tempo reale,
    clicca il secondo angolo per confermare e avviare il download.
    """

    def __init__(self, canvas, on_completed=None, espandi_catastale=False):
        super().__init__(canvas)
        self.canvas = canvas
        self.first_point = None
        self.preview_rb = None
        self.on_completed = on_completed
        self.espandi_catastale = espandi_catastale
        self._create_preview_rubberband()

    def _create_preview_rubberband(self):
        self.preview_rb = QgsRubberBand(self.canvas, _GEOM_POLYGON)
        self.preview_rb.setColor(QColor(0, 120, 255, 40))
        self.preview_rb.setStrokeColor(QColor(0, 120, 255, 180))
        self.preview_rb.setWidth(2)
        self.preview_rb.setLineStyle(_DashLine)

    def _update_preview(self, second_point):
        if not self.first_point:
            return
        self.preview_rb.reset(_GEOM_POLYGON)
        p1 = self.first_point
        p2 = second_point
        self.preview_rb.addPoint(QgsPointXY(p1.x(), p1.y()))
        self.preview_rb.addPoint(QgsPointXY(p2.x(), p1.y()))
        self.preview_rb.addPoint(QgsPointXY(p2.x(), p2.y()))
        self.preview_rb.addPoint(QgsPointXY(p1.x(), p2.y()))
        self.preview_rb.addPoint(QgsPointXY(p1.x(), p1.y()))
        self.preview_rb.show()

    def canvasPressEvent(self, event):
        point = self.toMapCoordinates(event.pos())

        if self.first_point is None:
            self.first_point = point
            print(f"\n[BBOX] Primo angolo: ({point.x():.6f}, {point.y():.6f})")
            print("[BBOX] Muovi il mouse e clicca per il secondo angolo...")
        else:
            second_point = point
            print(f"[BBOX] Secondo angolo: ({second_point.x():.6f}, {second_point.y():.6f})")

            # Rimuovi anteprima
            self.preview_rb.reset()
            self.canvas.scene().removeItem(self.preview_rb)

            # Calcola rettangolo
            rect = QgsRectangle(
                min(self.first_point.x(), second_point.x()),
                min(self.first_point.y(), second_point.y()),
                max(self.first_point.x(), second_point.x()),
                max(self.first_point.y(), second_point.y()),
            )

            # Trasforma e scarica
            project_crs = QgsProject.instance().crs()
            print(f"\n[CRS] CRS del progetto: {project_crs.authid()}")
            min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(rect, project_crs)
            esegui_download_e_caricamento(
                min_lat, min_lon, max_lat, max_lon,
                layer_name="Particelle WFS (BBox)",
                espandi_catastale=self.espandi_catastale
            )

            # Ripristina Pan e riapri dialog
            qgis_iface.actionPan().trigger()
            if self.on_completed:
                self.on_completed()

    def canvasMoveEvent(self, event):
        if self.first_point is not None:
            point = self.toMapCoordinates(event.pos())
            self._update_preview(point)

    def deactivate(self):
        if self.preview_rb:
            self.preview_rb.reset()
            try:
                self.canvas.scene().removeItem(self.preview_rb)
            except Exception:
                pass
        super().deactivate()


# =============================================================================
# TOOL 2: SELEZIONA POLIGONO
# =============================================================================

class PolySelectTool(QgsMapTool):
    """
    Tool per selezionare un poligono esistente sulla mappa.
    Estrae il bbox della geometria e avvia il download WFS.
    """

    def __init__(self, canvas, on_completed=None, espandi_catastale=False):
        super().__init__(canvas)
        self.canvas = canvas
        self.on_completed = on_completed
        self.espandi_catastale = espandi_catastale

    def canvasPressEvent(self, event):
        click_map_point = self.toMapCoordinates(event.pos())
        project_crs = QgsProject.instance().crs()

        print(f"\n[DEBUG] Click alle coordinate progetto ({project_crs.authid()}): "
              f"({click_map_point.x():.6f}, {click_map_point.y():.6f})")

        poly_layers = []
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and _is_polygon_layer(lyr):
                poly_layers.append(lyr.name())
        print(f"[DEBUG] Layer poligonali trovati: {poly_layers if poly_layers else 'NESSUNO'}")

        found = False
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not _is_polygon_layer(layer):
                continue

            layer_crs = layer.crs()

            if project_crs.authid() != layer_crs.authid():
                to_layer = QgsCoordinateTransform(
                    project_crs, layer_crs, QgsProject.instance()
                )
                click_layer_point = to_layer.transform(click_map_point)
            else:
                click_layer_point = click_map_point

            tolerance = self.canvas.mapUnitsPerPixel() * 10
            if project_crs.authid() != layer_crs.authid():
                tolerance_layer = tolerance * 2
            else:
                tolerance_layer = tolerance

            search_rect = QgsRectangle(
                click_layer_point.x() - tolerance_layer,
                click_layer_point.y() - tolerance_layer,
                click_layer_point.x() + tolerance_layer,
                click_layer_point.y() + tolerance_layer,
            )

            request = QgsFeatureRequest().setFilterRect(search_rect)
            click_geom = QgsGeometry.fromPointXY(click_layer_point)

            for feat in layer.getFeatures(request):
                geom = feat.geometry()
                if geom.isNull() or geom.isEmpty():
                    continue
                if not geom.contains(click_geom):
                    continue

                found = True
                feat_id = feat.id()
                layer_name = layer.name()

                print("\n[POLIGONO] Feature selezionata:")
                print(f"           Layer: {layer_name}")
                print(f"           Feature ID: {feat_id}")
                print(f"           CRS del layer: {layer_crs.authid()}")

                bbox = geom.boundingBox()
                print(f"[POLIGONO] BBox geometria ({layer_crs.authid()}):")
                print(f"           xMin={bbox.xMinimum():.7f}, yMin={bbox.yMinimum():.7f}")
                print(f"           xMax={bbox.xMaximum():.7f}, yMax={bbox.yMaximum():.7f}")

                print(f"\n[CRS] CRS del layer sorgente: {layer_crs.authid()}")
                min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(
                    bbox, layer_crs
                )

                # Trasforma la geometria del poligono in EPSG:6706 per il filtering
                wfs_crs = QgsCoordinateReferenceSystem(WFS_CRS_ID)
                if layer_crs.authid() != wfs_crs.authid():
                    transform_to_wfs = QgsCoordinateTransform(
                        layer_crs, wfs_crs, QgsProject.instance()
                    )
                    poly_geom_wfs = QgsGeometry(geom)
                    poly_geom_wfs.transform(transform_to_wfs)
                else:
                    poly_geom_wfs = geom

                esegui_download_e_caricamento(
                    min_lat, min_lon, max_lat, max_lon,
                    filter_geom=poly_geom_wfs,
                    layer_name="Particelle WFS (Poligono)",
                    espandi_catastale=self.espandi_catastale
                )

                qgis_iface.actionPan().trigger()
                if self.on_completed:
                    self.on_completed()
                return

        if not found:
            print("[POLIGONO] Nessun poligono trovato nel punto cliccato. Riprova.")

    def deactivate(self):
        super().deactivate()


# =============================================================================
# TOOL 3: SELEZIONA LINEA (linea + buffer)
# =============================================================================

class LineSelectTool(QgsMapTool):
    """
    Tool per selezionare una linea sulla mappa.
    Crea un buffer e scarica le particelle che intersecano il buffer.
    """

    def __init__(self, canvas, buffer_distance=BUFFER_DISTANCE_M, on_completed=None,
                 espandi_catastale=False):
        super().__init__(canvas)
        self.canvas = canvas
        self.buffer_distance = buffer_distance
        self.buffer_rb = None  # Rubberband per visualizzare il buffer
        self.espandi_catastale = espandi_catastale
        self.on_completed = on_completed

    def _visualizza_buffer(self, buffer_geom, buffer_crs):
        """Visualizza il buffer sulla mappa."""
        # Rimuovi eventuale rubberband precedente
        if self.buffer_rb:
            self.canvas.scene().removeItem(self.buffer_rb)
            self.buffer_rb = None

        # Trasforma nel CRS del progetto se necessario
        project_crs = QgsProject.instance().crs()
        if buffer_crs.authid() != project_crs.authid():
            transform = QgsCoordinateTransform(
                buffer_crs, project_crs, QgsProject.instance()
            )
            buffer_geom_proj = QgsGeometry(buffer_geom)
            buffer_geom_proj.transform(transform)
        else:
            buffer_geom_proj = buffer_geom

        # Crea rubberband arancione per il buffer
        self.buffer_rb = QgsRubberBand(self.canvas, _GEOM_POLYGON)
        self.buffer_rb.setColor(QColor(255, 140, 0, 60))
        self.buffer_rb.setStrokeColor(QColor(255, 100, 0, 200))
        self.buffer_rb.setWidth(2)
        self.buffer_rb.setToGeometry(buffer_geom_proj, None)
        self.buffer_rb.show()

    def canvasPressEvent(self, event):
        click_map_point = self.toMapCoordinates(event.pos())
        project_crs = QgsProject.instance().crs()

        print(f"\n[DEBUG] Click alle coordinate progetto ({project_crs.authid()}): "
              f"({click_map_point.x():.6f}, {click_map_point.y():.6f})")

        # Trova layer lineari
        line_layers = []
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and _is_line_layer(lyr):
                line_layers.append(lyr.name())
        print(f"[DEBUG] Layer lineari trovati: {line_layers if line_layers else 'NESSUNO'}")

        found = False
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not _is_line_layer(layer):
                continue

            layer_crs = layer.crs()

            # Trasforma punto click nel CRS del layer
            if project_crs.authid() != layer_crs.authid():
                to_layer = QgsCoordinateTransform(
                    project_crs, layer_crs, QgsProject.instance()
                )
                click_layer_point = to_layer.transform(click_map_point)
            else:
                click_layer_point = click_map_point

            # Crea area di ricerca
            tolerance = self.canvas.mapUnitsPerPixel() * 15
            if project_crs.authid() != layer_crs.authid():
                tolerance_layer = tolerance * 2
            else:
                tolerance_layer = tolerance

            search_rect = QgsRectangle(
                click_layer_point.x() - tolerance_layer,
                click_layer_point.y() - tolerance_layer,
                click_layer_point.x() + tolerance_layer,
                click_layer_point.y() + tolerance_layer,
            )

            request = QgsFeatureRequest().setFilterRect(search_rect)
            click_geom = QgsGeometry.fromPointXY(click_layer_point)

            # Trova la linea più vicina
            min_distance = float('inf')
            closest_feature = None
            closest_layer = None

            for feat in layer.getFeatures(request):
                geom = feat.geometry()
                if geom.isNull() or geom.isEmpty():
                    continue
                distance = geom.distance(click_geom)
                if distance < min_distance:
                    min_distance = distance
                    closest_feature = feat
                    closest_layer = layer

            if closest_feature is not None and min_distance <= tolerance_layer:
                found = True
                layer_crs = closest_layer.crs()

                # Controlla se il CRS è proiettato
                if layer_crs.isGeographic():
                    print(f"\n[ERRORE] Il layer '{closest_layer.name()}' usa un CRS "
                          f"geografico ({layer_crs.authid()}).")
                    print(f"         Per calcolare correttamente il buffer di "
                          f"{self.buffer_distance}m,")
                    print("         riproietta il layer in un CRS proiettato "
                          "(es. EPSG:3857, UTM).")
                    QMessageBox.warning(
                        qgis_iface.mainWindow(),
                        "CRS non valido",
                        f"Il layer '{closest_layer.name()}' usa un CRS geografico "
                        f"({layer_crs.authid()}).\n\n"
                        f"Per calcolare correttamente il buffer di "
                        f"{self.buffer_distance}m, "
                        f"riproietta il layer in un CRS proiettato "
                        f"(es. EPSG:3857, UTM).",
                    )
                    return

                feat_id = closest_feature.id()
                layer_name = closest_layer.name()

                print("\n[LINEA] Linea selezionata:")
                print(f"                Layer: {layer_name}")
                print(f"                Feature ID: {feat_id}")
                print(f"                CRS del layer: {layer_crs.authid()}")

                # Crea buffer
                line_geom = closest_feature.geometry()
                buffer_geom = line_geom.buffer(self.buffer_distance, 8)

                print(f"[BUFFER] Creato buffer di {self.buffer_distance}m")
                print(f"         Area buffer: ~{buffer_geom.area():.1f} m²")

                # Visualizza il buffer sulla mappa
                self._visualizza_buffer(buffer_geom, layer_crs)

                # Estrai bbox dal buffer
                bbox = buffer_geom.boundingBox()
                print(f"[BUFFER] BBox del buffer ({layer_crs.authid()}):")
                print(f"         xMin={bbox.xMinimum():.7f}, yMin={bbox.yMinimum():.7f}")
                print(f"         xMax={bbox.xMaximum():.7f}, yMax={bbox.yMaximum():.7f}")

                # Trasforma bbox e buffer per WFS
                print(f"\n[CRS] CRS del layer sorgente: {layer_crs.authid()}")
                min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(bbox, layer_crs)

                # Trasforma il buffer nel CRS WFS per il filtering
                wfs_crs = QgsCoordinateReferenceSystem(WFS_CRS_ID)
                if layer_crs.authid() != wfs_crs.authid():
                    transform_to_wfs = QgsCoordinateTransform(
                        layer_crs, wfs_crs, QgsProject.instance()
                    )
                    buffer_geom_wfs = QgsGeometry(buffer_geom)
                    buffer_geom_wfs.transform(transform_to_wfs)
                else:
                    buffer_geom_wfs = buffer_geom

                # Esegui download con filtro buffer
                esegui_download_e_caricamento(
                    min_lat, min_lon, max_lat, max_lon,
                    filter_geom=buffer_geom_wfs,
                    layer_name=f"Particelle WFS (Linea buffer {self.buffer_distance} m)",
                    espandi_catastale=self.espandi_catastale
                )

                qgis_iface.actionPan().trigger()
                if self.on_completed:
                    self.on_completed()
                return

        if not found:
            print("[LINEA] Nessuna linea trovata nel punto cliccato. Riprova.")

    def deactivate(self):
        # Rimuovi rubberband buffer
        if self.buffer_rb:
            try:
                self.canvas.scene().removeItem(self.buffer_rb)
            except Exception:
                pass
            self.buffer_rb = None
        super().deactivate()


# =============================================================================
# CLASSE PLUGIN PRINCIPALE
# =============================================================================

class WfsCatastoDownloadParticelleBbox:
    """Plugin QGIS per il download delle particelle catastali dal WFS
    dell'Agenzia delle Entrate."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = "&WFS Catasto Download Particelle"
        self.toolbar = None
        self._active_tool = None
        self._avviso_accettato = False
        self._dlg = None

    def initGui(self):
        """Crea azione nella toolbar e nel menu."""
        self.toolbar = self.iface.addToolBar("WFS Catasto Download Particelle")
        self.toolbar.setObjectName("WfsCatastoDownloadParticelleBbox")

        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            icon = QIcon(":/images/themes/default/mActionAddWfsLayer.svg")

        action = QAction(
            icon,
            "WFS Catasto Download Particelle",
            self.iface.mainWindow(),
        )
        action.setWhatsThis(
            "Download particelle catastali dal WFS Agenzia delle Entrate"
        )
        action.triggered.connect(self.run)

        self.toolbar.addAction(action)
        self.iface.addPluginToVectorMenu(self.menu, action)
        self.actions.append(action)

    def unload(self):
        """Rimuove azione dalla toolbar e dal menu."""
        for action in self.actions:
            self.iface.removePluginVectorMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        if self.toolbar:
            del self.toolbar
        self._active_tool = None

    def _reopen_dialog(self):
        """Riapre il dialog dopo un breve ritardo (per completare l'evento del tool)."""
        QTimer.singleShot(200, self._show_dialog)

    def _show_dialog(self):
        """Mostra il dialog non-modale (crea o riutilizza)."""
        if self._dlg is None:
            self._dlg = SceltaModalitaDialog(
                self.iface.mainWindow(),
                default_buffer_m=BUFFER_DISTANCE_M,
            )
            self._dlg.accepted.connect(self._on_modalita_scelta)
        self._dlg.scelta = None
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    def _on_modalita_scelta(self):
        """Callback quando l'utente sceglie una modalità dal dialog."""
        dlg = self._dlg
        canvas = self.iface.mapCanvas()
        espandi = dlg.espandi_catastale

        if dlg.scelta == "disegna":
            print("\n  MODALITÀ: Disegna BBox")
            print("  >>> Clicca sulla mappa per il PRIMO angolo")
            print("  >>> Muovi il mouse per l'anteprima")
            print("  >>> Clicca per il SECONDO angolo")
            print("  >>> Il download partirà automaticamente\n")
            tool = BBoxDrawTool(canvas, on_completed=self._reopen_dialog,
                                espandi_catastale=espandi)
            canvas.setMapTool(tool)
            self._active_tool = tool

        elif dlg.scelta == "poligono":
            print("\n  MODALITÀ: Seleziona Poligono")
            print("  >>> Clicca su un poligono nella mappa")
            print("  >>> Il bbox verrà estratto e il CRS verificato")
            print("  >>> Il download partirà automaticamente\n")
            tool = PolySelectTool(canvas, on_completed=self._reopen_dialog,
                                  espandi_catastale=espandi)
            canvas.setMapTool(tool)
            self._active_tool = tool

        elif dlg.scelta == "asse":
            buffer_m = dlg.buffer_distance
            print("\n  MODALITÀ: Seleziona Linea")
            print("  >>> Clicca su una linea nella mappa")
            print(f"  >>> Verrà creato un buffer di {buffer_m}m")
            print("  >>> Verranno scaricate solo le particelle che intersecano il buffer")
            print("  >>> ATTENZIONE: Il layer deve avere un CRS proiettato (metri)\n")
            tool = LineSelectTool(canvas, buffer_distance=buffer_m,
                                  on_completed=self._reopen_dialog,
                                  espandi_catastale=espandi)
            canvas.setMapTool(tool)
            self._active_tool = tool

    def run(self):
        """Apre il dialog di scelta modalità e attiva il tool selezionato."""

        # Avviso obbligatorio alla prima esecuzione per sessione QGIS
        if not self._avviso_accettato:
            avviso = AvvisoDialog(self.iface.mainWindow())
            result_avviso = _exec_dialog(avviso)
            if result_avviso != _DialogAccepted:
                print("[INFO] Avviso non accettato. Plugin non avviato.")
                return
            self._avviso_accettato = True

        print("\n" + "=" * 60)
        print("  WFS CATASTO - Download Particelle")
        print("=" * 60)

        self._show_dialog()
