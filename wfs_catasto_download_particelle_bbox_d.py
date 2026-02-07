"""
WFS Catasto Download Particelle BBox - Dialog
==============================================
Interfaccia grafica per la scelta della modalità di selezione area.

Compatibile con QGIS 3 (Qt5) e QGIS 4 (Qt6).
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QSpinBox,
    QCheckBox,
    QScrollArea,
    QWidget,
)

# Compatibilità Qt5 / Qt6 - enum scoped
try:
    _WinHelpHint = Qt.WindowType.WindowContextHelpButtonHint
    _WinCloseHint = Qt.WindowType.WindowCloseButtonHint
    _WinStaysOnTop = Qt.WindowType.WindowStaysOnTopHint
    _AlignCenter = Qt.AlignmentFlag.AlignCenter
    _RichText = Qt.TextFormat.RichText
except AttributeError:
    _WinHelpHint = Qt.WindowContextHelpButtonHint
    _WinCloseHint = Qt.WindowCloseButtonHint
    _WinStaysOnTop = Qt.WindowStaysOnTopHint
    _AlignCenter = Qt.AlignCenter
    _RichText = Qt.RichText


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
            "dal servizio WFS dell'Agenzia delle Entrate (INSPIRE).<br><br>"
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

    def __init__(self, parent=None, default_buffer_m=50):
        super().__init__(parent)
        self.scelta = None
        self.buffer_distance = default_buffer_m
        self._default_buffer_m = default_buffer_m
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("WFS Catasto - Scelta modalità")
        self.setMinimumWidth(400)
        self.setWindowFlags(
            self.windowFlags()
            & ~_WinHelpHint
            | _WinStaysOnTop
        )

        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Titolo
        titolo = QLabel("Download Particelle Catastali WFS")
        font_titolo = QFont()
        font_titolo.setPointSize(13)
        font_titolo.setBold(True)
        titolo.setFont(font_titolo)
        titolo.setAlignment(_AlignCenter)
        layout.addWidget(titolo)

        # Sottotitolo
        sottotitolo = QLabel(
            "Seleziona la modalità per definire l'area di interesse:"
        )
        sottotitolo.setAlignment(_AlignCenter)
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
        desc1.setStyleSheet("font-weight: normal;")
        g1_layout.addWidget(desc1)

        btn_disegna = QPushButton("  Disegna BBox sulla mappa")
        btn_disegna.setMinimumHeight(40)
        btn_disegna.setStyleSheet(
            "QPushButton { background-color: #2962FF; color: white; "
            "font-size: 12px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
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
        desc2.setStyleSheet("font-weight: normal;")
        g2_layout.addWidget(desc2)

        btn_poligono = QPushButton("  Seleziona Poligono sulla mappa")
        btn_poligono.setMinimumHeight(40)
        btn_poligono.setStyleSheet(
            "QPushButton { background-color: #00897B; color: white; "
            "font-size: 12px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #006B5E; }"
        )
        btn_poligono.clicked.connect(self._on_poligono)
        g2_layout.addWidget(btn_poligono)
        group2.setLayout(g2_layout)
        layout.addWidget(group2)

        # --- Gruppo 3: Seleziona Asse Stradale ---
        group3 = QGroupBox("Seleziona Linea")
        group3.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #ccc; "
            "border-radius: 5px; margin-top: 10px; padding-top: 15px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        g3_layout = QVBoxLayout()
        desc3 = QLabel(
            "Clicca su una linea nella mappa.\n"
            "Verrà creato un buffer e scaricate le particelle\n"
            "che intersecano il buffer.\n\n"
            "\u26a0 Il layer deve avere un CRS proiettato (metri)."
        )
        desc3.setWordWrap(True)
        desc3.setStyleSheet("font-weight: normal;")
        g3_layout.addWidget(desc3)

        # Spinbox per valore buffer
        buffer_layout = QHBoxLayout()
        buffer_label = QLabel("Distanza buffer (0-100m):")
        buffer_label.setStyleSheet("font-weight: normal;")
        buffer_layout.addWidget(buffer_label)

        self.buffer_spinbox = QSpinBox()
        self.buffer_spinbox.setRange(0, 100)
        self.buffer_spinbox.setValue(self._default_buffer_m)
        self.buffer_spinbox.setSuffix(" m")
        self.buffer_spinbox.setMinimumWidth(100)
        self.buffer_spinbox.setMinimumHeight(32)
        self.buffer_spinbox.setStyleSheet(
            "QSpinBox { font-size: 12px; padding: 4px; }"
        )
        self.buffer_spinbox.valueChanged.connect(self._on_buffer_changed)
        buffer_layout.addWidget(self.buffer_spinbox)
        buffer_layout.addStretch()
        g3_layout.addLayout(buffer_layout)

        btn_asse = QPushButton("  Seleziona Linea")
        btn_asse.setMinimumHeight(40)
        btn_asse.setStyleSheet(
            "QPushButton { background-color: #FF6D00; color: white; "
            "font-size: 12px; font-weight: bold; border: none; "
            "border-radius: 4px; }"
            "QPushButton:hover { background-color: #E65100; }"
        )
        btn_asse.clicked.connect(self._on_asse)
        g3_layout.addWidget(btn_asse)
        group3.setLayout(g3_layout)
        layout.addWidget(group3)

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
        layout.addWidget(btn_annulla)

        self.setLayout(layout)

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
