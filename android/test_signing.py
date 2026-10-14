#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. D-013 signing, public identity and rejection controls.
import base64
import contextlib
import hashlib
import json
import os
import pathlib
import re
import secrets
import signal
import sys
import subprocess
import tempfile

TEST_CERT_SHA256 = '6bd277aa2b4feb1bd4eae5524defff7be22600c043aaa5e7d9e675aee6920ff0'
REPOSITORY = 'sayenah/ES-DE-Plus'
DEBUG = pathlib.Path('android/app/build/outputs/apk/debug/app-debug.apk')
RELEASE = pathlib.Path('android/app/build/outputs/apk/release/app-release-smoke.apk')
UNSIGNED_RELEASE = RELEASE.with_name('app-release-unsigned.apk')
UPDATE = pathlib.Path('android/.deps/update')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def eligible(repository, event, ref, image, rebuild='', failure='none'):
    return (repository == REPOSITORY and event in ('push', 'workflow_dispatch') and
            ref == 'refs/heads/main' and image == 'api34' and not rebuild and failure in ('', 'none'))


def stable_run():
    return eligible(os.getenv('GITHUB_REPOSITORY'), os.getenv('GITHUB_EVENT_NAME'),
                    os.getenv('GITHUB_REF'), os.getenv('IMAGE'), os.getenv('REBUILD_RUN', ''),
                    os.getenv('FAILURE', 'none'))


def tools():
    return pathlib.Path(os.environ['ANDROID_HOME']) / 'build-tools/36.0.0'


def public_version(commit='HEAD'):
    count = int(subprocess.check_output(['git', 'rev-list', '--count', '--first-parent', commit], text=True))
    sha = subprocess.check_output(['git', 'rev-parse', commit], text=True).strip()
    code = 1000 + count
    require(1001 <= code <= 2100000000 and re.fullmatch('[a-f0-9]{40}', sha), 'Invalid Android version')
    return {'version_code': code, 'version_name': 'test-' + sha[:9]}


def inspect_apk(apk, expected, debug=True):
    verified = subprocess.run([str(tools() / 'apksigner'), 'verify', '--verbose', '--print-certs', str(apk)],
                              capture_output=True, text=True)
    require(verified.returncode == 0, 'APK signature verification failed')
    fingerprints = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})$', verified.stdout, re.M)
    require('Number of signers: 1' in verified.stdout and fingerprints == [expected],
            'APK must have exactly one signer matching the expected certificate')
    badging = subprocess.check_output([str(tools() / 'aapt2'), 'dump', 'badging', str(apk)], text=True)
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.M)
    require(match and match[1] == 'org.esdeplus.frontend' and
            "application-label:'ES-DE Plus'" in badging and
            ('application-debuggable' in badging) == debug, 'Unexpected APK identity: ' + repr({
                'package_version': match.groups() if match else None,
                'label': re.findall(r"^application[^\n]*", badging, re.M), 'debug_expected': debug}))
    with pathlib.Path(apk).open('rb') as stream:
        apk_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': apk_hash,
            'signer_sha256': expected, 'version_code': int(match[2]), 'version_name': match[3],
            'certificate': verified.stdout.strip(), 'badging': badging.strip()}


def expected_cert():
    return TEST_CERT_SHA256 if stable_run() else pathlib.Path('android/evidence/test-signer.txt').read_text().strip()


def quiet(arguments, env=None):
    # Signing tools can report input paths/details on failure; never replay their
    # output or let CalledProcessError include credential-bearing input values.
    result = subprocess.run(arguments, env=env, capture_output=True)
    require(result.returncode == 0, 'Signing operation failed; publication stopped pending key-custody review')
    return result.stdout


def clean_environment():
    return {key: value for key, value in os.environ.items()
            if key not in ('ESDEPLUS_TEST_KEYSTORE_B64', 'ESDEPLUS_TEST_KEYSTORE_PASSWORD')}


def signer_arguments(key, alias):
    return ['--ks', str(key), '--ks-type', 'PKCS12', '--ks-key-alias', alias,
            '--ks-pass', 'env:ESDEPLUS_SIGN_PASSWORD', '--key-pass', 'env:ESDEPLUS_SIGN_PASSWORD']


def sign(apk, destination, key, alias, password, additional=None):
    env = clean_environment()
    env['ESDEPLUS_SIGN_PASSWORD'] = password
    args = [str(tools() / 'apksigner'), 'sign', '--v4-signing-enabled', 'false', *signer_arguments(key, alias)]
    if additional:
        # Both throwaway stores use the same alias. A v2-only control avoids
        # colliding JAR signer filenames and v3's single-signer restriction.
        args += ['--v1-signing-enabled', 'false', '--v3-signing-enabled', 'false',
                 '--next-signer', *signer_arguments(additional, alias)]
    quiet([*args, '--out', str(destination), str(apk)], env)


