import os  # For file path correction
import hashlib  # SHA256 for Release file
import re  # Regular expressions.
import json  # Used to parse various JSON files
import platform  # Detect use of WSL.
import tempfile  # Temporary files for deb patching
from subprocess import call  # Call dpkg-deb
from pydpkg import Dpkg  # Retrieve data from DEBs
from util.PackageLister import PackageLister
from util.DpkgPy import DpkgPy
import shutil  # Used to copy files


def _rebuild_ar_archive(tmpdir, members, output_path):
    """
    Write a System V ar archive for Debian .deb files.
    macOS BSD ar injects __.SYMDEF and breaks packages, so rebuild in Python.
    """
    with open(output_path, 'wb') as archive:
        archive.write(b'!<arch>\n')
        for name in members:
            path = os.path.join(tmpdir, name)
            with open(path, 'rb') as member_file:
                data = member_file.read()
            header = (
                name.encode('ascii').ljust(16)[:16]
                + str(int(os.path.getmtime(path))).encode('ascii').ljust(12)[:12]
                + b'0     '
                + b'0     '
                + b'100644  '
                + str(len(data)).encode('ascii').ljust(10)[:10]
                + b'`\n'
            )
            archive.write(header)
            archive.write(data)
            if len(data) % 2 == 1:
                archive.write(b'\n')


