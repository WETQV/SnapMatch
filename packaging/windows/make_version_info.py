"""Генерирует version_info.txt для PyInstaller из строки версии (например 1.0.5.0)."""
import sys

version = sys.argv[1]
parts = [int(p) for p in version.split(".")]
parts = (parts + [0, 0, 0, 0])[:4]
tup = ", ".join(str(p) for p in parts)
text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({tup}),
    prodvers=({tup}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(u'040904B0', [
        StringStruct(u'CompanyName', u'WETQV Development'),
        StringStruct(u'FileDescription', u'SnapMatch'),
        StringStruct(u'FileVersion', u'{version}'),
        StringStruct(u'InternalName', u'SnapMatch'),
        StringStruct(u'LegalCopyright', u'2026 WETQV. All rights reserved.'),
        StringStruct(u'OriginalFilename', u'SnapMatch.exe'),
        StringStruct(u'ProductName', u'SnapMatch'),
        StringStruct(u'ProductVersion', u'{version}'),
        StringStruct(u'Comments', u'Desktop AI Assistant with Telegram Bot Integration')
      ])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
with open("version_info.txt", "w", encoding="utf-8") as fh:
    fh.write(text)
