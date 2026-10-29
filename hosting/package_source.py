"""Create a clean, reviewable deployment ZIP with an explicit source allowlist."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"hosting"/"stratum-public-demo.zip"


def source_files():
    files=[ROOT/name for name in ('Dockerfile','.dockerignore','render.yaml','requirements-lock.txt',
                                 'requirements-hosting.txt','requirements-test.txt','README.md')]
    files.extend((ROOT/'twin').glob('*.py'))
    files.extend((ROOT/'web').glob('*'))
    files.extend((ROOT/'tests').glob('test_*.py'))
    files.extend([ROOT/'hosting'/'README.md',ROOT/'hosting'/'package_source.py'])
    return sorted({p.resolve() for p in files if p.is_file()})


def main():
    manifest=[]
    with zipfile.ZipFile(OUTPUT,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for file in source_files():
            relative=file.relative_to(ROOT).as_posix()
            content=file.read_bytes()
            archive.writestr(relative,content)
            manifest.append({'path':relative,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
    (ROOT/'hosting'/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'archive':str(OUTPUT),'files':len(manifest),'bytes':OUTPUT.stat().st_size}))


if __name__=='__main__':main()
