# Rende importabili i moduli della pipeline (sbwt, bmtf, rle, pc) come fa il codice in src/,
# sia per pytest sia per gli script di questa cartella.
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
