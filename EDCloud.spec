# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for EDCloud
# Note: WinFSP doit etre installe sur la machine cible (driver kernel).

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'winfspy',
        'winfspy.plumbing',
        'winfspy.plumbing.bindings',
        'winfspy.plumbing.exceptions',
        'winfspy.plumbing.file_attribute',
        'winfspy.plumbing.file_system_interface',
        'winfspy.plumbing.get_winfsp_dir',
        'winfspy.plumbing.security_descriptor',
        'winfspy.plumbing.service',
        'winfspy.plumbing.status',
        'winfspy.plumbing.win32_filetime',
        'cffi',
        '_cffi_backend',
        'winreg',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'tkinter',
        'tkinter.messagebox',
        'tkinter.simpledialog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='EDCloud',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='EDCloud.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
