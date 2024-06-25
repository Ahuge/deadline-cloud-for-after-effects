# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
import os
import shutil
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class HatchCustomBuildHook(BuildHookInterface):
    """
    This class implements Hatch's [custom build hook] (https://hatch.pypa.io/1.6/plugins/build-hook/custom/)
    for a copy_version_py operation that copies the _version.py file generated by the hatch-vcs build hook into
    specified destination directories. See the `[[tool.hatch.build.hooks.custom]]` section in `pyproject.toml`.
    """

    def _validate_config(self):
        if sorted(self.config) != [
            "copy_version_py",
            "jsx_version_minimum",
            "jsx_version_path",
            "path",
        ] or list(self.config["copy_version_py"]) != ["destinations"]:
            raise RuntimeError(
                "Configuration of the custom build hook must be like { 'copy_version_py': {'destinations': ['path1', ...]}}."
                + f" Received:\n{self.config}"
            )

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        self._validate_config()

        for destination in self.config["copy_version_py"]["destinations"]:
            print(f"Copying _version.py to {destination}")
            shutil.copy(
                os.path.join(self.root, "_version.py"),
                os.path.join(self.root, destination),
            )
        self._update_jsx_version()
        self._create_jsx_bundles()

    def _create_jsx_bundles(self):
        import jsxbundler
        ipc_jsx_source = os.path.join(os.path.dirname(__file__), "src", "aeipc", "ipc.jsx")
        ipc_jsx_destination = os.path.join(os.path.dirname(__file__), "src", "deadline", "ae_adaptor", "clientipc", "ipc.jsx")
        jsxbundler._bundle(src_file=ipc_jsx_source, dest_file=ipc_jsx_destination)

    def _update_jsx_version(self):
        version_requirement = self.config["jsx_version_minimum"]
        jsx_content = [
            '// THIS FILE IS AUTO-GENERATED BY "hatch_custom_hook.py".\n',
            "// Manual changes in this file will be overwritten at build time.\n",
            f"var __DEADLINE_CLOUD_MINIMUM_VERSION__ = {version_requirement};\n",
        ]
        with open(os.path.join(self.root, self.config["jsx_version_path"]), "wt") as wf:
            wf.writelines(jsx_content)

    def clean(self, versions: list[str]) -> None:
        self._validate_config()

        cleaned_count = 0
        for destination in self.config["copy_version_py"]["destinations"]:
            print(f"Cleaning _version.py from {destination}")
            clean_path = os.path.join(self.root, destination, "_version.py")
            try:
                os.remove(clean_path)
                cleaned_count += 1
            except FileNotFoundError:
                pass
        print(f"Cleaned {cleaned_count} items")
