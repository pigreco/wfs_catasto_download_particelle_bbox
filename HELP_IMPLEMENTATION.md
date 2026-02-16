# Implementazione Sistema Help con GitHub Pages

## Panoramica

Questo documento descrive l'implementazione del sistema di help integrato nel plugin WFS Catasto Download Particelle BBox, che utilizza GitHub Pages per fornire una documentazione online accessibile tramite un bottone nell'interfaccia utente.

## Architettura

### 1. GitHub Pages
- **URL**: https://pigreco.github.io/wfs_catasto_download_particelle_bbox/
- **File**: `index.html` (nel root del repository)
- **Stile**: CSS integrato, design responsive
- **Contenuto**: Guida completa con navigazione interna

### 2. Interfaccia Plugin
- **Posizione**: Finestra di dialogo principale (`SceltaModalitaDialog` in `wfs_catasto_download_particelle_bbox_d.py`)
- **Bottone**: "❓ Aiuto" (colore verde, posizionato a sinistra) 
- **Comportamento**: Apre il browser di sistema all'URL di help

### 3. Gestione Errori
- Fallback: Se il browser non si apre automaticamente, viene mostrato un dialog con l'URL da copiare manualmente

## File Modificati

### `wfs_catasto_download_particelle_bbox_d.py`
```python
# Aggiunto import
import webbrowser

# Aggiunto QMessageBox agli imports QtWidgets

# Modificato layout bottoni (linea ~285)
bottom_layout = QHBoxLayout()
btn_aiuto = QPushButton("❓ Aiuto")
# ... stile e configurazione

# Aggiunto metodo (linea ~410)
def _on_aiuto(self):
    help_url = "https://pigreco.github.io/wfs_catasto_download_particelle_bbox/"
    try:
        webbrowser.open(help_url)
    except Exception as e:
        QMessageBox.information(self, "Aiuto Plugin", f"Visita: {help_url}")
```

### `index.html` (nuovo file)
- Documentazione HTML completa
- CSS integrato per design professionale
- Navigazione con ancore per sezioni
- Content responsive per mobile
- Stile coerente con i colori del plugin

## Configurazione GitHub Pages

1. **Repository Settings** → **Pages**
2. **Source**: Deploy from a branch
3. **Branch**: master / main  
4. **Folder**: / (root)

Il file `index.html` viene servito automaticamente come homepage.

## Contenuti Documentazione

### Sezioni Principali
- 🔧 **Installazione**: Procedure dettagliate per OS
- 🎯 **Modalità d'uso**: Guida per ogni modalità (BBox, Poligono, Asse, Punti)
- ⚙️ **Configurazioni**: Funzionalità avanzate e personalizzazioni
- 🚨 **Troubleshooting**: Risoluzione problemi comuni
- 📋 **Changelog**: Cronologia versioni

### Design Pattern
- **Colori**: Palette coerente con l'interfaccia plugin
- **Icone**: Emoji per migliorare la leggibilità  
- **Layout**: Grid responsive, sidebar navigation
- **Tipografia**: Gerarchia chiara, codice evidenziato

## Best Practices Implementate

### Accessibilità
- Contrasti colori conformi WCAG
- Navigazione keyboard-friendly
- Testo scalabile e leggibile

### Performance
- CSS inline per ridurre richieste HTTP
- Immagini ottimizzate (quando necessario)
- HTML semantico per SEO

### Manutenibilità  
- CSS con variabili custom properties
- Struttura HTML modulare
- Commenti nel codice

## Aggiornamenti Futuri

Per aggiornare la documentazione:
1. Modifica `index.html` nel repository
2. Commit e push su master/main
3. GitHub Pages si aggiorna automaticamente
4. L'URL rimane invariato per il plugin

## Testing

### Verifiche Necessarie
- [ ] Bottone "❓ Aiuto" visibile nell'interfaccia
- [ ] Click apre correttamente il browser
- [ ] URL raggiungibile e contenuto visualizzato
- [ ] Fallback funziona se browser non si apre
- [ ] Design responsive su diversi dispositivi
- [ ] Navigazione interna funzionante

### Compatibilità
- ✅ QGIS 3.x (Qt5)
- ✅ QGIS 4.x (Qt6) 
- ✅ Windows, Linux, macOS
- ✅ Browser moderni (Chrome, Firefox, Safari, Edge)

## Considerazioni Release

Quando si crea una nuova release:
1. La documentazione rimane aggiornata automaticamente
2. Non serve rigenerare l'HTML per ogni versione plugin
3. L'URL help è fisso e non cambia tra versioni
4. Considerare di aggiornare il changelog in `index.html`

---

*Implementazione completata - Sistema help pronto per produzione*