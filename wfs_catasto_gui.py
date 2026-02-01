"""
Script PyQGIS - Download WFS Catasto con BBox interattivo o Selezione Poligono
================================================================================
Da eseguire nella Console Python di QGIS.

Modalità:
  A) Disegna BBox: clicca 2 punti sulla mappa per definire il rettangolo
  B) Seleziona Poligono: clicca su un poligono esistente, ne estrae il bbox

Se l'area è troppo grande per una singola chiamata WFS, il bbox viene
suddiviso automaticamente in tile più piccoli con download intervallato
e progress bar.
"""

import math
import os
import re
import tempfile
import time
import urllib.request
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
    QgsFields,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, QVariant, QTimer
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QSizePolicy,
    QMessageBox,
    QProgressDialog,
    QApplication,
)
from qgis.utils import iface


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
MAX_TILE_KM2 = 2.0
# Pausa tra le chiamate WFS in secondi
PAUSA_SECONDI = 5


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
    rb = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
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

        urllib.request.urlretrieve(wfs_url, tmp_path)

        # Verifica errori nel contenuto
        with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
            contenuto = f.read(2048)
        if '<ExceptionReport' in contenuto or '<ows:ExceptionReport' in contenuto:
            print(f"  [ERRORE] Il server ha restituito un errore per questo tile")
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


def esegui_download_e_caricamento(min_lat, min_lon, max_lat, max_lon):
    """
    Gestisce il download WFS: singolo o multi-tile con progress bar.
    """
    area_km2 = stima_area_km2(min_lat, min_lon, max_lat, max_lon)
    print(f"\n[BBOX] Dimensione stimata: ~{area_km2:.1f} km²")

    # --- Calcola griglia tile ---
    tiles = calcola_griglia_tile(min_lat, min_lon, max_lat, max_lon, MAX_TILE_KM2)
    n_tiles = len(tiles)

    if n_tiles > 1:
        # Chiedi conferma per download multiplo
        tempo_stimato = n_tiles * PAUSA_SECONDI
        minuti = tempo_stimato // 60
        secondi = tempo_stimato % 60
        tempo_str = f"{minuti} min {secondi} sec" if minuti > 0 else f"{secondi} sec"
        msg = (
            f"L'area selezionata (~{area_km2:.1f} km²) verrà suddivisa\n"
            f"in {n_tiles} tile per rispettare i limiti del server WFS.\n\n"
            f"Tempo stimato: ~{tempo_str}\n"
            f"(pausa di {PAUSA_SECONDI} sec tra ogni chiamata)\n\n"
            f"Vuoi procedere?"
        )
        risposta = QMessageBox.question(
            iface.mainWindow(),
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
        iface.mainWindow(),
    )
    progress.setWindowTitle("WFS Catasto - Download")
    progress.setWindowModality(Qt.WindowModal)
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
            print(f"    [ERRORE] Tile fallito")

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
            iface.mainWindow(),
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
            iface.mainWindow(),
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
    print(f"\n--- Deduplicazione ---")
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
        print(f"    [AVVISO] Nessun campo ID trovato, salto dedup per attributo")
        dopo_dedup_id = list(all_features)

    if duplicati_id > 0:
        print(f"    Duplicati per attributo rimossi: {duplicati_id}")
    else:
        print(f"    Nessun duplicato per attributo")

    # FASE 2: Verifica geometrie duplicate (stessa geometria, ID diverso)
    # Le feature vengono MANTENUTE tutte, ma segnalate con un campo attributo
    print(f"\n--- Verifica geometrie duplicate ---")
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
    geom_dup_map = {}  # indice -> (bool, int_gruppo)
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
        print(f"    Nessuna geometria duplicata trovata")

    # Riepilogo deduplicazione
    print(f"\n    --- Riepilogo ---")
    print(f"    Feature iniziali:              {len(all_features)}")
    print(f"    Duplicati per attributo:        {duplicati_id} (rimossi)")
    print(f"    Geometrie duplicate:            {duplicati_geom} (mantenute, segnalate)")
    print(f"    Feature finali:                 {len(dopo_dedup_id)}")

    # Tutte le feature vengono mantenute
    unique_features = dopo_dedup_id

    # --- Crea layer temporaneo in memoria ---
    print(f"\n--- Creazione layer temporaneo ---")
    geom_type_str = QgsWkbTypes.displayString(layer_info["wkb_type"])
    crs = layer_info["crs"]
    mem_uri = f"{geom_type_str}?crs={crs.authid()}"

    mem_layer = QgsVectorLayer(mem_uri, "Particelle Catastali WFS", "memory")
    mem_provider = mem_layer.dataProvider()

    # Copia campi originali + aggiungi campi segnalazione duplicati
    original_fields = layer_info["fields"].toList()
    original_fields.append(QgsField("geom_duplicata", QVariant.String))
    original_fields.append(QgsField("gruppo_duplicato", QVariant.Int))
    mem_provider.addAttributes(original_fields)
    mem_layer.updateFields()

    # Indici dei nuovi campi
    idx_geom_dup = mem_layer.fields().indexOf("geom_duplicata")
    idx_gruppo_dup = mem_layer.fields().indexOf("gruppo_duplicato")

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

        new_features.append(new_feat)

    mem_provider.addFeatures(new_features)
    mem_layer.updateExtents()

    # Aggiungi al progetto
    QgsProject.instance().addMapLayer(mem_layer)
    feat_count = mem_layer.featureCount()

    print(f"[OK] Layer temporaneo caricato con {feat_count} feature(s)")
    print(f"     CRS: {crs.authid()}")
    print(f"     Geometria: {geom_type_str}")
    print(f"     Campi aggiunti: 'geom_duplicata' (si/no), 'gruppo_duplicato' (n. gruppo)")

    # Zoom sul layer (trasforma extent nel CRS del progetto)
    canvas = iface.mapCanvas()
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
    if errori > 0:
        print(f"  Tile con errori:          {errori}")
    if duplicati_id > 0:
        print(f"  Duplicati (attributo):    {duplicati_id} rimossi")
    if duplicati_geom > 0:
        print(f"  Geometrie duplicate:      {duplicati_geom} segnalate")
        print(f"  Gruppi duplicati:         {len(geom_duplicati_gruppi)}")
        print(f"  Filtra con: \"geom_duplicata\" = 'si'")
    print("=" * 60)


