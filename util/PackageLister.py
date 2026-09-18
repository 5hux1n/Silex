import json  # Used to parse various JSON files
import os  # Used to navigate files so we know what tweak folders exist.
import re
from PIL import Image  # Used to get image screenshot size.


class PackageLister:
    """
    PackageLister gathers data on packages that will be in the repo.
    It also includes some helper functions related to os.
    """

    def __init__(self, version):
        super(PackageLister, self).__init__()
        self.version = version
        self.root = os.path.dirname(os.path.abspath(__file__)) + "/../"

    def CreateFile(self, path, contents):
        """
        Creates a text file (properly).

        String path: A file location to create a file at. Is relative to project root.
        String contents: The contents of the file to be created.
        """
        with open(self.root + path, "w") as text_file:
            text_file.write(contents)

    def CreateFolder(self, path):
        """
        Creates a folder.

        String path: A file location to create a folder at. Is relative to project root.
        """
        if not os.path.exists(self.root + path):
            os.makedirs(self.root + path)

    # 数据目录名：本 fork 用 silex_data，上游 Silica 用 silica_data。
    SILEX_DATA_DIR = "silex_data"
    LEGACY_DATA_DIR = "silica_data"

    def NormalizeDataDirs(self):
        """
        兼容上游 Silica 的 silica_data 目录名。

        本 fork 把数据目录改名成了 silex_data，导致从上游 Silica 迁移过来的包
        （只有 silica_data）被判定为"未配置"，进而触发交互式脚手架甚至报错。
        这里为这类包建立 silex_data -> silica_data 的软链接别名：
        非破坏性、可逆，现有全部代码无需改动。
        """
        pkgs = self.root + "Packages"
        if not os.path.isdir(pkgs):
            return
        for folder in os.listdir(pkgs):
            if folder.lower() == ".ds_store":
                continue
            base = os.path.join(pkgs, folder)
            if not os.path.isdir(base) or os.path.islink(base):
                continue
            newd = os.path.join(base, self.SILEX_DATA_DIR)
            oldd = os.path.join(base, self.LEGACY_DATA_DIR)
            if not os.path.exists(newd) and os.path.isdir(oldd):
                try:
                    os.symlink(self.LEGACY_DATA_DIR, newd)
                    print("  [兼容] " + folder + ": 已建立 "
                          + self.SILEX_DATA_DIR + " -> " + self.LEGACY_DATA_DIR)
                except Exception as e:
                    print("  [兼容] " + folder + ": 建立别名失败 " + str(e))

    def ListDirNames(self):
        """
        List the file names for package entries.
        """
        package_list = []
        for folder in os.listdir(self.root + "Packages"):
            if folder.lower() != ".ds_store":
                package_list.append(folder)
        return package_list

    def GetTweakRelease(self):
        """
        Create a "tweak release" object that combines the index.json of every package.
        Analogous to Packages.bz2.
        """
        tweak_release = []
        for tweak_entry in PackageLister.ListDirNames(self):
            with open(self.root + "Packages/" + tweak_entry + "/silex_data/index.json", "r") as content_file:
                try:
                    data = json.load(content_file)
                except Exception:
                    PackageLister.ErrorReporter(self, "Configuration Error!", "The package configuration file at \"" +
                        self.root + "Packages/" + tweak_entry + "/silex_data/index.json\" is malformatted. Please check"
                        " for any syntax errors in a JSON linter and run Silex again.")
                data['_folder_name'] = tweak_entry
                tweak_release.append(data)
        return tweak_release

    def GetScreenshots(self, tweak_data):
        """
        Get an array of screenshot names copied over to the static site.

        Object tweak_data: A single index of a "tweak release" object.
        """
        image_list = []
        try:
            for folder in os.listdir(self.root + "docs/assets/" + tweak_data['bundle_id'] + "/screenshot/"):
                if folder.lower() != ".ds_store":
                    image_list.append(folder)
        except Exception:
            pass
        return image_list

    def PackageSourcePath(self, tweak_data, relative_path):
        """
        Resolve a package-relative source path under Packages/<folder>/.
        """
        return os.path.join(self.root, "Packages", tweak_data['_folder_name'], relative_path)

    def PackageHasDescription(self, tweak_data):
        """
        Check whether a package provides a Markdown description file.
        """
        return os.path.isfile(self.PackageSourcePath(tweak_data, os.path.join("silex_data", "description.md")))

    def _strip_markdown(self, text):
        """
        Reduce Markdown to plain text for short homepage summaries.
        """
        text = re.sub(r'```.*?```', ' ', text, flags=re.DOTALL)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'(\*\*|__|\*|_|~~)', '', text)
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _first_markdown_paragraph(self, text):
        """
        Return the first non-empty paragraph from a Markdown document.
        """
        for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n')):
            plain = self._strip_markdown(block)
            if plain:
                return plain
        return self._strip_markdown(text)

    def PackageDescriptionPreview(self, tweak_data, max_length=120):
        """
        Build a short plain-text preview for repo cards and listings.
        Prefer tagline; otherwise extract the first paragraph from description.md.
        """
        tagline = tweak_data.get('tagline', '').strip()
        if tagline:
            description = tagline
        else:
            description = ''
            try:
                with open(self.PackageSourcePath(tweak_data, os.path.join("silex_data", "description.md")), "r") as content_file:
                    description = self._first_markdown_paragraph(content_file.read())
            except Exception:
                pass

        description = self._strip_markdown(description)
        if len(description) > max_length:
            return description[:max_length - 1].rstrip() + '…'
        return description

    def GetScreenshotSize(self, tweak_data):
        """
        Get the size of a screenshot.

        Object tweak_data: A single index of a "tweak release" object.
        """
        try:
            for folder in os.listdir(self.root + "docs/assets/" + tweak_data['bundle_id'] + "/screenshot/"):
                if folder.lower() != ".ds_store":
                    with Image.open(self.root + "docs/assets/" + tweak_data['bundle_id'] + "/screenshot/" + folder) as img:
                        width, height = img.size
                        if height > width:
                            width = round((400 * width) / height)
                            height = 400
                        else:
                            height = round((200 * height) / width)
                            width = 200
                        return "{" + str(width) + "," + str(height) + "}"
        except Exception:
            return False

    def DirNameToBundleID(self, package_name):
        """
        Take a human-readable directory name and find the corresponding bundle id.

        String package_name: The name of a folder in Packages/ that holds tweak information.
        """
        with open(self.root + "Packages/" + package_name + "/silex_data/index.json", "r") as content_file:
            data = json.load(content_file)
            return data['bundle_id']

    def BundleIdToDirName(self, bundle_id):
        """
        Take a bundle id and find the corresponding human-readable directory name.

        String bundle_id: The bundle ID of the tweak.
        """
        for package_name in PackageLister.ListDirNames(self):
            new_bundle = PackageLister.DirNameToBundleID(self, package_name)
            if new_bundle == bundle_id:
                return package_name
        return None

    def GetRepoSettings(self):
        with open(self.root + "Styles/settings.json", "r") as content_file:
            try:
                return json.load(content_file)
            except Exception:
                PackageLister.ErrorReporter(self, "Configuration Error!", "The Silex configuration file at \"" +
                    self.root + "Styles/settings.json\" is malformatted. Please check for any syntax errors in a JSON"
                    " linter and run Silex again.")

    def FullPathCname(self, repo_settings):
        """
        Some people may use a sub-folder like "repo" to put repo contents in.
        While this is not recommended, Silex does support this.

        Object repo_settings: An object of repo settings.
        """
        try:
            if repo_settings['subfolder'] != "":
                subfolder = "/" + repo_settings['subfolder']
            else:
                subfolder = ""
        except Exception:
            subfolder = ""
        return subfolder

    def ResolveCategory(self, tweak_release, bundle_id):
        """
        Returns the category name when given a bundle ID.

        Object tweak_release: A "tweak release" object.
        String bundle_id: The bundle ID of the tweak.
        """
        for tweak in tweak_release:
            if tweak['bundle_id'] == bundle_id:
                return tweak['section']
        return "Other"

    def ResolveVersion(self, tweak_release, bundle_id):
        """
        Returns the version when given a bundle ID.

        Object tweak_release: A "tweak release" object.
        String bundle_id: The bundle ID of the tweak.
        """
        for tweak in tweak_release:
            if tweak['bundle_id'] == bundle_id:
                return tweak['version']
        return "0.0.0"

    def ErrorReporter(self, title, message):
        print('\033[91m- {0} -\n{1}\033[0m'.format(title, message))
        quit()
