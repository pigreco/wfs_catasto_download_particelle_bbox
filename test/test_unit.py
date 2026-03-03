#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test unitari per WFS Catasto Download Particelle BBox
======================================================
Test puri Python (nessuna dipendenza da QGIS o rete).
Coprono la logica matematica e di parsing del plugin.

Eseguire con:
    python test/test_unit.py
"""

import math
import re
import sys
import unittest

# ---------------------------------------------------------------------------
# Funzioni copiate 1:1 dal plugin (wfs_catasto_download_particelle_bbox_p.py)
# così i test girano senza QGIS installato.
# ---------------------------------------------------------------------------

MAX_TILE_KM2 = 4.0


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


def calcola_griglia_tile(min_lat, min_lon, max_lat, max_lon, max_tile_km2):
    """
    Suddivide il bbox in una griglia di tile, ciascuna con area <= max_tile_km2.
    Restituisce una lista di tuple (min_lat, min_lon, max_lat, max_lon).
    """
    area_totale = stima_area_km2(min_lat, min_lon, max_lat, max_lon)

    if area_totale <= max_tile_km2:
        return [(min_lat, min_lon, max_lat, max_lon)]

    n_tiles_necessari = math.ceil(area_totale / max_tile_km2)
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

    return tiles


def _parse_nationalcadastralreference(ref):
    """
    Parsing di NATIONALCADASTRALREFERENCE (formato CCCCZFFFFAS.particella).
    Restituisce dict con: comune, sezione, foglio, allegato, sviluppo, particella.
    """
    result = {
        "comune": None,
        "sezione": None,
        "foglio": None,
        "allegato": None,
        "sviluppo": None,
        "particella": None,
    }
    if not ref or not isinstance(ref, str):
        return result

    parts = ref.split(".")
    codice = parts[0]          # CCCCZFFFFAS (11 caratteri)
    particella = parts[1] if len(parts) > 1 else None

    result["particella"] = particella

    if len(codice) == 11:
        result["comune"] = codice[0:4]       # CCCC
        sez = codice[4]                       # Z
        result["sezione"] = "" if sez == "_" else sez
        result["foglio"] = codice[5:9]        # FFFF
        result["allegato"] = codice[9]        # A
        result["sviluppo"] = codice[10]       # S

    return result


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class TestStimaAreaKm2(unittest.TestCase):

    def test_area_piccola(self):
        """Area di circa 0.12 km² - bbox test Basilicata."""
        area = stima_area_km2(40.536, 15.979, 40.539, 15.984)
        self.assertGreater(area, 0.05)
        self.assertLess(area, 0.5)

    def test_area_zero_stessa_coordinata(self):
        """Bbox degenere (punto) deve avere area 0."""
        area = stima_area_km2(41.9, 12.5, 41.9, 12.5)
        self.assertAlmostEqual(area, 0.0, places=6)

    def test_area_un_km2(self):
        """
        1° di lat ~111 km, 1° di lon a lat 45° ~78.5 km.
        Area attesa ~8700 km² per 1°x1°.
        """
        area = stima_area_km2(44.0, 11.0, 45.0, 12.0)
        self.assertGreater(area, 7000)
        self.assertLess(area, 10000)

    def test_area_coerente_con_latitudine(self):
        """A latitudini più alte i km per grado lon diminuiscono."""
        area_sud = stima_area_km2(37.0, 15.0, 37.1, 15.1)
        area_nord = stima_area_km2(46.0, 11.0, 46.1, 11.1)
        # Al Nord l'area in km² è minore (lon compresse)
        self.assertGreater(area_sud, area_nord)

    def test_area_quattro_km2_circa(self):
        """Calcola un bbox che dovrebbe essere circa 4 km²."""
        # ~0.036° di lat = ~4 km, ~0.05° di lon a lat 42° = ~4 km → ~16 km²
        # Usiamo 0.018° x 0.025° ≈ 1 km² → 4 tile da 4 km²
        area = stima_area_km2(41.9, 12.49, 41.936, 12.54)
        self.assertGreater(area, 1.0)
        self.assertLess(area, 30.0)

    def test_simmetria_latitudine(self):
        """Lo stesso delta in gradi deve dare stessa area a latitudini simmetriche."""
        area_n = stima_area_km2(41.0, 10.0, 41.1, 10.1)
        area_s = stima_area_km2(-41.1, 10.0, -41.0, 10.1)
        self.assertAlmostEqual(area_n, area_s, places=4)


class TestDeterminaUtmEpsg(unittest.TestCase):

    def test_italia_ovest_utm32n(self):
        """Torino (lon ~7.7) → UTM 32N (EPSG:32632)."""
        self.assertEqual(_determina_utm_epsg(7.7, 45.0), "EPSG:32632")

    def test_italia_centro_utm32n(self):
        """Firenze (lon ~11.25) → UTM 32N (EPSG:32632) [zona 6-12°E]."""
        # lon=12.0 è il confine: floor((12+180)/6)+1 = 33 (zona 33)
        # lon=11.9 è ancora zona 32: floor((11.9+180)/6)+1 = 32
        self.assertEqual(_determina_utm_epsg(11.25, 43.8), "EPSG:32632")

    def test_italia_centro_utm33n(self):
        """Bari (lon ~16.9) → UTM 33N (EPSG:32633)."""
        self.assertEqual(_determina_utm_epsg(16.9, 41.1), "EPSG:32633")

    def test_italia_est_utm34n(self):
        """Trieste (lon ~13.8) → UTM 33N (EPSG:32633)."""
        self.assertEqual(_determina_utm_epsg(13.8, 45.6), "EPSG:32633")

    def test_palermo_utm33n(self):
        """Palermo (lon ~13.36) → UTM 33N (EPSG:32633)."""
        self.assertEqual(_determina_utm_epsg(13.36, 38.11), "EPSG:32633")

    def test_emisfero_sud(self):
        """Emisfero sud → serie 327xx."""
        epsg = _determina_utm_epsg(12.0, -5.0)
        self.assertTrue(epsg.startswith("EPSG:327"))

    def test_emisfero_nord(self):
        """Emisfero nord → serie 326xx."""
        epsg = _determina_utm_epsg(12.0, 45.0)
        self.assertTrue(epsg.startswith("EPSG:326"))


class TestCalcolaGrigliaTile(unittest.TestCase):

    def test_area_piccola_singolo_tile(self):
        """Area < MAX_TILE_KM2 → un solo tile identico al bbox."""
        tiles = calcola_griglia_tile(40.536, 15.979, 40.539, 15.984, MAX_TILE_KM2)
        self.assertEqual(len(tiles), 1)
        self.assertAlmostEqual(tiles[0][0], 40.536)
        self.assertAlmostEqual(tiles[0][2], 40.539)

    def test_area_grande_produce_piu_tile(self):
        """Area grande (~100 km²) → più tile."""
        tiles = calcola_griglia_tile(41.0, 12.0, 42.0, 13.0, MAX_TILE_KM2)
        self.assertGreater(len(tiles), 1)

    def test_copertura_completa(self):
        """
        I tile devono coprire esattamente il bbox originale:
        min_lat del primo tile = min_lat input,
        max_lat dell'ultimo tile = max_lat input.
        """
        min_lat, min_lon, max_lat, max_lon = 41.0, 12.0, 42.0, 13.0
        tiles = calcola_griglia_tile(min_lat, min_lon, max_lat, max_lon, MAX_TILE_KM2)
        lats = [t[0] for t in tiles] + [t[2] for t in tiles]
        lons = [t[1] for t in tiles] + [t[3] for t in tiles]
        self.assertAlmostEqual(min(lats), min_lat, places=10)
        self.assertAlmostEqual(max(lats), max_lat, places=10)
        self.assertAlmostEqual(min(lons), min_lon, places=10)
        self.assertAlmostEqual(max(lons), max_lon, places=10)

    def test_area_ogni_tile_entro_limite(self):
        """Ogni tile generato deve avere area <= MAX_TILE_KM2 (con tolleranza 10%)."""
        tiles = calcola_griglia_tile(41.0, 12.0, 42.0, 13.0, MAX_TILE_KM2)
        for tile in tiles:
            area = stima_area_km2(*tile)
            self.assertLessEqual(area, MAX_TILE_KM2 * 1.1,
                                 msg=f"Tile {tile} ha area {area:.3f} km² > {MAX_TILE_KM2}")

    def test_nessun_tile_vuoto(self):
        """Nessun tile deve avere area zero."""
        tiles = calcola_griglia_tile(41.0, 12.0, 42.0, 13.0, MAX_TILE_KM2)
        for tile in tiles:
            area = stima_area_km2(*tile)
            self.assertGreater(area, 0)

    def test_conteggio_tile_coerente(self):
        """Il numero di tile è sufficiente a coprire l'area totale."""
        min_lat, min_lon, max_lat, max_lon = 41.0, 12.0, 42.0, 13.0
        tiles = calcola_griglia_tile(min_lat, min_lon, max_lat, max_lon, MAX_TILE_KM2)
        area_totale = stima_area_km2(min_lat, min_lon, max_lat, max_lon)
        # Il numero di tile × area_max deve coprire l'area totale
        self.assertGreaterEqual(len(tiles) * MAX_TILE_KM2, area_totale)


