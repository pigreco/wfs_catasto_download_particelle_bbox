## Note sulla codifica dell'output della query al WMS dell'Agenzia delle Entrate
Nell'esempio di sopra, la query dà in output il codice G273_003400.1298. Qual è il significato?

La struttura della prima parte, come riportato nella documentazione ufficiale a pagina 4 (grazie Stefano Campus per avermela suggerita), è

CCCCZFFFFAS

ovvero:

- "CCCC", rappresenta il codice nazionale del comune (es.: H282 per il comune di Rieti);
- "Z", rappresenta il codice della sezione censuaria (es. A, oppure B). Se la sezione è assente si utilizza il carattere '_'
- "FFFF", rappresenta il numero del foglio, riempito eventualmente con caratteri '0' a sinistra se il numero ha meno di 4 cifre (es. 0001 per il foglio numero 1). Se la mappa rappresenta un quadro d'unione dei bordi di più mappe allora FFFF rappresenta il numero identificativo della richiesta (modulo 10000);
- "A", rappresenta il codice allegato. Assume il valore 0 se la mappa non è un allegato. Se la mappa rappresenta un quadro d'unione dei bordi di più mappe allora "A" ha il valore 'Q';
- "S", rappresenta il codice dello sviluppo. Assume il valore 0 se la mappa non è uno sviluppo. Se la mappa rappresenta un quadro d'unione dei bordi di più mappe allora S ha il valore 'U'.
Mentre l'ultima parte, dopo il . è il numero di particella.
