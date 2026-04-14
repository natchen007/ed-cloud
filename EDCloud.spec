import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')
pil_datas, pil_binaries, pil_hiddenimports = collect_all('PIL')

_platform_imports = []
if sys.platform == "win32":
    _platform_imports = [
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
        'pystray._win32',
    ]
else:
    _platform_imports = [
        'fuse',
    ]
    if sys.platform == "darwin":
        _platform_imports.append('pystray._darwin')
    else:
        _platform_imports.append('pystray._appindicator')
        _platform_imports.append('pystray._xorg')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=pystray_binaries + pil_binaries,
    datas=pystray_datas + pil_datas,
    hiddenimports=_platform_imports + pystray_hiddenimports + pil_hiddenimports + [
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