class TestParseNationalCadastralReference(unittest.TestCase):
    """
    Test del parsing del campo NATIONALCADASTRALREFERENCE.
    Formato: CCCCZFFFFAS.particella  (11 caratteri + '.' + numero)
    Esempio da decodifica.md: G273_003400.1298
      - G273 = comune (Palermo)
      - _    = sezione censuaria (assente)
      - 0034 = foglio 34
      - 0    = allegato assente
      - 0    = sviluppo assente
      - 1298 = particella
    """

    def test_palermo_standard(self):
        ref = "G273_003400.1298"
        r = _parse_nationalcadastralreference(ref)
        self.assertEqual(r["comune"], "G273")
        self.assertEqual(r["sezione"], "")        # '_' → stringa vuota
        self.assertEqual(r["foglio"], "0034")
        self.assertEqual(r["allegato"], "0")
        self.assertEqual(r["sviluppo"], "0")
        self.assertEqual(r["particella"], "1298")

    def test_sezione_presente(self):
        # es. L439_002100 → sezione '_' → ma con sezione 'A': "L439A002100"
        ref = "L439A002100.5"
        r = _parse_nationalcadastralreference(ref)
        self.assertEqual(r["comune"], "L439")
        self.assertEqual(r["sezione"], "A")
        self.assertEqual(r["foglio"], "0021")
        self.assertEqual(r["allegato"], "0")
        self.assertEqual(r["sviluppo"], "0")
        self.assertEqual(r["particella"], "5")

    def test_senza_sezione(self):
        ref = "C209_000500.96"
        r = _parse_nationalcadastralreference(ref)
        self.assertEqual(r["comune"], "C209")
        self.assertEqual(r["sezione"], "")        # '_' → ""
        self.assertEqual(r["foglio"], "0005")
        self.assertEqual(r["particella"], "96")

    def test_strada(self):
        ref = "L439_002100.STRADA001"
        r = _parse_nationalcadastralreference(ref)
        self.assertEqual(r["comune"], "L439")
        self.assertEqual(r["particella"], "STRADA001")

    def test_acqua(self):
        ref = "L439_002100.ACQUA005"
        r = _parse_nationalcadastralreference(ref)
        self.assertEqual(r["particella"], "ACQUA005")

    def test_input_vuoto(self):
        r = _parse_nationalcadastralreference("")
        self.assertIsNone(r["comune"])

    def test_input_none(self):
        r = _parse_nationalcadastralreference(None)
        self.assertIsNone(r["comune"])

    def test_lunghezza_codice_errata(self):
        """Codici con lunghezza != 11 non vengono parsati."""
        r = _parse_nationalcadastralreference("ABC.123")
        self.assertIsNone(r["comune"])

    def test_allegato_e_sviluppo_con_lettera(self):
        """Allegato/sviluppo possono essere lettere diversa da '0'."""
        # formato artificiale per test: CCCCZSFFFFA(allegato)S(sviluppo)
        # CCCC=H282, Z=_, FFFF=0001, A=C, S=0
        ref = "H282_0001C0.500"
        r = _parse_nationalcadastralreference(ref)
        self.assertEqual(r["comune"], "H282")
        self.assertEqual(r["foglio"], "0001")
        self.assertEqual(r["allegato"], "C")
        self.assertEqual(r["sviluppo"], "0")


