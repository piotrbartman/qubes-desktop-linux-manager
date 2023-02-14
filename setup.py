#!/usr/bin/env python3
""" Setup.py file """
import os
import subprocess
import setuptools
import setuptools.command.install


# create and install translation files
class InstallWithLocale(setuptools.command.install.install):
    def create_mo_files(self):
        data_files = []
        localedir = 'locale'
        po_dirs = [localedir + '/' + l + '/LC_MESSAGES/'
                   for l in next(os.walk(localedir))[1]]
        for d in po_dirs:
            mo_dir = os.path.join(self.root, 'usr/share', d)
            os.makedirs(mo_dir, exist_ok=True)
            mo_files = []
            po_files = [f
                        for f in next(os.walk(d))[2]
                        if os.path.splitext(f)[1] == '.po']
            for po_file in po_files:
                filename, extension = os.path.splitext(po_file)
                mo_file = filename + '.mo'
                msgfmt_cmd = 'msgfmt {} -o {}'.format(
                    d + po_file,
                    os.path.join(mo_dir, mo_file))
                subprocess.check_call(msgfmt_cmd, shell=True)
                mo_files.append(d + mo_file)
            data_files.append((d, mo_files))
        return data_files

    def run(self):
        self.create_mo_files()
        super().run()


setuptools.setup(
    name='qui',
    version='0.1',
    author='Invisible Things Lab',
    author_email='marmarta@invisiblethingslab.com',
    description='Qubes User Interface And Configuration Package',
    license='GPL2+',
    url='https://www.qubes-os.org/',
    packages=["qui", "qui.updater", "qui.tray", "qubes_config",
              "qubes_config.global_config", "qubes_config.widgets",
              "qubes_config.new_qube"],
    entry_points={
        'gui_scripts': [
            'qui-domains = qui.tray.domains:main',
            'qui-devices = qui.tray.devices:main',
            'qui-disk-space = qui.tray.disk_space:main',
            'qui-updates = qui.tray.updates:main',
            'qubes-update-gui = qui.updater.updater:main',
            'qui-clipboard = qui.clipboard:main',
            'qubes-new-qube = qubes_config.new_qube.new_qube_app:main',
            'qubes-global-config = qubes_config.global_config.global_config:main'
        ]
    },
    package_data={'qui': ["updater.glade",
                          "updater_settings.glade",
                          "qubes-updater-base.css",
                          "qubes-updater-light.css",
                          "qubes-updater-dark.css"],
                  'qubes_config': ["new_qube.glade",
                                   "global_config.glade",
                                   "qubes-new-qube-base.css",
                                   "qubes-new-qube-light.css",
                                   "qubes-new-qube-dark.css",
                                   "qubes-global-config-base.css",
                                   "qubes-global-config-light.css",
                                   "qubes-global-config-dark.css"]},
    cmdclass={
        'install': InstallWithLocale
    },
)
