#!/usr/bin/env python3

import shutil
import os
from pathlib import Path
import re
import json

from util.DepictionGenerator import DepictionGenerator
from util.PackageLister import PackageLister
from util.DebianPackager import DebianPackager

version = "1.2.2"


def main():
    print("Silex Compiler {0}".format(version))

    root = os.path.dirname(os.path.abspath(__file__)) + "/"

    DepictionGenerator.CleanUp()

    try:
        shutil.rmtree(root + "temp/")
    except Exception:
        pass

    PackageLister.CreateFolder("docs")
    PackageLister.CreateFolder("docs/web")
    PackageLister.CreateFolder("docs/depiction")
    PackageLister.CreateFolder("docs/depiction/web")
    PackageLister.CreateFolder("docs/depiction/native")
    PackageLister.CreateFolder("docs/depiction/native/help")
    PackageLister.CreateFolder("docs/pkg")
    PackageLister.CreateFolder("docs/assets")
    PackageLister.CreateFolder("docs/api")

    PackageLister.NormalizeDataDirs()
    DebianPackager.CheckForSilexData()

    tweak_release = PackageLister.GetTweakRelease()
    repo_settings = PackageLister.GetRepoSettings()
    buildable_release = [tweak for tweak in tweak_release if not tweak.get('template_only')]

    for tweak in tweak_release:
        PackageLister.CreateFolder("docs/assets/" + tweak['bundle_id'])

    for package_name in PackageLister.ListDirNames():
        package_bundle_id = PackageLister.DirNameToBundleID(package_name)

        try:
            shutil.copy(root + "Packages/" + package_name + "/silex_data/icon.png",
                        root + "docs/assets/" + package_bundle_id + "/icon.png")
        except Exception:
            category = PackageLister.ResolveCategory(tweak_release, package_bundle_id)
            category = re.sub(r'\([^)]*\)', '', category).strip()
            try:
                shutil.copy(root + "Styles/Generic/Icon/" + category + ".png",
                            root + "docs/assets/" + package_bundle_id + "/icon.png")
            except Exception:
                try:
                    shutil.copy(root + "Styles/Generic/Icon/Generic.png",
                                root + "docs/assets/" + package_bundle_id + "/icon.png")
                except Exception:
                    PackageLister.ErrorReporter("Configuration Error!", "You are missing a file at " + root +
                        "Styles/Generic/Icon/Generic.png. Please place an icon here to be the repo's default.")

        try:
            shutil.copy(root + "Packages/" + package_name + "/silex_data/banner.png",
                        root + "docs/assets/" + package_bundle_id + "/banner.png")
        except Exception:
            category = PackageLister.ResolveCategory(tweak_release, package_bundle_id)
            category = re.sub(r'\([^)]*\)', '', category).strip()
            try:
                shutil.copy(root + "Styles/Generic/Banner/" + category + ".png",
                            root + "docs/assets/" + package_bundle_id + "/banner.png")
            except Exception:
                try:
                    shutil.copy(root + "Styles/Generic/Banner/Generic.png",
                                root + "docs/assets/" + package_bundle_id + "/banner.png")
                except Exception:
                    PackageLister.ErrorReporter("Configuration Error!", "You are missing a file at " + root +
                        "Styles/Generic/Banner/Generic.png. Please place a banner here to be the repo's default.")

        try:
            shutil.copy(root + "Packages/" + package_name + "/silex_data/description.md",
                        root + "docs/assets/" + package_bundle_id + "/description.md")
        except Exception:
            pass

        try:
            shutil.copytree(root + "Packages/" + package_name + "/silex_data/screenshots",
                            root + "docs/assets/" + package_bundle_id + "/screenshot")
        except Exception:
            pass

    try:
        shutil.copy(root + "Styles/icon.png", root + "docs/CydiaIcon.png")
    except Exception:
        PackageLister.ErrorReporter("Configuration Error!", "You are missing a file at " + root + "Styles/icon.png. Please add a PNG here to act as the repo's icon.")

    shutil.copy(root + "Styles/index.css", root + "docs/web/index.css")
    shutil.copy(root + "Styles/index.js", root + "docs/web/index.js")

    index_html = DepictionGenerator.RenderIndexHTML()
    PackageLister.CreateFile("docs/index.html", index_html)
    PackageLister.CreateFile("docs/404.html", index_html)

    for tweak_data in tweak_release:
        tweak_html = DepictionGenerator.RenderPackageHTML(tweak_data)
        PackageLister.CreateFile("docs/depiction/web/" + tweak_data['bundle_id'] + ".html", tweak_html)

    if "github.io" not in repo_settings['cname'].lower():
        PackageLister.CreateFile("docs/CNAME", repo_settings['cname'])

    carousel_obj = DepictionGenerator.NativeFeaturedCarousel(tweak_release)
    PackageLister.CreateFile("docs/sileo-featured.json", carousel_obj)

    for tweak_data in tweak_release:
        tweak_json = DepictionGenerator.RenderPackageNative(tweak_data)
        PackageLister.CreateFile("docs/depiction/native/" + tweak_data['bundle_id'] + ".json", tweak_json)
        help_depiction = DepictionGenerator.RenderNativeHelp(tweak_data)
        PackageLister.CreateFile("docs/depiction/native/help/" + tweak_data['bundle_id'] + ".json", help_depiction)

    release_file = DebianPackager.CompileRelease(repo_settings)
    PackageLister.CreateFile("docs/Release", release_file)

    PackageLister.CreateFolder("temp")
    for package_name in PackageLister.ListDirNames():
        bundle_id = PackageLister.DirNameToBundleID(package_name)
        package_data = next((tweak for tweak in buildable_release if tweak['bundle_id'] == bundle_id), None)
        if not package_data:
            continue

        try:
            shutil.copytree(root + "Packages/" + package_name, root + "temp/" + bundle_id, dirs_exist_ok=True)
            shutil.rmtree(root + "temp/" + bundle_id + "/silex_data")
        except Exception:
            try:
                shutil.rmtree(root + "temp/" + bundle_id + "/silex_data")
            except Exception:
                pass

        script_check = Path(root + "Packages/" + package_name + "/silex_data/scripts/")
        if script_check.is_dir():
            shutil.copytree(root + "Packages/" + package_name + "/silex_data/scripts", root + "temp/" + bundle_id + "/DEBIAN", dirs_exist_ok=True)
        else:
            PackageLister.CreateFolder("temp/" + bundle_id + "/DEBIAN")

    for tweak_data in buildable_release:
        control_file = DebianPackager.CompileControl(tweak_data, repo_settings)
        PackageLister.CreateFile("temp/" + tweak_data['bundle_id'] + "/DEBIAN/control", control_file)
        DebianPackager.CreateDEB(tweak_data['bundle_id'], tweak_data['version'], repo_settings)
        shutil.copy(root + "temp/" + tweak_data['bundle_id'] + ".deb", root + "docs/pkg/" + tweak_data['bundle_id'] + ".deb")

    DebianPackager.CompilePackages()
    DebianPackager.SignRelease()

    PackageLister.CreateFile("docs/.nojekyll", "")

    PackageLister.CreateFile("docs/api/tweak_release.json", json.dumps(tweak_release, separators=(',', ':')))
    PackageLister.CreateFile("docs/api/repo_settings.json", json.dumps(repo_settings, separators=(',', ':')))
    PackageLister.CreateFile("docs/api/about.json", json.dumps(DepictionGenerator.SilexAbout(), separators=(',', ':')))
    PackageLister.CreateFile("docs/api/version.json", DepictionGenerator.RenderVersionAPI(tweak_release))
    PackageLister.CreateFile("docs/api/packages.json", DepictionGenerator.RenderPackagesAPI(tweak_release))
    PackageLister.CreateFile("docs/api/featured.json", DepictionGenerator.RenderFeaturedAPI(tweak_release))
    PackageLister.CreateFile("docs/api/search.json", DepictionGenerator.RenderSearchAPI(tweak_release))
    PackageLister.CreateFile("docs/api/channels.json", DepictionGenerator.RenderChannelsAPI(tweak_release))

    shutil.rmtree(root + "temp/")

    try:
        if repo_settings['automatic_git'].lower() == "true":
            DebianPackager.PushToGit()
    except Exception:
        pass


if __name__ == '__main__':
    DepictionGenerator = DepictionGenerator(version)
    PackageLister = PackageLister(version)
    DebianPackager = DebianPackager(version)
    main()
