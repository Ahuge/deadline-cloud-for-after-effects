# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Utility functions for the handling of fonts
"""

import ctypes
import logging
import os
import shutil
import sys
import traceback
from ctypes import wintypes

try:
    import winreg
except ImportError:
    import _winreg as winreg

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

FONTS_REG_PATH = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"

HWND_BROADCAST = 0xFFFF
SMTO_ABORTIFHUNG = 0x0002
WM_FONTCHANGE = 0x001D
GFRI_DESCRIPTION = 1
GFRI_ISTRUETYPE = 3

INSTALL_SCOPE_USER = "USER"
INSTALL_SCOPE_SYSTEM = "SYSTEM"

FONT_LOCATION_SYSTEM = os.path.join(os.environ.get("SystemRoot"), "Fonts")
FONT_LOCATION_USER = os.path.join(os.environ.get("LocalAppData"), "Microsoft", "Windows", "Fonts")

# Font extensions supported in gdi32.AddFontResourceW
# OpenType fonts without an extension can also be installed (e.g. Adobe Fonts)
FONT_EXTENSIONS = [".otf", ".ttf", ".fon", ""]

logger = logging.getLogger(__name__)

def find_fonts(session_dir):
    """
    Looks for all font files that were sent along with the job

    :param session_dir: the root folder in which to look for files

    :returns: a set with all found fonts
    """
    fonts = set()
    for subfolder in os.listdir(session_dir):
        # Only look in assetroot folders
        if not subfolder.startswith("assetroot-"):
            continue
        # Look for the tempFonts folder
        asset_dir = os.path.join(session_dir, subfolder)
        full_sub_dir = None
        for path, dirs, files in os.walk(asset_dir):
            for d in dirs:
                if "tempFonts" in d:
                    full_sub_dir = os.path.join(path, d)
                    logger.debug(f"tempFonts directory: {full_sub_dir}")
                    break

        if not full_sub_dir:
            logger.debug(f"Couldn't recursively find tempFonts in subfolder: {subfolder}")
            continue

        for file_name in os.listdir(full_sub_dir):
            full_assetpath = os.path.join(full_sub_dir, file_name)
            _, ext = os.path.splitext(full_assetpath)
            if ext.lower() in FONT_EXTENSIONS:
                logger.debug(f"Adding: {full_assetpath}")
                fonts.add(full_assetpath)
            else:
                logger.warning(f"A file that is not a supported font was found in the tempFonts folder: {full_assetpath}")
    return fonts


def get_font_name(dst_path):
    """
    Get a font's Windows system name, which is the name stored in the registry.

    :param dst_path: path of font that needs to be named

    :returns: string with the font's name
    """
    try:
        filename = os.path.basename(dst_path)
        fontname = os.path.splitext(filename)[0]

        # Try to get the font's real name
        cb = wintypes.DWORD()
        if gdi32.GetFontResourceInfoW(filename, ctypes.byref(cb), None, GFRI_DESCRIPTION):
            buf = (ctypes.c_wchar * cb.value)()
            if gdi32.GetFontResourceInfoW(filename, ctypes.byref(cb), buf, GFRI_DESCRIPTION):
                fontname = buf.value
        is_truetype = wintypes.BOOL()
        cb.value = ctypes.sizeof(is_truetype)
        gdi32.GetFontResourceInfoW(
            filename, ctypes.byref(cb), ctypes.byref(is_truetype), GFRI_ISTRUETYPE
        )
        if is_truetype:
            fontname += " (TrueType)"

    except Exception as e:
        raise

    return fontname


def install_font(src_path, scope=INSTALL_SCOPE_USER):
    """
    Install provided font to the worker machine

    :param src_path: path of font that needs to be installed

    :returns: boolean that represents if the font was installed and a string with any traceback that was created
    """
    try:
        # Determine font destination
        if scope == INSTALL_SCOPE_SYSTEM:
            dst_dir = FONT_LOCATION_SYSTEM
            registry_scope = winreg.HKEY_LOCAL_MACHINE
        else:
            # Check if the Fonts folder exists, create it if it doesn't
            if not os.path.exists(FONT_LOCATION_USER):
                logger.info(f"Creating User Fonts folder: {FONT_LOCATION_USER}")
                os.makedirs(FONT_LOCATION_USER)

            dst_dir = FONT_LOCATION_USER
            registry_scope = winreg.HKEY_CURRENT_USER
        dst_path = os.path.join(dst_dir, os.path.basename(src_path))

        # Copy the font to the Windows Fonts folder
        shutil.copy(src_path, dst_path)

        # Load the font in the current session, remove font when loading fails
        if not gdi32.AddFontResourceW(dst_path):
            os.remove(dst_path)
            raise WindowsError(f'AddFontResource failed to load "{src_path}"')

        # Notify running programs
        user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, 1000, None
        )

        # Store the fontname/filename in the registry
        filename = os.path.basename(dst_path)
        fontname = get_font_name(dst_path)

        # Creates registry if it doesn't exist, opens when it does exist
        with winreg.CreateKeyEx(registry_scope, FONTS_REG_PATH, 0, access= winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, fontname, 0, winreg.REG_SZ, filename)
    except Exception:
        return False, traceback.format_exc()
    return True, ""


def uninstall_font(src_path, scope=INSTALL_SCOPE_USER):
    """
    Uninstall provided font from the worker machine

    :param src_path: path of font that needs to be removed

    :returns: boolean that represents if the font was uninstalled and a string with any traceback that was created
    """
    try:
        # Determine where the font was installed
        if scope == INSTALL_SCOPE_SYSTEM:
            dst_path = os.path.join(FONT_LOCATION_SYSTEM, os.path.basename(src_path))
            registry_scope = winreg.HKEY_LOCAL_MACHINE
        else:
            dst_path = os.path.join(FONT_LOCATION_USER, os.path.basename(src_path))
            registry_scope = winreg.HKEY_CURRENT_USER

        # Remove the fontname/filename from the registry
        fontname = get_font_name(dst_path)

        with winreg.OpenKey(registry_scope, FONTS_REG_PATH, 0, access= winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, fontname)

        # Unload the font in the current session
        if not gdi32.RemoveFontResourceW(dst_path):
            os.remove(dst_path)
            raise WindowsError(f'RemoveFontResourceW failed to load "{src_path}"')

        if os.path.exists(dst_path):
            os.remove(dst_path)

        # Notify running programs
        user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, 1000, None
        )
    except Exception:
        return False, traceback.format_exc()
    return True, ""


def _install_fonts(session_dir):
    """
    Calls all needed functions for installing fonts

    :param session_dir: directory of the session
    """
    logger.info("Looking for fonts to install...")
    fonts = find_fonts(session_dir)

    if not fonts:
        logger.info("No custom fonts found, continuing task...")
        return
    for font in fonts:
        logger.info("Installing font: " + font)
        installed, msg = install_font(font)
        if not installed:
            raise RuntimeError(f"Error installing font: {msg}")


def _remove_fonts(session_dir):
    """
    Calls all needed functions for removing fonts

    :param session_dir: directory of the session
    """
    logger.info("Looking for fonts to uninstall...")
    fonts = find_fonts(session_dir)

    if not fonts:
        logger.info("No custom fonts found, finishing task...")
        return

    for font in fonts:
        logger.info("Uninstalling font: " + font)
        removed, msg = uninstall_font(font)
        if not removed:
            # Don't fail task if font didn't get uninstalled
            logger.error(f"Error uninstalling font: {msg}")


def setup_logger():
    """
    Does a basic setup for a logger
    """
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(levelname)s:%(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


if __name__ == "__main__":
    setup_logger()
    session_dir = sys.argv[2]

    logger.debug(f"Running font script job: {sys.argv[1]}")

    if sys.argv[1] == "install":
        _install_fonts(session_dir)
    if sys.argv[1] == "remove":
        _remove_fonts(session_dir)