#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error
import re
import selectors
import time
import threading
import subprocess

import pkg_resources
import gi  # isort:skip

from qubes_config.widgets.gtk_utils import load_icon_at_gtk_size, \
    load_theme, is_theme_light, \
    copy_to_global_clipboard
from qubes_config.widgets.utils import get_feature
from qui.updater.progress_page import ProgressPage
from qui.updater.updater_settings import Settings
from qui.updater.summary_page import SummaryPage
from qui.updater.intro_page import IntroPage
from qui.updater.utils import Theme, UpdateStatus

gi.require_version('Gtk', '3.0')  # isort:skip

from gi.repository import Gtk, Gdk, GObject, Gio  # isort:skip
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
            flags=Gio.ApplicationFlags.FLAGS_NONE)

        self.qapp = qapp

        self.primary = False
        self.connect("activate", self.do_activate)

        self.disable_checkboxes = False
        self.update_thread = None

    def perform_setup(self, *_args, **_kwargs):
        # pylint: disable=attribute-defined-outside-init
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain("desktop-linux-manager")
        self.builder.add_from_file(pkg_resources.resource_filename(
            'qui', 'updater.glade'))

        self.main_window = self.builder.get_object("main_window")

        self.next_button = self.builder.get_object("button_next")
        self.next_button.connect("clicked", self.next_clicked)
        self.cancel_button = self.builder.get_object("button_cancel")

        load_theme(widget=self.main_window,
                   light_theme_path=pkg_resources.resource_filename(
                       'qui', 'qubes-updater-light.css'),
                   dark_theme_path=pkg_resources.resource_filename(
                       'qui', 'qubes-updater-dark.css'))
        self.theme = Theme.LIGHT if is_theme_light(self.main_window) \
            else Theme.DARK

        self.header_label = self.builder.get_object("header_label")
        self.button_settings = self.builder.get_object("button_settings")
        self.button_settings = self.builder.get_object("button_settings")
        self.button_settings.connect("clicked", self.open_settings_window)
        settings_pixbuf = load_icon_at_gtk_size(
            'qubes-customize', Gtk.IconSize.LARGE_TOOLBAR)
        settings_image = Gtk.Image.new_from_pixbuf(settings_pixbuf)
        self.button_settings.set_image(settings_image)

        self.stack = self.builder.get_object("main_stack")

        self.intro_page = IntroPage(
            self.builder, self.theme, self.next_button)
        self.settings = Settings(
            self.main_window,
            self.qapp,
            refresh_callback=self.intro_page.refresh_update_list
        )
        self.summary_page = SummaryPage(
            self.builder, self.theme, self.next_button)
        self.intro_page.populate_vm_list(self.qapp, self.settings)
        self.progress_page = ProgressPage(
            self.builder,
            self.stack,
            self.theme,
            self.header_label,
            self.next_button,
            self.cancel_button
        )

        headers = [(3, "name"), (3, "progress_name"), (3, "summary_name"),
                   (3, "restart_name"), (4, "available"), (5, "check"),
                   (6, "update"), (8, "summary_status")]

        def cell_data_func(_column, cell, model, it, data):
            # Get the object from the model
            obj = model.get_value(it, data)
            # Set the cell value to the name of the object
            cell.set_property("markup", str(obj))

        for col, name in headers:
            renderer = self.builder.get_object(name + "_renderer")
            column = self.builder.get_object(name + "_column")
            column.set_cell_data_func(renderer, cell_data_func, col)
            renderer.props.ypad = 10
            if not name.endswith("name") and name != "summary_status":
                # center
                renderer.props.xalign = 0.5

        self.restart_button = self.builder.get_object("restart_button")

        self.cancel_button.connect("clicked", self.cancel_clicked)
        self.main_window.connect("delete-event", self.window_close)
        self.main_window.connect("key-press-event", self.check_escape)

        self.summary_list = self.builder.get_object("summary_list")
        self.summary_list.connect("row-activated", self.back_by_row_selection)

        self.list_page = self.builder.get_object("list_page")
        self.restart_page = self.builder.get_object("restart_page")

        self.label_summary = self.builder.get_object("label_summary")
        self.info_how_it_works = self.builder.get_object("info_how_it_works")
        self.info_how_it_works.set_label(
            self.info_how_it_works.get_label().format(
                MAYBE='<span foreground="Orange"><b>MAYBE</b></span>'))

        self.load_css()

        self.main_window.show_all()

        self.update_thread = None

    def open_settings_window(self, _emitter):
        self.settings.show()

    def do_activate(self, *_args, **_kwargs):
        if not self.primary:
            self.perform_setup()
            self.primary = True
            self.hold()
        else:
            self.main_window.present()

    @staticmethod
    def load_css():
        style_provider = Gtk.CssProvider()
        css = b'''
        .black-border { 
            border-width: 1px; 
            border-color: #c6c6c6; 
            border-style: solid;
        }
        '''
        style_provider.load_from_data(css)

        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def next_clicked(self, _emitter):
        if self.stack.get_visible_child() == self.list_page:
            self.vms_to_update = self.intro_page.get_vms_to_update()
            self.intro_page.active = False

            self.progress_page.show_progress_page()
            self.next_button.set_sensitive(False)
            self.cancel_button.set_label(l("_Cancel updates"))
            self.cancel_button.show()

            self.header_label.set_text(l("Update in progress..."))
            self.header_label.set_halign(Gtk.Align.CENTER)

            # pylint: disable=attribute-defined-outside-init
            self.update_thread = threading.Thread(
                target=self.progress_page.perform_update,
                args=(self.vms_to_update, self.settings)
            )
            self.update_thread.start()

        elif self.stack.get_visible_child() == self.progress_page.page:
            (qube_updated_num, qube_no_updates_num,
             qube_failed_num) = self.get_update_summary()
            qube_updated_plural = "s" if qube_updated_num != 1 else ""
            qube_no_updates_plural = "s" if qube_no_updates_num != 1 else ""
            qube_failed_plural = "s" if qube_failed_num != 1 else ""
            summary = f"{qube_updated_num} qube{qube_updated_plural} " + \
                      l("updated successfully.") + "\n" \
                      f"{qube_no_updates_num} qube{qube_no_updates_plural} " + \
                      l("attempted to update but found no updates.") + "\n" \
                      f"{qube_failed_num} qube{qube_failed_plural} " + \
                      l("failed to update.")
            self.label_summary.set_label(summary)
            if not self.summary_page.is_populated:
                self.summary_page.populate_restart_list(
                    restart=self.restart_button.get_active(),
                    vm_list_wrapped=self.vms_to_update,
                    settings=self.settings
                )
            self.stack.set_visible_child(self.restart_page)
            self.cancel_button.set_label(l("_Back"))
            self.cancel_button.show()
            self.summary_page.refresh_buttons()
        elif self.stack.get_visible_child() == self.restart_page:
            self.main_window.hide()
            self.restart_thread = threading.Thread(
                target=self.summary_page.perform_restart)
            self.restart_thread.start()
            self.exit_updater()

    def get_update_summary(self):
        qube_updated_num = len(
            [row for row in self.vms_to_update
             if row.status == UpdateStatus.Success])
        qube_no_updates_num = len(
            [row for row in self.vms_to_update
             if row.status == UpdateStatus.NoUpdatesFound])
        qube_failed_num = len(
            [row for row in self.vms_to_update
             if row.status in
             (UpdateStatus.Error, UpdateStatus.Cancelled)])
        return qube_updated_num, qube_no_updates_num, qube_failed_num

    def cancel_clicked(self, _emitter):
        if self.stack.get_visible_child() == self.restart_page:
            self.progress_page.show_progress_page()
        else:
            self.cancel_updates()

    def back_by_row_selection(self, _emitter, path, *args):
        self.progress_page.show_progress_page()
        self.progress_page.row_selected(_emitter, path, *args)

    def cancel_updates(self, *_args, **_kwargs):
        # pylint: disable=attribute-defined-outside-init
        if self.update_thread and self.update_thread.is_alive():
            self.progress_page.exit_triggered = True
            dialog = Gtk.MessageDialog(
                self.main_window, Gtk.DialogFlags.MODAL, Gtk.MessageType.OTHER,
                Gtk.ButtonsType.NONE, l(
                    "Waiting for current qube to finish updating."
                    " Updates for remaining qubes have been cancelled."))
            dialog.show()
            while self.update_thread.is_alive():
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
        if self.stack.get_visible_child() == self.progress_page.page:
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
