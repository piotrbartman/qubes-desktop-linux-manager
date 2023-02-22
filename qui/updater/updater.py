#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error
import time

import pkg_resources
import gi  # isort:skip

from qubes_config.widgets.gtk_utils import load_icon_at_gtk_size, \
    load_theme, is_theme_light
from qui.updater.progress_page import ProgressPage
from qui.updater.style import load_css
from qui.updater.updater_settings import Settings
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

    def __init__(self, qapp):
        super().__init__(
            application_id="org.gnome.example",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.qapp = qapp
        self.primary = False
        self.connect("activate", self.do_activate)

    def do_activate(self, *_args, **_kwargs):
        if not self.primary:
            self.perform_setup()
            self.primary = True
            self.hold()
        else:
            self.main_window.present()

    def perform_setup(self, *_args, **_kwargs):
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

        self.intro_page = IntroPage(self.builder, self.next_button)
        self.progress_page = ProgressPage(
            self.builder,
            self.header_label,
            self.next_button,
            self.cancel_button
        )
        self.summary_page = SummaryPage(
            self.builder,
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
        self.settings = Settings(
            self.main_window,
            self.qapp,
            refresh_callback=self.intro_page.refresh_update_list
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
            renderer: Gtk.CellRenderer = self.builder.get_object(name + "_renderer")
            column: Gtk.TreeViewColumn = self.builder.get_object(name + "_column")
            column.set_cell_data_func(renderer, cell_data_func, col)
            renderer.props.ypad = 10
            if not name.endswith("name") and name != "summary_status":
                # center
                renderer.props.xalign = 0.5

        self.main_window.connect("delete-event", self.window_close)
        self.main_window.connect("key-press-event", self.check_escape)

        load_css()

        self.intro_page.populate_vm_list(self.qapp, self.settings)
        self.main_window.show_all()

    def open_settings_window(self, _emitter):
        self.settings.show()

    def next_clicked(self, _emitter):
        if self.intro_page.is_visible:
            vms_to_update = self.intro_page.get_vms_to_update()
            self.intro_page.active = False
            self.progress_page.show()
            self.progress_page.init_update(vms_to_update, self.settings)
        elif self.progress_page.is_visible:
            if not self.summary_page.is_populated:
                self.summary_page.populate_restart_list(
                    restart=self.intro_page.restart_button.get_active(),
                    vm_updated=self.progress_page.vms_to_update,
                    settings=self.settings
                )
            self.summary_page.show(*self.progress_page.get_update_summary())
        elif self.summary_page.is_visible:
            self.main_window.hide()
            self.summary_page.restart_selected_vms()
            self.exit_updater()

    def cancel_clicked(self, _emitter):
        if self.summary_page.is_visible:
            self.progress_page.show()
        else:
            self.cancel_updates()

    def cancel_updates(self, *_args, **_kwargs):
        # pylint: disable=attribute-defined-outside-init
        if self.progress_page.update_thread \
                and self.progress_page.update_thread.is_alive():
            self.progress_page.exit_triggered = True
            dialog = Gtk.MessageDialog(
                self.main_window, Gtk.DialogFlags.MODAL, Gtk.MessageType.OTHER,
                Gtk.ButtonsType.NONE, l(
                    "Waiting for current qube to finish updating."
                    " Updates for remaining qubes have been cancelled."))
            dialog.show()
            while self.progress_page.update_thread.is_alive():
                while Gtk.events_pending():
                    Gtk.main_iteration()
                time.sleep(1)
            dialog.hide()
        else:
            self.exit_updater()

    def check_escape(self, _widget, event, _data=None):
        if event.keyval == Gdk.KEY_Escape:
            self.cancel_updates()

    def window_close(self, *_args, **_kwargs):
        if self.progress_page.is_visible:
            self.cancel_updates()
        self.exit_updater()

    def exit_updater(self, _emitter=None):
        if self.primary:
            self.release()


def main():
    qapp = Qubes()
    app = QubesUpdater(qapp)
    app.run()


if __name__ == '__main__':
    main()