def PatchDebControl(deb_path, replacements):
    """
    Patch control fields in a .deb using system tools (ar, zstd, tar).
    replacements: dict of field → value, e.g. {'Package': 'xxx', 'Section': 'Roothide'}
    Returns path to patched deb (same as input path, overwritten).
    """
    import subprocess, tempfile

    tmpdir = tempfile.mkdtemp()

    try:
        # 1. Extract ar archive, then remove macOS resource fork files
        subprocess.run(['ar', 'x', deb_path], cwd=tmpdir, check=True, capture_output=True)
        for f in list(os.listdir(tmpdir)):
            if f.startswith('._'):
                os.remove(os.path.join(tmpdir, f))

        # 2. Find control.tar.* and decompress
        control_tar = None
        for f in os.listdir(tmpdir):
            if f.startswith('control.tar'):
                control_tar = f
                break

        if not control_tar:
            raise RuntimeError('No control.tar.* found in deb')

        if control_tar.endswith('.zst'):
            subprocess.run(['zstd', '-d', control_tar, '-o', 'control.tar'], cwd=tmpdir, check=True, capture_output=True)
        elif control_tar.endswith('.xz'):
            subprocess.run(['xz', '-d', '-k', control_tar], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(['mv', control_tar.replace('.xz', ''), 'control.tar'], cwd=tmpdir, check=True)
        elif control_tar.endswith('.gz'):
            subprocess.run(['gunzip', '-k', control_tar], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(['mv', control_tar.replace('.gz', ''), 'control.tar'], cwd=tmpdir, check=True)
        else:
            raise RuntimeError('Unknown control.tar compression: ' + control_tar)

        # 3. Extract control file from tar
        control_dir = os.path.join(tmpdir, 'control_dir')
        os.makedirs(control_dir)
        subprocess.run(['tar', '-xf', 'control.tar', '-C', control_dir], cwd=tmpdir, check=True, capture_output=True)

        # 4. Modify control fields
        control_file = os.path.join(control_dir, 'control')
        if not os.path.exists(control_file):
            control_file = os.path.join(control_dir, './control')
        with open(control_file, 'r') as cf:
            content = cf.read()
        for field, value in replacements.items():
            if field == 'Description':
                # Description can span multiple lines (continuation lines start with space)
                # dpkg requires empty lines to use " ." as paragraph separator
                formatted = value.replace('\n\n', '\n .\n ').replace('\n', '\n ')
                content = re.sub(r'^Description:.*(?:\n .*)*', 'Description: ' + formatted, content, flags=re.MULTILINE)
            else:
                content = re.sub(r'^' + field + r':.*$', field + ': ' + value, content, flags=re.MULTILINE)
        with open(control_file, 'w') as cf:
            cf.write(content)

        # 5. Rebuild control.tar with same compression
        os.remove(os.path.join(tmpdir, 'control.tar'))
        subprocess.run(['tar', '-cf', 'control.tar', '-C', control_dir, '.'], cwd=tmpdir, check=True, capture_output=True)

        if control_tar.endswith('.zst'):
            subprocess.run(['zstd', '-f', 'control.tar', '-o', control_tar], cwd=tmpdir, check=True, capture_output=True)
        elif control_tar.endswith('.xz'):
            subprocess.run(['xz', '-f', 'control.tar'], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(['mv', 'control.tar.xz', control_tar], cwd=tmpdir, check=True)
        elif control_tar.endswith('.gz'):
            subprocess.run(['gzip', '-f', 'control.tar'], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(['mv', 'control.tar.gz', control_tar], cwd=tmpdir, check=True)

        # Remove extracted control.tar
        try:
            os.remove(os.path.join(tmpdir, 'control.tar'))
        except:
            pass

        # 6. Rebuild ar archive in deb member order
        tmp_files = os.listdir(tmpdir)
        members = []
        if 'debian-binary' in tmp_files:
            members.append('debian-binary')
        for name in ('control.tar.gz', 'control.tar.xz', 'control.tar.zst'):
            if name in tmp_files:
                members.append(name)
                break
        for name in sorted(tmp_files):
            if name.startswith('data.tar.'):
                members.append(name)
        _rebuild_ar_archive(tmpdir, members, deb_path)

    finally:
        shutil.rmtree(tmpdir)

    return deb_path


class DebianPackager(object):
    """
    DebianPackager deals with making a functional repo and deals
    with dpkg-deb and dpkg-scanpackages.
    """

    def __init__(self, version):
        super(DebianPackager, self).__init__()
        self.version = version
        self.root = os.path.dirname(os.path.abspath(__file__)) + "/../"
        self.PackageLister = PackageLister(self.version)

    def CompileRelease(self, repo_settings):
        """
        Compiles a Release file from a repo_settings object

        Object repo_settings: An object of repo settings.
        """
        # Collect architectures from all packages
        tweak_release = self.PackageLister.GetTweakRelease()
        architectures = set()
        for tweak in tweak_release:
            try:
                if tweak['architecture']:
                    architectures.add(tweak['architecture'])
            except Exception:
                architectures.add("iphoneos-arm64")
        if not architectures:
            architectures.add("iphoneos-arm64")

        release_file = "Origin: " + repo_settings['name'] + "\n"
        release_file += "Label: " + repo_settings['name'] + "\n"
        release_file += "Suite: stable\n"
        release_file += "Version: 1.0\n"
        release_file += "Codename: ios\n"
        release_file += "Architectures: " + " ".join(sorted(architectures)) + "\n"
        release_file += "Components: main\n"
        release_file += "Description: " + repo_settings['description'].replace("\n\n", "\n .\n ").replace("\n", "\n ") + "\n"

        return release_file

    def CompileControl(self, tweak_data, repo_settings):
        """
        Compiles a CONTROL file from a tweak_data object

        Object tweak_data: A single index of a "tweak release" object.
        Object repo_settings: An object of repo settings.
        """
        subfolder = PackageLister.FullPathCname(self, repo_settings)

        try:
            if tweak_data['architecture']:
                arch = tweak_data['architecture']
        except Exception:
            arch = "iphoneos-arm64"

        control_file = "Architecture: " + arch + "\n"
        # Mandatory properties include name, bundle id, and version.
        control_file += "Package: " + tweak_data['bundle_id'] + "\n"
        control_file += "Name: " + tweak_data['name'] + "\n"
        control_file += "Version: " + tweak_data['version'] + "\n"
        # Known properties
        control_file += "Depiction: https://" + repo_settings['cname'] + subfolder + "/depiction/web/" + tweak_data[
            'bundle_id'] \
                        + ".html\n"
        control_file += "SileoDepiction: https://" + repo_settings['cname'] + subfolder + "/depiction/native/" \
                        + tweak_data['bundle_id'] + ".json\n"
        control_file += "ModernDepiction: https://" + repo_settings['cname'] + subfolder + "/depiction/native/" \
                        + tweak_data['bundle_id'] + ".json\n"
        control_file += "Icon: https://" + repo_settings['cname'] + subfolder + "/assets/" + tweak_data[
            'bundle_id'] + "/icon.png\n"

        # Optional properties
        try:
            if tweak_data['tagline']:
                # APT note: Multi-line descriptions are in the spec, but must be indicated with a leading space.
                control_file += "Description: " + tweak_data['tagline'].replace("\n\n", "\n .\n ").replace("\n", "\n ") + "\n"
        except Exception:
            control_file += "Description: An awesome package!\n"

        try:
            if tweak_data['homepage']:
                control_file += "Homepage: " + tweak_data['homepage'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['section']:
                control_file += "Section: " + tweak_data['section'] + "\n"
        except Exception:
            control_file += "Section: Unknown\n"

        try:
            if tweak_data['pre_dependencies']:
                control_file += "Pre-Depends: " + tweak_data['pre_dependencies'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['dependencies']:
                control_file += "Depends: firmware (>=" + tweak_data['works_min'] + "), " + tweak_data[
                    'dependencies'] + "\n"
        except Exception:
            control_file += "Depends: firmware (>=" + tweak_data['works_min'] + ")\n"

        try:
            if tweak_data['conflicts']:
                control_file += "Conflicts: " + tweak_data['conflicts'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['replaces']:
                control_file += "Replaces: " + tweak_data['replaces'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['provides']:
                control_file += "Provides: " + tweak_data['provides'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['build_depends']:
                control_file += "Build-Depends: " + tweak_data['build_depends'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['recommends']:
                control_file += "Recommends: " + tweak_data['recommends'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['suggests']:
                control_file += "Suggests: " + tweak_data['suggests'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['enhances']:
                control_file += "Enhances: " + tweak_data['enhances'] + "\n"
        except Exception:
            pass

        try:
            if tweak_data['breaks']:
                control_file += "Breaks: " + tweak_data['breaks'] + "\n"
        except Exception:
            pass
        try:
            if tweak_data['tags']:
                control_file += "Tags: compatible_min::ios" + tweak_data['works_min'] + ", compatible_max::ios" + tweak_data['works_max'] + ", " + tweak_data['tags'] + "\n"
        except Exception:
            control_file += "Tags: compatible_min::ios" + tweak_data['works_min'] + ", compatible_max::ios" + tweak_data['works_max'] + "\n"

        try:
            if tweak_data['developer']:
                try:
                    if tweak_data['developer']['email']:
                        control_file += "Author: " + tweak_data['developer']['name'] + " <" + tweak_data['developer'][
                            'email'] + ">\n"
                except Exception:
                    control_file += "Author: " + tweak_data['developer']['name'] + "\n"
        except Exception:
            control_file += "Author: Unknown\n"

        try:
            if tweak_data['maintainer']['email']:
                control_file += "Maintainer: " + tweak_data['maintainer']['name'] + " <" \
                                + tweak_data['maintainer']['email'] + ">\n"
        except Exception:
            try:
                control_file += "Maintainer: " + tweak_data['maintainer']['name'] + "\n"
            except Exception:
                try:
                    if tweak_data['developer']['email']:
                        control_file += "Maintainer: " + tweak_data['developer']['name'] + " <" \
                                        + tweak_data['developer']['email'] + ">\n"
                except Exception:
                    try:
                        control_file += "Maintainer: " + tweak_data['developer']['name'] + "\n"
                    except Exception:
                        control_file += "Maintainer: Unknown\n"

        try:
            if tweak_data['sponsor']:
                try:
                    if tweak_data['sponsor']['email']:
                        control_file += "Sponsor: " + tweak_data['sponsor']['name'] + " <" + tweak_data['sponsor'][
                            'email'] + ">\n"
                except Exception:
                    control_file += "Sponsor: " + tweak_data['sponsor']['name'] + "\n"
        except Exception:
            pass

        # other_control
        try:
            if tweak_data['other_control']:
                for line in tweak_data['other_control']:
                    control_file += line + "\n"
        except Exception:
            pass

        return control_file

    def CreateDEB(self, bundle_id, recorded_version, repo_settings=None):
        """
        Copy all .deb files from temp/ to docs/pkg/, preserving original filenames.
        The newest .deb is also copied as bundle_id.deb for direct download links.
        Supports multi-version: keep old debs in Packages/<name>/ and all versions
        will appear in the repo for users to choose.
        """
        import glob as glob_module
        temp_dir = self.root + "temp/" + bundle_id
        all_debs = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith(".deb")]

        if not all_debs:
            # Fallback: copy existing docs/pkg/ deb
            try:
                shutil.copy(self.root + "docs/pkg/" + bundle_id + ".deb",
                            self.root + "temp/" + bundle_id + ".deb")
            except:
                PackageLister.ErrorReporter(self, "Package Error!",
                    "No .deb found for " + bundle_id +
                    ". Place the .deb in Packages/<name>/ and re-run.")
            return

        # Sort by dpkg version descending (newest first)
        all_debs.sort(key=lambda p: Dpkg(p).version, reverse=True)

        # Read tweak_release to find matching index.json data for each deb
        try:
            tweak_release = self.PackageLister.GetTweakRelease()
        except:
            tweak_release = []

        # Patch all debs: Description from tagline, plus name/section fixes for roothide
        for deb_path in all_debs:
            internal = Dpkg(deb_path)
            replacements = {}

            # Find matching tweak_data.
            # 精确 bundle_id 必须优先：同一份包常同时有 arm64 条目与 roothide 条目，
            # 两者 bundle_id 不同但 deb 内部的 Package 名相同。若先按 internal.package
            # 匹配，就会把 arm64 条目的 Section/Name 套到 roothide 包上，
            # 且结果取决于 os.listdir 顺序 —— 这正是包间显示不一致的另一个来源。
            tweak_data = None
            for t in tweak_release:
                if t['bundle_id'] == bundle_id:
                    tweak_data = t
                    break
            if tweak_data is None:
                for t in tweak_release:
                    if t['bundle_id'] == internal.package:
                        tweak_data = t
                        break

            if tweak_data:
                # Always inject tagline as Description
                try:
                    if tweak_data['tagline']:
                        replacements['Description'] = tweak_data['tagline']
                except:
                    pass

                # ---- 核心修复 ----
                # CompileControl 会算出 Depiction / SileoDepiction / ModernDepiction /
                # Icon / Section / Author / Maintainer ... 但旧实现只把其中 4 个字段
                # 写回 deb，导致索引里的元数据取决于【源 deb 里原本带了什么】：
                # 带着这些字段的包（如弹幕助手）在 Sileo 走原生现代样式，
                # 没带的包则回退旧样式 —— 这正是各包显示效果不一致的根因。
                # 现在直接把 CompileControl 的全部字段套用上去，保证一致。
                if repo_settings:
                    try:
                        for _line in self.CompileControl(tweak_data, repo_settings).splitlines():
                            if _line.startswith(' ') or ': ' not in _line:
                                continue
                            _k, _v = _line.split(': ', 1)
                            # Architecture / Version / Package 以 deb 自身为准
                            # （Package 由下方 roothide 分支按需改写）。
                            # Name 则采用 index.json —— 它是仓库展示元数据的唯一来源，
                            # 否则会出现"同一个包在不同地方名字不同"的不一致。
                            if _k in ('Architecture', 'Version', 'Package'):
                                continue
                            replacements[_k] = _v
                    except Exception:
                        pass

                # For roothide: fix Package name, Section, display Name
                if internal.package != bundle_id:
                    replacements['Package'] = bundle_id
                    try:
                        if tweak_data['section']:
                            replacements['Section'] = tweak_data['section']
                    except Exception:
                        pass
                    if tweak_data.get('section') == 'Roothide':
                        replacements['Name'] = tweak_data['name'] + ' (Roothide)'

            if replacements:
                PatchDebControl(deb_path, replacements)

        newest = all_debs[0]
        newest_deb = Dpkg(newest)

        if len(all_debs) > 1:
            # Multi-version: copy older debs with original filenames (version + arch)
            # Newest is already copied as bundle_id.deb below
            for deb_path in all_debs[1:]:
                name = os.path.basename(deb_path)
                shutil.copy(deb_path, self.root + "docs/pkg/" + name)

        # Always copy newest as bundle_id.deb (short name for download links)
        shutil.copy(newest, self.root + "docs/pkg/" + bundle_id + ".deb")
        shutil.copy(newest, self.root + "temp/" + bundle_id + ".deb")

        # If newest version > recorded, update index.json and extract scripts
        if Dpkg.compare_versions(recorded_version, newest_deb.version) == -1:
            folder = PackageLister.BundleIdToDirName(self, bundle_id)
            if folder:
                DpkgPy.control_extract(self, newest,
                    self.root + "Packages/" + folder + "/silex_data/scripts/")
                try:
                    os.remove(self.root + "Packages/" + folder +
                              "/silex_data/scripts/control")
                except:
                    pass
                if not os.listdir(self.root + "Packages/" + folder +
                                 "/silex_data/scripts/"):
                    try:
                        os.rmdir(self.root + "Packages/" + folder +
                                "/silex_data/scripts/")
                    except:
                        pass
                package_name = folder
                with open(self.root + "Packages/" + package_name +
                          "/silex_data/index.json", "r") as f:
                    update_json = json.load(f)
                update_json['version'] = newest_deb.version
                with open(self.root + "Packages/" + package_name +
                          "/silex_data/index.json", "w") as f:
                    json.dump(update_json, f, ensure_ascii=False, indent=4)

    def CheckForSilexData(self):
        """
        Ensures that a silex_data file exists and if it doesn't, try to create one with as much data as we have.
        If there is a DEB file, it will take data from its CONTROL file. It will also auto-update the version number.
        If there is no DEB file, it will use the name of the folder, version 1.0.0, try to guess some dependencies,
            and add some placeholder data.
        :return:
        """
        for folder in os.listdir(self.root + "Packages"):
            if folder.lower() != ".ds_store":
                if not os.path.isdir(self.root + "Packages/" + folder + "/silex_data"):
                    print("It seems like the package \"" + folder + "\" is not configured. Let's set it up!")
                    is_deb = False
                    deb_path = ""
                    try:
                        for file_name in os.listdir(self.root + "Packages/" + folder):
                            if file_name.endswith(".deb"):
                                is_deb = True
                                deb_path = self.root + "Packages/" + folder + "/" + file_name
                    except Exception:
                        PackageLister.ErrorReporter(self, "Configuration Error!", "Please put your .deb file inside of "
                            "its own folder. The \"Packages\" directory should be made of multiple folders that each "
                            "contain data for a single package.\n Please fix this issue and try again.")

                    # This will be the default scaffolding for our package. Eventually I'll neuter it to only be the
                    # essential elements; it's also kinda a reference to me.
                    output = {
                        "bundle_id": "co.silex.unknown",
                        "name": "Unknown Package",
                        "version": "1.0.0",
                        "tagline": "An unknown package.",
                        "homepage": "https://shuga.co/",
                        "developer": {
                            "name": "Unknown",
                            "email": "idk@example.com"
                        },
                        "maintainer": {
                            "name": "Unknown",
                            "email": "idk@example.com"
                        },
                        "section": "Themes",

                        "works_min": "8.0",
                        "works_max": "13.0",
                        "featured": "false"
                    }

                    if is_deb:
                        print("Extracting data from DEB...")
                        deb = Dpkg(deb_path)
                        output['name'] = deb.headers['Name']
                        output['bundle_id'] = deb.headers['Package']
                        try:
                            output['tagline'] = deb.headers['Description']
                        except Exception:
                            output['tagline'] = input("What is a brief description of the package? ")
                        try:
                            output['homepage'] = deb.headers['Homepage']
                        except Exception:
                            pass
                        try:
                            remove_email_regex = re.compile('<.*?>')
                            output['developer']['name'] = remove_email_regex.sub("", deb.headers['Author'])
                        except Exception:
                            output['developer']['name'] = input("Who originally made this package? This may be"
                                                                " your name. ")
                        output['developer']['email'] = input("What is the original author's email address? ")
                        try:
                            remove_email_regex = re.compile('<.*?>')
                            output['maintainer']['name'] = remove_email_regex.sub("", deb.headers['Maintainer'])
                        except Exception:
                            output['maintainer']['name'] = input("Who maintains this package now?"
                                                                 " This is likely your name. ")
                        output['maintainer']['email'] = input("What is the maintainer's email address? ")
                        try:
                            output['sponsor']['name'] = remove_email_regex.sub("", deb.headers['Sponsor'])
                        except Exception:
                            pass
                        try:
                            output['dependencies'] = deb.headers['Depends']
                        except Exception:
                            pass
                        try:
                            output['section'] = deb.headers['Section']
                        except Exception:
                            pass
                        try:
                            output['version'] = deb.headers['Version']
                        except Exception:
                            output['version'] = "1.0.0"
                        try:
                            output['conflicts'] = deb.headers['Conflicts']
                        except Exception:
                            pass
                        try:
                            output['replaces'] = deb.headers['Replaces']
                        except Exception:
                            pass
                        try:
                            output['provides'] = deb.headers['Provides']
                        except Exception:
                            pass
                        try:
                            output['build_depends'] = deb.headers['Build-Depends']
                        except Exception:
                            pass
                        try:
                            output['recommends'] = deb.headers['Recommends']
                        except Exception:
                            pass
                        try:
                            output['suggests'] = deb.headers['Suggests']
                        except Exception:
                            pass
                        try:
                            output['enhances'] = deb.headers['Enhances']
                        except Exception:
                            pass
                        try:
                            output['breaks'] = deb.headers['Breaks']
                        except Exception:
                            pass
                        try:
                            output['tags'] = deb.headers['Tag']
                        except Exception:
                            pass
                        try:
                            output['suggests'] = deb.headers['Suggests']
                        except Exception:
                            pass
                        # These still need data.
                        output['works_min'] = input("What is the lowest iOS version the package works on? ")
                        output['works_max'] = input("What is the highest iOS version the package works on? ")
                        output['featured'] = input("Should this package be featured on your repo? (true/false) ")
                        set_tint = input("What would you like this package's tint color to be? To keep it at"
                                         " the default, leave this blank: ")
                        if set_tint != "":
                            output['tint'] = set_tint
                        print("All done! Please look over the generated \"index.json\" file and consider populating the"
                              " \"silex_data\" folder with a description, screenshots, and an icon.")
                        # Extract Control file and scripts from DEB
                        DpkgPy.control_extract(self, deb_path, self.root + "Packages/" + folder +
                                               "/silex_data/scripts/")
                        # Remove the Control; it's not needed.
                        os.remove(self.root + "Packages/" + folder + "/silex_data/scripts/Control")
                        if not os.listdir(self.root + "Packages/" + folder + "/silex_data/scripts/"):
                            os.rmdir(self.root + "Packages/" + folder + "/silex_data/scripts/")
                    else:
                        print("Estimating dependencies...")
                        # Use the filesystem to see if Zeppelin, Anemone, LockGlyph, XenHTML, and similar.
                        # If one of these are found, set it as a dependency.
                        # If multiple of these are found, use a hierarchy system, with Anemone as the highest priority,
                        # for determining the category.
                        output['dependencies'] = ""
                        output['section'] = "Themes"

                        if os.path.isdir(self.root + "Packages/" + folder + "/Library/Zeppelin"):
                            output['section'] = "Themes (Zeppelin)"
                            output['dependencies'] += "com.alexzielenski.zeppelin, "

                        if os.path.isdir(self.root + "Packages/" + folder + "/Library/Application Support/LockGlyph"):
                            output['section'] = "Themes (LockGlyph)"
                            output['dependencies'] += "com.evilgoldfish.lockglypgh, "

                        if os.path.isdir(self.root + "Packages/" + folder + "/var/mobile/Library/iWidgets"):
                            output['section'] = "Widgets"
                            output['dependencies'] += "com.matchstic.xenhtml, "

                        if os.path.isdir(self.root + "Packages/" + folder + "/Library/Wallpaper"):
                            output['section'] = "Wallpapers"

                        if os.path.isdir(self.root + "Packages/" + folder + "/Library/Themes"):
                            output['section'] = "Themes"
                            output['dependencies'] += "com.anemonetheming.anemone, "

                        if output['dependencies'] != "":
                            output['dependencies'] = output['dependencies'][:-2]

                        repo_settings = PackageLister.GetRepoSettings(self)
                        # Ask for name
                        output['name'] = input("What should we name this package? ")
                        # Automatically generate a bundle ID from the package name.
                        domain_breakup = repo_settings['cname'].split(".")[::-1]
                        only_alpha_regex = re.compile('[^a-zA-Z]')
                        machine_safe_name = only_alpha_regex.sub("", output['name']).lower()
                        output['bundle_id'] = ".".join(str(x) for x in domain_breakup) + "." + machine_safe_name
                        output['tagline'] = input("What is a brief description of the package? ")
                        output['homepage'] = "https://" + repo_settings['cname']
                        # I could potentially default this to what is in settings.json but attribution may be an issue.
                        output['developer']['name'] = input("Who made this package? This is likely your name. ")
                        output['developer']['email'] = input("What is the author's email address? ")
                        output['works_min'] = input("What is the lowest iOS version the package works on? ")
                        output['works_max'] = input("What is the highest iOS version the package works on? ")
                        output['featured'] = input("Should this package be featured on your repo? (true/false) ")
                    PackageLister.CreateFolder(self, "Packages/" + folder + "/silex_data/")
                    PackageLister.CreateFile(self, "Packages/" + folder + "/silex_data/index.json", json.dumps(output, ensure_ascii=False, indent=4))

    def CompilePackages(self):
        """
        Creates Packages, Packages.bz2, Packages.xz, and Packages.zst files.
        Sileo 2.5+ prefers Packages.zst; older clients fall back to .xz / .bz2.

        After dpkg-scanpackages runs, depiction/icon fields are injected directly
        into the plain-text Packages file based on each package's index.json, so
        the source .deb files are never modified or repackaged.
        """
        # TODO: Update DpkgPy to generate DEB files without dependencies (for improved win32 support)
        call(["dpkg-scanpackages", "-m", "."], cwd=self.root + "docs/", stdout=open(self.root + "docs/Packages", "w"))

        # --- Inject depiction fields without touching .deb files ---
        repo_settings = PackageLister.GetRepoSettings(self)
        cname = repo_settings.get("cname", "")
        subfolder = PackageLister.FullPathCname(self, repo_settings)
        base_url = "https://" + cname + subfolder

        packages_path = self.root + "docs/Packages"
        with open(packages_path, "r") as f:
            raw = f.read()

        # Parse stanzas (separated by blank lines)
        stanzas = re.split(r'\n\n+', raw.strip())
        out_stanzas = []
        for stanza in stanzas:
            if not stanza.strip():
                continue
            # Extract bundle_id from the Package: field
            m = re.search(r'^Package:\s*(\S+)', stanza, re.MULTILINE)
            if not m:
                out_stanzas.append(stanza)
                continue
            bundle_id = m.group(1)
            # Remove any existing depiction fields (idempotent re-runs)
            for field in ("Depiction", "SileoDepiction", "ModernDepiction", "Icon"):
                stanza = re.sub(r'^' + field + r':.*\n?', '', stanza, flags=re.MULTILINE)
            stanza = stanza.rstrip('\n')
            # Append depiction fields
            stanza += (
                "\nDepiction: {base}/depiction/web/{bid}.html"
                "\nSileoDepiction: {base}/depiction/native/{bid}.json"
                "\nModernDepiction: {base}/depiction/native/{bid}.json"
                "\nIcon: {base}/assets/{bid}/icon.png"
            ).format(base=base_url, bid=bundle_id)
            out_stanzas.append(stanza)

        with open(packages_path, "w") as f:
            f.write("\n\n".join(out_stanzas) + "\n")
        # --- End injection ---

        call(["bzip2", "-kf", "Packages"], cwd=self.root + "docs/")
        call(["xz", "-kf", "Packages"], cwd=self.root + "docs/")
        # Generate Packages.zst for Sileo 2.5+ (preferred format)
        import shutil as _shutil
        if _shutil.which("zstd"):
            call(["zstd", "--single-thread", "-f", "-19", "Packages", "-o", "Packages.zst"], cwd=self.root + "docs/")

    def SignRelease(self):
        """
        Signs Release to create Release.gpg. Also adds hash for Packages.bz2/.xz/.zst in Release.
        """
        import shutil as _shutil
        zst_path = self.root + "docs/Packages.zst"
        has_zst = os.path.exists(zst_path)

        with open(self.root + "docs/Packages", "rb") as packages_file,\
            open(self.root + "docs/Packages.bz2", "rb") as content_file,\
            open(self.root + "docs/Packages.xz", "rb") as content_file_xz:
            packages_raw = packages_file.read()
            packages_sha256_hash = hashlib.sha256(packages_raw).hexdigest()
            packages_size = os.path.getsize(self.root + "docs/Packages")
            bzip_raw = content_file.read()
            bzip_sha256_hash = hashlib.sha256(bzip_raw).hexdigest()
            bzip_size = os.path.getsize(self.root + "docs/Packages.bz2")
            xz_raw = content_file_xz.read()
            xz_sha256_hash = hashlib.sha256(xz_raw).hexdigest()
            xz_size = os.path.getsize(self.root + "docs/Packages.xz")
            with open(self.root + "docs/Release", "a") as text_file:
                sha_block = ("\nSHA256:\n " + str(packages_sha256_hash) + " " + str(packages_size) + " Packages"
                             "\n " + str(bzip_sha256_hash) + " " + str(bzip_size) + " Packages.bz2"
                             "\n " + str(xz_sha256_hash) + " " + str(xz_size) + " Packages.xz")
                if has_zst:
                    with open(zst_path, "rb") as zst_file:
                        zst_raw = zst_file.read()
                    zst_sha256_hash = hashlib.sha256(zst_raw).hexdigest()
                    zst_size = os.path.getsize(zst_path)
                    sha_block += "\n " + str(zst_sha256_hash) + " " + str(zst_size) + " Packages.zst"
                sha_block += "\n"
                text_file.write(sha_block)
                repo_settings = PackageLister.GetRepoSettings(self)
                try:
                    if repo_settings['enable_gpg'].lower() == "true":
                        print("Signing repository with GPG...")
                        key = "Silex MobileAPT Repository"  # Most of the time, this is acceptable.
                        call(["gpg", "-abs", "-u", key, "-o", "Release.gpg", "Release"], cwd=self.root + "docs/")
                        print("Generated Release.gpg!")
                except Exception:
                    pass

    def PushToGit(self):
        """
        Commit and push the repo to a git server (which would likely be GitHub).
        """
        # TODO: use GitPython instead of calling Git directly.
        call(["git", "add", "."], cwd=self.root)
        call(["git", "commit", "-am", "Repo contents updated via Silex"], cwd=self.root)
        call(["git", "push"], cwd=self.root)
