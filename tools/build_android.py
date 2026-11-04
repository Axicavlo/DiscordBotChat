"""Build on Windows using local portable tools; no WSL or global Java changes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / '.build-tools'
GRADLE_VERSION = '8.9'
PYTHON_VERSION = '3.12.10'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ChatBot-build/1.0'})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def archive(url, target, checksum=None, algorithm='sha256'):
    marker = target / '.complete'
    if marker.exists():
        return
    print(f'Downloading {url}', flush=True)
    data = fetch(url)
    if checksum and hashlib.new(algorithm, data).hexdigest().lower() != checksum.lower():
        raise RuntimeError(f'Checksum mismatch: {url}')
    package = TOOLS / 'download.zip'
    package.write_bytes(data)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as zipped:
        for name in zipped.namelist():
            if not (target / name).resolve().is_relative_to(target.resolve()):
                raise RuntimeError('Unsafe archive path')
        zipped.extractall(target)
    package.unlink()
    marker.touch()


def run(args, env, input_text=None):
    print('Running: ' + str(args[0]), flush=True)
    # .bat files require cmd.exe; list2cmdline quotes paths, not arbitrary shell text.
    if str(args[0]).lower().endswith('.bat'):
        args = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', subprocess.list2cmdline([str(x) for x in args])]
    subprocess.run(args, cwd=ROOT / 'android', env=env, input=input_text, text=True, check=True)


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This launcher builds on Windows.')
    TOOLS.mkdir(exist_ok=True)
    env = os.environ.copy()
    env['GRADLE_USER_HOME'] = str(TOOLS / 'gradle-cache')
    env['ANDROID_USER_HOME'] = str(TOOLS / 'android-user')

    # Official Adoptium metadata supplies the JDK URL and SHA-256.
    jdk_dir = TOOLS / 'jdk17'
    if not (jdk_dir / '.complete').exists():
        metadata = json.loads(fetch('https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows&vendor=eclipse'))
        package = metadata[0]['binary']['package']
        archive(package['link'], jdk_dir, package['checksum'])
    java = next(jdk_dir.glob('*/bin/java.exe'))
    env['JAVA_HOME'] = str(java.parents[1])
    env['PATH'] = str(java.parent) + os.pathsep + env.get('PATH', '')

    python_package = TOOLS / 'python312-build'
    # The official NuGet distribution includes venv, which Chaquopy requires.
    archive(f'https://www.nuget.org/api/v2/package/python/{PYTHON_VERSION}', python_package)
    python_dir = python_package / 'tools'
    env['CHATBOT_BUILD_PYTHON'] = str(python_dir / 'python.exe')

    gradle_dir = TOOLS / 'gradle'
    gradle_url = f'https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip'
    if not (gradle_dir / '.complete').exists():
        archive(gradle_url, gradle_dir, fetch(gradle_url + '.sha256').decode().strip())
    gradle = gradle_dir / f'gradle-{GRADLE_VERSION}' / 'bin' / 'gradle.bat'

    sdk = TOOLS / 'android-sdk'
    sdk_archive = TOOLS / 'android-cli-19'
    if not (sdk_archive / '.complete').exists():
        repository = ET.fromstring(fetch('https://dl.google.com/android/repository/repository2-1.xml'))
        entry = next(x for x in repository.findall('remotePackage') if x.attrib['path'] == 'cmdline-tools;19.0')
        windows = next(x.find('complete') for x in entry.findall('./archives/archive') if x.findtext('host-os') == 'windows')
        archive('https://dl.google.com/android/repository/' + windows.findtext('url'), sdk_archive,
                windows.findtext('checksum'), windows.find('checksum').attrib.get('type', 'sha1'))
    cli = sdk / 'cmdline-tools' / '19.0'
    if not cli.exists():
        cli.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(sdk_archive / 'cmdline-tools', cli)
    env['ANDROID_HOME'] = str(sdk)
    env['ANDROID_SDK_ROOT'] = str(sdk)
    sdkmanager = cli / 'bin' / 'sdkmanager.bat'
    # Running this build accepts the Android SDK licenses for the local toolchain.
    if not (sdk / 'licenses' / 'android-sdk-license').exists():
        run([sdkmanager, f'--sdk_root={sdk}', '--licenses'], env, 'y\n' * 100)
    if not (sdk / 'platforms' / 'android-35' / 'android.jar').exists() or not (sdk / 'build-tools' / '35.0.0').exists():
        run([sdkmanager, f'--sdk_root={sdk}', 'platforms;android-35', 'build-tools;35.0.0', 'platform-tools'], env, 'y\n' * 100)

    # Pure-Python paths are supported by these libraries. Building portable wheels
    # avoids freezing Android to the old native wheels in third-party indexes.
    wheels = TOOLS / 'python-wheels'
    wheels.mkdir(exist_ok=True)
    packages = {'aiohttp': '3.14.5', 'multidict': '7.2.1', 'yarl': '1.25.1',
                'frozenlist': '1.8.0', 'propcache': '0.5.4'}
    wheel_env = env.copy()
    for package in packages:
        wheel_env[package.upper() + '_NO_EXTENSIONS'] = '1'
    for package, version in packages.items():
        if not list(wheels.glob(f'{package}-{version}-*none-any.whl')):
            run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-binary=:all:',
                 '--wheel-dir', str(wheels), f'{package}=={version}'], wheel_env)
        if not list(wheels.glob(f'{package}-{version}-*none-any.whl')):
            raise RuntimeError(f'{package}: expected a portable Python wheel')
    run([gradle, '--no-daemon', 'assembleDebug'], env)
    sys.path.insert(0, str(ROOT))
    from chatbot_core.version import VERSION
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    apk = ROOT / 'android/app/build/outputs/apk/debug/app-debug.apk'
    shutil.copy2(apk, output / f'ChatBot-{VERSION}.apk')
    shutil.copy2(apk, output / 'ChatBot.apk')
    print(f'APK ready: {output / "ChatBot.apk"}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'APK build failed: {error}', file=sys.stderr)
        sys.exit(1)
