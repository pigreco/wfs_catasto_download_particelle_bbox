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
import webbrowser
from datetime import datetime

from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsRectangle,
    QgsPointXY,
    QgsWkbTypes,
    QgsFeatureRequest,
    QgsGeometry,
    QgsFeature,
    QgsField,
    QgsExpression,
    QgsRuleBasedRenderer,
    QgsFillSymbol,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, QVariant, QTimer, QSettings
from qgis.PyQt.QtGui import QColor, QIcon, QKeySequence
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QMessageBox,
    QProgressDialog,
    QApplication,
    QShortcut,
)
from qgis.utils import iface as qgis_iface

from .wfs_catasto_download_particelle_bbox_d import AvvisoDialog, SceltaModalitaDialog, AboutDialog
from .get_particella_wfs import get_particella_info


# =============================================================================
# COMPATIBILITÀ QGIS 3 / QGIS 4 (Qt5 / Qt6)
# =============================================================================

# Tipo geometria per QgsRubberBand e controlli layer
try:
    _GEOM_POLYGON = Qgis.GeometryType.Polygon
    _GEOM_LINE = Qgis.GeometryType.Line
    _GEOM_POINT = Qgis.GeometryType.Point
except AttributeError:
    _GEOM_POLYGON = QgsWkbTypes.PolygonGeometry
    _GEOM_LINE = QgsWkbTypes.LineGeometry
    _GEOM_POINT = QgsWkbTypes.PointGeometry


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


def _is_point_layer(layer):
    """Verifica se il layer è puntuale (compatibile QGIS 3/4)."""
    try:
        return layer.geometryType() == Qgis.GeometryType.Point
    except AttributeError:
        return layer.geometryType() == 0


def _set_show_feature_count(tree_layer, value):
    """Imposta showFeatureCount compatibile con QGIS 3 (Qt5) e QGIS 4 (Qt6)."""
    try:
        tree_layer.setShowFeatureCount(bool(value))  # QGIS 3.32+ / QGIS 4 (Qt6)
    except AttributeError:
        # Fallback QGIS < 3.32: usa int (1/0) per compatibilità QVariant Qt6
        tree_layer.setCustomProperty("showFeatureCount", 1 if value else 0)


def _refresh_feature_counts_deferred(layer_id):
    """Aggiorna i conteggi per-regola nella legenda dopo il render del canvas.

    In Qt6/QGIS 4 i conteggi sono calcolati asincronamente (dopo il render):
    questa funzione viene chiamata via QTimer per garantire che il canvas
    abbia già eseguito il render prima di richiedere il refresh della legenda.
    """
    tl = QgsProject.instance().layerTreeRoot().findLayer(layer_id)
    if tl is None:
        return
    _set_show_feature_count(tl, False)
    _set_show_feature_count(tl, True)
    try:
        qgis_iface.layerTreeView().layerTreeModel().refreshLayerLegend(tl)
    except Exception as e:
        print(f"[WFS Catasto] deferred refreshLayerLegend: {e}")


def _applica_stile_particelle(layer):
    """Applica stile rule-based al layer particelle in base al campo LABEL.

    - Particelle numeriche → arancione
    - STRADA → grigio
    - ACQUA → blu
    """
    # Simbolo base (serve come root per il renderer)
    root_rule = QgsRuleBasedRenderer.Rule(None)

    # Regola STRADA → grigio
    sym_strada = QgsFillSymbol.createSimple({
        "color": "153,153,153,255",
        "outline_color": "102,102,102,255",
        "outline_width": "0.3",
    })
    rule_strada = QgsRuleBasedRenderer.Rule(sym_strada)
    rule_strada.setLabel("Strada")
    rule_strada.setFilterExpression('"LABEL" LIKE \'%STRADA%\'')
    root_rule.appendChild(rule_strada)

    # Regola ACQUA → blu
    sym_acqua = QgsFillSymbol.createSimple({
        "color": "74,144,217,255",
        "outline_color": "44,95,138,255",
        "outline_width": "0.3",
    })
    rule_acqua = QgsRuleBasedRenderer.Rule(sym_acqua)
    rule_acqua.setLabel("Acqua")
    rule_acqua.setFilterExpression('"LABEL" LIKE \'%ACQUA%\'')
    root_rule.appendChild(rule_acqua)

    # Regola ELSE (particelle numeriche) → arancione
    sym_particella = QgsFillSymbol.createSimple({
        "color": "255,140,0,255",
        "outline_color": "204,112,0,255",
        "outline_width": "0.3",
    })
    rule_particella = QgsRuleBasedRenderer.Rule(sym_particella)
    rule_particella.setLabel("Particella")
    rule_particella.setIsElse(True)
    root_rule.appendChild(rule_particella)

    renderer = QgsRuleBasedRenderer(root_rule)
    layer.setRenderer(renderer)


# Qt enum scoped (Qt6) vs flat (Qt5)
try:
    _WindowModal = Qt.WindowModality.WindowModal
    _DashLine = Qt.PenStyle.DashLine
    _DialogAccepted = QDialog.DialogCode.Accepted
    _Key_Escape = Qt.Key.Key_Escape
    _LeftButton = Qt.MouseButton.LeftButton
    _RightButton = Qt.MouseButton.RightButton
    _MB_Yes = QMessageBox.StandardButton.Yes
    _MB_No = QMessageBox.StandardButton.No
except AttributeError:
    _WindowModal = Qt.WindowModal
    _DashLine = Qt.DashLine
    _DialogAccepted = QDialog.Accepted
    _Key_Escape = Qt.Key_Escape
    _LeftButton = Qt.LeftButton
    _RightButton = Qt.RightButton
    _MB_Yes = QMessageBox.Yes
    _MB_No = QMessageBox.No


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

# WMS Catasto
WMS_BASE_URL = "https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php"
WMS_LAYERS = [
    "province",
    "CP.CadastralZoning",
    "acque",
    "strade",
    "vestizioni",
    "fabbricati",
    "CP.CadastralParcel",
]
WMS_CONNECTION_NAME = "Catasto AdE"
WMS_LAYER_NAME = "Cartografia Catastale WMS AdE"


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


