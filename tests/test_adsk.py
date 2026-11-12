#!/usr/bin/env python3
"""Test del modulo ADSK su un mini-emulatore TMS9900 con Arduino simulato.

Le routine di 4A DOS (parser, stampa, errori, HONK) sono sostituite da
trappole; l'Arduino simula i registri della DSR APEDSK99 v12s.

Uso: python3 tests/test_adsk.py build/adsk.bin
"""

import sys

ORG = 0x2B76
WP = 0x2A0A
CALLST, LSTDRV, CALLBF = 0x5FC6, 0x5FC7, 0x5FC8
ACOMND, ASUBCM, RDINT = 0x5FE8, 0x5FE9, 0x5FEA
BIAS = 0x60

TRAPS = {0x64BA: "MAINLP", 0x6542: "ERRMIS", 0x6520: "ERRPAR",
         0x6536: "ERRDEV", 0x6546: "ERRTXT", 0x6C1A: "QCMD"}


def biased(text):
    t = text.ljust(32)[:32]
    return bytes((ord(c) + BIAS) & 0xFF for c in t)


class Arduino:
    """Comportamento ridotto dello sketch APEDSK99_012s."""

    def __init__(self, m):
        self.m = m
        self.lines = []
        self.mapped = {1: True, 2: False, 3: False}
        self.log = []

    def status(self, code, msg=None):
        self.m.mem[CALLST] = code
        if msg is not None:
            self.m.mem[CALLBF:CALLBF + 32] = biased(msg)

    def command(self, cmd):
        m = self.m
        drv = m.mem[CALLBF]
        name = bytes(m.mem[CALLBF + 2:CALLBF + 12]).split(b"\0")[0].decode("latin-1")
        self.log.append((cmd, drv, name, m.mem[ASUBCM]))
        if cmd in (0x01, 0x02):
            self.status(0xFF)
        elif cmd in (0x03, 0x30, 0x31, 0x32):
            if cmd == 0x03 and not self.mapped.get(drv):
                self.status(0, "DOAD NOT MAPPED")
                return
            self.lines = ["LINE %d OF CMD %02X" % (i, cmd) for i in range(1, 4)]
            self.next_line()
        elif cmd == 0x10:
            if name == "NOPE":
                self.status(1, "DOAD NOT FOUND")
            else:
                self.status(0xFF)
        elif cmd in (0x11, 0x20, 0x21, 0x22, 0x23, 0x24):
            self.status(0xFF)
        elif cmd == 0x34:
            self.status(9, "APEDSK99 V12S")
        elif cmd == 0x35:
            self.status(0xFF, "2026-11-12 17:00")
        elif cmd == 0x36:
            self.status(0, "DOAD NOT MAPPED")
        elif cmd == 0x68:
            self.status(0xFF)
        m.mem[ACOMND] = 0

    def next_line(self):
        if self.lines:
            self.status(0xFF, self.lines.pop(0))
        else:
            self.status(0xF0)


