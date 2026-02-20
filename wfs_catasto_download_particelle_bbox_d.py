"""
WFS Catasto Download Particelle BBox - Dialog
==============================================
Interfaccia grafica per la scelta della modalità di selezione area.

Compatibile con QGIS 3 (Qt5) e QGIS 4 (Qt6).
"""

import configparser
import os
import webbrowser

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QPixmap
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QCheckBox,
    QScrollArea,
    QWidget,
    QFrame,
    QMessageBox,
)

# Compatibilità Qt5 / Qt6 - enum scoped
try:
    _WinHelpHint = Qt.WindowType.WindowContextHelpButtonHint
    _WinCloseHint = Qt.WindowType.WindowCloseButtonHint
    _AlignCenter = Qt.AlignmentFlag.AlignCenter
    _RichText = Qt.TextFormat.RichText
except AttributeError:
    _WinHelpHint = Qt.WindowContextHelpButtonHint
    _WinCloseHint = Qt.WindowCloseButtonHint
    _AlignCenter = Qt.AlignCenter
    _RichText = Qt.RichText

try:
    _KeepAspectRatio = Qt.AspectRatioMode.KeepAspectRatio
    _SmoothTransformation = Qt.TransformationMode.SmoothTransformation
except AttributeError:
    _KeepAspectRatio = Qt.KeepAspectRatio
    _SmoothTransformation = Qt.SmoothTransformation


def _is_point_layer(layer):
    """Verifica se il layer è puntuale (compatibile Qt5/Qt6)."""
    try:
        from qgis.core import Qgis
        return layer.geometryType() == Qgis.GeometryType.Point
    except AttributeError:
        return layer.geometryType() == 0


def _is_polygon_layer(layer):
    """Verifica se il layer è poligonale (compatibile Qt5/Qt6)."""
    try:
        from qgis.core import Qgis
        return layer.geometryType() == Qgis.GeometryType.Polygon
    except AttributeError:
        return layer.geometryType() == 2


def _plugin_version():
    """Legge la versione dal file metadata.txt del plugin."""
    meta_path = os.path.join(os.path.dirname(__file__), "metadata.txt")
    cfg = configparser.ConfigParser()
    cfg.read(meta_path)
    return cfg.get("general", "version", fallback="")


