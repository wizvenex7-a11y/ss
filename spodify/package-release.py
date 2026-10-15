import hashlib
import json
import pathlib
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET

root = pathlib.Path(__file__).resolve().parent
output = root.parent / "public" / "downloads"
apk = output / "spodify.apk"
source = output / "spodify.zip"
built_apk = root / "app/build/outputs/apk/debug/app-debug.apk"
if not built_apk.is_file():
    sys.exit("Build the debug APK before packaging the release.")
output.mkdir(parents=True, exist_ok=True)
apk.write_bytes(built_apk.read_bytes())
assert apk.read_bytes() == built_apk.read_bytes(), "APK copy is not byte-identical"
reports = list((root / "app/build/test-results/testDebugUnitTest").glob("TEST-*.xml"))
assert reports, "Unit test results are required"
suites = [ET.parse(path).getroot() for path in reports]
tests = sum(int(s.get("tests", 0)) for s in suites)
assert tests > 0
assert all(int(s.get("failures", 0)) + int(s.get("errors", 0)) + int(s.get("skipped", 0)) == 0 for s in suites)
lint = ET.parse(root / "app/build/reports/lint-results-debug.xml").getroot()
assert not [issue for issue in lint.findall("issue") if issue.get("severity") in ("Error", "Fatal")], "Lint errors remain"
subprocess.run([sys.argv[1], "verify", "--verbose", str(apk)], check=True)
excluded = {".gradle", ".kotlin", "build", ".idea", ".git", "__pycache__"}
files = sorted(p for p in root.rglob("*") if p.is_file() and not any(part in excluded for part in p.relative_to(root).parts) and p.name != "local.properties" and p.suffix not in {".jks", ".keystore", ".apk", ".zip"} and not p.name.startswith(".env"))
with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, "spodify/" + path.relative_to(root).as_posix())
with zipfile.ZipFile(source) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist()) == len(files)
    for path in files:
        assert archive.read("spodify/" + path.relative_to(root).as_posix()) == path.read_bytes(), str(path)

def describe(path):
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

manifest = {
    "version": "1.0.0",
    "package": "app.spodify.player",
    "minAndroid": "8.0",
    "buildType": "debug",
    "apk": describe(apk),
    "source": {**describe(source), "files": len(files), "exactMatch": True},
    "checks": {"unitTestsPassed": tests, "lintErrors": 0, "lintWarnings": sum(issue.get("severity") == "Warning" for issue in lint.findall("issue")), "signatureVerified": True, "deviceTested": False},
    "rea": {"version": "6.5.0", "apkInspection": "blocked_missing_jadx_backend"}
}
(output / "release.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