class CPU:
    def __init__(self, blob, tokens, aa=True):
        self.mem = bytearray(65536)
        self.mem[ORG:ORG + len(blob)] = blob
        self.mem[0x4000] = 0xAA if aa else 0x00
        self.mem[LSTDRV] = 2
        self.tokens = list(tokens)
        self.ard = Arduino(self)
        self.out = []
        self.honks = 0
        self.st = 0
        self.pc = ORG
        self.wp = WP
        self.put_token()                       # la parola del comando

    # --- memoria
    def rw(self, a):
        a &= 0xFFFE
        return self.mem[a] << 8 | self.mem[a + 1]

    def ww(self, a, v):
        a &= 0xFFFE
        self.mem[a], self.mem[a + 1] = v >> 8 & 0xFF, v & 0xFF
        if a == RDINT:
            self.ard.next_line()

    def rb(self, a):
        return self.mem[a]

    def wb(self, a, v):
        self.mem[a] = v
        if a == ACOMND and v:
            self.ard.command(v)

    def reg(self, n):
        return self.rw(self.wp + 2 * n)

    def setreg(self, n, v):
        self.ww(self.wp + 2 * n, v & 0xFFFF)

    def fetch(self):
        w = self.rw(self.pc)
        self.pc = (self.pc + 2) & 0xFFFF
        return w

    # --- indirizzamento
    def ea(self, t, r, byte):
        if t == 0:
            return ("r", r)
        if t == 1:
            return ("m", self.reg(r))
        if t == 2:
            x = self.fetch()
            return ("m", (x + (self.reg(r) if r else 0)) & 0xFFFF)
        a = self.reg(r)
        self.setreg(r, a + (1 if byte else 2))
        return ("m", a)

    def get(self, e, byte):
        k, a = e
        if k == "r":
            v = self.reg(a)
            return v >> 8 if byte else v
        return self.rb(a) if byte else self.rw(a)

    def put(self, e, v, byte):
        k, a = e
        if k == "r":
            if byte:
                self.setreg(a, (v & 0xFF) << 8 | (self.reg(a) & 0xFF))
            else:
                self.setreg(a, v)
        elif byte:
            self.wb(a, v & 0xFF)
        else:
            self.ww(a, v & 0xFFFF)

    # --- stato: bit L>, A>, EQ
    def cmp(self, a, b, byte):
        bits = 8 if byte else 16
        sa = a - (1 << bits) if a >> (bits - 1) else a
        sb = b - (1 << bits) if b >> (bits - 1) else b
        self.st = (a > b) << 2 | (sa > sb) << 1 | (a == b)

    def lgt(self):
        return self.st >> 2 & 1

    def eq(self):
        return self.st & 1

    # --- trappole su routine di 4A DOS
    def put_token(self):
        tok = self.tokens.pop(0) if self.tokens else ""
        self.mem[0x2800] = len(tok)
        self.mem[0x2801:0x2801 + len(tok)] = tok.upper().encode()

    def trap(self):
        if self.pc == 0x655A:                  # PRINT
            r3 = self.reg(3)
            n = self.mem[r3]
            assert 1 <= n <= 40, "lunghezza riga %d" % n
            self.out.append(bytes(self.mem[r3 + 1:r3 + 1 + n]).decode())
            ret = self.reg(11)
            for r in (0, 1, 2, 3, 4, 7, 9, 11):
                self.setreg(r, 0xDEAD)
            self.pc = ret
            return None
        if self.pc == 0x6E2E:                  # HONK
            self.honks += 1
            for r in (0, 1, 2):
                self.setreg(r, 0xDEAD)
            self.pc = self.reg(11)
            return None
        if self.pc in TRAPS:
            res = TRAPS[self.pc]
            if res == "ERRTXT":
                res += ":%04X" % self.reg(3)
            return res
        if not ORG <= self.pc < ORG + 0x300:
            raise RuntimeError("PC fuori dal modulo: >%04X" % self.pc)
        return None

    def run(self, limit=20000):
        for _ in range(limit):
            r = self.trap()
            if r:
                return r
            if self.pc in (0x655A, 0x6E2E):
                continue
            self.step()
        raise RuntimeError("troppi passi")

    def step(self):
        op = self.fetch()
        if op & 0xC000 and op >> 12 not in (0x1,):          # formato I
            top = op >> 12
            byte = top & 1
            s = self.ea(op >> 4 & 3, op & 15, byte)
            sv = self.get(s, byte)
            d = self.ea(op >> 10 & 3, op >> 6 & 15, byte)
            if top in (0xC, 0xD):                          # MOV, MOVB
                self.put(d, sv, byte)
                self.cmp(sv, 0, byte)
            elif top in (0x8, 0x9):                        # C, CB
                self.cmp(sv, self.get(d, byte), byte)
            else:
                raise RuntimeError("op %04X" % op)
            return
        if op >> 8 in range(0x10, 0x1D):                    # salti
            disp = op & 0xFF
            disp = disp - 256 if disp & 0x80 else disp
            c = op >> 8
            L, A, E = self.st >> 2 & 1, self.st >> 1 & 1, self.st & 1
            take = {0x10: True, 0x11: not A and not E, 0x12: (not A) or E,
                    0x13: E, 0x14: L or E, 0x15: A, 0x16: not E,
                    0x1A: not L and not E, 0x1B: L and not E}[c]
            if take:
                self.pc = (self.pc + 2 * disp) & 0xFFFF
            return
        if op & 0xFFF0 == 0x0200:                           # LI
            v = self.fetch()
            self.setreg(op & 15, v)
            self.cmp(v, 0, False)
            return
        if op & 0xFFF0 == 0x0220:                           # AI
            v = (self.reg(op & 15) + self.fetch()) & 0xFFFF
            self.setreg(op & 15, v)
            self.cmp(v, 0, False)
            return
        if op & 0xFFF0 == 0x0280:                           # CI
            self.cmp(self.reg(op & 15), self.fetch(), False)
            return
        grp = op & 0xFFC0
        e = self.ea(op >> 4 & 3, op & 15, False)
        if grp == 0x0440:                                   # B
            self.pc = e[1] if e[0] == "m" else self.reg(e[1])
        elif grp == 0x0680:                                 # BL
            self.setreg(11, self.pc)
            self.pc = e[1]
        elif grp == 0x0400:                                 # BLWP (solo PARSE)
            assert e == ("m", 0x6298), e
            self.put_token()
        elif grp == 0x04C0:                                 # CLR
            self.put(e, 0, False)
        elif grp == 0x06C0:                                 # SWPB
            v = self.get(e, False)
            self.put(e, (v >> 8) | (v & 0xFF) << 8, False)
        elif grp in (0x0600, 0x0580):                       # DEC, INC
            v = (self.get(e, False) + (-1 if grp == 0x0600 else 1)) & 0xFFFF
            self.put(e, v, False)
            self.cmp(v, 0, False)
        else:
            raise RuntimeError("op %04X a >%04X" % (op, self.pc - 2))