# =============================================================================
# TOOL 1: DISEGNA BBOX (due click)
# =============================================================================

class BBoxDrawTool(QgsMapTool):
    """
    Tool interattivo: clicca il primo angolo, anteprima in tempo reale,
    clicca il secondo angolo per confermare e avviare il download.
    """

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.first_point = None
        self.preview_rb = None
        self._create_preview_rubberband()

    def _create_preview_rubberband(self):
        self.preview_rb = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.preview_rb.setColor(QColor(0, 120, 255, 40))
        self.preview_rb.setStrokeColor(QColor(0, 120, 255, 180))
        self.preview_rb.setWidth(2)
        self.preview_rb.setLineStyle(Qt.DashLine)

    def _update_preview(self, second_point):
        if not self.first_point:
            return
        self.preview_rb.reset(QgsWkbTypes.PolygonGeometry)
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

            # Disegna rettangolo definitivo
            disegna_rubberband_da_rect(
                self.canvas, rect, (255, 50, 50, 50), (255, 0, 0, 220)
            )

            # Trasforma e scarica
            project_crs = QgsProject.instance().crs()
            print(f"\n[CRS] CRS del progetto: {project_crs.authid()}")
            min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(rect, project_crs)
            esegui_download_e_caricamento(min_lat, min_lon, max_lat, max_lon)

            # Ripristina Pan
            iface.actionPan().trigger()

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

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas

    def _is_polygon_layer(self, layer):
        """Verifica se il layer è poligonale (compatibile con tutte le versioni QGIS)."""
        try:
            return layer.geometryType() == Qgis.GeometryType.Polygon
        except AttributeError:
            return layer.geometryType() == 2

    def canvasPressEvent(self, event):
        click_map_point = self.toMapCoordinates(event.pos())
        project_crs = QgsProject.instance().crs()

        print(f"\n[DEBUG] Click alle coordinate progetto ({project_crs.authid()}): "
              f"({click_map_point.x():.6f}, {click_map_point.y():.6f})")

        poly_layers = []
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and self._is_polygon_layer(lyr):
                poly_layers.append(lyr.name())
        print(f"[DEBUG] Layer poligonali trovati: {poly_layers if poly_layers else 'NESSUNO'}")

        found = False
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not self._is_polygon_layer(layer):
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

                print(f"\n[POLIGONO] Feature selezionata:")
                print(f"           Layer: {layer_name}")
                print(f"           Feature ID: {feat_id}")
                print(f"           CRS del layer: {layer_crs.authid()}")

                bbox = geom.boundingBox()
                print(f"[POLIGONO] BBox geometria ({layer_crs.authid()}):")
                print(f"           xMin={bbox.xMinimum():.7f}, yMin={bbox.yMinimum():.7f}")
                print(f"           xMax={bbox.xMaximum():.7f}, yMax={bbox.yMaximum():.7f}")

                if layer_crs.authid() != project_crs.authid():
                    to_project = QgsCoordinateTransform(
                        layer_crs, project_crs, QgsProject.instance()
                    )
                    bbox_proj = to_project.transformBoundingBox(bbox)
                else:
                    bbox_proj = bbox

                disegna_rubberband_da_rect(
                    self.canvas, bbox_proj, (50, 200, 50, 50), (0, 180, 0, 220)
                )

                print(f"\n[CRS] CRS del layer sorgente: {layer_crs.authid()}")
                min_lat, min_lon, max_lat, max_lon = trasforma_bbox_a_wfs(
                    bbox, layer_crs
                )

                esegui_download_e_caricamento(min_lat, min_lon, max_lat, max_lon)

                iface.actionPan().trigger()
                return

        if not found:
            print("[POLIGONO] Nessun poligono trovato nel punto cliccato. Riprova.")

    def deactivate(self):
        super().deactivate()


