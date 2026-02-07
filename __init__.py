"""
WFS Catasto Download Particelle BBox - Plugin QGIS
===================================================
Download particelle catastali dal WFS dell'Agenzia delle Entrate
tramite BBox interattivo, selezione poligono o asse stradale con buffer.

Autore: Salvatore Fiandaca
Email: pigrecoinfinito@gmail.com
"""


def classFactory(iface):
    from .wfs_catasto_download_particelle_bbox_p import WfsCatastoDownloadParticelleBbox
    return WfsCatastoDownloadParticelleBbox(iface)