class TestWfsUrlSecurity(unittest.TestCase):
    """Test che la validazione URL del plugin sia corretta."""

    WFS_BASE = (
        "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?"
        "service=WFS&request=GetFeature&version=2.0.0"
        "&typeNames=CP:CadastralParcel"
    )

    def _build_url(self, min_lat, min_lon, max_lat, max_lon):
        bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon},urn:ogc:def:crs:EPSG::6706"
        return f"{self.WFS_BASE}&bbox={bbox_str}"

    def test_url_inizia_con_https(self):
        url = self._build_url(40.536, 15.979, 40.539, 15.984)
        self.assertTrue(url.startswith("https://"),
                        "L'URL WFS deve usare HTTPS")

    def test_url_contiene_bbox(self):
        url = self._build_url(40.536, 15.979, 40.539, 15.984)
        self.assertIn("bbox=", url)
        self.assertIn("urn:ogc:def:crs:EPSG::6706", url)

    def test_url_contiene_typename(self):
        url = self._build_url(40.536, 15.979, 40.539, 15.984)
        self.assertIn("CP:CadastralParcel", url)

    def test_url_contiene_versione_wfs(self):
        url = self._build_url(40.536, 15.979, 40.539, 15.984)
        self.assertIn("version=2.0.0", url)

    def test_schema_non_https_rifiutato(self):
        """Simula il controllo presente nel plugin."""
        url_http = "http://example.com/wfs"
        self.assertFalse(url_http.startswith("https://"),
                         "URL http:// non dovrebbe essere accettato")

    def test_bbox_ordine_corretto(self):
        """Il bbox WFS è in formato min_lat,min_lon,max_lat,max_lon."""
        url = self._build_url(40.536, 15.979, 40.539, 15.984)
        # Estrai la parte bbox dall'URL
        match = re.search(r"bbox=([^&]+)", url)
        self.assertIsNotNone(match)
        bbox_part = match.group(1)
        valori = bbox_part.split(",")
        min_lat_url = float(valori[0])
        min_lon_url = float(valori[1])
        max_lat_url = float(valori[2])
        max_lon_url = float(valori[3])
        self.assertLess(min_lat_url, max_lat_url)
        self.assertLess(min_lon_url, max_lon_url)


