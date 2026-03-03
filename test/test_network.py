#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test di rete per WFS Catasto Download Particelle BBox
=====================================================
Verifica che i servizi WFS e WMS dell'Agenzia delle Entrate siano
raggiungibili e rispondano in modo corretto.

Richiede connessione internet. Eseguire con:
    python test/test_network.py

Per evitare sovraccarico del server WFS, questi test usano:
- GetCapabilities (nessun download dati)
- Un solo bbox minimo (~0.1 km²) per il test WFS GetFeature
- Nessuna pausa artificiosa (i tile di test sono 1 solo)
"""

import sys
import time
import unittest
import urllib.request
import urllib.error
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Costanti (identiche al plugin)
# ---------------------------------------------------------------------------
WFS_BASE_URL = (
    "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php"
)
WMS_BASE_URL = (
    "https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php"
)

# Bbox di test: area in Basilicata (da particelle_esempio.geojson)
# ~0.3° x 0.4° = ~0.1 km², ben entro il limite di 4 km²
TEST_MIN_LAT = 40.536
TEST_MIN_LON = 15.979
TEST_MAX_LAT = 40.539
TEST_MAX_LON = 15.984

TIMEOUT_SEC = 30   # timeout per ogni richiesta HTTP


def _fetch_url(url, timeout=TIMEOUT_SEC):
    """Scarica una URL e restituisce il contenuto testuale."""
    req = urllib.request.Request(url, headers={"User-Agent": "WFSCatastoTest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class TestWfsGetCapabilities(unittest.TestCase):
    """Verifica che il servizio WFS risponda a GetCapabilities."""

    @classmethod
    def setUpClass(cls):
        url = (
            f"{WFS_BASE_URL}?service=WFS&request=GetCapabilities&version=2.0.0"
        )
        try:
            cls.content = _fetch_url(url)
            cls.available = True
        except Exception as e:
            cls.content = ""
            cls.available = False
            cls.error = str(e)

    def test_servizio_raggiungibile(self):
        """Il server WFS risponde senza errori HTTP."""
        if not self.available:
            self.fail(f"WFS non raggiungibile: {self.error}")

    def test_risposta_non_vuota(self):
        """La risposta non è vuota."""
        self.skipTest("Dipende da test_servizio_raggiungibile") if not self.available else None
        self.assertGreater(len(self.content), 100)

    def test_risposta_xml_valida(self):
        """La risposta è XML ben formato."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        try:
            ET.fromstring(self.content)
        except ET.ParseError as e:
            self.fail(f"La risposta GetCapabilities non è XML valido: {e}")

    def test_contiene_wfs_capabilities(self):
        """La risposta contiene il tag WFS_Capabilities o simile."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertTrue(
            "Capabilities" in self.content or "capabilities" in self.content,
            "La risposta non contiene 'Capabilities'"
        )

    def test_contiene_cadastralparcel(self):
        """Il servizio espone il layer CP:CadastralParcel."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertIn(
            "CadastralParcel", self.content,
            "GetCapabilities non elenca il layer CadastralParcel"
        )

    def test_nessun_exception_report(self):
        """La risposta non contiene un errore ExceptionReport."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertNotIn(
            "ExceptionReport", self.content,
            "WFS ha restituito un ExceptionReport invece di Capabilities"
        )


class TestWfsGetFeature(unittest.TestCase):
    """
    Verifica che il WFS restituisca feature per un'area di test nota.
    Area: Basilicata (da particelle_esempio.geojson, ~0.1 km²).
    """

    @classmethod
    def setUpClass(cls):
        bbox_str = (
            f"{TEST_MIN_LAT},{TEST_MIN_LON},{TEST_MAX_LAT},{TEST_MAX_LON},"
            "urn:ogc:def:crs:EPSG::6706"
        )
        url = (
            f"{WFS_BASE_URL}?service=WFS&request=GetFeature&version=2.0.0"
            f"&typeNames=CP:CadastralParcel&bbox={bbox_str}"
        )
        cls.url = url
        try:
            t0 = time.time()
            cls.content = _fetch_url(url)
            cls.elapsed = time.time() - t0
            cls.available = True
        except Exception as e:
            cls.content = ""
            cls.elapsed = 0
            cls.available = False
            cls.error = str(e)

    def test_servizio_raggiungibile(self):
        if not self.available:
            self.fail(f"WFS GetFeature non raggiungibile: {self.error}")

    def test_risposta_xml_valida(self):
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        try:
            ET.fromstring(self.content)
        except ET.ParseError as e:
            self.fail(f"La risposta GetFeature non è XML valido: {e}")

    def test_nessun_exception_report(self):
        """Il server non ha restituito un errore."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertNotIn(
            "ExceptionReport", self.content,
            "WFS ha restituito un ExceptionReport"
        )

    def test_contiene_feature_collection(self):
        """La risposta contiene una FeatureCollection (o simile GML)."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        has_collection = (
            "FeatureCollection" in self.content
            or "member" in self.content
        )
        self.assertTrue(has_collection,
                        "La risposta non sembra una FeatureCollection GML")

    def test_contiene_almeno_una_feature(self):
        """L'area di test deve contenere almeno una particella."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertIn(
            "CadastralParcel", self.content,
            "Nessuna particella catastale trovata nell'area di test"
        )

    def test_contiene_nationalcadastralreference(self):
        """Il campo NATIONALCADASTRALREFERENCE è presente nelle feature."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertIn(
            "NATIONALCADASTRALREFERENCE", self.content,
            "Campo NATIONALCADASTRALREFERENCE assente nella risposta"
        )

    def test_contiene_administrativeunit(self):
        """Il campo ADMINISTRATIVEUNIT è presente nelle feature."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertIn(
            "ADMINISTRATIVEUNIT", self.content,
            "Campo ADMINISTRATIVEUNIT assente nella risposta"
        )

    def test_contiene_label(self):
        """Il campo LABEL è presente nelle feature."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertIn("LABEL", self.content,
                      "Campo LABEL assente nella risposta")

    def test_tempo_risposta_accettabile(self):
        """Il server risponde entro 30 secondi."""
        if not self.available:
            self.skipTest("WFS non raggiungibile")
        self.assertLess(
            self.elapsed, TIMEOUT_SEC,
            f"Il server ha impiegato {self.elapsed:.1f}s (limite: {TIMEOUT_SEC}s)"
        )

    def test_url_usa_https(self):
        """L'URL della richiesta usa HTTPS."""
        self.assertTrue(self.url.startswith("https://"),
                        "L'URL WFS deve usare HTTPS")