@contextlib.contextmanager
def credential_file(encoded, password):
    require(encoded and password, 'Missing signing credentials; no fallback key is permitted')
    # Runner temp is outside the repository, all cache roots and upload paths.
    with tempfile.TemporaryDirectory(prefix='esdeplus-sign-', dir=os.environ['RUNNER_TEMP']) as temporary:
        key = pathlib.Path(temporary) / 'test.p12'
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError('Invalid signing material; publication stopped pending Founder ruling') from None
        descriptor = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        require(key.stat().st_mode & 0o777 == 0o600, 'Keystore permissions must be 600')
        yield key
    require(not pathlib.Path(temporary).exists(), 'Signing material cleanup failed')


def reject(label, action):
    try:
        action()
    except (ValueError, FileNotFoundError):
        print('PASS: rejected ' + label)
    else:
        raise ValueError('Rejection control escaped: ' + label)


def fixture_key(directory, name, password):
    key = directory / (name + '.p12')
    env = clean_environment()
    env['ESDEPLUS_SIGN_PASSWORD'] = password
    quiet(['keytool', '-genkeypair', '-noprompt', '-storetype', 'PKCS12', '-keystore', str(key),
           '-alias', 'fixture', '-storepass:env', 'ESDEPLUS_SIGN_PASSWORD', '-keypass:env', 'ESDEPLUS_SIGN_PASSWORD',
           '-keyalg', 'RSA', '-keysize', '2048', '-validity', '2', '-dname', 'CN=ES-DE-Plus CI fixture'], env)
    key.chmod(0o600)
    certificate = quiet(['keytool', '-exportcert', '-keystore', str(key), '-alias', 'fixture',
                         '-storepass:env', 'ESDEPLUS_SIGN_PASSWORD'], env)
    return key, hashlib.sha256(certificate).hexdigest()


def terminate_signing(number, frame):
    # Unwind credential_file on runner cancellation as well as ordinary errors.
    raise SystemExit(128 + number)


