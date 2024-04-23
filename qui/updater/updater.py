#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error
import argparse
import logging
import time

import pkg_resources
import gi  # isort:skip

from qubes_config.widgets.gtk_utils import load_icon_at_gtk_size, load_theme, \
    show_dialog_with_icon, RESPONSES_OK
from qui.updater.progress_page import ProgressPage
from qui.updater.updater_settings import Settings, OverridenSettings
from qui.updater.summary_page import SummaryPage
from qui.updater.intro_page import IntroPage

gi.require_version('Gtk', '3.0')  # isort:skip
from gi.repository import Gtk, Gdk, Gio  # isort:skip
from qubesadmin import Qubes

# using locale.gettext is necessary for Gtk.Builder translation support to work
# in most cases gettext is better, but it cannot handle Gtk.Builder/glade files
import locale
from locale import gettext as l

locale.bindtextdomain("desktop-linux-manager", "/usr/locales/")
locale.textdomain('desktop-linux-manager')


class QubesUpdater(Gtk.Application):
    # pylint: disable=too-many-instance-attributes

    LOGPATH = '/var/log/qubes/qui.updater.log'
    LOG_FORMAT = '%(asctime)s %(message)s'

    def __init__(self, qapp, cliargs):
        super().__init__(
            application_id="org.gnome.example",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.qapp = qapp
        self.primary = False
        self.do_nothing = False
        self.connect("activate", self.do_activate)
        self.cliargs = cliargs

        log_handler = logging.FileHandler(
            QubesUpdater.LOGPATH, encoding='utf-8')
        log_formatter = logging.Formatter(QubesUpdater.LOG_FORMAT)
        log_handler.setFormatter(log_formatter)

        self.log = logging.getLogger('vm-update.agent.PackageManager')
        self.log.addHandler(log_handler)
        self.log.setLevel(self.cliargs.log)

    def do_activate(self, *_args, **_kwargs):
        if not self.primary:
            self.log.debug("Primary activation")
            self.perform_setup()
            self.primary = True
            self.hold()
        else:
            self.log.debug("Secondary activation")
            if self.do_nothing:
                show_dialog_with_icon(
                    None, l("Quit"),
                    l("Nothing to do."),
                    buttons=RESPONSES_OK,
                    icon_name="check_yes"
                )
                self.window_close()
            else:
                self.main_window.present()

    def perform_setup(self, *_args, **_kwargs):
        self.log.debug("Setup")
        # pylint: disable=attribute-defined-outside-init
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain("desktop-linux-manager")
        self.builder.add_from_file(pkg_resources.resource_filename(
            'qui', 'updater.glade'))

        self.main_window: Gtk.Window = self.builder.get_object("main_window")
        self.next_button: Gtk.Button = self.builder.get_object("button_next")
        self.next_button.connect("clicked", self.next_clicked)
        self.cancel_button: Gtk.Button = self.builder.get_object(
            "button_cancel")
        self.cancel_button.connect("clicked", self.cancel_clicked)

        load_theme(widget=self.main_window,
                   light_theme_path=pkg_resources.resource_filename(
                       'qui', 'qubes-updater-light.css'),
                   dark_theme_path=pkg_resources.resource_filename(
                       'qui', 'qubes-updater-dark.css'))

        self.header_label: Gtk.Label = self.builder.get_object("header_label")

        self.intro_page = IntroPage(self.builder, self.log, self.next_button)
        self.progress_page = ProgressPage(
            self.builder,
            self.log,
            self.header_label,
            self.next_button,
            self.cancel_button
        )
        self.summary_page = SummaryPage(
            self.builder,
            self.log,
            self.next_button,
            self.cancel_button,
            self.progress_page.back_by_row_selection
        )

        self.button_settings: Gtk.Button = self.builder.get_object(
            "button_settings")
        self.button_settings.connect("clicked", self.open_settings_window)
        settings_pixbuf = load_icon_at_gtk_size(
            'qubes-customize', Gtk.IconSize.LARGE_TOOLBAR)
        settings_image = Gtk.Image.new_from_pixbuf(settings_pixbuf)
        self.button_settings.set_image(settings_image)

        overriden_restart = None
        if self.cliargs.restart:
            overriden_restart = True
        elif  self.cliargs.no_restart:
            overriden_restart = False

        overrides = OverridenSettings(
            restart=overriden_restart,
            max_concurrency=self.cliargs.max_concurrency,
            update_if_stale=self.cliargs.update_if_stale,
        )

        self.settings = Settings(
            self.main_window,
            self.qapp,
            self.log,
            refresh_callback=self.intro_page.refresh_update_list,
            overrides=overrides,
        )

        headers = [(3, "intro_name"), (3, "progress_name"), (3, "summary_name"),
                   (3, "restart_name"), (4, "available"), (5, "check"),
                   (6, "update"), (8, "summary_status")]

        def cell_data_func(_column, cell, model, it, data):
            # Get the object from the model
            obj = model.get_value(it, data)
            # Set the cell value to the name of the object
            cell.set_property("markup", str(obj))

        for col, name in headers:
            renderer: Gtk.CellRenderer = self.builder.get_object(
                name + "_renderer")
            column: Gtk.TreeViewColumn = self.builder.get_object(
                name + "_column")
            column.set_cell_data_func(renderer, cell_data_func, col)
            renderer.props.ypad = 10
            if not name.endswith("name") and name != "summary_status":
                # center
                renderer.props.xalign = 0.5

        self.main_window.connect("delete-event", self.window_close)
        self.main_window.connect("key-press-event", self.check_escape)

        self.intro_page.populate_vm_list(self.qapp, self.settings)

        if skip_intro_if_args(self.cliargs):
            self.log.info("Skipping intro page.")
            self.intro_page.select_rows_ignoring_conditions(
                cliargs=self.cliargs, dom0=self.qapp.domains['dom0'])
            if len(self.intro_page.get_vms_to_update()) == 0:
                self.do_nothing = True
                return
            self.next_clicked(None, skip_intro=True)
        else:
            self.log.info("Show intro page.")
        self.main_window.show_all()
        width = self.intro_page.vm_list.get_preferred_width().natural_width
        self.main_window.resize(width + 50, int(width * 1.2))
        self.main_window.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        # return 0

    def open_settings_window(self, _emitter):
        self.settings.show()

    def next_clicked(self, _emitter, skip_intro=False):
        self.log.debug("Next clicked")
        if self.intro_page.is_visible or skip_intro:
            vms_to_update = self.intro_page.get_vms_to_update()
            self.intro_page.active = False
            self.progress_page.show()
            self.progress_page.init_update(vms_to_update, self.settings)
        elif self.progress_page.is_visible:
            if not self.summary_page.is_populated:
                self.summary_page.populate_restart_list(
                    restart=True,
                    vm_updated=self.progress_page.vms_to_update,
                    settings=self.settings
                )
            self.summary_page.show(*self.progress_page.get_update_summary())
        elif self.summary_page.is_visible:
            self.main_window.hide()
            self.log.debug("Hide main window")
            # ensuring that main_window will be hidden
            while Gtk.events_pending():
                Gtk.main_iteration()
            self.summary_page.restart_selected_vms()
            self.exit_updater()

    def cancel_clicked(self, _emitter):
        self.log.debug("Cancel clicked")
        if self.summary_page.is_visible:
            self.progress_page.show()
        elif self.progress_page.is_visible:
            self.cancel_updates()
        else:
            self.exit_updater()

    def cancel_updates(self, *_args, **_kwargs):
        self.log.info("User initialize interruption")
        if self.progress_page.update_thread \
                and self.progress_page.update_thread.is_alive():
            self.progress_page.interrupt_update()
            self.log.info("Update interrupted")
            show_dialog_with_icon(self.main_window, l("Updating cancelled"), l(
                "Waiting for current qube to finish updating."
                " Updates for remaining qubes have been cancelled."),
                                  buttons=RESPONSES_OK, icon_name="qubes-info")

            self.log.debug("Waiting to finish ongoing updates")
            while self.progress_page.update_thread.is_alive():
                while Gtk.events_pending():
                    Gtk.main_iteration()
                time.sleep(0.1)

    def check_escape(self, _widget, event, _data=None):
        if event.keyval == Gdk.KEY_Escape:
            self.window_close()

    def window_close(self, *_args, **_kwargs):
        self.log.debug("Close window")
        if self.progress_page.exit_triggered:
            self.cancel_updates()
        else:
            self.cancel_updates()
            self.exit_updater()

    def exit_updater(self, _emitter=None):
        if self.primary:
            self.log.debug("Exit")
            self.release()


def parse_args(args):
    parser = argparse.ArgumentParser()

    parser.add_argument('--log', action='store', default='WARNING',
                        help='Provide logging level. Values: DEBUG, INFO, '
                             'WARNING (default), ERROR, CRITICAL')
    parser.add_argument('--max-concurrency', action='store',
                        help='Maximum number of VMs configured simultaneously '
                             '(default: number of cpus)',
                        type=int)
    restart_gr = parser.add_mutually_exclusive_group()
    restart_gr.add_argument('--restart', action='store_true',
                            help='Restart AppVMs whose template '
                                 'has been updated.')
    restart_gr.add_argument('--no-restart', action='store_true',
                            help='Do not restart AppVMs whose template '
                                 'has been updated.')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--targets', action='store',
                       help='Comma separated list of VMs to target')
    group.add_argument('--all', action='store_true',
                       help='Target all updatable VMs (AdminVM, '
                            'TemplateVMs and StandaloneVMs)')
    group.add_argument('--update-if-stale', action='store',
                       help='Target all TemplateVMs with known updates or for '
                            'which last update check was more than N days '
                            'ago.',
                       type=int)

    parser.add_argument('--skip', action='store',
                        help='Comma separated list of VMs to be skipped, '
                             'works with all other options.', default="")
    parser.add_argument('--templates', action='store_true',
                        help='Target all TemplatesVMs')
    parser.add_argument('--standalones', action='store_true',
                        help='Target all StandaloneVMs')
    parser.add_argument('--dom0', action='store_true',
                        help='Target dom0')

    args = parser.parse_args(args)

    return args


def skip_intro_if_args(args):
    return args is not None and (args.templates or args.standalones or args.skip
                                 or args.update_if_stale or args.all
                                 or args.targets or args.dom0)


def main(args=None):
    cliargs = parse_args(args)
    qapp = Qubes()
    app = QubesUpdater(qapp, cliargs)
    app.run()


if __name__ == '__main__':
    main()
