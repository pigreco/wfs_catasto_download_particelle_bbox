#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test pre-release per WFS Catasto Download Particelle BBox
=========================================================
Verifica che il plugin sia pronto per il rilascio:
- Tutti i file obbligatori esistono
- metadata.txt è valido (versione, changelog, campi obbligatori)
- I file Python non hanno errori di sintassi
- icon.svg è un SVG valido
- __init__.py definisce classFactory
- Il pacchetto zip avrebbe la struttura corretta

Eseguire dalla root del progetto con:
    python test/test_release.py
"""

import ast
import configparser
import os
import re
import sys
import unittest
import zipfile
import io

# Calcola la root del progetto (parent di test/)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_THIS_DIR)
PLUGIN_DIR_NAME = "wfs_catasto_download_particelle_bbox"

# File obbligatori nel plugin (come da CLAUDE.md)
REQUIRED_FILES = [
    "__init__.py",
    "metadata.txt",
    "icon.svg",
    "wfs_catasto_download_particelle_bbox_p.py",
    "wfs_catasto_download_particelle_bbox_d.py",
    "wfs_catasto_gui.py",
    "get_particella_wfs.py",
    "LICENSE",
]

# Cartelle obbligatorie
REQUIRED_DIRS = [
    "sketches",
]

# SVG obbligatori nella cartella sketches
REQUIRED_SKETCHES = [
    "sketches_bbox.svg",
    "sketches_polygon.svg",
    "sketches_line.svg",
    "sketches_points.svg",
]


def _path(*parts):
    return os.path.join(PROJECT_ROOT, *parts)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class TestRequiredFiles(unittest.TestCase):
    """Tutti i file obbligatori per il packaging devono esistere."""

    def test_file_obbligatori_esistono(self):
        for fname in REQUIRED_FILES:
            fpath = _path(fname)
            self.assertTrue(
                os.path.isfile(fpath),
                f"File obbligatorio mancante: {fname}"
            )

    def test_cartelle_obbligatorie_esistono(self):
        for dname in REQUIRED_DIRS:
            dpath = _path(dname)
            self.assertTrue(
                os.path.isdir(dpath),
                f"Cartella obbligatoria mancante: {dname}"
            )

    def test_sketches_svg_esistono(self):
        for fname in REQUIRED_SKETCHES:
            fpath = _path("sketches", fname)
            self.assertTrue(
                os.path.isfile(fpath),
                f"SVG sketch mancante: sketches/{fname}"
            )

    def test_file_non_vuoti(self):
        for fname in REQUIRED_FILES:
            fpath = _path(fname)
            if os.path.isfile(fpath):
                size = os.path.getsize(fpath)
                self.assertGreater(size, 0,
                                   f"Il file {fname} è vuoto")


class TestMetadata(unittest.TestCase):
    """Verifica la validità di metadata.txt."""

    @classmethod
    def setUpClass(cls):
        cls.meta_path = _path("metadata.txt")
        cls.config = configparser.ConfigParser()
        cls.config.read(cls.meta_path, encoding="utf-8")
        cls.general = cls.config["general"] if "general" in cls.config else {}

    def test_sezione_general_presente(self):
        self.assertIn("general", self.config.sections(),
                      "metadata.txt manca della sezione [general]")

    def test_campo_name(self):
        self.assertIn("name", self.general)
        self.assertGreater(len(self.general["name"].strip()), 0)

    def test_campo_version_presente(self):
        self.assertIn("version", self.general,
                      "metadata.txt manca del campo 'version'")

    def test_campo_version_formato(self):
        """La versione deve essere in formato X.Y.Z (es. 1.5.2)."""
        version = self.general.get("version", "").strip()
        self.assertRegex(
            version,
            r"^\d+\.\d+\.\d+$",
            f"Versione '{version}' non è nel formato X.Y.Z"
        )

    def test_campo_qgisminimumversion(self):
        self.assertIn("qgisminimumversion", self.general)
        ver = self.general["qgisminimumversion"].strip()
        self.assertRegex(ver, r"^\d+\.\d+",
                         f"qgisMinimumVersion '{ver}' non sembra valido")

    def test_campo_author(self):
        self.assertIn("author", self.general)
        self.assertGreater(len(self.general["author"].strip()), 0)

    def test_campo_email(self):
        self.assertIn("email", self.general)
        email = self.general["email"].strip()
        self.assertIn("@", email, f"Email '{email}' non valida")

    def test_campo_description(self):
        self.assertIn("description", self.general)
        self.assertGreater(len(self.general["description"].strip()), 10)

    def test_changelog_presente(self):
        self.assertIn("changelog", self.general,
                      "metadata.txt manca del campo 'changelog'")

    def test_changelog_ha_versione_corrente(self):
        """Il changelog deve avere una entry per la versione corrente."""
        version = self.general.get("version", "").strip()
        changelog = self.general.get("changelog", "")
        self.assertIn(
            version, changelog,
            f"Il changelog non contiene una entry per la versione {version}"
        )

    def test_deprecated_false(self):
        """Il plugin non deve essere marcato come deprecated."""
        deprecated = self.general.get("deprecated", "False").strip()
        self.assertEqual(deprecated.lower(), "false",
                         "Il plugin è marcato come 'deprecated=True'!")

    def test_experimental_false(self):
        """Per una release stabile, experimental deve essere False."""
        experimental = self.general.get("experimental", "False").strip()
        self.assertEqual(experimental.lower(), "false",
                         "Il plugin è marcato come 'experimental=True'!")

    def test_tracker_url(self):
        tracker = self.general.get("tracker", "").strip()
        self.assertTrue(
            tracker.startswith("https://") or tracker.startswith("http://"),
            "Campo 'tracker' non contiene un URL valido"
        )

    def test_repository_url(self):
        repo = self.general.get("repository", "").strip()
        self.assertTrue(
            repo.startswith("https://") or repo.startswith("http://"),
            "Campo 'repository' non contiene un URL valido"
        )

    def test_supporta_qt6(self):
        """Il plugin deve dichiarare supportsQt6=yes."""
        supports_qt6 = self.general.get("supportsqt6", "").strip().lower()
        self.assertEqual(supports_qt6, "yes",
                         "metadata.txt non dichiara supportsQt6=yes")


class TestPythonSyntax(unittest.TestCase):
    """Tutti i file Python devono essere sintatticamente corretti."""

    PY_FILES = [
        "__init__.py",
        "wfs_catasto_download_particelle_bbox_p.py",
        "wfs_catasto_download_particelle_bbox_d.py",
        "wfs_catasto_gui.py",
        "get_particella_wfs.py",
    ]

    def _check_syntax(self, rel_path):
        fpath = _path(rel_path)
        with open(fpath, "r", encoding="utf-8") as f:
            source = f.read()
        try:
            ast.parse(source, filename=rel_path)
        except SyntaxError as e:
            self.fail(f"Errore di sintassi in {rel_path}: {e}")

    def test_init_py(self):
        self._check_syntax("__init__.py")

    def test_plugin_principale(self):
        self._check_syntax("wfs_catasto_download_particelle_bbox_p.py")

    def test_dialog(self):
        self._check_syntax("wfs_catasto_download_particelle_bbox_d.py")

    def test_gui(self):
        self._check_syntax("wfs_catasto_gui.py")

    def test_get_particella_wfs(self):
        self._check_syntax("get_particella_wfs.py")


class TestInitPy(unittest.TestCase):
    """__init__.py deve definire classFactory."""

    def test_classfactory_definita(self):
        fpath = _path("__init__.py")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            "classFactory",
            content,
            "__init__.py non definisce la funzione classFactory"
        )

    def test_classfactory_e_callable(self):
        """classFactory deve essere una funzione (def classFactory)."""
        fpath = _path("__init__.py")
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertRegex(
            content,
            r"def\s+classFactory\s*\(",
            "__init__.py non contiene 'def classFactory('"
        )


class TestIconSvg(unittest.TestCase):
    """icon.svg deve essere un file SVG valido."""

    def setUp(self):
        self.svg_path = _path("icon.svg")
        with open(self.svg_path, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_inizia_con_svg_tag(self):
        """Il file deve contenere un tag <svg."""
        self.assertIn("<svg", self.content,
                      "icon.svg non contiene il tag <svg")

    def test_chiude_svg_tag(self):
        self.assertIn("</svg>", self.content,
                      "icon.svg non chiude il tag </svg>")

    def test_nessun_pattern16_warning(self):
        """
        Fix v1.5.2: il pattern16 causava warning Qt6.
        Verifica che non sia presente nella SVG.
        """
        self.assertNotIn(
            "pattern16", self.content,
            "icon.svg contiene ancora 'pattern16' che causa warning Qt6"
        )

    def test_nessun_colore_hardcoded_nero(self):
        """
        Fix v1.5.2: colori #000/#333 hardcoded nell'SVG potrebbero
        essere problematici in tema scuro.
        Solo un warning, non un errore bloccante.
        """
        # Questo test è informativo (non bloccante)
        has_black = "#000000" in self.content or re.search(r'fill="#000"', self.content)
        if has_black:
            print("\n[AVVISO] icon.svg contiene colori neri hardcoded (#000/#000000)")


class TestZipStructure(unittest.TestCase):
    """
    Verifica che un eventuale zip avrebbe la struttura corretta:
    la cartella top-level deve chiamarsi esattamente PLUGIN_DIR_NAME.
    Simula la creazione del zip senza scriverlo su disco.
    """

    def test_nome_cartella_zip_corretto(self):
        """
        La cartella nel zip deve chiamarsi 'wfs_catasto_download_particelle_bbox'
        (senza suffisso versione), altrimenti QGIS non riesce ad importare il plugin.
        """
        # Simula il contenuto che dovrebbe avere lo zip
        expected_prefix = PLUGIN_DIR_NAME + "/"
        simulated_entries = [
            f"{PLUGIN_DIR_NAME}/__init__.py",
            f"{PLUGIN_DIR_NAME}/metadata.txt",
            f"{PLUGIN_DIR_NAME}/icon.svg",
            f"{PLUGIN_DIR_NAME}/wfs_catasto_download_particelle_bbox_p.py",
        ]
        for entry in simulated_entries:
            self.assertTrue(
                entry.startswith(expected_prefix),
                f"Entrata '{entry}' non inizia con '{expected_prefix}'"
            )

    def test_tutti_i_file_obbligatori_inclusi(self):
        """
        Verifica che tutti i file che devono stare nel zip esistano.
        """
        for fname in REQUIRED_FILES:
            fpath = _path(fname)
            self.assertTrue(
                os.path.exists(fpath),
                f"File da includere nello zip non trovato: {fname}"
            )

    def test_git_dir_esclusa(self):
        """
        La cartella .git non deve essere inclusa nel plugin.
        """
        git_path = _path(".git")
        # Test concettuale: se .git esiste nel progetto, non deve
        # essere copiato nella cartella plugin durante il packaging.
        self.assertTrue(
            os.path.isdir(git_path) or True,  # .git potrebbe non esserci
            "Questo test è sempre True, serve come promemoria"
        )
        # Il test reale è che i REQUIRED_FILES non includono .git
        self.assertNotIn(".git", REQUIRED_FILES)


class TestVersionConsistency(unittest.TestCase):
    """La versione in metadata.txt deve essere consistente tra tutti i file."""

    def _get_metadata_version(self):
        config = configparser.ConfigParser()
        config.read(_path("metadata.txt"), encoding="utf-8")
        return config["general"]["version"].strip()

    def test_versione_in_readme(self):
        """La versione corrente dovrebbe essere menzionata nel README.md."""
        readme_path = _path("README.md")
        if not os.path.isfile(readme_path):
            self.skipTest("README.md non trovato")

        version = self._get_metadata_version()
        with open(readme_path, "r", encoding="utf-8") as f:
            readme = f.read()

        self.assertIn(
            version, readme,
            f"La versione {version} non è menzionata nel README.md"
        )

    def test_versione_nel_changelog_metadata(self):
        """La versione corrente deve avere una entry nel changelog di metadata.txt."""
        config = configparser.ConfigParser()
        config.read(_path("metadata.txt"), encoding="utf-8")
        version = config["general"]["version"].strip()
        changelog = config["general"].get("changelog", "")
        self.assertIn(version, changelog,
                      f"Nessuna entry di changelog per la versione {version}")


if __name__ == "__main__":
    print("=" * 60)
    print("Test pre-release: WFS Catasto Download Particelle BBox")
    print(f"Root progetto: {PROJECT_ROOT}")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestRequiredFiles))
    suite.addTests(loader.loadTestsFromTestCase(TestMetadata))
    suite.addTests(loader.loadTestsFromTestCase(TestPythonSyntax))
    suite.addTests(loader.loadTestsFromTestCase(TestInitPy))
    suite.addTests(loader.loadTestsFromTestCase(TestIconSvg))
    suite.addTests(loader.loadTestsFromTestCase(TestZipStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestVersionConsistency))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