# =============================================================================
# GUI - DIALOGO SCELTA MODALITÀ
# =============================================================================

class SceltaModalitaDialog(QDialog):
    """Finestra di dialogo per scegliere la modalità di definizione del BBox."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scelta = None
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("WFS Catasto - Scelta modalità")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Titolo
        titolo = QLabel("Download Particelle Catastali WFS")
        font_titolo = QFont()
        font_titolo.setPointSize(13)
        font_titolo.setBold(True)
        titolo.setFont(font_titolo)
        titolo.setAlignment(Qt.AlignCenter)
        layout.addWidget(titolo)

        # Sottotitolo
        sottotitolo = QLabel("Seleziona la modalità per definire l'area di interesse:")
        sottotitolo.setAlignment(Qt.AlignCenter)
        sottotitolo.setStyleSheet("color: #555;")
        layout.addWidget(sottotitolo)

        # --- Gruppo 1: Disegna BBox ---
        group1 = QGroupBox("Disegna BBox")
        group1.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #ccc; "
            "border-radius: 5px; margin-top: 10px; padding-top: 15px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        g1_layout = QVBoxLayout()
        desc1 = QLabel(
            "Clicca due punti sulla mappa per disegnare\n"
            "un rettangolo che definisce l'area di download."
        )
        desc1.setWordWrap(True)
        desc1.setStyleSheet("color: #333; font-weight: normal;")
        g1_layout.addWidget(desc1)

        btn_disegna = QPushButton("  Disegna BBox sulla mappa")
        btn_disegna.setMinimumHeight(40)
        btn_disegna.setStyleSheet(
            "QPushButton { background-color: #2962FF; color: white; "
            "font-size: 12px; font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1E4FD0; }"
        )
        btn_disegna.clicked.connect(self._on_disegna)
        g1_layout.addWidget(btn_disegna)
        group1.setLayout(g1_layout)
        layout.addWidget(group1)

        # --- Gruppo 2: Seleziona Poligono ---
        group2 = QGroupBox("Seleziona Poligono")
        group2.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #ccc; "
            "border-radius: 5px; margin-top: 10px; padding-top: 15px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        g2_layout = QVBoxLayout()
        desc2 = QLabel(
            "Clicca su un poligono esistente in mappa.\n"
            "Il bbox della geometria verrà estratto automaticamente.\n"
            "Se l'area è grande, verrà suddivisa in tile automaticamente."
        )
        desc2.setWordWrap(True)
        desc2.setStyleSheet("color: #333; font-weight: normal;")
        g2_layout.addWidget(desc2)

        btn_poligono = QPushButton("  Seleziona Poligono sulla mappa")
        btn_poligono.setMinimumHeight(40)
        btn_poligono.setStyleSheet(
            "QPushButton { background-color: #00897B; color: white; "
            "font-size: 12px; font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #006B5E; }"
        )
        btn_poligono.clicked.connect(self._on_poligono)
        g2_layout.addWidget(btn_poligono)
        group2.setLayout(g2_layout)
        layout.addWidget(group2)

        # --- Pulsante annulla ---
        btn_annulla = QPushButton("Annulla")
        btn_annulla.setMinimumHeight(32)
        btn_annulla.setStyleSheet(
            "QPushButton { color: #777; font-size: 11px; border: 1px solid #ccc; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #f0f0f0; }"
        )
        btn_annulla.clicked.connect(self.reject)
        layout.addWidget(btn_annulla)

        self.setLayout(layout)

    def _on_disegna(self):
        self.scelta = "disegna"
        self.accept()

    def _on_poligono(self):
        self.scelta = "poligono"
        self.accept()


# =============================================================================
# AVVIO PRINCIPALE
# =============================================================================

def avvia():
    print("\n" + "=" * 60)
    print("  WFS CATASTO - Download Particelle")
    print("=" * 60)

    dlg = SceltaModalitaDialog(iface.mainWindow())
    result = dlg.exec_()

    if result != QDialog.Accepted or dlg.scelta is None:
        print("[INFO] Operazione annullata dall'utente.")
        return

    canvas = iface.mapCanvas()

    if dlg.scelta == "disegna":
        print("\n  MODALITÀ: Disegna BBox")
        print("  >>> Clicca sulla mappa per il PRIMO angolo")
        print("  >>> Muovi il mouse per l'anteprima")
        print("  >>> Clicca per il SECONDO angolo")
        print("  >>> Il download partirà automaticamente\n")
        tool = BBoxDrawTool(canvas)
        canvas.setMapTool(tool)
        canvas._wfs_tool = tool

    elif dlg.scelta == "poligono":
        print("\n  MODALITÀ: Seleziona Poligono")
        print("  >>> Clicca su un poligono nella mappa")
        print("  >>> Il bbox verrà estratto e il CRS verificato")
        print("  >>> Il download partirà automaticamente\n")
        tool = PolySelectTool(canvas)
        canvas.setMapTool(tool)
        canvas._wfs_tool = tool


avvia()