def run(blob, line, **kw):
    toks = line.split()
    c = CPU(blob, toks, **kw)
    return c, c.run()


def main():
    blob = open(sys.argv[1] if len(sys.argv) > 1 else "build/adsk.bin", "rb").read()
    fails = 0

    def check(name, cond, info=""):
        nonlocal fails
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(info)))
        fails += not cond

    c, r = run(blob, "LDIR")
    check("LDIR elenca 3 righe", r == "MAINLP" and c.out == [
        "LINE 1 OF CMD 31", "LINE 2 OF CMD 31", "LINE 3 OF CMD 31"], (r, c.out))

    c, r = run(blob, "mdsk 1 games")
    check("MDSK 1 GAMES", r == "MAINLP" and c.ard.log == [(0x10, 1, "GAMES", 0)]
          and not c.out and c.mem[LSTDRV] == 1, (r, c.ard.log, c.out))

    c, r = run(blob, "MDSK 3 NOPE")
    check("MDSK errore -> messaggio + HONK", r == "MAINLP" and
          c.out == ["DOAD NOT FOUND"] and c.honks == 1, (r, c.out, c.honks))

    for line, exp in (("MDSK", "ERRMIS"), ("MDSK 1", "ERRMIS"),
                      ("MDSK 4 X", "ERRPAR"), ("MDSK 0 X", "ERRPAR"),
                      ("MDSK 12 X", "ERRPAR"), ("MDSK 1 NOMELUNGO", "ERRPAR"),
                      ("PDSK", "ERRMIS"), ("FGET", "ERRMIS")):
        c, r = run(blob, line)
        check("%s -> %s" % (line, exp), r == exp and not c.ard.log, (r, c.ard.log))

    c, r = run(blob, "MDSK 1 ABCDEFGH")
    check("nome di 8 caratteri", r == "MAINLP" and c.ard.log[0][2] == "ABCDEFGH", c.ard.log)

    c, r = run(blob, "LDSK")
    check("LDSK senza numero usa LSTDRV (DSK2 non montato)", r == "MAINLP" and
          c.ard.log[0][:2] == (3, 2) and c.out == ["DOAD NOT MAPPED"] and c.honks == 1,
          (r, c.ard.log, c.out))

    c, r = run(blob, "LDSK 1")
    check("LDSK 1", r == "MAINLP" and len(c.out) == 3, (r, c.out))

    c, r = run(blob, "PDSK 2")
    check("PDSK 2", r == "MAINLP" and c.ard.log == [(1, 2, "", 0)], c.ard.log)

    c, r = run(blob, "FGET DEMO")
    check("FGET DEMO", r == "MAINLP" and c.ard.log[0][0] == 0x21
          and c.ard.log[0][2] == "DEMO", c.ard.log)

    c, r = run(blob, "ARST")
    check("ARST: versione poi sottocomando >68", r == "MAINLP" and
          c.out == ["APEDSK99 V12S"] and c.honks == 0 and
          [x[0] for x in c.ard.log] == [0x34, 0x68] and c.ard.log[0][3] == 0x68,
          (r, c.out, c.ard.log))

    c, r = run(blob, "TIME")
    check("TIME stampa data/ora", r == "MAINLP" and c.out == ["2026-11-12 17:00"], c.out)

    c, r = run(blob, "ACFG")
    check("ACFG senza ACFG.DSK -> errore", r == "MAINLP" and c.honks == 1, (r, c.out))

    c, r = run(blob, "FOO")
    check("parola sconosciuta -> Illegal Command", r == "ERRTXT:608F", r)
    c, r = run(blob, "FOOBAR")
    check("parola di 6 lettere -> Illegal Command", r == "ERRTXT:608F", r)

    c, r = run(blob, "LDIR", aa=False)
    check("senza APEDSK99 -> Device Error", r == "ERRDEV" and not c.ard.log, r)

    for aa in (True, False):
        c, r = run(blob, "EXIT", aa=aa)
        q = [i for i in range(ORG, ORG + len(blob) - 3)
             if c.mem[i:i + 4] == b"QUIT"]
        check("EXIT (APEDSK99 %s) -> segnale QUIT + reset" % ("presente" if aa else "assente"),
              r == "QCMD" and len(q) == 1 and not c.ard.log, (r, q))

    print("\n%d errori" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
