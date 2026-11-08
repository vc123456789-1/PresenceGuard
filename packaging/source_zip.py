"""Build the source archive from an explicit list, excluding all user data."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    '.gitignore', 'README.md', 'requirements.txt', 'main.py', 'guard.py',
    'vision.py', 'platform_support.py', 'windows_session.py',
    'docs/MODELS.md', 'docs/TEST_REPORT.md',
    'packaging/build.ps1', 'packaging/installer.iss', 'packaging/app.ico',
    'packaging/requirements-build.txt', 'packaging/source_zip.py',
    'models/face_detection_yunet_2023mar.onnx',
    'models/face_recognition_sface_2021dec.onnx',
    'models/YUNET-LICENSE.txt', 'models/SFACE-LICENSE.txt',
]

def make_archive(destination):
    files = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    files += sorted((ROOT / 'tests').glob('test_*.py'))
    with ZipFile(destination, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, 'PresenceGuard-Source/' + path.relative_to(ROOT).as_posix())

if __name__ == '__main__':
    output = ROOT / 'release' / 'PresenceGuard-Source.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    make_archive(output)
    print(f'Source archive created: {output}')