def _determina_utm_epsg(lon, lat):
    """
    Determina il codice EPSG della zona UTM per una coordinata in gradi.
    Per l'Italia: UTM 32N (6-12E), 33N (12-18E), 34N (18-24E).
    """
    zona = int(math.floor((lon + 180.0) / 6.0)) + 1
    if lat >= 0:
        epsg = 32600 + zona
    else:
        epsg = 32700 + zona
    return f"EPSG:{epsg}"


def carica_wms_catasto():
    """
    Aggiunge la connessione WMS del Catasto al profilo QGIS (se non presente)
    e carica un layer WMS combinato nel progetto corrente.
    Il layer viene posizionato in fondo al pannello Layer, prima di eventuali basemap XYZ.
    """
    # Controlla se il layer WMS è già nel progetto
    for layer in QgsProject.instance().mapLayers().values():
        if layer.providerType() == "wms" and WMS_BASE_URL in layer.source():
            print(f"[WMS] Layer WMS Catasto già presente nel progetto: {layer.name()}")
            return

    # Aggiungi connessione WMS in QSettings se non presente
    settings = QSettings()
    key_prefix = f"qgis/connections-wms/{WMS_CONNECTION_NAME}"
    existing_url = settings.value(f"{key_prefix}/url", "")
    if not existing_url:
        settings.setValue(f"{key_prefix}/url", WMS_BASE_URL)
        print(f"[WMS] Connessione '{WMS_CONNECTION_NAME}' aggiunta al profilo QGIS")
    else:
        print(f"[WMS] Connessione '{WMS_CONNECTION_NAME}' già presente nel profilo")

    # Costruisci URI con tutti i layer combinati
    layers_params = "&".join(f"layers={l}" for l in WMS_LAYERS)
    styles_params = "&".join("styles=" for _ in WMS_LAYERS)
    uri = (
        f"contextualWMSLegend=0"
        f"&crs=EPSG:6706"
        f"&dpiMode=7"
        f"&featureCount=10"
        f"&format=image/png"
        f"&{layers_params}"
        f"&{styles_params}"
        f"&url={WMS_BASE_URL}"
    )

    wms_layer = QgsRasterLayer(uri, WMS_LAYER_NAME, "wms")
    if not wms_layer.isValid():
        print("[WMS] ERRORE: impossibile caricare il layer WMS Catasto")
        return

    QgsProject.instance().addMapLayer(wms_layer, False)
    root = QgsProject.instance().layerTreeRoot()

    # Inserisci in fondo ma prima di eventuali mappe di sfondo (XYZ tiles)
    children = root.children()
    pos = len(children)  # default: ultima posizione
    for i in range(len(children) - 1, -1, -1):
        node = children[i]
        if hasattr(node, "layer") and node.layer():
            src = node.layer().source()
            if "type=xyz" in src:
                pos = i
            else:
                break
        else:
            break
    root.insertLayer(pos, wms_layer)

    print(f"[WMS] Layer '{WMS_LAYER_NAME}' caricato nel progetto")


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
                                  espandi_catastale=False,
                                  post_filter_points=None,
                                  carica_wms=False,
                                  append_to_layer=None):
    """
    Gestisce il download WFS: singolo o multi-tile con progress bar.

    Args:
        min_lat, min_lon, max_lat, max_lon: Coordinate bbox in EPSG:6706
        filter_geom: (opzionale) QgsGeometry in EPSG:6706 per filtrare le feature
        layer_name: (opzionale) Nome del layer di output
                     che intersecano questa geometria (es. buffer linea/punti)
    """
    area_km2 = stima_area_km2(min_lat, min_lon, max_lat, max_lon)
    print(f"\n[BBOX] Dimensione stimata: ~{area_km2:.1f} km²")

    # --- Calcola griglia tile ---
    tiles = calcola_griglia_tile(min_lat, min_lon, max_lat, max_lon, MAX_TILE_KM2)
    n_tiles_totali = len(tiles)

    # --- Filtra tile che intersecano il filtro spaziale (ottimizzazione) ---
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
                f"ma solo {n_tiles} intersecano il filtro spaziale.\n\n"
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
            _MB_Yes | _MB_No,
            _MB_Yes,
        )
        if risposta == _MB_No:
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
            _MB_Yes | _MB_No,
            _MB_Yes,
        )
        if risposta == _MB_No:
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
            "- L'area selezionata è in mare o fuori dalla copertura catastale italiana\n"
            "- Non ci sono particelle catastali in quest'area\n"
            "- Il server WFS non è raggiungibile\n\n"
            "Suggerimento: in modalità 'Seleziona Punti', se un punto cade in mare\n"
            "o in un'area priva di dati catastali, seleziona solo i punti validi\n"
            "(su terraferma) prima di avviare il download.",
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

    # --- FASE 3: Filtro spaziale (opzionale, per linea / punti) ---
    filtrate_spaziale = 0
    filtrate_punti = 0
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

    # --- FASE 3b: Filtro puntuale (point-in-polygon, per modalità Punti) ---
    if post_filter_points is not None:
        print("\n--- Filtro puntuale (point-in-polygon) ---")
        features_con_punto = []
        nuova_geom_dup_map_2 = {}

        for i, feat in enumerate(dopo_dedup_id):
            geom = feat.geometry()
            if geom.isNull() or geom.isEmpty():
                continue
            contiene_punto = False
            for pt_geom in post_filter_points:
                if geom.intersects(pt_geom):
                    contiene_punto = True
                    break
            if contiene_punto:
                nuovo_idx = len(features_con_punto)
                features_con_punto.append(feat)
                if i in geom_dup_map:
                    nuova_geom_dup_map_2[nuovo_idx] = geom_dup_map[i]

        filtrate_punti = len(dopo_dedup_id) - len(features_con_punto)
        print(f"    Feature dopo filtro buffer:    {len(dopo_dedup_id)}")
        print(f"    Feature che contengono punti:  {len(features_con_punto)}")
        print(f"    Feature escluse:               {filtrate_punti}")

        dopo_dedup_id = features_con_punto
        geom_dup_map = nuova_geom_dup_map_2

    # Tutte le feature vengono mantenute
    unique_features = dopo_dedup_id

    # --- Modalità append o creazione nuovo layer ---
    is_append = (append_to_layer is not None
                 and append_to_layer.isValid()
                 and QgsProject.instance().mapLayer(append_to_layer.id()) is not None)

    if is_append:
        # --- Append a layer esistente ---
        mem_layer = append_to_layer
        mem_provider = mem_layer.dataProvider()
        crs = mem_layer.crs()
        print(f"\n--- Append a layer esistente: {mem_layer.name()} ---")
        print(f"    Feature già presenti: {mem_layer.featureCount()}")

        # Deduplicazione cross-click: escludi feature già presenti (per gml_id)
        existing_ids = set()
        idx_gml_existing = mem_layer.fields().indexOf("gml_id")
        if idx_gml_existing >= 0:
            for feat in mem_layer.getFeatures():
                gml_val = feat.attribute(idx_gml_existing)
                if gml_val:
                    existing_ids.add(gml_val)

        idx_gml_source = layer_info["fields"].indexOf("gml_id")
        pre_dedup = len(unique_features)
        if existing_ids and idx_gml_source >= 0:
            unique_features = [
                f for f in unique_features
                if f.attribute(idx_gml_source) not in existing_ids
            ]
            cross_dup = pre_dedup - len(unique_features)
            if cross_dup > 0:
                print(f"    Duplicati cross-click rimossi: {cross_dup}")

    else:
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
        # In append: avvisa se il layer esistente non ha i campi espansi
        if is_append and any(i < 0 for i in [idx_sezione, idx_foglio, idx_allegato, idx_sviluppo]):
            risposta = QMessageBox.warning(
                qgis_iface.mainWindow(),
                "Campi catastali mancanti",
                "Il layer di destinazione non contiene i campi del riferimento "
                "catastale espanso (sezione, foglio, allegato, sviluppo).\n\n"
                "Vuoi aggiungere comunque i dati (senza quei campi)?\n\n"
                "Suggerimento: disattiva 'Espandi riferimento catastale' oppure "
                "scegli 'nuovo layer' come destinazione.",
                _MB_Yes | _MB_No,
                _MB_No,
            )
            if risposta == _MB_No:
                return None

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
                    if idx_sezione >= 0:
                        new_feat.setAttribute(idx_sezione, "" if sez == "_" else sez)
                    try:
                        if idx_foglio >= 0:
                            new_feat.setAttribute(idx_foglio, int(codice[5:9]))
                    except ValueError:
                        if idx_foglio >= 0:
                            new_feat.setAttribute(idx_foglio, None)
                    if idx_allegato >= 0:
                        new_feat.setAttribute(idx_allegato, codice[9])
                    if idx_sviluppo >= 0:
                        new_feat.setAttribute(idx_sviluppo, codice[10])

        new_features.append(new_feat)

    mem_provider.addFeatures(new_features)
    mem_layer.updateExtents()

    if not is_append:
        # Applica stile rule-based (arancione/grigio/blu)
        _applica_stile_particelle(mem_layer)

        # Aggiungi al progetto
        QgsProject.instance().addMapLayer(mem_layer)
        # Mostra conteggio feature per categoria in legenda (immediato + deferred per Qt6)
        mem_layer.triggerRepaint()
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(mem_layer.id())
        if tree_layer:
            _set_show_feature_count(tree_layer, True)
            try:
                qgis_iface.layerTreeView().layerTreeModel().refreshLayerLegend(tree_layer)
            except Exception as e:
                print(f"[WFS Catasto] refreshLayerLegend (nuovo layer): {e}")
        # In Qt6 i conteggi per-regola sono calcolati dopo il render: refresh differito
        QTimer.singleShot(500, lambda: _refresh_feature_counts_deferred(mem_layer.id()))

    feat_count = mem_layer.featureCount()

    if is_append:
        n_aggiunte = len(new_features)
        print(f"[OK] Aggiunte {n_aggiunte} feature (totale: {feat_count})")
        # Re-applica lo stile: resetta i conteggi interni del renderer rule-based
        # (necessario perché setCustomProperty("showFeatureCount", True) non rilancia
        # le query di conteggio per-regola se il valore era già True)
        _applica_stile_particelle(mem_layer)
        mem_layer.triggerRepaint()
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(mem_layer.id())
        if tree_layer:
            # Toggle off → on forza QGIS a rieseguire le query di conteggio per-regola
            _set_show_feature_count(tree_layer, False)
            _set_show_feature_count(tree_layer, True)
            try:
                qgis_iface.layerTreeView().layerTreeModel().refreshLayerLegend(tree_layer)
            except Exception as e:
                print(f"[WFS Catasto] refreshLayerLegend (append): {e}")
        # In Qt6 i conteggi per-regola sono calcolati dopo il render: refresh differito
        QTimer.singleShot(500, lambda: _refresh_feature_counts_deferred(mem_layer.id()))
        qgis_iface.messageBar().pushMessage(
            "WFS Catasto",
            f"Aggiunte {n_aggiunte} particelle a '{mem_layer.name()}' (totale nel layer: {feat_count})",
            level=Qgis.MessageLevel.Success if hasattr(Qgis, 'MessageLevel') else Qgis.Success,
            duration=6,
        )
    else:
        geom_type_str = _wkb_display_string(layer_info["wkb_type"])
        print(f"[OK] Layer temporaneo caricato con {feat_count} feature(s)")
        print(f"     CRS: {crs.authid()}")
        print(f"     Geometria: {geom_type_str}")
        print("     Campi aggiunti: 'geom_duplicata' (si/no), 'gruppo_duplicato' (n. gruppo)")
        if espandi_catastale:
            print("     Campi catastali: 'sezione', 'foglio', 'allegato', 'sviluppo'")
        qgis_iface.messageBar().pushMessage(
            "WFS Catasto",
            f"Caricate {feat_count} particelle nel layer '{mem_layer.name()}'",
            level=Qgis.MessageLevel.Success if hasattr(Qgis, 'MessageLevel') else Qgis.Success,
            duration=6,
        )

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

    # Carica WMS Catasto se richiesto
    if carica_wms:
        carica_wms_catasto()

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
    if filtrate_punti > 0:
        print(f"  Filtro punti (PiP):       {filtrate_punti} escluse (non contengono punti)")
    print("=" * 60)

    return mem_layer