class AvvisoDialog(QDialog):
    """Finestra di avviso sull'uso responsabile del plugin (una volta per sessione QGIS)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("WFS Catasto - Avviso Importante")
        self.setMinimumSize(550, 480)
        self.setWindowFlags(
            self.windowFlags()
            & ~_WinHelpHint
            & ~_WinCloseHint
        )

        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        # Icona e titolo
        titolo = QLabel("\u26a0  AVVISO IMPORTANTE")
        font_titolo = QFont()
        font_titolo.setPointSize(16)
        font_titolo.setBold(True)
        titolo.setFont(font_titolo)
        titolo.setAlignment(_AlignCenter)
        titolo.setStyleSheet("color: #D32F2F;")
        layout.addWidget(titolo)

        # Area scrollabile per il testo
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #ccc; border-radius: 5px; }"
        )

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(15, 15, 15, 15)

        testo_avviso = QLabel(
            "Questo plugin consente di scaricare le particelle catastali "
            "dal servizio WFS dell'<a href=\"https://www.agenziaentrate.gov.it/portale/cartografia-catastale-wfs\">Agenzia delle Entrate</a> (INSPIRE) disponibile con licenza <a href=\"https://creativecommons.org/licenses/by/4.0/deed.it\">CC-BY 4.0</a>.<br><br>"
            "Si raccomanda un uso <b>responsabile</b> e <b>moderato</b> del plugin. "
            "Il download massivo o ripetuto di grandi quantit\u00e0 di dati "
            "potrebbe compromettere la disponibilit\u00e0 del servizio WFS "
            "dell'Agenzia delle Entrate, arrecando disservizio a tutti "
            "gli utenti.<br><br>"
            "L'autore invita al rispetto dell'<b>etica professionale</b> e delle "
            "buone pratiche nell'utilizzo delle risorse pubbliche condivise: "
            "il servizio WFS \u00e8 messo a disposizione dalla pubblica "
            "amministrazione per finalit\u00e0 istituzionali e professionali, "
            "non per lo scaricamento indiscriminato dei dati.<br><br>"
            "L'autore declina ogni responsabilit\u00e0 per eventuali usi "
            "impropri del plugin o per conseguenze derivanti da un "
            "utilizzo non conforme alle condizioni del servizio WFS "
            "dell'Agenzia delle Entrate."
        )
        testo_avviso.setTextFormat(_RichText)
        testo_avviso.setOpenExternalLinks(True)
        testo_avviso.setWordWrap(True)
        testo_avviso.setStyleSheet("font-size: 12px;")
        scroll_layout.addWidget(testo_avviso)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Checkbox obbligatoria
        self.check_accetto = QCheckBox(
            "Ho letto e compreso l'avviso. Mi impegno ad utilizzare "
            "il plugin in modo responsabile e moderato."
        )
        self.check_accetto.setStyleSheet(
            "QCheckBox { font-size: 11px; font-weight: bold; }"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self.check_accetto.toggled.connect(self._on_check_toggled)
        layout.addWidget(self.check_accetto)

        # Pulsanti
        btn_layout = QHBoxLayout()

        self.btn_accetta = QPushButton("Accetto e prosegui")
        self.btn_accetta.setMinimumHeight(40)
        self.btn_accetta.setEnabled(False)
        self.btn_accetta.setStyleSheet(
            "QPushButton { background-color: #388E3C; color: white; "
            "font-size: 12px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #2E7D32; }"
            "QPushButton:disabled { background-color: #A5D6A7; color: #eee; }"
        )
        self.btn_accetta.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_accetta)

        btn_rifiuta = QPushButton("Rifiuto e chiudi")
        btn_rifiuta.setMinimumHeight(40)
        btn_rifiuta.setStyleSheet(
            "QPushButton { background-color: #D32F2F; color: white; "
            "font-size: 12px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #B71C1C; }"
        )
        btn_rifiuta.clicked.connect(self.reject)
        btn_layout.addWidget(btn_rifiuta)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _on_check_toggled(self, checked):
        self.btn_accetta.setEnabled(checked)


class SceltaModalitaDialog(QDialog):
    """Finestra di dialogo per scegliere la modalità di definizione dell'area."""

    # Stile comune per i QGroupBox delle celle
    _CELL_STYLE = (
        "QGroupBox { font-weight: bold; border: 1px solid #ccc; "
        "border-radius: 5px; margin-top: 10px; padding-top: 15px; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
    )

    def __init__(self, parent=None, default_buffer_m=50,
                 default_buffer_punti_m=1, default_snap_px=15):
        super().__init__(parent)
        self.scelta = None
        self.buffer_distance = default_buffer_m
        self.buffer_punti_distance = default_buffer_punti_m
        self.snap_tolerance = default_snap_px
        self._default_buffer_m = default_buffer_m
        self._default_buffer_punti_m = default_buffer_punti_m
        self._default_snap_px = default_snap_px
        self._init_ui()

    def showEvent(self, event):
        """Aggiorna le combo dei layer ogni volta che il dialog viene mostrato."""
        super().showEvent(event)
        self._refresh_layer_combos()

    def _refresh_layer_combos(self):
        """Ripopola le combo con i layer correnti del progetto."""
        # --- Sorgente punti: si azzera sempre a "(clicca sulla mappa)" ---
        self.combo_source_layer.blockSignals(True)
        self.combo_source_layer.clear()
        self.combo_source_layer.addItem("(clicca sulla mappa)", None)
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and _is_point_layer(layer):
                self.combo_source_layer.addItem(layer.name(), layer.id())
        # Non ripristinare la selezione: ogni operazione parte da "(clicca sulla mappa)"
        self.combo_source_layer.blockSignals(False)

        # --- Layer destinazione append (locale Punti e globale) ---
        polygon_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and _is_polygon_layer(layer)
            and ("Particelle" in layer.name() or "WFS" in layer.name())
        ]

        self.combo_append_layer.blockSignals(True)
        current_append_id = self.combo_append_layer.currentData()
        self.combo_append_layer.clear()
        self.combo_append_layer.addItem("(nuovo layer)", None)
        for layer in polygon_layers:
            self.combo_append_layer.addItem(layer.name(), layer.id())
        if current_append_id is not None:
            idx = self.combo_append_layer.findData(current_append_id)
            if idx >= 0:
                self.combo_append_layer.setCurrentIndex(idx)
        self.combo_append_layer.blockSignals(False)

        self.combo_output_globale.blockSignals(True)
        current_global_id = self.combo_output_globale.currentData()
        self.combo_output_globale.clear()
        self.combo_output_globale.addItem("(seleziona layer...)", None)
        for layer in polygon_layers:
            self.combo_output_globale.addItem(layer.name(), layer.id())
        if current_global_id is not None:
            idx = self.combo_output_globale.findData(current_global_id)
            if idx >= 0:
                self.combo_output_globale.setCurrentIndex(idx)
        self.combo_output_globale.blockSignals(False)

    def _init_ui(self):
        ver = _plugin_version()
        titolo_str = "WFS Catasto - Scelta modalità"
        if ver:
            titolo_str += f"  v{ver}"
        self.setWindowTitle(titolo_str)
        self.setMinimumWidth(580)
        self.setWindowFlags(self.windowFlags() & ~_WinHelpHint)

        layout = QVBoxLayout()
        layout.setSpacing(3)
        layout.setContentsMargins(12, 12, 12, 12)

        # --- Titolo ---
        titolo_lbl = QLabel(
            'Download Particelle Catastali WFS '
            '(<a href="https://creativecommons.org/licenses/by/4.0/deed.it">'
            'CC-BY 4.0</a>)'
        )
        font_titolo = QFont()
        font_titolo.setPointSize(13)
        font_titolo.setBold(True)
        titolo_lbl.setFont(font_titolo)
        titolo_lbl.setAlignment(_AlignCenter)
        titolo_lbl.setTextFormat(_RichText)
        titolo_lbl.setOpenExternalLinks(True)
        layout.addWidget(titolo_lbl)

        sottotitolo = QLabel("Seleziona la modalità per definire l'area di interesse:")
        sottotitolo.setAlignment(_AlignCenter)
        layout.addWidget(sottotitolo)

        layout.addSpacing(4)

        # Dimensioni icona SVG per le righe
        ico_w, ico_h = 56, 44

        # --- Righe modalità ---
        layout.addWidget(self._row_bbox(ico_w, ico_h))
        layout.addWidget(self._row_poligono(ico_w, ico_h))
        layout.addWidget(self._row_linea(ico_w, ico_h))
        layout.addWidget(self._row_punti(ico_w, ico_h))

        # --- Separatore ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine if hasattr(QFrame, 'Shape') else QFrame.HLine)
        sep.setStyleSheet("color: #ccc;")
        layout.addWidget(sep)

        # --- Riga Output ---
        layout.addWidget(self._row_output(ico_w, ico_h))

        # --- Riga Opzioni ---
        layout.addWidget(self._row_opzioni(ico_w, ico_h))

        # Connessione checkbox -> abilita/disabilita combo e mostra/nasconde app_row locale
        self.check_output_globale.toggled.connect(self._on_output_globale_toggled)

        # --- Separatore ---
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine if hasattr(QFrame, 'Shape') else QFrame.HLine)
        sep2.setStyleSheet("color: #ccc;")
        layout.addWidget(sep2)

        # --- Pulsanti in basso ---
        bottom_layout = QHBoxLayout()
        btn_annulla = QPushButton("Chiudi")
        btn_annulla.setMinimumHeight(32)
        btn_annulla.setStyleSheet(
            "QPushButton { background-color: #D32F2F; color: white; "
            "font-size: 11px; font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #B71C1C; }"
        )
        btn_annulla.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_annulla, 3)
        btn_aiuto = QPushButton("❓ Guida")
        btn_aiuto.setMinimumHeight(32)
        btn_aiuto.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-size: 11px; font-weight: bold; border: none; border-radius: 4px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        btn_aiuto.clicked.connect(self._on_aiuto)
        bottom_layout.addWidget(btn_aiuto, 1)
        layout.addLayout(bottom_layout)

        self.setLayout(layout)

    # ---- Righe lista ----

    _BTN_STYLE = (
        "QPushButton {{ background-color: {color}; color: white; "
        "font-size: 11px; font-weight: bold; border: none; border-radius: 4px; }}"
        "QPushButton:hover {{ background-color: {hover}; }}"
    )
    _LBL_STYLE = "font-weight: normal; font-size: 10px;"
    _DESC_STYLE = "font-size: 10px; color: #666;"

    def _make_row(self):
        """Crea un QWidget riga con QHBoxLayout interno."""
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(8)
        return w, row

    def _row_bbox(self, ico_w, ico_h):
        w, row = self._make_row()
        row.addWidget(self._svg_label("sketches_bbox.svg", ico_w, ico_h))
        btn = QPushButton("Disegna BBox")
        btn.setMinimumHeight(32)
        btn.setFixedWidth(160)
        btn.setStyleSheet(self._BTN_STYLE.format(color="#2962FF", hover="#1E4FD0"))
        btn.clicked.connect(self._on_disegna)
        row.addWidget(btn)
        desc = QLabel("Disegna un rettangolo sulla mappa")
        desc.setStyleSheet(self._DESC_STYLE)
        desc.setWordWrap(True)
        row.addWidget(desc, 1)
        return w

    def _row_poligono(self, ico_w, ico_h):
        w, row = self._make_row()
        row.addWidget(self._svg_label("sketches_polygon.svg", ico_w, ico_h))
        btn = QPushButton("Seleziona Poligono")
        btn.setMinimumHeight(32)
        btn.setFixedWidth(160)
        btn.setStyleSheet(self._BTN_STYLE.format(color="#00897B", hover="#006B5E"))
        btn.clicked.connect(self._on_poligono)
        row.addWidget(btn)
        desc = QLabel("Clicca su un poligono in mappa")
        desc.setStyleSheet(self._DESC_STYLE)
        desc.setWordWrap(True)
        row.addWidget(desc, 1)
        return w

    def _row_linea(self, ico_w, ico_h):
        w, row = self._make_row()
        row.addWidget(self._svg_label("sketches_line.svg", ico_w, ico_h))
        btn = QPushButton("Seleziona Linea")
        btn.setMinimumHeight(32)
        btn.setFixedWidth(160)
        btn.setStyleSheet(self._BTN_STYLE.format(color="#F57F17", hover="#E65100"))
        btn.clicked.connect(self._on_asse)
        row.addWidget(btn)
        buf_lbl = QLabel("Buffer:")
        buf_lbl.setStyleSheet(self._LBL_STYLE)
        row.addWidget(buf_lbl)
        self.buffer_spinbox = QSpinBox()
        self.buffer_spinbox.setRange(0, 100)
        self.buffer_spinbox.setValue(self._default_buffer_m)
        self.buffer_spinbox.setSuffix(" m")
        self.buffer_spinbox.setFixedWidth(68)
        self.buffer_spinbox.setStyleSheet("QSpinBox { font-size: 11px; padding: 2px; }")
        self.buffer_spinbox.valueChanged.connect(self._on_buffer_changed)
        row.addWidget(self.buffer_spinbox)
        desc = QLabel("Clicca su una linea o disegna una polilinea")
        desc.setStyleSheet(self._DESC_STYLE)
        desc.setWordWrap(True)
        row.addWidget(desc, 1)
        return w

    def _row_punti(self, ico_w, ico_h):
        """Riga Seleziona Punti: riga principale + sotto-riga per Sorgente/Aggiungi a."""
        outer = QWidget()
        vbox = QVBoxLayout(outer)
        vbox.setContentsMargins(2, 2, 2, 2)
        vbox.setSpacing(2)

        # Riga principale: SVG + bottone + buffer + snap + descrizione
        main_row = QHBoxLayout()
        main_row.setSpacing(8)
        main_row.addWidget(self._svg_label("sketches_points.svg", ico_w, ico_h))
        btn = QPushButton("Seleziona Punti")
        btn.setMinimumHeight(32)
        btn.setFixedWidth(160)
        btn.setStyleSheet(self._BTN_STYLE.format(color="#7B1FA2", hover="#6A1B9A"))
        btn.clicked.connect(self._on_punti)
        main_row.addWidget(btn)
        buf_lbl = QLabel("Buffer:")
        buf_lbl.setStyleSheet(self._LBL_STYLE)
        main_row.addWidget(buf_lbl)
        self.buffer_punti_spinbox = QSpinBox()
        self.buffer_punti_spinbox.setRange(0, 100)
        self.buffer_punti_spinbox.setValue(self._default_buffer_punti_m)
        self.buffer_punti_spinbox.setSuffix(" m")
        self.buffer_punti_spinbox.setFixedWidth(68)
        self.buffer_punti_spinbox.setStyleSheet("QSpinBox { font-size: 11px; padding: 2px; }")
        self.buffer_punti_spinbox.valueChanged.connect(self._on_buffer_punti_changed)
        main_row.addWidget(self.buffer_punti_spinbox)
        snap_lbl = QLabel("Snap:")
        snap_lbl.setStyleSheet(self._LBL_STYLE)
        main_row.addWidget(snap_lbl)
        self.snap_spinbox = QSpinBox()
        self.snap_spinbox.setRange(1, 50)
        self.snap_spinbox.setValue(self._default_snap_px)
        self.snap_spinbox.setSuffix(" px")
        self.snap_spinbox.setFixedWidth(68)
        self.snap_spinbox.setStyleSheet("QSpinBox { font-size: 11px; padding: 2px; }")
        self.snap_spinbox.valueChanged.connect(self._on_snap_changed)
        main_row.addWidget(self.snap_spinbox)
        desc = QLabel("Clicca su layer di punti per scaricare")
        desc.setStyleSheet(self._DESC_STYLE)
        desc.setWordWrap(True)
        main_row.addWidget(desc, 1)
        vbox.addLayout(main_row)

        # Sotto-riga: Sorgente + Aggiungi a (rientrata sotto il bottone)
        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        sub_row.addSpacing(ico_w + 8)
        src_lbl = QLabel("Sorgente:")
        src_lbl.setStyleSheet(self._LBL_STYLE)
        sub_row.addWidget(src_lbl)
        self.combo_source_layer = QComboBox()
        self.combo_source_layer.addItem("(clicca sulla mappa)", None)
        self.combo_source_layer.setStyleSheet("font-size: 10px;")
        self.combo_source_layer.setToolTip(
            "Scegli un layer punti dal progetto oppure lascia\n"
            "'(clicca sulla mappa)' per selezionarlo cliccando."
        )
        sub_row.addWidget(self.combo_source_layer, 1)
        # widget_append_row - nascosto quando il controllo Output globale e' attivo
        self.widget_append_row = QWidget()
        app_row_layout = QHBoxLayout(self.widget_append_row)
        app_row_layout.setContentsMargins(0, 0, 0, 0)
        app_row_layout.setSpacing(8)
        app_lbl = QLabel("Aggiungi a:")
        app_lbl.setStyleSheet(self._LBL_STYLE)
        app_row_layout.addWidget(app_lbl)
        self.combo_append_layer = QComboBox()
        self.combo_append_layer.addItem("(nuovo layer)", None)
        self.combo_append_layer.setStyleSheet("font-size: 10px;")
        self.combo_append_layer.setToolTip(
            "Scegli un layer Particelle WFS esistente a cui aggiungere\n"
            "le nuove particelle, oppure lascia '(nuovo layer)'."
        )
        app_row_layout.addWidget(self.combo_append_layer, 1)
        sub_row.addWidget(self.widget_append_row, 1)
        vbox.addLayout(sub_row)

        return outer

    def _row_output(self, ico_w, ico_h):
        w, row = self._make_row()
        marker = QLabel("⬡")
        marker.setFixedSize(ico_w, ico_h)
        marker.setAlignment(_AlignCenter)
        marker.setStyleSheet(
            "background-color: #E3F2FD; border-radius: 4px; "
            "border: 1px solid #90CAF9; color: #1565C0; font-size: 18px;"
        )
        row.addWidget(marker)
        self.check_output_globale = QCheckBox("Aggiungi a layer esistente:")
        self.check_output_globale.setStyleSheet(self._LBL_STYLE)
        self.check_output_globale.setChecked(False)
        row.addWidget(self.check_output_globale)
        self.combo_output_globale = QComboBox()
        self.combo_output_globale.setStyleSheet("font-size: 10px;")
        self.combo_output_globale.setEnabled(False)
        self.combo_output_globale.setToolTip(
            "Layer Particelle WFS esistente a cui accodare i risultati\n"
            "di qualsiasi modalita' di download."
        )
        row.addWidget(self.combo_output_globale, 1)
        lbl = QLabel("Output")
        lbl.setStyleSheet("font-size: 10px; color: #1565C0; font-weight: bold;")
        row.addWidget(lbl)
        return w

    def _row_opzioni(self, ico_w, ico_h):
        w, row = self._make_row()
        marker = QLabel("⚙")
        marker.setFixedSize(ico_w, ico_h)
        marker.setAlignment(_AlignCenter)
        marker.setStyleSheet(
            "background-color: #F3E5F5; border-radius: 4px; "
            "border: 1px solid #CE93D8; color: #6A1B9A; font-size: 18px;"
        )
        row.addWidget(marker)
        self.check_espandi_catastale = QCheckBox(
            "Espandi riferimento catastale (sezione, foglio, allegato, sviluppo)"
        )
        self.check_espandi_catastale.setStyleSheet(self._LBL_STYLE)
        self.check_espandi_catastale.setChecked(False)
        row.addWidget(self.check_espandi_catastale)
        self.check_carica_wms = QCheckBox("Carica WMS Cartografia Catastale")
        self.check_carica_wms.setStyleSheet(self._LBL_STYLE)
        self.check_carica_wms.setChecked(False)
        row.addWidget(self.check_carica_wms)
        lbl = QLabel("Opzioni")
        lbl.setStyleSheet("font-size: 10px; color: #6A1B9A; font-weight: bold;")
        row.addWidget(lbl)
        return w

        # ---- Helpers ----

    def _svg_label(self, filename, max_w=140, max_h=121):
        """Crea una QLabel con l'immagine SVG dalla cartella sketches."""
        path = os.path.join(os.path.dirname(__file__), "sketches", filename)
        lbl = QLabel()
        lbl.setAlignment(_AlignCenter)
        lbl.setMaximumSize(max_w, max_h)
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            lbl.setPixmap(
                pixmap.scaled(max_w, max_h, _KeepAspectRatio, _SmoothTransformation)
            )
        return lbl

    @property
    def espandi_catastale(self):
        return self.check_espandi_catastale.isChecked()

    @property
    def carica_wms(self):
        return self.check_carica_wms.isChecked()

    # ---- Slot ----

    def _on_disegna(self):
        self.scelta = "disegna"
        self.accept()

    def _on_poligono(self):
        self.scelta = "poligono"
        self.accept()

    def _on_buffer_changed(self, value):
        self.buffer_distance = value

    def _on_asse(self):
        self.scelta = "asse"
        self.accept()

    def _on_buffer_punti_changed(self, value):
        self.buffer_punti_distance = value

    def _on_snap_changed(self, value):
        self.snap_tolerance = value

    def _on_punti(self):
        self.scelta = "punti"
        self.accept()

    def _on_output_globale_toggled(self, checked):
        """Abilita/disabilita combo globale e mostra/nasconde app_row locale di Punti."""
        self.combo_output_globale.setEnabled(checked)
        self.widget_append_row.setVisible(not checked)

    @property
    def selected_point_layer(self):
        """Restituisce il layer punti sorgente selezionato, o None se 'clicca sulla mappa'."""
        layer_id = self.combo_source_layer.currentData()
        if layer_id is None:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    @property
    def append_to_wfs_layer(self):
        """Restituisce il layer WFS destinazione selezionato, o None se 'nuovo layer'.

        Se il controllo Output globale è attivo, ha precedenza sul combo locale.
        """
        if self.check_output_globale.isChecked():
            return self.output_globale_layer
        layer_id = self.combo_append_layer.currentData()
        if layer_id is None:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    @property
    def output_globale_layer(self):
        """Restituisce il layer destinazione globale, o None se non attivo/selezionato."""
        if not self.check_output_globale.isChecked():
            return None
        layer_id = self.combo_output_globale.currentData()
        if layer_id is None:
            return None
        return QgsProject.instance().mapLayer(layer_id)
    
    def _on_aiuto(self):
        """Apre la pagina di aiuto del plugin su GitHub Pages."""
        help_url = "https://pigreco.github.io/wfs_catasto_download_particelle_bbox/"
        try:
            webbrowser.open(help_url)
        except Exception as e:
            QMessageBox.information(
                self,
                "Aiuto Plugin",
                f"Impossibile aprire il browser automaticamente.\n\n"
                f"Visita manualmente: {help_url}\n\n"
                f"Errore: {str(e)}"
            )


