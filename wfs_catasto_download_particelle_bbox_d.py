"""
WFS Catasto Download Particelle BBox - Dialog
==============================================
Interfaccia grafica per la scelta della modalità di selezione area.

Compatibile con QGIS 3 (Qt5) e QGIS 4 (Qt6).
"""

import configparser
import os
import webbrowser

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QSpinBox,
    QCheckBox,
    QScrollArea,
    QWidget,
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

    def _init_ui(self):
        ver = _plugin_version()
        titolo = "WFS Catasto - Scelta modalità"
        if ver:
            titolo += f"  v{ver}"
        self.setWindowTitle(titolo)
        self.setMinimumWidth(500)
        self.setWindowFlags(
            self.windowFlags()
            & ~_WinHelpHint
        )

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Titolo
        titolo = QLabel(
            'Download Particelle Catastali WFS '
            '(<a href="https://creativecommons.org/licenses/by/4.0/deed.it">'
            'CC-BY 4.0</a>)'
        )
        font_titolo = QFont()
        font_titolo.setPointSize(13)
        font_titolo.setBold(True)
        titolo.setFont(font_titolo)
        titolo.setAlignment(_AlignCenter)
        titolo.setTextFormat(_RichText)
        titolo.setOpenExternalLinks(True)
        layout.addWidget(titolo)

        # Sottotitolo
        sottotitolo = QLabel(
            "Seleziona la modalità per definire l'area di interesse:"
        )
        sottotitolo.setAlignment(_AlignCenter)
        layout.addWidget(sottotitolo)

        # --- Griglia 2x2 ---
        grid = QGridLayout()
        grid.setSpacing(8)

        # Dimensioni SVG per la griglia (uguali per tutte le celle)
        svg_w, svg_h = 200, 160

        # (0,0) Disegna BBox
        grid.addWidget(self._cell_bbox(svg_w, svg_h), 0, 0)
        # (0,1) Seleziona Poligono
        grid.addWidget(self._cell_poligono(svg_w, svg_h), 0, 1)
        # (1,0) Seleziona Linea
        grid.addWidget(self._cell_linea(svg_w, svg_h), 1, 0)
        # (1,1) Seleziona Punti
        grid.addWidget(self._cell_punti(svg_w, svg_h), 1, 1)

        layout.addLayout(grid)

        # --- Opzioni ---
        group_opzioni = QGroupBox("Opzioni")
        group_opzioni.setStyleSheet(self._CELL_STYLE)
        go_layout = QVBoxLayout()
        self.check_espandi_catastale = QCheckBox(
            "Espandi riferimento catastale (sezione, foglio, allegato, sviluppo)"
        )
        self.check_espandi_catastale.setStyleSheet("font-weight: normal;")
        self.check_espandi_catastale.setChecked(False)
        go_layout.addWidget(self.check_espandi_catastale)
        self.check_carica_wms = QCheckBox(
            "Carica WMS Cartografia Catastale"
        )
        self.check_carica_wms.setStyleSheet("font-weight: normal;")
        self.check_carica_wms.setChecked(False)
        go_layout.addWidget(self.check_carica_wms)
        group_opzioni.setLayout(go_layout)
        layout.addWidget(group_opzioni)

        # --- Layout per i pulsanti in basso ---
        bottom_layout = QHBoxLayout()
        
        # --- Pulsante Aiuto ---
        btn_aiuto = QPushButton("❓ Aiuto")
        btn_aiuto.setMinimumHeight(32)
        btn_aiuto.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-size: 11px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        btn_aiuto.clicked.connect(self._on_aiuto)
        bottom_layout.addWidget(btn_aiuto)
        
        # Spaziatore per spingere "Chiudi" a destra
        bottom_layout.addStretch()

        # --- Pulsante chiudi ---
        btn_annulla = QPushButton("Chiudi")
        btn_annulla.setMinimumHeight(32)
        btn_annulla.setStyleSheet(
            "QPushButton { background-color: #D32F2F; color: white; "
            "font-size: 11px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #B71C1C; }"
        )
        btn_annulla.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_annulla)
        
        layout.addLayout(bottom_layout)

        self.setLayout(layout)

    # ---- Celle della griglia ----

    def _cell_bbox(self, svg_w, svg_h):
        """Cella (0,0): Disegna BBox."""
        group = QGroupBox("Disegna BBox")
        group.setStyleSheet(self._CELL_STYLE)
        gl = QVBoxLayout()

        gl.addWidget(self._svg_label("sketches_bbox.svg", svg_w, svg_h))

        desc = QLabel("Disegna un rettangolo sulla mappa")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-weight: normal; font-size: 10px;")
        desc.setAlignment(_AlignCenter)
        gl.addWidget(desc)

        gl.addStretch()

        btn = QPushButton("Disegna BBox")
        btn.setMinimumHeight(34)
        btn.setStyleSheet(
            "QPushButton { background-color: #2962FF; color: white; "
            "font-size: 11px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #1E4FD0; }"
        )
        btn.clicked.connect(self._on_disegna)
        gl.addWidget(btn)

        group.setLayout(gl)
        return group

    def _cell_poligono(self, svg_w, svg_h):
        """Cella (0,1): Seleziona Poligono."""
        group = QGroupBox("Seleziona Poligono")
        group.setStyleSheet(self._CELL_STYLE)
        gl = QVBoxLayout()

        gl.addWidget(self._svg_label("sketches_polygon.svg", svg_w, svg_h))

        desc = QLabel("Clicca su un poligono in mappa")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-weight: normal; font-size: 10px;")
        desc.setAlignment(_AlignCenter)
        gl.addWidget(desc)

        gl.addStretch()

        btn = QPushButton("Seleziona Poligono")
        btn.setMinimumHeight(34)
        btn.setStyleSheet(
            "QPushButton { background-color: #00897B; color: white; "
            "font-size: 11px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #006B5E; }"
        )
        btn.clicked.connect(self._on_poligono)
        gl.addWidget(btn)

        group.setLayout(gl)
        return group

    def _cell_linea(self, svg_w, svg_h):
        """Cella (1,0): Seleziona Linea con buffer."""
        group = QGroupBox("Seleziona o disegna Linea")
        group.setStyleSheet(self._CELL_STYLE)
        gl = QVBoxLayout()

        gl.addWidget(self._svg_label("sketches_line.svg", svg_w, svg_h))

        desc = QLabel("Clicca su una linea o disegna una polilinea")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-weight: normal; font-size: 10px;")
        desc.setAlignment(_AlignCenter)
        gl.addWidget(desc)

        # Buffer: label + spinbox sulla stessa riga
        buf_row = QHBoxLayout()
        buf_lbl = QLabel("Buffer:")
        buf_lbl.setStyleSheet("font-weight: normal; font-size: 10px;")
        buf_row.addWidget(buf_lbl)
        self.buffer_spinbox = QSpinBox()
        self.buffer_spinbox.setRange(0, 100)
        self.buffer_spinbox.setValue(self._default_buffer_m)
        self.buffer_spinbox.setSuffix(" m")
        self.buffer_spinbox.setStyleSheet(
            "QSpinBox { font-size: 11px; padding: 2px; }"
        )
        self.buffer_spinbox.valueChanged.connect(self._on_buffer_changed)
        buf_row.addWidget(self.buffer_spinbox)
        buf_row.addStretch()
        gl.addLayout(buf_row)

        gl.addStretch()

        btn = QPushButton("Seleziona o disegna Linea")
        btn.setMinimumHeight(34)
        btn.setStyleSheet(
            "QPushButton { background-color: #FF6D00; color: white; "
            "font-size: 11px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #E65100; }"
        )
        btn.clicked.connect(self._on_asse)
        gl.addWidget(btn)

        group.setLayout(gl)
        return group

    def _cell_punti(self, svg_w, svg_h):
        """Cella (1,1): Seleziona Punti con buffer."""
        group = QGroupBox("Seleziona Punti")
        group.setStyleSheet(self._CELL_STYLE)
        gl = QVBoxLayout()

        gl.addWidget(self._svg_label("sketches_points.svg", svg_w, svg_h))

        desc = QLabel("Clicca su layer di punti per scaricare")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-weight: normal; font-size: 10px;")
        desc.setAlignment(_AlignCenter)
        gl.addWidget(desc)

        # Buffer + Snap sulla stessa riga
        params_row = QHBoxLayout()
        buf_lbl = QLabel("Buffer:")
        buf_lbl.setStyleSheet("font-weight: normal; font-size: 10px;")
        params_row.addWidget(buf_lbl)
        self.buffer_punti_spinbox = QSpinBox()
        self.buffer_punti_spinbox.setRange(0, 100)
        self.buffer_punti_spinbox.setValue(self._default_buffer_punti_m)
        self.buffer_punti_spinbox.setSuffix(" m")
        self.buffer_punti_spinbox.setStyleSheet(
            "QSpinBox { font-size: 11px; padding: 2px; }"
        )
        self.buffer_punti_spinbox.valueChanged.connect(
            self._on_buffer_punti_changed
        )
        params_row.addWidget(self.buffer_punti_spinbox)
        snap_lbl = QLabel("Snap:")
        snap_lbl.setStyleSheet("font-weight: normal; font-size: 10px;")
        params_row.addWidget(snap_lbl)
        self.snap_spinbox = QSpinBox()
        self.snap_spinbox.setRange(1, 50)
        self.snap_spinbox.setValue(self._default_snap_px)
        self.snap_spinbox.setSuffix(" px")
        self.snap_spinbox.setStyleSheet(
            "QSpinBox { font-size: 11px; padding: 2px; }"
        )
        self.snap_spinbox.valueChanged.connect(self._on_snap_changed)
        params_row.addWidget(self.snap_spinbox)
        params_row.addStretch()
        gl.addLayout(params_row)

        gl.addStretch()

        btn = QPushButton("Seleziona Punti")
        btn.setMinimumHeight(34)
        btn.setStyleSheet(
            "QPushButton { background-color: #7B1FA2; color: white; "
            "font-size: 11px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #6A1B9A; }"
        )
        btn.clicked.connect(self._on_punti)
        gl.addWidget(btn)

        group.setLayout(gl)
        return group

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