# =============================================================================
# TOOL 1: DISEGNA BBOX (due click)
# =============================================================================

class BBoxDrawTool(QgsMapTool):
    """
    Tool interattivo: clicca il primo angolo, anteprima in tempo reale,
    clicca il secondo angolo per confermare e avviare il download.
    """

    def __init__(self, canvas, on_completed=None, espandi_catastale=False,
                 carica_wms=False, append_to_layer=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.first_point = None
        self.preview_rb = None
        self.on_completed = on_completed
        self.espandi_catastale = espandi_catastale
        self.append_to_layer = append_to_layer
        self.carica_wms = carica_wms
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
                espandi_catastale=self.espandi_catastale,
                carica_wms=self.carica_wms,
                append_to_layer=self.append_to_layer,
            )

            # Ripristina Pan e riapri dialog
            qgis_iface.actionPan().trigger()
            if self.on_completed:
                self.on_completed()

    def canvasMoveEvent(self, event):
        if self.first_point is not None:
            point = self.toMapCoordinates(event.pos())
            self._update_preview(point)

    def keyPressEvent(self, event):
        if event.key() == _Key_Escape:
            print("[BBOX] Operazione annullata dall'utente (ESC).")
            qgis_iface.actionPan().trigger()
            if self.on_completed:
                self.on_completed()

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

    def __init__(self, canvas, on_completed=None, espandi_catastale=False,
                 carica_wms=False, append_to_layer=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.on_completed = on_completed
        self.espandi_catastale = espandi_catastale
        self.carica_wms = carica_wms
        self.append_to_layer = append_to_layer

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
                    espandi_catastale=self.espandi_catastale,
                    carica_wms=self.carica_wms,
                    append_to_layer=self.append_to_layer,
                )

                qgis_iface.actionPan().trigger()
                if self.on_completed:
                    self.on_completed()
                return

        if not found:
            print("[POLIGONO] Nessun poligono trovato nel punto cliccato. Riprova.")

    def keyPressEvent(self, event):
        if event.key() == _Key_Escape:
            print("[POLIGONO] Operazione annullata dall'utente (ESC).")
            qgis_iface.actionPan().trigger()
            if self.on_completed:
                self.on_completed()

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
                 espandi_catastale=False, carica_wms=False, append_to_layer=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.buffer_distance = buffer_distance
        self.buffer_rb = None  # Rubberband per visualizzare il buffer
        self.espandi_catastale = espandi_catastale
        self.carica_wms = carica_wms
        self.append_to_layer = append_to_layer
        self.on_completed = on_completed
        # Stato per modalità disegno polilinea
        self._draw_points = []  # Vertici della polilinea in coordinate mappa
        self._draw_rb = None    # Rubberband per la polilinea in costruzione
        self._drawing = False   # True quando si sta disegnando

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

    def _esegui_download_da_linea(self, line_geom, geom_crs):
        """Crea buffer dalla linea ed esegue il download WFS."""
        buffer_geom = line_geom.buffer(self.buffer_distance, 8)

        print(f"[BUFFER] Creato buffer di {self.buffer_distance}m")
        print(f"         Area buffer: ~{buffer_geom.area():.1f} m²")

        # Visualizza il buffer sulla mappa
        self._visualizza_buffer(buffer_geom, geom_crs)

        # Estrai bbox dal buffer
        bbox = buffer_geom.boundingBox()
        print(f"[BUFFER] BBox del buffer ({geom_crs.authid()}):")
        print(f"         xMin={bbox.xMinimum():.7f}, yMin={bbox.yMinimum():.7f}")
        print(f"         xMax={bbox.xMaximum():.7f}, yMax={bbox.yMaximum():.7f}")

        # Trasforma bbox e buffer per WFS
        print(f"\n[CRS] CRS del layer sorgente: {geom_crs.authid()}")
        min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(bbox, geom_crs)

        # Trasforma il buffer nel CRS WFS per il filtering
        wfs_crs = QgsCoordinateReferenceSystem(WFS_CRS_ID)
        if geom_crs.authid() != wfs_crs.authid():
            transform_to_wfs = QgsCoordinateTransform(
                geom_crs, wfs_crs, QgsProject.instance()
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
            espandi_catastale=self.espandi_catastale,
            carica_wms=self.carica_wms,
            append_to_layer=self.append_to_layer,
        )

        qgis_iface.actionPan().trigger()
        if self.on_completed:
            self.on_completed()

    def _reset_disegno(self):
        """Resetta lo stato di disegno polilinea."""
        self._draw_points = []
        self._drawing = False
        if self._draw_rb:
            try:
                self.canvas.scene().removeItem(self._draw_rb)
            except Exception:
                pass
            self._draw_rb = None
        qgis_iface.statusBarIface().clearMessage()

    def _aggiorna_rubber_band(self, cursor_point=None):
        """Aggiorna il rubber band della polilinea in costruzione."""
        if self._draw_rb:
            try:
                self.canvas.scene().removeItem(self._draw_rb)
            except Exception:
                pass
            self._draw_rb = None

        if len(self._draw_points) < 1:
            return

        self._draw_rb = QgsRubberBand(self.canvas, _GEOM_LINE)
        self._draw_rb.setColor(QColor(255, 100, 0, 200))
        self._draw_rb.setWidth(2)
        self._draw_rb.setLineStyle(_DashLine)

        points = list(self._draw_points)
        if cursor_point:
            points.append(cursor_point)

        for pt in points:
            self._draw_rb.addPoint(pt)
        self._draw_rb.show()

    def canvasMoveEvent(self, event):
        """Aggiorna il segmento elastico durante il disegno."""
        if not self._drawing or len(self._draw_points) < 1:
            return
        cursor_point = self.toMapCoordinates(event.pos())
        self._aggiorna_rubber_band(cursor_point)

    def canvasPressEvent(self, event):
        click_map_point = self.toMapCoordinates(event.pos())
        project_crs = QgsProject.instance().crs()

        # --- Click destro: termina la polilinea ---
        if event.button() == _RightButton:
            if self._drawing and len(self._draw_points) >= 2:
                print(f"\n[LINEA] Polilinea disegnata con {len(self._draw_points)} vertici")

                # Controlla se il CRS è proiettato
                if project_crs.isGeographic():
                    print(f"\n[ERRORE] Il CRS del progetto è geografico "
                          f"({project_crs.authid()}).")
                    QMessageBox.warning(
                        qgis_iface.mainWindow(),
                        "CRS non valido",
                        f"Il CRS del progetto è geografico "
                        f"({project_crs.authid()}).\n\n"
                        f"Per calcolare correttamente il buffer di "
                        f"{self.buffer_distance}m, "
                        f"imposta un CRS proiettato per il progetto "
                        f"(es. EPSG:3857, UTM).",
                    )
                    self._reset_disegno()
                    return

                line_geom = QgsGeometry.fromPolylineXY(self._draw_points)
                self._reset_disegno()
                self._esegui_download_da_linea(line_geom, project_crs)
            elif self._drawing:
                print("[LINEA] Servono almeno 2 punti per completare la polilinea.")
                qgis_iface.statusBarIface().showMessage(
                    "Servono almeno 2 punti. Click sinistro per aggiungere vertici.",
                    3000
                )
            return

        # --- Click sinistro ---
        # Se siamo già in modalità disegno, aggiungi vertice
        if self._drawing:
            self._draw_points.append(QgsPointXY(click_map_point))
            self._aggiorna_rubber_band()
            n = len(self._draw_points)
            print(f"[LINEA] Vertice {n} aggiunto: "
                  f"({click_map_point.x():.6f}, {click_map_point.y():.6f})")
            qgis_iface.statusBarIface().showMessage(
                f"Vertici: {n} | Click sinistro: aggiungi | "
                f"Click destro: termina | ESC: annulla",
                0
            )
            return

        # --- Prima prova a selezionare una linea esistente ---
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

                line_geom = closest_feature.geometry()
                self._esegui_download_da_linea(line_geom, layer_crs)
                return

        # --- Nessuna linea trovata: entra in modalità disegno ---
        if not found:
            self._drawing = True
            self._draw_points = [QgsPointXY(click_map_point)]
            self._aggiorna_rubber_band()
            print(f"[LINEA] Nessuna linea trovata. Modalità disegno polilinea attivata.")
            print(f"[LINEA] Vertice 1: ({click_map_point.x():.6f}, {click_map_point.y():.6f})")
            qgis_iface.statusBarIface().showMessage(
                "Vertici: 1 | Click sinistro: aggiungi | "
                "Click destro: termina | ESC: annulla",
                0
            )

    def keyPressEvent(self, event):
        if event.key() == _Key_Escape:
            if self._drawing:
                print("[LINEA] Disegno polilinea annullato (ESC).")
                self._reset_disegno()
            else:
                print("[LINEA] Operazione annullata dall'utente (ESC).")
                qgis_iface.actionPan().trigger()
                if self.on_completed:
                    self.on_completed()

    def deactivate(self):
        # Rimuovi rubberband buffer
        if self.buffer_rb:
            try:
                self.canvas.scene().removeItem(self.buffer_rb)
            except Exception:
                pass
            self.buffer_rb = None
        # Rimuovi rubberband disegno polilinea
        if self._draw_rb:
            try:
                self.canvas.scene().removeItem(self._draw_rb)
            except Exception:
                pass
            self._draw_rb = None
        self._draw_points = []
        self._drawing = False
        super().deactivate()