class TestWmsGetCapabilities(unittest.TestCase):
    """Verifica che il servizio WMS risponda a GetCapabilities."""

    @classmethod
    def setUpClass(cls):
        url = (
            f"{WMS_BASE_URL}?SERVICE=WMS&REQUEST=GetCapabilities"
        )
        try:
            cls.content = _fetch_url(url)
            cls.available = True
        except Exception as e:
            cls.content = ""
            cls.available = False
            cls.error = str(e)

    def test_servizio_raggiungibile(self):
        if not self.available:
            self.fail(f"WMS non raggiungibile: {self.error}")

    def test_risposta_xml_valida(self):
        if not self.available:
            self.skipTest("WMS non raggiungibile")
        try:
            ET.fromstring(self.content)
        except ET.ParseError as e:
            self.fail(f"La risposta WMS GetCapabilities non è XML valido: {e}")

    def test_contiene_wms_capabilities(self):
        if not self.available:
            self.skipTest("WMS non raggiungibile")
        self.assertIn("WMS_Capabilities", self.content,
                      "La risposta non contiene WMS_Capabilities")

    def test_contiene_layer_cadastralparcel(self):
        """Il WMS espone il layer CP.CadastralParcel."""
        if not self.available:
            self.skipTest("WMS non raggiungibile")
        self.assertIn(
            "CadastralParcel", self.content,
            "Il WMS non espone CadastralParcel"
        )

    def test_nessun_exception_report(self):
        if not self.available:
            self.skipTest("WMS non raggiungibile")
        self.assertNotIn(
            "ExceptionReport", self.content,
            "WMS ha restituito un ExceptionReport"
        )


if __name__ == "__main__":
    print("=" * 60)
    print("Test di rete: WFS e WMS Catasto Agenzia delle Entrate")
    print(f"Area di test: lat [{TEST_MIN_LAT},{TEST_MAX_LAT}]  "
          f"lon [{TEST_MIN_LON},{TEST_MAX_LON}]")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestWfsGetCapabilities))
    suite.addTests(loader.loadTestsFromTestCase(TestWfsGetFeature))
    suite.addTests(loader.loadTestsFromTestCase(TestWmsGetCapabilities))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
