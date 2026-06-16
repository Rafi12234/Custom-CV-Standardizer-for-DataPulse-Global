# convert_font.py
# Run once to convert GeneralSans-Medium.otf → GeneralSans-Medium.ttf
# Required because ReportLab TTFont does not support PostScript-outline OTF files.

from pathlib import Path

OTF_PATH = Path("assets/fonts/GeneralSans-Medium.otf")
TTF_PATH = Path("assets/fonts/GeneralSans-Medium.ttf")

if not OTF_PATH.exists():
    print(f"ERROR: OTF file not found at {OTF_PATH}")
    exit(1)

try:
    from fontTools.ttLib import TTFont as FTFont
    font = FTFont(str(OTF_PATH))
    font.flavor = None          # strip OTF wrapper → plain TTF
    font.save(str(TTF_PATH))
    print(f"Converted successfully:\n  {OTF_PATH}\n  → {TTF_PATH}")
except ImportError:
    print("ERROR: fonttools not installed. Run: pip install fonttools")
except Exception as e:
    print(f"ERROR during conversion: {e}")