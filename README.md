# 4A DOS + APEDSK99

Aggiunge a **4A DOS** (Monty Schmidt, 1987), nella versione per FinalGROM99
preparata da Tursi e JediMatt42, i comandi di
[APEDSK99](https://github.com/jambuur/APEDSK99): si possono montare DOAD,
elencare la SD, usare l'FTP e così via direttamente dal prompt di 4A DOS e
dai file BATCH.

Le normali operazioni su disco di 4A DOS funzionano già con APEDSK99, perché
la sua DSR è quella del controller TI adattata. Questo progetto aggiunge
solo i comandi specifici di APEDSK99.

## Comandi

| Comando | Equivalente TI BASIC | Funzione |
|---|---|---|
| `PDSK n` | `CALL PDSK(n)` | protegge DSKn |
| `UDSK n` | `CALL UDSK(n)` | toglie la protezione a DSKn |
| `LDSK [n]` | `CALL LDSK(n)` | elenca i file di DSKn (senza numero: l'ultimo usato) |
| `MDSK n NOME` | `CALL MDSK(n,"NOME")` | monta il DOAD NOME su DSKn |
| `NDSK n NOME` | `CALL NDSK(n,"NOME")` | rinomina il DOAD montato su DSKn |
| `RDSK NOME` | `CALL RDSK("NOME")` | cancella un DOAD dalla SD |
| `FGET NOME` | `CALL FGET("NOME")` | scarica un DOAD dal server FTP |
| `FPUT NOME` | `CALL FPUT("NOME")` | carica un DOAD sul server FTP |
| `CDIR NOME` | `CALL CDIR("NOME")` | cambia la cartella di lavoro |
| `ADSR NOME` | `CALL ADSR("NOME")` | carica un'altra DSR e resetta |
| `SMAP` | `CALL SMAP` | mostra i DOAD montati e le cartelle |
| `LDIR` | `CALL LDIR` | elenca i DOAD nella cartella |
| `AHLP` | `CALL AHLP` | aiuto di APEDSK99 |
| `TIME` | `CALL TIME` | data e ora dal server NTP |
| `ACFG` | `CALL ACFG` | applica la configurazione di rete (ACFG.DSK su DSK1) |
| `ARST` | `CALL ARST` | mostra la versione e resetta APEDSK99 |

I nomi vanno da 1 a 8 caratteri e si scrivono senza virgolette. 4A DOS li
converte in maiuscolo. Gli elenchi lunghi rispettano `MORE`, e i messaggi
vanno anche su `OUTPUT` se è attivo, come quelli degli altri comandi.

## Come funziona

- **Niente BASIC.** Le CALL della DSR leggono i parametri dai token del TI
  BASIC, quindi non si possono chiamare da 4A DOS. Il modulo scrive invece
  direttamente nei registri dell'Arduino mappati in memoria nella RAM della
  DSR (v12s): `CALLBF` a `>5FC8`, `ACOMND` a `>5FE8`, `CALLST` a `>5FC6` e
  `RDINT` a `>5FEA`.
- **Aggancio.** Nella ROM di 4A DOS non c'è spazio libero. Quando una parola
  non è nella tabella comandi, 4A DOS salta a `>653C` ("Illegal Command").
  Lì la patch mette un `B @>2B76`. Il modulo cerca la parola fra i comandi
  APEDSK99 e, se non la trova, mostra il solito "Illegal Command".
- **Dove sta il codice.** Il modulo (538 byte) è nella GROM a `>6500`.
  All'avvio la routine GPL a `>64E0`, chiamata dal codice di avvio di
  JediMatt42 a `>6012`, lo copia in RAM a `>2B76`–`>2D8F`. Il valore
  iniziale di FSTLOW (`>2028`) passa da `>2B76` a `>2D90`, così il loader di
  `LOAD` non lo sovrascrive.

Byte modificati:

| File | Indirizzo | Prima | Dopo |
|---|---|---|---|
| 4ADOSC.BIN | `>653C` | `0203 608F` (LI R3,>608F) | `0460 2B76` (B @>2B76) |
| 4ADOSC.BIN | `>779A` | `2B76` | `2D90` (FSTLOW) |
| 4ADOSG.BIN | `>6016` | `40 98` (BR >6098) | `44 E0` (BR >64E0) |
| 4ADOSG.BIN | `>64B4` | `06` "4A DOS" | `0E` "4ADOS APEDSK99" (nome nel menu) |
| 4ADOSG.BIN | `>64E0` | vuoto | routine GPL di copia |
| 4ADOSG.BIN | `>6500` | vuoto | modulo ADSK |

## Costruzione

I file originali di 4A DOS non sono nel repository. Servono come input:

```sh
git clone https://github.com/endlos99/xdt99
python3 tools/build.py --rom 4ADOSC.BIN --grom 4ADOSG.BIN --xdt99 ./xdt99
python3 tests/test_adsk.py build/adsk.bin
```

Lo script controlla l'SHA-256 dei file originali e i byte da sostituire
prima di applicare le patch. Poi scrive `build/4ADOSC.BIN` e
`build/4ADOSG.BIN`, da copiare sulla SD del FinalGROM99 al posto dei file
originali.

`tests/test_adsk.py` esegue il modulo su un mini-emulatore TMS9900 con un
Arduino simulato. Prova parametri, errori, elenchi su più righe, ARST e
TIME.

## Limiti

- Gli indirizzi dei registri sono quelli della DSR **v12s**. Se una versione
  futura li sposta, bisogna aggiornare `src/adsk.a99`.
- `ACHR` non c'è, perché 4A DOS carica già il proprio set di caratteri.
- `TIME` mostra data e ora, ma non c'è una variabile `NTP$` da riempire.
- Il modulo viene copiato in RAM solo all'avvio della cartuccia. Se un
  programma lanciato da 4A DOS sovrascrive `>2B76`–`>2D8F`, basta riavviare
  4A DOS dal menu del FinalGROM99.
- Una parola di 4 lettere sconosciuta passa prima dal modulo, ma il
  risultato non cambia: "Illegal Command".