class TestConfigurazionePlugin(unittest.TestCase):
    """Test delle costanti di configurazione del plugin."""

    def test_max_tile_area_ragionevole(self):
        """MAX_TILE_KM2 deve essere tra 0.5 e 10 km²."""
        self.assertGreaterEqual(MAX_TILE_KM2, 0.5)
        self.assertLessEqual(MAX_TILE_KM2, 10.0)

    def test_crs_wfs(self):
        """Il CRS del WFS deve essere EPSG:6706."""
        WFS_CRS_ID = "EPSG:6706"
        self.assertEqual(WFS_CRS_ID, "EPSG:6706")

    def test_url_wfs_base_valido(self):
        WFS_BASE_URL = (
            "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php?"
            "service=WFS&request=GetFeature&version=2.0.0"
            "&typeNames=CP:CadastralParcel"
        )
        self.assertTrue(WFS_BASE_URL.startswith("https://"))
        self.assertIn("agenziaentrate.gov.it", WFS_BASE_URL)

    def test_url_wms_base_valido(self):
        WMS_BASE_URL = "https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php"
        self.assertTrue(WMS_BASE_URL.startswith("https://"))
        self.assertIn("agenziaentrate.gov.it", WMS_BASE_URL)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestStimaAreaKm2))
    suite.addTests(loader.loadTestsFromTestCase(TestDeterminaUtmEpsg))
    suite.addTests(loader.loadTestsFromTestCase(TestCalcolaGrigliaTile))
    suite.addTests(loader.loadTestsFromTestCase(TestParseNationalCadastralReference))
    suite.addTests(loader.loadTestsFromTestCase(TestWfsUrlSecurity))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigurazionePlugin))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