# =============================================================================
# TOOL 4: SELEZIONA PUNTI (layer punti + buffer + dissolve)
# =============================================================================

class PointSelectTool(QgsMapTool):
    """
    Tool per selezionare un layer di punti sulla mappa.
    Per TUTTI i punti del layer:
    1. Crea buffer individuale attorno a ciascun punto
    2. Dissolve i buffer in una singola geometria (filter_geom)
    3. Scarica le particelle WFS nel bbox del dissolve
    4. Post-filtra: mantiene solo le particelle che contengono almeno un punto
    """

    def __init__(self, canvas, buffer_distance=1, snap_tolerance=15,
                 on_completed=None, espandi_catastale=False, carica_wms=False,
                 source_layer=None, initial_append_layer=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.buffer_distance = buffer_distance
        self.snap_tolerance = snap_tolerance
        self.buffer_rb = None
        self.espandi_catastale = espandi_catastale
        self.carica_wms = carica_wms
        self.on_completed = on_completed
        self.source_layer = source_layer
        self._session_layer = initial_append_layer
        self._esc_shortcut = None

    def activate(self):
        super().activate()
        self._esc_shortcut = QShortcut(
            QKeySequence(_Key_Escape), self.canvas
        )
        try:
            ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        except AttributeError:
            ctx = Qt.WidgetWithChildrenShortcut
        self._esc_shortcut.setContext(ctx)
        self._esc_shortcut.activated.connect(self._on_esc)
        # Se è stato preimpostato un layer sorgente, elaboralo subito
        if self.source_layer is not None:
            QTimer.singleShot(100, lambda: self._processa_layer_punti(self.source_layer))

    def _on_esc(self):
        """Gestisce ESC: termina la sessione click singolo."""
        print("[PUNTI] Operazione annullata dall'utente (ESC).")
        qgis_iface.actionPan().trigger()
        if self.on_completed:
            self.on_completed()

    def _visualizza_buffer(self, buffer_geom, buffer_crs):
        """Visualizza il buffer dissolto sulla mappa (viola)."""
        if self.buffer_rb:
            self.canvas.scene().removeItem(self.buffer_rb)
            self.buffer_rb = None

        project_crs = QgsProject.instance().crs()
        if buffer_crs.authid() != project_crs.authid():
            transform = QgsCoordinateTransform(
                buffer_crs, project_crs, QgsProject.instance()
            )
            buffer_geom_proj = QgsGeometry(buffer_geom)
            buffer_geom_proj.transform(transform)
        else:
            buffer_geom_proj = buffer_geom

        self.buffer_rb = QgsRubberBand(self.canvas, _GEOM_POLYGON)
        self.buffer_rb.setColor(QColor(123, 31, 162, 60))
        self.buffer_rb.setStrokeColor(QColor(123, 31, 162, 200))
        self.buffer_rb.setWidth(2)
        self.buffer_rb.setToGeometry(buffer_geom_proj, None)
        self.buffer_rb.show()

    def canvasPressEvent(self, event):
        """Click sulla mappa: scarica la particella sotto il cursore (modalità sessione).

        Quando 'Sorgente' = '(clicca sulla mappa)' ogni click scarica la particella
        catastale nel punto cliccato e la accumula nello stesso layer di sessione.
        Premi ESC per terminare la sessione e riaprire il dialogo.

        Quando 'Sorgente' = layer specifico il processing parte automaticamente
        all'avvio (in activate()) e il click sulla mappa viene ignorato.
        """
        if self.source_layer is not None:
            # Modalità layer sorgente: il processing è già partito automaticamente.
            return

        click_map_point = self.toMapCoordinates(event.pos())
        project_crs = QgsProject.instance().crs()
        print(f"\n[PUNTI] Click mappa ({project_crs.authid()}): "
              f"({click_map_point.x():.6f}, {click_map_point.y():.6f})")
        self._processa_click_singolo(click_map_point, project_crs)

    def _processa_layer_punti(self, layer):
        """Processa i punti del layer (selezionati o tutti): buffer, dissolve, download, filtro.

        Chiamato solo in modalità 'Sorgente = layer specifico' (auto-processing da activate()).
        Al termine (anche in caso di errore) deattiva il tool e riapre il dialogo.
        """
        try:
            layer_crs = layer.crs()
            layer_name = layer.name()
            n_selected = layer.selectedFeatureCount()
            n_features = layer.featureCount()

            print(f"\n[PUNTI] Layer sorgente: {layer_name}")
            print(f"        CRS: {layer_crs.authid()}")
            print(f"        Punti nel layer: {n_features}")
            print(f"        Punti selezionati: {n_selected}")

            if n_features == 0:
                QMessageBox.warning(
                    qgis_iface.mainWindow(),
                    "Layer vuoto",
                    f"Il layer '{layer_name}' non contiene feature.",
                )
                return

            # Usa i punti selezionati se disponibili, altrimenti tutti
            if n_selected > 0:
                features = layer.selectedFeatures()
                print(f"[PUNTI] Uso {n_selected} punti selezionati")
            else:
                features = layer.getFeatures()
                print(f"[PUNTI] Nessuna selezione, uso tutti i {n_features} punti")

            all_points = []
            for feat in features:
                geom = feat.geometry()
                if geom.isNull() or geom.isEmpty():
                    continue
                all_points.append(geom)

            if not all_points:
                QMessageBox.warning(
                    qgis_iface.mainWindow(),
                    "Nessun punto valido",
                    f"Il layer '{layer_name}' non contiene geometrie valide.",
                )
                return

            print(f"[PUNTI] Punti validi: {len(all_points)}")

            # Determina CRS di lavoro per il buffer
            if layer_crs.isGeographic():
                print(f"[PUNTI] CRS geografico rilevato ({layer_crs.authid()}).")
                print("        Auto-riproiezione in zona UTM...")

                # Calcola centroide medio per determinare zona UTM
                sum_x, sum_y = 0.0, 0.0
                for pt_geom in all_points:
                    centroid = pt_geom.centroid().asPoint()
                    sum_x += centroid.x()
                    sum_y += centroid.y()
                avg_lon = sum_x / len(all_points)
                avg_lat = sum_y / len(all_points)

                utm_epsg = _determina_utm_epsg(avg_lon, avg_lat)
                buffer_crs = QgsCoordinateReferenceSystem(utm_epsg)
                print(f"        Centroide punti: ({avg_lon:.6f}, {avg_lat:.6f})")
                print(f"        Zona UTM scelta: {utm_epsg}")

                # Riproietta punti in UTM per il buffer
                transform_to_utm = QgsCoordinateTransform(
                    layer_crs, buffer_crs, QgsProject.instance()
                )
                points_for_buffer = []
                for pt_geom in all_points:
                    pt_utm = QgsGeometry(pt_geom)
                    pt_utm.transform(transform_to_utm)
                    points_for_buffer.append(pt_utm)
            else:
                buffer_crs = layer_crs
                points_for_buffer = all_points
                print(f"[PUNTI] CRS proiettato ({layer_crs.authid()}), "
                      "nessuna riproiezione necessaria.")

            # Buffer individuale + Dissolve
            print(f"[PUNTI] Creazione buffer di {self.buffer_distance}m "
                  f"per {len(points_for_buffer)} punti...")

            buffer_geoms = []
            for pt_geom in points_for_buffer:
                buf = pt_geom.buffer(self.buffer_distance, 8)
                if not buf.isNull() and not buf.isEmpty():
                    buffer_geoms.append(buf)

            if not buffer_geoms:
                QMessageBox.warning(
                    qgis_iface.mainWindow(),
                    "Errore buffer",
                    "Impossibile creare i buffer per i punti.",
                )
                return

            dissolved = QgsGeometry.unaryUnion(buffer_geoms)
            if dissolved.isNull() or dissolved.isEmpty():
                QMessageBox.warning(
                    qgis_iface.mainWindow(),
                    "Errore dissolve",
                    "Impossibile dissolvere i buffer.",
                )
                return

            print("[PUNTI] Buffer dissolto creato.")
            print(f"        Area dissolve: ~{dissolved.area():.1f} m²")

            # Visualizza il buffer dissolto
            self._visualizza_buffer(dissolved, buffer_crs)

            # Trasforma bbox e dissolve in EPSG:6706
            bbox = dissolved.boundingBox()
            print(f"[PUNTI] BBox del dissolve ({buffer_crs.authid()}):")
            print(f"        xMin={bbox.xMinimum():.7f}, yMin={bbox.yMinimum():.7f}")
            print(f"        xMax={bbox.xMaximum():.7f}, yMax={bbox.yMaximum():.7f}")

            min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(
                bbox, buffer_crs
            )

            wfs_crs = QgsCoordinateReferenceSystem(WFS_CRS_ID)
            if buffer_crs.authid() != wfs_crs.authid():
                transform_to_wfs = QgsCoordinateTransform(
                    buffer_crs, wfs_crs, QgsProject.instance()
                )
                dissolved_wfs = QgsGeometry(dissolved)
                dissolved_wfs.transform(transform_to_wfs)
            else:
                dissolved_wfs = dissolved

            # Trasforma punti originali in WFS CRS per post-filtro
            wfs_points = []
            if layer_crs.authid() != wfs_crs.authid():
                transform_pts_to_wfs = QgsCoordinateTransform(
                    layer_crs, wfs_crs, QgsProject.instance()
                )
                for pt_geom in all_points:
                    pt_wfs = QgsGeometry(pt_geom)
                    pt_wfs.transform(transform_pts_to_wfs)
                    wfs_points.append(pt_wfs)
            else:
                wfs_points = list(all_points)

            # Download WFS con filtro
            result_layer = esegui_download_e_caricamento(
                min_lat, min_lon, max_lat, max_lon,
                filter_geom=dissolved_wfs,
                layer_name=f"Particelle WFS (Punti buffer {self.buffer_distance} m)",
                espandi_catastale=self.espandi_catastale,
                post_filter_points=wfs_points,
                carica_wms=self.carica_wms,
                append_to_layer=self._session_layer,
            )
            if result_layer is not None:
                self._session_layer = result_layer

        finally:
            # Sempre: deattiva il tool e riapri il dialogo
            qgis_iface.actionPan().trigger()
            if self.on_completed:
                self.on_completed()

    def _processa_click_singolo(self, click_point, click_crs):
        """Fallback: usa il punto cliccato per scaricare la particella sottostante."""
        BUFFER_CLICK_M = 1  # buffer fisso 1 m

        pt_geom = QgsGeometry.fromPointXY(click_point)

        # Determina CRS proiettato per il buffer
        if click_crs.isGeographic():
            lon = click_point.x()
            lat = click_point.y()
            utm_epsg = _determina_utm_epsg(lon, lat)
            buffer_crs = QgsCoordinateReferenceSystem(utm_epsg)
            print(f"[PUNTI] Auto-riproiezione click in {utm_epsg}")

            transform_to_utm = QgsCoordinateTransform(
                click_crs, buffer_crs, QgsProject.instance()
            )
            pt_utm = QgsGeometry(pt_geom)
            pt_utm.transform(transform_to_utm)
        else:
            buffer_crs = click_crs
            pt_utm = pt_geom

        # Buffer 1 m
        buffer_geom = pt_utm.buffer(BUFFER_CLICK_M, 8)
        self._visualizza_buffer(buffer_geom, buffer_crs)

        # Trasforma in WFS CRS
        bbox = buffer_geom.boundingBox()
        min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(
            bbox, buffer_crs
        )

        wfs_crs = QgsCoordinateReferenceSystem(WFS_CRS_ID)
        if buffer_crs.authid() != wfs_crs.authid():
            transform_to_wfs = QgsCoordinateTransform(
                buffer_crs, wfs_crs, QgsProject.instance()
            )
            buffer_wfs = QgsGeometry(buffer_geom)
            buffer_wfs.transform(transform_to_wfs)
        else:
            buffer_wfs = buffer_geom

        # Punto originale in WFS CRS per post-filtro
        if click_crs.authid() != wfs_crs.authid():
            transform_pt_wfs = QgsCoordinateTransform(
                click_crs, wfs_crs, QgsProject.instance()
            )
            pt_wfs = QgsGeometry(pt_geom)
            pt_wfs.transform(transform_pt_wfs)
        else:
            pt_wfs = pt_geom

        result_layer = esegui_download_e_caricamento(
            min_lat, min_lon, max_lat, max_lon,
            filter_geom=buffer_wfs,
            layer_name="Particelle WFS (click punto)",
            espandi_catastale=self.espandi_catastale,
            post_filter_points=[pt_wfs],
            carica_wms=self.carica_wms,
            append_to_layer=self._session_layer,
        )
        if result_layer is not None:
            self._session_layer = result_layer

    def deactivate(self):
        if self._esc_shortcut:
            self._esc_shortcut.setEnabled(False)
            self._esc_shortcut.deleteLater()
            self._esc_shortcut = None
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
        """Crea azioni nella toolbar e nel menu Plugin."""
        self.toolbar = self.iface.addToolBar("WFS Catasto Download Particelle")
        self.toolbar.setObjectName("WfsCatastoDownloadParticelleBbox")

        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            icon = QIcon(":/images/themes/default/mActionAddWfsLayer.svg")

        # Azione principale - Avvio plugin
        action_main = QAction(
            icon,
            "Avvia Download Particelle Catastali",
            self.iface.mainWindow(),
        )
        action_main.setWhatsThis(
            "Avvia il download delle particelle catastali dal WFS Agenzia delle Entrate"
        )
        action_main.triggered.connect(self.run)
        
        # Azione informazioni
        info_icon = QIcon(":/images/themes/default/mActionHelpContents.svg")
        action_info = QAction(
            info_icon,
            "Informazioni",
            self.iface.mainWindow(),
        )
        action_info.setWhatsThis(
            "Informazioni sul plugin WFS Catasto Download Particelle"
        )
        action_info.triggered.connect(self.show_about)
        
        # Azione guida
        help_icon = QIcon(":/images/themes/default/mActionHelpContents.svg")
        action_guida = QAction(
            help_icon,
            "Guida",
            self.iface.mainWindow(),
        )
        action_guida.setWhatsThis(
            "Apre la guida online del plugin WFS Catasto Download Particelle"
        )
        action_guida.triggered.connect(self.show_help)

        # Aggiungi alla toolbar (solo azione principale)
        self.toolbar.addAction(action_main)
        
        # Aggiungi al menu Plugin con sottomenu
        self.iface.addPluginToMenu(self.menu, action_main)
        self.iface.addPluginToMenu(self.menu, action_info)
        self.iface.addPluginToMenu(self.menu, action_guida)
        
        self.actions.append(action_main)
        self.actions.append(action_info)
        self.actions.append(action_guida)

        # Registra la funzione personalizzata nel calcolatore di campi
        QgsExpression.registerFunction(get_particella_info)
        print("[OK] Funzione personalizzata 'get_particella_info' registrata")

    def unload(self):
        """Rimuove azioni dalla toolbar e dal menu."""
        # Deregistra la funzione personalizzata
        QgsExpression.unregisterFunction('get_particella_info')
        print("[OK] Funzione personalizzata 'get_particella_info' deregistrata")
        
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
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
        wms = dlg.carica_wms
        append_globale = dlg.output_globale_layer

        if dlg.scelta == "disegna":
            print("\n  MODALITÀ: Disegna BBox")
            print("  >>> Clicca sulla mappa per il PRIMO angolo")
            print("  >>> Muovi il mouse per l'anteprima")
            print("  >>> Clicca per il SECONDO angolo")
            print("  >>> Il download partirà automaticamente\n")
            if append_globale is not None:
                print(f"  >>> Output globale: aggiungi a '{append_globale.name()}'\n")
            tool = BBoxDrawTool(canvas, on_completed=self._reopen_dialog,
                                espandi_catastale=espandi, carica_wms=wms,
                                append_to_layer=append_globale)
            canvas.setMapTool(tool)
            self._active_tool = tool

        elif dlg.scelta == "poligono":
            print("\n  MODALITÀ: Seleziona Poligono")
            print("  >>> Clicca su un poligono nella mappa")
            print("  >>> Il bbox verrà estratto e il CRS verificato")
            print("  >>> Il download partirà automaticamente\n")
            if append_globale is not None:
                print(f"  >>> Output globale: aggiungi a '{append_globale.name()}'\n")
            tool = PolySelectTool(canvas, on_completed=self._reopen_dialog,
                                  espandi_catastale=espandi, carica_wms=wms,
                                  append_to_layer=append_globale)
            canvas.setMapTool(tool)
            self._active_tool = tool

        elif dlg.scelta == "asse":
            buffer_m = dlg.buffer_distance
            print("\n  MODALITÀ: Seleziona Linea")
            print("  >>> Clicca su una linea nella mappa")
            print(f"  >>> Verrà creato un buffer di {buffer_m}m")
            print("  >>> Verranno scaricate solo le particelle che intersecano il buffer")
            print("  >>> ATTENZIONE: Il layer deve avere un CRS proiettato (metri)\n")
            if append_globale is not None:
                print(f"  >>> Output globale: aggiungi a '{append_globale.name()}'\n")
            tool = LineSelectTool(canvas, buffer_distance=buffer_m,
                                  on_completed=self._reopen_dialog,
                                  espandi_catastale=espandi, carica_wms=wms,
                                  append_to_layer=append_globale)
            canvas.setMapTool(tool)
            self._active_tool = tool

        elif dlg.scelta == "punti":
            buffer_m = dlg.buffer_punti_distance
            snap_px = dlg.snap_tolerance
            source_lyr = dlg.selected_point_layer
            append_lyr = dlg.append_to_wfs_layer
            print("\n  MODALITÀ: Seleziona Punti")
            if source_lyr is not None:
                print(f"  >>> Layer sorgente: {source_lyr.name()}")
            else:
                print("  >>> Clicca vicino a un punto in mappa")
            print(f"  >>> Verrà creato un buffer di {buffer_m}m per ogni punto del layer")
            print(f"  >>> Tolleranza snap: {snap_px} px")
            if append_lyr is not None:
                print(f"  >>> Aggiungi a layer esistente: {append_lyr.name()}")
            else:
                print("  >>> Verrà creato un nuovo layer")
            print("  >>> CRS geografico supportato (auto-riproiezione UTM)\n")
            tool = PointSelectTool(canvas, buffer_distance=buffer_m,
                                   snap_tolerance=snap_px,
                                   on_completed=self._reopen_dialog,
                                   espandi_catastale=espandi, carica_wms=wms,
                                   source_layer=source_lyr,
                                   initial_append_layer=append_lyr)
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
        
    def show_about(self):
        """Mostra il dialog con le informazioni sul plugin."""
        about_dlg = AboutDialog(self.iface.mainWindow())
        # Compatibilità Qt5/Qt6
        try:
            about_dlg.exec()  # Qt6
        except AttributeError:
            about_dlg.exec_()  # Qt5
            
    def show_help(self):
        """Apre la pagina di aiuto del plugin su GitHub Pages."""
        url = "https://pigreco.github.io/wfs_catasto_download_particelle_bbox/"
        try:
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Aiuto Plugin",
                f"Impossibile aprire la pagina di aiuto.\n\n"
                f"Apri manualmente: {url}\n\n"
                f"Errore: {str(e)}"
            )