class AboutDialog(QDialog):
    """Dialog con informazioni sul plugin."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Informazioni - WFS Catasto Download Particelle")
        self.setWindowFlags(self.windowFlags() & ~_WinHelpHint | _WinCloseHint)
        self.setMinimumSize(650, 500)
        self.setMaximumSize(800, 700)
        
        # Layout principale
        layout = QVBoxLayout()
        
        # Scroll area per contenuto
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        
        # Titolo
        title_label = QLabel("<h2>WFS Catasto Download Particelle BBox</h2>")
        title_label.setAlignment(_AlignCenter)
        title_label.setTextFormat(_RichText)
        content_layout.addWidget(title_label)
        
        # Versione
        version = _plugin_version()
        version_label = QLabel(f"<h3>Versione: {version}</h3>")
        version_label.setAlignment(_AlignCenter)
        version_label.setTextFormat(_RichText)
        content_layout.addWidget(version_label)
        
        # Autore
        author_label = QLabel("<b>Autore:</b> <a href=\"https://github.com/pigreco\">Salvatore Fiandaca</a>")
        author_label.setTextFormat(_RichText)
        author_label.setWordWrap(True)
        author_label.setOpenExternalLinks(True)
        content_layout.addWidget(author_label)
        
        content_layout.addWidget(QLabel(""))  # Spaziatura
        
        # Descrizione
        desc_label = QLabel("<b>Descrizione:</b>")
        desc_label.setTextFormat(_RichText)
        content_layout.addWidget(desc_label)
        
        description = "Plugin per QGIS che consente di scaricare le particelle catastali dal servizio WFS dell'Agenzia delle Entrate (INSPIRE).<br><br><b>Quattro modalità di selezione dell'area di interesse:</b><br><br>&nbsp;&nbsp;• <b>Disegna BBox:</b><br>&nbsp;&nbsp;&nbsp;&nbsp;Clicca due punti sulla mappa per disegnare un rettangolo<br><br>&nbsp;&nbsp;• <b>Seleziona Poligono:</b><br>&nbsp;&nbsp;&nbsp;&nbsp;Clicca su un poligono esistente per estrarne il bounding box<br><br>&nbsp;&nbsp;• <b>Seleziona Linea:</b><br>&nbsp;&nbsp;&nbsp;&nbsp;Due modalità disponibili:<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1. Clicca su una linea esistente nei layer<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;2. Disegna una nuova polilinea sulla mappa<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(click sinistro per aggiungere vertici, destro per terminare)<br>&nbsp;&nbsp;&nbsp;&nbsp;Applica automaticamente un buffer personalizzabile (0-100m)<br>&nbsp;&nbsp;&nbsp;&nbsp;per scaricare tutte le particelle che intersecano la zona bufferizzata<br><br>&nbsp;&nbsp;• <b>Seleziona Punti:</b><br>&nbsp;&nbsp;&nbsp;&nbsp;Tre modalità disponibili:<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1. Clicca su un layer di punti esistente<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;2. Disegna/traccia un nuovo punto sulla mappa<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;3. Selezione diretta sulla mappa<br>&nbsp;&nbsp;&nbsp;&nbsp;Supporta buffer personalizzabile attorno ai punti, selezione parziale<br>&nbsp;&nbsp;&nbsp;&nbsp;del layer e auto-riproiezione UTM per CRS geografici<br><br><b>Funzionalità avanzate:</b><br><br>&nbsp;&nbsp;• Espansione riferimento catastale (sezione, foglio, allegato, sviluppo)<br>&nbsp;&nbsp;• Download multi-tile con progress bar<br>&nbsp;&nbsp;• Deduplicazione feature e filtro spaziale<br>&nbsp;&nbsp;• Compatibile con QGIS 3 (Qt5) e QGIS 4 (Qt6)"
        desc_text = QLabel(description)
        desc_text.setTextFormat(_RichText)
        desc_text.setWordWrap(True)
        content_layout.addWidget(desc_text)
        
        content_layout.addWidget(QLabel(""))  # Spaziatura
        
        # Licenza
        license_label = QLabel("<b>Licenza:</b> Questo plugin è rilasciato sotto licenza open source.")
        license_label.setTextFormat(_RichText)
        license_label.setWordWrap(True)
        content_layout.addWidget(license_label)
        
        content_layout.addWidget(QLabel(""))  # Spaziatura
        
        # Riferimenti e servizi
        refs_label = QLabel("<b>Riferimenti e servizi utilizzati:</b>")
        refs_label.setTextFormat(_RichText)
        content_layout.addWidget(refs_label)
        
        refs_text = QLabel(
            "• <b>Servizio WFS:</b><br>"
            "&nbsp;&nbsp;<a href=\"https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php\">https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php</a><br><br>"
            "• <b>Servizio WMS:</b><br>"
            "&nbsp;&nbsp;<a href=\"https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php\">https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php</a><br><br>"
            "• <b>Documentazione ufficiale:</b><br>"
            "&nbsp;&nbsp;<a href=\"https://www.agenziaentrate.gov.it/portale/cartografia-catastale-wfs\">Cartografia Catastale WFS - Agenzia delle Entrate</a><br><br>"
            "• <b>Licenza dati:</b> <a href=\"https://creativecommons.org/licenses/by/4.0/deed.it\">CC-BY 4.0</a>"
        )
        refs_text.setTextFormat(_RichText)
        refs_text.setWordWrap(True)
        refs_text.setOpenExternalLinks(True)
        content_layout.addWidget(refs_text)
        
        content_layout.addStretch()
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)
        
        # Pulsante Chiudi
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_button = QPushButton("Chiudi")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
