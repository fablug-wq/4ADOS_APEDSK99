#!/usr/bin/env python3
"""Costruisce 4ADOSC.BIN / 4ADOSG.BIN con i comandi APEDSK99.

Uso:
    python3 tools/build.py --rom orig/4ADOSC.BIN --grom orig/4ADOSG.BIN \
        [--xdt99 /percorso/xdt99] [--out build]

Richiede xdt99 (https://github.com/endlos99/xdt99) per xas99 e xga99.
I file originali non sono inclusi nel repository: servono come input.
"""

import argparse
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# file di partenza attesi (versione FG99 di JediMatt42 / Tursi)
SHA_ROM = "b9540a4800594f11eb0d072a7ada170ce8c5e017c48b0305efed1281534cf77c"
SHA_GROM = "195ee452ff6b2a6172062b40e24c2b27d39df9592261eba40b8e8f56b2ed9a2f"

BASE = 0x6000
RAMDST = 0x2B76          # inizio modulo in RAM (ex FSTLOW)
HOOK_GROM = 0x64E0       # routine GPL di copia
BLOB_GROM = 0x6500       # modulo nella GROM
GROM_END = 0x7800        # fine del file GROM da 6K


def run(cmd, xdt99):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([xdt99, os.path.join(xdt99, "lib")])
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("errore: %s\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))


def patch(buf, addr, old, new, what):
    o = addr - BASE
    if bytes(buf[o:o + len(old)]) != bytes(old):
        sys.exit("errore: byte inattesi a >%04X (%s): %s"
                 % (addr, what, bytes(buf[o:o + len(old)]).hex()))
    buf[o:o + len(new)] = new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True, help="4ADOSC.BIN originale")
    ap.add_argument("--grom", required=True, help="4ADOSG.BIN originale")
    ap.add_argument("--xdt99", default=os.environ.get("XDT99", "xdt99"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build"))
    ap.add_argument("--force", action="store_true",
                    help="ignora il controllo SHA-256 dei file originali")
    a = ap.parse_args()

    rom = bytearray(open(a.rom, "rb").read())
    grom = bytearray(open(a.grom, "rb").read())
    for name, data, sha in (("ROM", rom, SHA_ROM), ("GROM", grom, SHA_GROM)):
        h = hashlib.sha256(data).hexdigest()
        if h != sha and not a.force:
            sys.exit("errore: %s diverso da quello atteso (%s). "
                     "Usa --force solo se sai cosa stai facendo." % (name, h))

    os.makedirs(a.out, exist_ok=True)
    xas = os.path.join(a.xdt99, "xas99.py")
    xga = os.path.join(a.xdt99, "xga99.py")
    blob_f = os.path.join(a.out, "adsk.bin")
    hook_f = os.path.join(a.out, "gromhook.bin")

    run([sys.executable, xas, "-b", "-R", os.path.join(ROOT, "src", "adsk.a99"),
         "-L", os.path.join(a.out, "adsk.lst"), "-o", blob_f], a.xdt99)
    blob = open(blob_f, "rb").read()
    size = len(blob) + (len(blob) & 1)
    blob += b"\x00" * (size - len(blob))
    fstlow = RAMDST + size

    run([sys.executable, xga, "-D", "ADSKSZ=%d" % size,
         "-L", os.path.join(a.out, "gromhook.lst"), "-o", hook_f,
         os.path.join(ROOT, "src", "gromhook.gpl")], a.xdt99)
    hook = open(hook_f, "rb").read()

    if BLOB_GROM + size > GROM_END:
        sys.exit("errore: modulo troppo grande per la GROM (%d byte)" % size)
    if HOOK_GROM + len(hook) > BLOB_GROM:
        sys.exit("errore: routine GPL troppo lunga")
    free = grom[HOOK_GROM - BASE:BLOB_GROM + size - BASE]
    if any(free):
        sys.exit("errore: l'area GROM >%04X->%04X non e' vuota"
                 % (HOOK_GROM, BLOB_GROM + size - 1))

    # --- ROM ---
    # tabella comandi esaurita: invece di "LI R3,>608F" (Illegal Command)
    # salta al modulo, che prova i comandi APEDSK99
    patch(rom, 0x653C, b"\x02\x03\x60\x8F",
          b"\x04\x60" + RAMDST.to_bytes(2, "big"), "Illegal Command")
    # banner all'avvio nell'ex ramo di errore CHARA1 (>63AE->6437)
    ban_f = os.path.join(a.out, "banner.bin")
    run([sys.executable, xas, "-b", "-R", os.path.join(ROOT, "src", "banner.a99"),
         "-L", os.path.join(a.out, "banner.lst"), "-o", ban_f], a.xdt99)
    ban = open(ban_f, "rb").read()
    if len(ban) > 0x6438 - 0x63AE or ban[2:4] != b"\x06\xA0":
        sys.exit("errore: banner.bin inatteso (%d byte)" % len(ban))
    patch(rom, 0x63AE, b"\x02\x01\x7E\xB4\x02\x02\x00\xD0", ban, "ramo CHARA1")
    patch(rom, 0x6470, b"\x04\x60\x71\xA6", b"\x04\x60\x63\xB0", "B AUTO-BAT")
    # FSTLOW iniziale (copiato a >2028): il loader E/A non sovrascrive il modulo
    patch(rom, 0x779A, b"\x2B\x76", fstlow.to_bytes(2, "big"), "FSTLOW")

    # --- GROM ---
    # BR >6098 -> BR >64E0 (routine di copia, che poi salta a >6098)
    patch(grom, 0x6016, b"\x40\x98",
          bytes([0x40 | ((HOOK_GROM >> 8) & 0x1F), HOOK_GROM & 0xFF]),
          "BR LAUNCH")
    # nome nel menu del FinalGROM99 (voce programma a >64B0, nome a >64B4)
    name = b"4ADOS APEDSK99"
    if any(grom[0x64BB - BASE:0x64D0 - BASE]):
        sys.exit("errore: area dopo il nome del menu non vuota")
    patch(grom, 0x64B4, b"\x064A DOS", bytes([len(name)]) + name, "nome menu")
    grom[HOOK_GROM - BASE:HOOK_GROM - BASE + len(hook)] = hook
    grom[BLOB_GROM - BASE:BLOB_GROM - BASE + size] = blob

    open(os.path.join(a.out, "4ADOSC.BIN"), "wb").write(rom)
    open(os.path.join(a.out, "4ADOSG.BIN"), "wb").write(grom)
    print("modulo ADSK: %d byte, RAM >%04X->%04X, nuovo FSTLOW >%04X"
          % (size, RAMDST, fstlow - 1, fstlow))
    print("scritti %s/4ADOSC.BIN e %s/4ADOSG.BIN" % (a.out, a.out))


if __name__ == "__main__":
    main()