def cancellation_control():
    before = set(pathlib.Path(os.environ['RUNNER_TEMP']).glob('esdeplus-sign-*'))
    script = """
import base64, secrets, signal, sys
sys.path.insert(0, 'android')
import test_signing
signal.signal(signal.SIGTERM, test_signing.terminate_signing)
with test_signing.credential_file(base64.b64encode(b'non-secret fixture').decode(), secrets.token_urlsafe(32)):
    print('READY', flush=True)
    signal.pause()
"""
    child = subprocess.Popen([sys.executable, '-c', script], env=clean_environment(),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        require(child.stdout.readline() == 'READY\n', 'Cancellation fixture failed to reach credential scope')
        child.terminate()
        require(child.wait(timeout=10) == 128 + signal.SIGTERM, 'Cancellation did not unwind signing scope')
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    require(set(pathlib.Path(os.environ['RUNNER_TEMP']).glob('esdeplus-sign-*')) == before,
            'Cancellation left signing material behind')
    print('PASS: actual SIGTERM cancellation removes credential directory; only non-secret result recorded')


def fixture_signing():
    UPDATE.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(32)
    # No stable credentials are inherited by any fixture process.
    with tempfile.TemporaryDirectory(prefix='esdeplus-controls-', dir=os.environ['RUNNER_TEMP']) as temporary:
        directory = pathlib.Path(temporary)
        key, cert = fixture_key(directory, 'one', password)
        other, other_cert = fixture_key(directory, 'two', password)
        sign(DEBUG, UPDATE / 'higher.apk', key, 'fixture', password)
        sign(UPDATE / 'lower-unsigned.apk', UPDATE / 'lower.apk', key, 'fixture', password)
        low = inspect_apk(UPDATE / 'lower.apk', cert)
        high = inspect_apk(UPDATE / 'higher.apk', cert)
        require(high['version_code'] == low['version_code'] + 1 and
                {k: high[k] for k in public_version()} == public_version(), 'Update fixture versions differ')
        (pathlib.Path('android/evidence/update-identity.txt')).write_text(json.dumps({'lower': low, 'higher': high}, indent=2))
        if not stable_run():
            sign(DEBUG, DEBUG, key, 'fixture', password)
            sign(UNSIGNED_RELEASE, RELEASE, key, 'fixture', password)
            pathlib.Path('android/evidence/test-signer.txt').write_text(cert + '\n')
        # Real signed APKs, not mocked verifier output.
        reject('ephemeral signer at the production pin', lambda: inspect_apk(UPDATE / 'higher.apk', TEST_CERT_SHA256))
        extra = directory / 'extra.apk'
        sign(DEBUG, extra, key, 'fixture', password, additional=other)
        reject('additional signer', lambda: inspect_apk(extra, cert))
        wrong = directory / 'wrong.apk'
        sign(DEBUG, wrong, other, 'fixture', password)
        reject('different single signer', lambda: inspect_apk(wrong, cert))
        tampered = directory / 'tampered.apk'
        data = bytearray((UPDATE / 'higher.apk').read_bytes())
        data[100] ^= 1
        tampered.write_bytes(data)
        reject('tampered APK', lambda: inspect_apk(tampered, cert))
        # Drive cleanup on actual signing failure, recording no tool output.
        for label, encoded, secret in [('missing credentials', '', ''), ('corrupt credentials', '!', password),
                                        ('failed signer', base64.b64encode(b'not a keystore').decode(), password)]:
            before = set(pathlib.Path(os.environ['RUNNER_TEMP']).glob('esdeplus-sign-*'))
            def failure():
                with credential_file(encoded, secret) as broken:
                    sign(DEBUG, directory / 'failed.apk', broken, 'fixture', secret)
            reject(label, failure)
            require(set(pathlib.Path(os.environ['RUNNER_TEMP']).glob('esdeplus-sign-*')) == before,
                    'Failure left signing material behind')
            print('PASS: failure cleanup, no secret recorded: ' + label)
    cancellation_control()
    print('PASS: throwaway keys removed; controls cannot upload APKs or call release APIs')


def sdk_controls():
    # Fast format/tool controls before native assembly. The real frontend APKs
    # still repeat every control after building; these payloads never upload.
    global DEBUG, RELEASE, UNSIGNED_RELEASE, UPDATE
    os.environ['IMAGE'] = 'sdk-controls'
    with tempfile.TemporaryDirectory(prefix='esdeplus-sdk-controls-', dir=os.environ['RUNNER_TEMP']) as temporary:
        root = pathlib.Path(temporary)
        DEBUG = root / 'debug.apk'
        RELEASE = root / 'release-smoke.apk'
        UNSIGNED_RELEASE = root / 'release-unsigned.apk'
        UPDATE = root / 'update'
        UPDATE.mkdir()
        version = public_version()
        values = root / 'res/values'
        values.mkdir(parents=True)
        (values / 'strings.xml').write_text('<resources><string name="app_name">ES-DE Plus</string></resources>')
        resources = root / 'resources.zip'
        subprocess.run([str(tools() / 'aapt2'), 'compile', '--dir', str(root / 'res'), '-o', str(resources)], check=True)
        for destination, code, debug in [(DEBUG, version['version_code'], True),
                                         (UNSIGNED_RELEASE, version['version_code'], False),
                                         (UPDATE / 'lower-unsigned.apk', version['version_code'] - 1, True)]:
            manifest = root / 'AndroidManifest.xml'
            manifest.write_text(f"""<manifest xmlns:android="http://schemas.android.com/apk/res/android"
package="org.esdeplus.frontend" android:versionCode="{code}" android:versionName="{version['version_name']}">
<uses-sdk android:minSdkVersion="29" android:targetSdkVersion="36"/>
<application android:label="@string/app_name" android:debuggable="{str(debug).lower()}"/>
</manifest>""")
            subprocess.run([str(tools() / 'aapt2'), 'link', '--manifest', str(manifest), '-I',
                            str(pathlib.Path(os.environ['ANDROID_HOME']) / 'platforms/android-36/android.jar'),
                            '-o', str(destination), str(resources)], check=True)
        fixture_signing()
    # No placeholder identity may survive into the real-APK gates/smoke.
    for name in ('test-signer.txt', 'update-identity.txt'):
        pathlib.Path('android/evidence', name).unlink(missing_ok=True)
    print('PASS: SDK-only signing fixtures removed; real frontend controls remain required after assembly')


def stable_signing():
    require(stable_run(), 'Stable signing is forbidden on this run/leg')
    encoded = os.environ.pop('ESDEPLUS_TEST_KEYSTORE_B64', '')
    password = os.environ.pop('ESDEPLUS_TEST_KEYSTORE_PASSWORD', '')
    alias = os.environ.get('ESDEPLUS_TEST_KEY_ALIAS', '')
    require(alias == 'esdeplus-test' and os.environ.get('ESDEPLUS_TEST_CERT_SHA256') == TEST_CERT_SHA256,
            'Missing or mismatched public signing metadata; stop pending Founder ruling')
    with credential_file(encoded, password) as key:
        sign(DEBUG, DEBUG, key, alias, password)
        sign(UNSIGNED_RELEASE, RELEASE, key, alias, password)
    # Only public metadata remains when audits/runtime begin.
    for apk, debug in [(DEBUG, True), (RELEASE, False)]:
        record = inspect_apk(apk, TEST_CERT_SHA256, debug)
        require({k: record[k] for k in public_version()} == public_version(), 'Signed variant version mismatch')
    pathlib.Path('android/evidence/test-signer.txt').write_text(TEST_CERT_SHA256 + '\n')
    print('PASS: both smoke variants signed with pinned stable test certificate; keystore removed')


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, terminate_signing)
    if sys.argv[1] == 'stable':
        stable_signing()
    elif sys.argv[1] == 'sdk-controls':
        sdk_controls()
    elif sys.argv[1] == 'fixtures':
        fixture_signing()
    else:
        version = public_version()
        print(json.dumps(version))
        if os.getenv('GITHUB_ENV'):
            with open(os.environ['GITHUB_ENV'], 'a') as stream:
                stream.write('ESDE_VERSION_CODE=' + str(version['version_code']) + '\n')
