# PyInstaller spec for the all-in-one Windows exe.
#
# Build with:  pyinstaller main.spec
# Output:      dist/X-Touch PTZ Control.exe
#
# config.yaml is created next to the exe on first run (core/paths.py::app_dir()),
# not bundled -- config.example.yaml can be copied alongside the exe for reference.

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# drivers/panasonic_models/registry.py loads every camera model module
# dynamically (pkgutil.iter_modules() + importlib.import_module()), never
# via a literal `import` statement -- PyInstaller's static analysis can't
# see that, so the 17 model files must be collected explicitly or the
# registry silently ends up empty (no button features, no gain/pedestal
# range) in the frozen exe.
_panasonic_models = collect_submodules("drivers.panasonic_models")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("web/static", "web/static"),
        ("web/templates", "web/templates"),
        ("Images/Icon.ico", "Images"),
    ],
    hiddenimports=[
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.utils",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "mido.backends.rtmidi",
        *_panasonic_models,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="X-Touch PTZ Control",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="Images/Icon.ico",
)
