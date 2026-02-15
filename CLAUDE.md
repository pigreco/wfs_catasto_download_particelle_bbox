# Note di progetto per Claude

## Release QGIS Plugin
Quando si crea una release GitHub per questo plugin QGIS, NON affidarsi al "Source code (zip)" automatico di GitHub: la cartella dentro il zip avrebbe il suffisso versione (es. `wfs_catasto_download_particelle_bbox-v1.4.0`) che rompe l'import Python in QGIS.

Bisogna sempre creare manualmente un file zip con la cartella top-level che si chiama esattamente `wfs_catasto_download_particelle_bbox` (senza suffisso versione) e allegarlo come asset alla release.

Prima di creare la release, aggiornare sempre:
1. `metadata.txt`: incrementare il campo `version` (es. `1.4.3` → `1.4.4`) e aggiungere una voce nel `changelog`
2. `README.md`: aggiungere la voce nel **Changelog** e documentare eventuali nuove funzionalità
3. Includere anche `get_particella_wfs.py` nel comando `cp` dello zip

Procedura:
```bash
cd /tmp
rm -rf wfs_catasto_download_particelle_bbox wfs_catasto_download_particelle_bbox.zip
mkdir wfs_catasto_download_particelle_bbox
# Copiare solo i file necessari al plugin (no .git, __pycache__, test, README, ecc.)
cp __init__.py metadata.txt icon.svg *_p.py *_d.py wfs_catasto_gui.py get_particella_wfs.py LICENSE  wfs_catasto_download_particelle_bbox/
cp -r sketches wfs_catasto_download_particelle_bbox/
zip -r wfs_catasto_download_particelle_bbox.zip wfs_catasto_download_particelle_bbox/
gh release upload vX.Y.Z wfs_catasto_download_particelle_bbox.zip --clobber
```
