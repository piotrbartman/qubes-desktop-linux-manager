#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error
import asyncio
import re
import time
import threading
import subprocess
import functools
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Union, Callable

import pkg_resources
import gi  # isort:skip

from qubes_config.widgets.gtk_utils import load_icon_at_gtk_size, \
    appviewer_lock, DATA, FROM, XEVENT, load_theme, is_theme_light, \
    copy_to_global_clipboard
from qubes_config.widgets.utils import get_boolean_feature
from qui.updater.updater_settings import Settings

gi.require_version('Gtk', '3.0')  # isort:skip

from gi.repository import Gtk, Gdk, GObject, Gio  # isort:skip
from qubesadmin import Qubes
from qubesadmin import exc
from qubesadmin.events.utils import wait_for_domain_shutdown

# using locale.gettext is necessary for Gtk.Builder translation support to work
# in most cases gettext is better, but it cannot handle Gtk.Builder/glade files
import locale
from locale import gettext as _

locale.bindtextdomain("desktop-linux-manager", "/usr/locales/")
locale.textdomain('desktop-linux-manager')


def disable_checkboxes(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.disable_checkboxes:
            return
        self.disable_checkboxes = True
        func(self, *args, **kwargs)
        self.disable_checkboxes = False

    return wrapper


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

    def perform_setup(self, *_args, **_kwargs):
        # pylint: disable=attribute-defined-outside-init
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain("desktop-linux-manager")
        self.builder.add_from_file(pkg_resources.resource_filename(
            'qui', 'updater.glade'))

        self.main_window = self.builder.get_object("main_window")

        self.vm_list = self.builder.get_object("vm_list")

        load_theme(widget=self.main_window,
                   light_theme_path=pkg_resources.resource_filename(
                       'qui', 'qubes-updater-light.css'),
                   dark_theme_path=pkg_resources.resource_filename(
                       'qui', 'qubes-updater-dark.css'))
        self.theme = Theme.LIGHT if is_theme_light(self.main_window) \
            else Theme.DARK

        self.settings = Settings(
            self.main_window,
            self.qapp,
            refresh_callback=self.refresh_update_list
        )

        self.header_label = self.builder.get_object("header_label")
        self.button_settings = self.builder.get_object("button_settings")
        self.button_settings = self.builder.get_object("button_settings")
        self.button_settings.connect("clicked", self.open_settings_window)
        settings_pixbuf = load_icon_at_gtk_size(
            'qubes-customize', Gtk.IconSize.LARGE_TOOLBAR)
        settings_image = Gtk.Image.new_from_pixbuf(settings_pixbuf)
        self.button_settings.set_image(settings_image)

        ###
        checkbox_column = self.builder.get_object("checkbox_column")
        checkbox_column.connect("clicked", self.on_header_toggled)
        header_button = checkbox_column.get_button()

        def pass_through_event_window(button):
            if not isinstance(button, Gtk.Button):
                raise TypeError("%r is not a gtk.Button" % button)
            event_window = button.get_event_window()
            event_window.set_pass_through(True)

        header_button.connect('realize', pass_through_event_window)

        self.checkbox_column_button = self.builder.get_object("checkbox_header")
        self.checkbox_column_button.set_inconsistent(True)
        self.checkbox_column_button.connect("toggled", self.on_header_toggled)
        self.update_checkbox_header = HeaderCheckbox(
            self.checkbox_column_button,
            allowed=("YES", "MAYBE", "NO"),
            callback_all=lambda: self.next_button.set_sensitive(True),
            callback_some=lambda: self.next_button.set_sensitive(True),
            callback_none=lambda: self.next_button.set_sensitive(False),
        )

        self.vm_list.connect("row-activated", self.on_checkbox_toggled)
        ###

        self.restart_list = self.builder.get_object("restart_list")
        self.restart_list.connect("row-activated", self.on_restart_checkbox_toggled)
        self.restart_list_store = self.builder.get_object("restart_list_store")
        restart_checkbox_column = self.builder.get_object(
            "restart_checkbox_column")
        restart_checkbox_column.connect("clicked",
                                        self.on_restart_header_toggled)
        restart_header_button = restart_checkbox_column.get_button()
        restart_header_button.connect('realize', pass_through_event_window)

        self.retart_checkbox_column_button = self.builder.get_object(
            "restart_checkbox_header")
        self.retart_checkbox_column_button.set_inconsistent(True)
        self.retart_checkbox_column_button.connect(
            "toggled", self.on_restart_header_toggled)
        self.restart_checkbox_header = HeaderCheckbox(
            self.retart_checkbox_column_button,
            allowed=("SYS", "OTHER", "EXCLUDED"),
            callback_all=lambda plural, num: self.next_button.set_label(
                f"_Finish and restart {num} qube{plural}"),
            callback_some=lambda plural, num: self.next_button.set_label(
                f"_Finish and restart {num} qube{plural}"),
            callback_none=lambda _, __: self.next_button.set_label("_Finish"),
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

        progress_list = self.builder.get_object("progress_list")
        progress_list.connect("row-activated", self.row_selected)
        progress_column = self.builder.get_object("progress_column")
        renderer = CellRendererProgressWithResult()
        renderer.props.ypad = 10
        progress_column.pack_start(renderer, True)
        progress_column.add_attribute(renderer, "pulse", 7)
        progress_column.add_attribute(renderer, "value", 7)
        progress_column.add_attribute(renderer, "status", 8)

        self.update_details = QubeUpdateDetails(self.builder)

        self.populate_vm_list()

        self.restart_button = self.builder.get_object("restart_button")

        self.next_button = self.builder.get_object("button_next")
        self.next_button.connect("clicked", self.next_clicked)

        self.cancel_button = self.builder.get_object("button_cancel")
        self.cancel_button.connect("clicked", self.cancel_clicked)
        self.main_window.connect("delete-event", self.window_close)
        self.main_window.connect("key-press-event", self.check_escape)

        self.summary_list = self.builder.get_object("summary_list")
        self.summary_list.connect("row-activated", self.back_by_row_selection)

        self.stack = self.builder.get_object("main_stack")
        self.list_page = self.builder.get_object("list_page")
        self.progress_page = self.builder.get_object("progress_page")
        self.restart_page = self.builder.get_object("restart_page")
        self.progressbar = self.builder.get_object("progressbar")
        progress_store = self.progressbar.get_model()
        progress_store.append([0])
        self.total_progress = progress_store[-1]
        self.progressbar_renderer = self.builder.get_object(
            "progressbar_renderer")
        self.progressbar_renderer.set_fixed_size(-1, 26)

        self.label_summary = self.builder.get_object("label_summary")
        self.info_how_it_works = self.builder.get_object("info_how_it_works")
        self.info_how_it_works.set_label(
            self.info_how_it_works.get_label().format(
                MAYBE='<span foreground="Orange"><b>MAYBE</b></span>'))

        self.load_css()

        self.main_window.show_all()

        self.update_thread = None
        self.exit_triggered = False

    @disable_checkboxes
    def on_checkbox_toggled(self, _emitter, path, *_args):
        if path is None:
            return

        it = self.list_store.get_iter(path)
        self.list_store[it][0].selected = \
            not self.list_store[it][0].selected
        selected_num = sum(row.selected for row in self.list_store_wrapped)
        if selected_num == len(self.list_store_wrapped):
            self.update_checkbox_header.state = HeaderCheckbox.ALL
        elif selected_num == 0:
            self.update_checkbox_header.state = HeaderCheckbox.NONE
        else:
            self.update_checkbox_header.state = HeaderCheckbox.SELECTED
        self.update_checkbox_header.set_buttons()

    @disable_checkboxes
    def on_header_toggled(self, _emitter):
        if len(self.list_store_wrapped) == 0:  # to avoid infinite loop
            return

        selected_num = selected_num_old = sum(
            row.selected for row in self.list_store_wrapped)
        while selected_num == selected_num_old:
            self.update_checkbox_header.next_state()
            for row in self.list_store_wrapped:
                row.selected = row.updates_available.value \
                               in self.update_checkbox_header.allowed
            selected_num = sum(row.selected for row in self.list_store_wrapped)

        self.update_checkbox_header.set_buttons()

    @disable_checkboxes
    def on_restart_checkbox_toggled(self, _emitter, path, *_args):
        if path is None:
            return

        it = self.restart_list_store.get_iter(path)
        self.restart_list_store[it][1] = \
            not self.restart_list_store[it][1]
        self.refresh_buttons()

    def refresh_buttons(self):
        selected_num = sum(
            row.selected for row in self.restart_list_store_wrapped)
        if selected_num == len(self.restart_list_store):
            self.restart_checkbox_header.state = HeaderCheckbox.ALL
        elif selected_num == 0:
            self.restart_checkbox_header.state = HeaderCheckbox.NONE
        else:
            self.restart_checkbox_header.state = HeaderCheckbox.SELECTED
        plural = "s" if selected_num > 1 else ""
        self.restart_checkbox_header.set_buttons(plural, selected_num)

    @disable_checkboxes
    def on_restart_header_toggled(self, _emitter):
        if len(self.restart_list_store_wrapped) == 0:  # to avoid infinite loop
            return

        selected_num = selected_num_old = sum(
            row.selected for row in self.restart_list_store_wrapped)
        while selected_num == selected_num_old:
            self.restart_checkbox_header.next_state()
            for row in self.restart_list_store_wrapped:
                row.selected = (
                    row.is_sys_qube and "SYS"
                    in self.restart_checkbox_header.allowed
                    or not row.is_excluded and "OTHER"
                    in self.restart_checkbox_header.allowed
                    or row.is_excluded and "EXCLUDED"
                    in self.restart_checkbox_header.allowed
                )
            selected_num = sum(
                row.selected for row in self.restart_list_store_wrapped)
        plural = "s" if selected_num > 1 else ""
        self.restart_checkbox_header.set_buttons(plural, selected_num)

    def populate_restart_list(self):
        if hasattr(self, "restart_list_store_wrapped"):
            return
        self.updated_tmpls = [
            row for row in self.list_store_wrapped
            if row.status
            and QubeClass[row.qube.klass] == QubeClass.TemplateVM
        ]
        possibly_changed_vms = {appvm for template in self.updated_tmpls
                                 for appvm in template.qube.appvms
                                }
        self.restart_list_store.set_sort_func(0, sort_func, 0)
        self.restart_list_store.set_sort_func(3, sort_func, 3)

        self.restart_list_store_wrapped = []

        for qube in possibly_changed_vms:
            if qube.is_running() \
                    and (qube.klass != 'DispVM' or not qube.auto_cleanup):
                to_restart = str(qube.name).startswith("sys-") \
                             and self.restart_button.get_active()
                row = RestartRowWrapper(
                    self.restart_list_store, qube, to_restart, self.theme)
                self.restart_list_store_wrapped.append(row)

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

    def populate_vm_list(self):
        result = False  # whether at least one VM has updates available
        self.list_store = self.vm_list.get_model()
        self.list_store_wrapped = []

        self.list_store.set_sort_func(0, sort_func, 0)
        self.list_store.set_sort_func(3, sort_func, 3)
        self.list_store.set_sort_func(4, sort_func, 4)
        self.list_store.set_sort_func(5, sort_func, 5)
        self.list_store.set_sort_func(6, sort_func, 6)
        self.list_store.set_sort_func(8, sort_func, 8)
        for vm in self.qapp.domains:
            if vm.klass == 'AdminVM':
                try:
                    state = bool(vm.features.get('updates-available', False))
                except exc.QubesDaemonCommunicationError:
                    state = False
                result = result or state
                qube_row = UpdateRowWrapper(
                    self.list_store, vm, state, self.theme)
                self.list_store_wrapped.append(qube_row)

                # TODO
                devel_deb = self.qapp.domains['devel-debian']
                qube_row = UpdateRowWrapper(
                    self.list_store, devel_deb, True, self.theme)
                self.list_store_wrapped.append(qube_row)
                devel_fed = self.qapp.domains['devel-fedora']
                qube_row = UpdateRowWrapper(
                    self.list_store, devel_fed, True, self.theme)
                self.list_store_wrapped.append(qube_row)
                # END TODO

        for vm in self.qapp.domains:
            if getattr(vm, 'updateable', False) and vm.klass != 'AdminVM':
                qube_row = UpdateRowWrapper(
                    self.list_store, vm, False, self.theme)
                self.settings.available_vms.append(vm)
                self.list_store_wrapped.append(qube_row)

        self.refresh_update_list()

        return result

    def refresh_update_list(self):
        output = subprocess.check_output(
            ['qubes-vm-update', '--dry-run',
             '--update-if-stale', str(self.settings.update_if_stale)])

        to_update = [vm_name.strip() for vm_name
                     in output.decode().split("\n")[0].split(":")[1].split(",")]

        for row in self.list_store_wrapped:
            row.updates_available = bool(row.qube.name in to_update)

    def next_clicked(self, _emitter):
        if self.stack.get_visible_child() == self.list_page:
            selected_rows = [row for row in self.list_store_wrapped
                             if row.selected]
            to_remove = [row for row in self.list_store_wrapped
                         if not row.selected]
            for elem in to_remove:
                elem.delete()
            self.list_store_wrapped = selected_rows

            self.show_progress_page()
            self.next_button.set_sensitive(False)
            self.cancel_button.set_label(_("_Cancel updates"))
            self.cancel_button.show()

            self.header_label.set_text(_("Update in progress..."))
            self.header_label.set_halign(Gtk.Align.CENTER)

            # pylint: disable=attribute-defined-outside-init
            self.update_thread = threading.Thread(target=self.perform_update)
            self.update_thread.start()

        elif self.stack.get_visible_child() == self.progress_page:
            qube_updated_num = len(
                [row for row in self.list_store_wrapped
                 if row.status == UpdateStatus.Success])
            qube_updated_plural = "s" if qube_updated_num != 1 else ""
            qube_no_updates_num = len(
                [row for row in self.list_store_wrapped
                 if row.status == UpdateStatus.NoUpdatesFound])
            qube_no_updates_plural = "s" if qube_no_updates_num != 1 else ""
            qube_failed_num = len(
                [row for row in self.list_store_wrapped
                 if row.status in
                 (UpdateStatus.Error, UpdateStatus.Cancelled)])
            qube_failed_plural = "s" if qube_failed_num != 1 else ""
            summary = f"{qube_updated_num} qube{qube_updated_plural} " + \
                      _("updated successfully.") + "\n" \
                                                   f"{qube_no_updates_num} qube{qube_no_updates_plural} " + \
                      _("attempted to update but found no updates.") + "\n" \
                                                                       f"{qube_failed_num} qube{qube_failed_plural} " + \
                      _("failed to update.")
            self.label_summary.set_label(summary)
            self.populate_restart_list()
            self.stack.set_visible_child(self.restart_page)
            self.cancel_button.set_label(_("_Back"))
            self.cancel_button.show()
            self.refresh_buttons()
        elif self.stack.get_visible_child() == self.restart_page:
            self.cancel_updates()
            self.perform_restart()

    def cancel_clicked(self, _emitter):
        if self.stack.get_visible_child() == self.restart_page:
            self.show_progress_page()
        else:
            self.cancel_updates()

    def back_by_row_selection(self, _emitter, path, *args):
        self.show_progress_page()
        self.row_selected(_emitter, path, *args)

    def show_progress_page(self):
        self.update_details.set_active_row(None)
        self.stack.set_visible_child(self.progress_page)

        self.next_button.set_label(_("_Next"))
        self.cancel_button.hide()

    def perform_restart(self):
        # TODO Move restart to one place
        tmpls_to_shutdown = [row.qube
                             for row in self.updated_tmpls
                             if row.qube.is_running()]
        to_restart = [qube_row.qube
                      for qube_row in self.restart_list_store_wrapped
                      if qube_row.selected
                      and qube_row.is_sys_qube]
        to_shutdown = [qube_row.qube
                       for qube_row in self.restart_list_store_wrapped
                       if qube_row.selected
                       and not qube_row.is_sys_qube]
        shutdown_domains(tmpls_to_shutdown)
        restart_vms(to_restart)
        shutdown_domains(to_shutdown)

    def row_selected(self, _emitter, path, _col):
        self.update_details.set_active_row(
            self.list_store_wrapped[path.get_indices()[0]])

    def perform_update(self):
        admins = [row for row in self.list_store_wrapped
                  if row.selected and row.qube.klass == 'AdminVM']
        templs = [row for row in self.list_store_wrapped
                  if row.selected and row.qube.klass != 'AdminVM']

        if admins:
            admin = admins[0]
            if self.exit_triggered:
                GObject.idle_add(admin.set_status, UpdateStatus.Cancelled)
                GObject.idle_add(
                    admin.append_text_view,
                    _("Canceled update for {}\n").format(admin.vm.name))

            GObject.idle_add(
                admin.append_text_view,
                _("Updating {}\n").format(admin.name))
            GObject.idle_add(admin.set_status, UpdateStatus.ProgressUnknown)
            time.sleep(1)

            self.update_details.update_buffer()

            self.ticker_done = False
            thread = threading.Thread(target=self.ticker, args=(admin,))
            thread.start()

            try:
                output = subprocess.check_output(
                    ['sudo', 'qubesctl', '--dom0-only', '--no-color',
                     'pkg.upgrade', 'refresh=True'],
                    stderr=subprocess.STDOUT).decode()
                ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
                output = ansi_escape.sub('', output)

                GObject.idle_add(admin.append_text_view, output)
                GObject.idle_add(admin.set_status, UpdateStatus.Success)
            except subprocess.CalledProcessError as ex:
                GObject.idle_add(
                    admin.append_text_view,
                    _("Error on updating {}: {}\n{}").format(
                        admin.vm.name, str(ex), ex.output.decode()))
                GObject.idle_add(admin.set_status, UpdateStatus.Error)
            self.ticker_done = True

        if templs:
            if self.exit_triggered:
                for row in templs:
                    GObject.idle_add(row.set_status, UpdateStatus.Cancelled)
                    GObject.idle_add(
                        row.append_text_view,
                        _("Canceled update for {}\n").format(row.vm.name))

            for row in templs:
                GObject.idle_add(
                    row.append_text_view,
                    _("Updating {}\n").format(row.name))
                GObject.idle_add(row.set_status, UpdateStatus.InProgress)
            self.update_details.update_buffer()

            try:
                targets = ",".join((row.name for row in templs))
                rows = {row.name: row for row in templs}

                args = []
                if self.settings.max_concurrency is not None:
                    args.extend(
                        ('--max-concurrency',
                         str(self.settings.max_concurrency)))
                proc = subprocess.Popen(
                    ['qubes-vm-update',
                     '--show-output',
                     '--just-print-progress',
                     *args,
                     '--targets', targets],
                    stderr=subprocess.PIPE, stdout=subprocess.PIPE)

                for untrusted_line in iter(proc.stderr.readline, ''):
                    if untrusted_line:
                        line = untrusted_line.decode().rstrip()
                        try:
                            name, prog = line.split()
                            progress = int(float(prog))
                        except ValueError:
                            continue

                        if progress == 100.:
                            GObject.idle_add(
                                rows[name].set_status, UpdateStatus.Success)

                        GObject.idle_add(
                            rows[name].set_update_progress, progress)
                        total_progress = sum(
                            row.get_update_progress()
                            for row in rows.values()) / len(rows)

                        GObject.idle_add(
                            self.set_total_progress, total_progress)
                    else:
                        break
                proc.stderr.close()

                for row in rows.values():
                    if row.get_update_progress() != 100.:
                        GObject.idle_add(row.set_status, UpdateStatus.Error)

                GObject.idle_add(self.set_total_progress, 100)

                name = ""
                for untrusted_line in iter(proc.stdout.readline, ''):
                    if untrusted_line:
                        line = untrusted_line.decode()
                        maybe_name, text = line.split(' ', 1)
                        if maybe_name[:-1] in rows.keys():
                            name = maybe_name[:-1]
                        GObject.idle_add(
                            rows[name].append_text_view, text)
                    else:
                        break
                self.update_details.update_buffer()
                proc.stdout.close()

                proc.wait()

            except subprocess.CalledProcessError as ex:
                for row in templs:
                    GObject.idle_add(
                        row.append_text_view,
                        _("Error on updating {}: {}\n{}").format(
                            row.name, str(ex), ex.output.decode()))
                    GObject.idle_add(row.set_status, UpdateStatus.Error)
                self.update_details.update_buffer()

        GObject.idle_add(self.next_button.set_sensitive, True)
        GObject.idle_add(self.header_label.set_text, _("Update finished"))
        GObject.idle_add(self.cancel_button.set_visible, False)

    def ticker(self, row):
        while not self.ticker_done:
            new_value = (row.get_update_progress()) % 100 + 1
            row.set_update_progress(new_value)
            time.sleep(1 / 12)

    def cancel_updates(self, *_args, **_kwargs):
        # pylint: disable=attribute-defined-outside-init
        if self.update_thread and self.update_thread.is_alive():
            self.exit_triggered = True
            dialog = Gtk.MessageDialog(
                self.main_window, Gtk.DialogFlags.MODAL, Gtk.MessageType.OTHER,
                Gtk.ButtonsType.NONE, _(
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
        if self.stack.get_visible_child() == self.progress_page:
            self.cancel_updates()
        self.exit_updater()

    def exit_updater(self, _emitter=None):
        if self.primary:
            self.release()

    def set_total_progress(self, progress):
        self.total_progress[0] = progress


class QubeUpdateDetails:

    def __init__(self, builder):
        self.active_row = None

        self.builder = builder
        self.qube_details = self.builder.get_object("qube_details")
        self.details_label = self.builder.get_object("details_label")
        self.qube_icon = self.builder.get_object("qube_icon")
        self.qube_label = self.builder.get_object("qube_label")
        self.colon = self.builder.get_object("colon")
        self.copy_button = self.builder.get_object("copy_button")
        self.copy_button.connect("clicked", self.copy_content)
        self.progress_textview = self.builder.get_object("progress_textview")
        self.progress_scrolled_window = self.builder.get_object(
            "progress_textview")

    def copy_content(self, _emitter):
        if self.active_row is None:
            return

        text = self.active_row.buffer
        if not text:
            return

        copy_to_global_clipboard(text)

    def set_active_row(self, row):
        self.active_row = row
        row_activated = self.active_row is not None
        if not row_activated:
            self.details_label.set_text(_("Select a qube to see details."))
        else:
            self.details_label.set_text(_("Details for") + "  ")
            self.qube_icon.set_from_pixbuf(self.active_row.icon)
            self.qube_label.set_markup(" " + str(self.active_row.color_name))
        self.update_buffer()

        self.qube_icon.set_visible(row_activated)
        self.qube_label.set_visible(row_activated)
        self.colon.set_visible(row_activated)
        self.progress_scrolled_window.set_visible(row_activated)
        self.progress_textview.set_visible(row_activated)
        self.copy_button.set_visible(row_activated)

    def update_buffer(self):
        if self.active_row is not None:
            buffer_ = self.progress_textview.get_buffer()
            buffer_.set_text(self.active_row.buffer)


class UpdateStatus(Enum):
    Success = 0
    NoUpdatesFound = 1
    Cancelled = 2
    Error = 3
    InProgress = 4
    ProgressUnknown = 5
    Undefined = 6

    def __str__(self):
        text = "Error"
        color = "red"
        if self == UpdateStatus.Success:
            text = "Updated successfully"
            color = "green"
        elif self == UpdateStatus.NoUpdatesFound:
            text = "No updates found"
            color = "orange"
        elif self == UpdateStatus.Cancelled:
            text = "Cancelled"
        elif self in (UpdateStatus.InProgress, UpdateStatus.ProgressUnknown):
            text = "In progress"

        return f'<span foreground="{color}">' + text + '</span>'

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return self.value < other.value


class Theme(Enum):
    LIGHT = 0
    DARK = 1


class QubeName:
    def __init__(self, name, color, theme):
        self.name = name
        self.color = color
        self.theme = theme

    def __str__(self):
        return f'<span foreground="{label_color_theme(self.theme, self.color)}'\
               '"><b>' + self.name + '</b></span>'

    def __eq__(self, other):
        return self.name == other.name

    def __lt__(self, other):
        return self.name < other.name


class UpdateRowWrapper(GObject.GObject):
    def __init__(self, list_store, qube, to_update: bool, theme: Theme):
        super().__init__()
        self.list_store = list_store
        self.qube = qube
        updates_available = bool(qube.features.get('updates-available', False))
        if to_update and not updates_available:
            updates_available = None
        selected = updates_available is True
        last_updates_check = qube.features.get('last-updates-check', None)
        last_update = qube.features.get('last-update', None)
        self.buffer: str = ""
        label = QubeLabel[self.qube.label.name]
        self.theme = theme
        qube_row = [
            self,
            selected,
            get_domain_icon(qube),
            QubeName(qube.name, label.name, theme),
            UpdatesAvailable(updates_available, theme),
            Date(last_updates_check),
            Date(last_update),
            0,
            UpdateStatus.Undefined,
        ]
        self.list_store.append(qube_row)
        self.qube_row = self.list_store[-1]

    def append_text_view(self, text):
        self.buffer += text

    @property
    def selected(self):
        return self.qube_row[1]

    @selected.setter
    def selected(self, value):
        self.qube_row[1] = value

    @property
    def icon(self):
        return self.qube_row[2]

    @property
    def name(self):
        return self.qube_row[3].name

    @property
    def color_name(self):
        return self.qube_row[3]

    @property
    def updates_available(self):
        return self.qube_row[4]

    @updates_available.setter
    def updates_available(self, value):
        updates_available = bool(
            self.qube.features.get('updates-available', False))
        if value and not updates_available:
            updates_available = None
        self.qube_row[4] = UpdatesAvailable(updates_available, self.theme)

    @property
    def last_updates_check(self):
        return self.qube_row[5]

    @property
    def last_update(self):
        return self.qube_row[6]

    def get_update_progress(self):
        return self.qube_row[7]

    @property
    def status(self) -> UpdateStatus:
        return self.qube_row[8]

    def set_status(self, status_code: UpdateStatus):
        self.qube_row[8] = status_code

    def __eq__(self, other):
        self_class = QubeClass[self.qube.klass]
        other_class = QubeClass[other.qube.klass]
        if self_class == other_class:
            self_label = QubeLabel[self.qube.label.name]
            other_label = QubeLabel[other.qube.label.name]
            return self_label.value == other_label.value
        return False

    def __lt__(self, other):
        self_class = QubeClass[self.qube.klass]
        other_class = QubeClass[other.qube.klass]
        if self_class == other_class:
            self_label = QubeLabel[self.qube.label.name]
            other_label = QubeLabel[other.qube.label.name]
            return self_label.value < other_label.value
        return self_class.value < other_class.value

    def set_update_progress(self, progress):
        self.qube_row[7] = progress

    def delete(self):
        self.list_store.remove(self.qube_row.iter)


class RestartRowWrapper(GObject.GObject):
    def __init__(self, list_store, qube, to_restart: bool, theme: Theme):
        super().__init__()
        self.list_store = list_store
        self.qube = qube
        self.theme = theme
        label = QubeLabel[self.qube.label.name]
        qube_row = [
            self,
            to_restart,
            get_domain_icon(qube),
            QubeName(qube.name, label.name, theme),
            '',
        ]
        self.list_store.append(qube_row)
        self.qube_row = self.list_store[-1]

    @property
    def selected(self):
        return self.qube_row[1]

    @selected.setter
    def selected(self, value):
        self.qube_row[1] = value

    @property
    def icon(self):
        return self.qube_row[2]

    @property
    def name(self):
        return self.qube.name

    @property
    def color_name(self):
        return self.qube_row[3]

    @property
    def additional_info(self):
        return self.qube_row[4]

    @property
    def is_sys_qube(self):
        return str(self.qube.name).startswith("sys-")

    @property
    def is_excluded(self):
        return not get_boolean_feature(self.qube, 'automatic-restart', True)

    def __eq__(self, other):
        self_class = QubeClass[self.qube.klass]
        other_class = QubeClass[other.qube.klass]
        if self_class == other_class:
            self_label = QubeLabel[self.qube.label.name]
            other_label = QubeLabel[other.qube.label.name]
            return self_label.value == other_label.value
        return False

    def __lt__(self, other):
        self_class = QubeClass[self.qube.klass]
        other_class = QubeClass[other.qube.klass]
        if self_class == other_class:
            self_label = QubeLabel[self.qube.label.name]
            other_label = QubeLabel[other.qube.label.name]
            return self_label.value < other_label.value
        return self_class.value < other_class.value

    def delete(self):
        self.list_store.remove(self.qube_row.iter)


class QubeClass(Enum):
    AdminVM = 0
    TemplateVM = 1
    StandaloneVM = 2
    AppVM = 3
    DispVM = 4


class QubeLabel(Enum):
    black = 0
    purple = 1
    blue = 2
    gray = 3
    green = 4
    yellow = 5
    orange = 6
    red = 7


class HeaderCheckbox:
    NONE = 0
    SAFE = 1
    EXTENDED = 2
    ALL = 3
    SELECTED = 4

    def __init__(
            self,
            header_button,
            allowed: tuple,
            callback_all: Callable,
            callback_some: Callable,
            callback_none: Callable
    ):
        self.header_button = header_button
        self.state = HeaderCheckbox.SAFE
        self._allowed = allowed
        self.callback_all = callback_all
        self.callback_some = callback_some
        self.callback_none = callback_none

    @property
    def allowed(self):
        if self.state == HeaderCheckbox.ALL:
            return self._allowed[:]
        if self.state == HeaderCheckbox.SAFE:
            return self._allowed[:1]
        if self.state == HeaderCheckbox.EXTENDED:
            return self._allowed[:2]
        if self.state == HeaderCheckbox.NONE:
            return ()

    def set_buttons(self, *args):
        if self.state == HeaderCheckbox.ALL:
            self.header_button.set_inconsistent(False)
            self.header_button.set_active(True)
            self.callback_all(*args)
        elif self.state == HeaderCheckbox.NONE:
            self.header_button.set_inconsistent(False)
            self.header_button.set_active(False)
            self.callback_none(*args)
        else:
            self.header_button.set_inconsistent(True)
            self.callback_some(*args)

    def next_state(self):
        self.state = (self.state + 1) % 4  # SELECTED is skipped


class Date(GObject.GObject):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.date_format_source = "%Y-%m-%d %H:%M:%S"
        if len(args) == 1 and args[0] is None:
            self.datetime = datetime.min
        elif len(args) == 1 and isinstance(args[0], str):
            self.datetime = datetime.strptime(args[0], self.date_format_source)
        else:
            self.datetime = datetime(*args, *kwargs)
        self.date_format = "%Y-%m-%d"

    @classmethod
    def from_datetime(cls, datetime_: datetime):
        self = cls(1, 1, 1)
        self.datetime = datetime_
        return self

    def __str__(self):
        date_str = self.datetime.strftime(self.date_format)
        today_str = datetime.today().strftime(self.date_format)
        yesterday = datetime.today() - timedelta(days=1)
        yesterday_str = yesterday.strftime(self.date_format)
        never_str = datetime.min.strftime(self.date_format)
        if date_str == today_str:
            return "today"
        elif date_str == yesterday_str:
            return "yesterday"
        elif date_str == never_str:
            return "never"
        else:
            return date_str

    def __eq__(self, other):
        return self.datetime == other.datetime

    def __lt__(self, other):
        return self.datetime < other.datetime

def label_color_theme(theme: Theme, color: str) -> str:
    if theme == Theme.DARK and color.lower() == "black":
        return "white"
    return color

class UpdatesAvailable:
    def __init__(self, value: Union[Optional[bool], str], theme: Theme):
        super().__init__()
        if isinstance(value, str):
            if value.upper() == "NO":
                value = False
            elif value.upper() == "YES":
                value = True
            else:
                value = None

        if value is None:
            self.value = "MAYBE"
            self.order = 1
            self.color = "orange"
        elif value:
            self.value = "YES"
            self.order = 0
            self.color = "green"
        else:
            self.value = "NO"
            self.order = 2
            self.color = label_color_theme(theme, "black")

    def __str__(self):
        return f'<span foreground="{self.color}"><b>' + self.value + '</b></span>'

    def __eq__(self, other):
        return self.order == other.order

    def __lt__(self, other):
        return self.order < other.order


class CellRendererProgressWithResult(
    Gtk.CellRendererProgress
):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._status = None

    @GObject.Property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    def do_render(self, context, widget, background_area, cell_area, flags):
        status: UpdateStatus = self.get_property('status')
        if status == UpdateStatus.Success:
            self.draw_icon('qubes-check-yes', context, cell_area)
        elif status == UpdateStatus.NoUpdatesFound:
            self.draw_icon('qubes-check-maybe', context, cell_area)
            self.set_property('text', "    (no updates found)")
            self.set_property("pulse", -1)
            self.set_property("value", 0)
            Gtk.CellRendererProgress.do_render(
                self, context, widget, background_area, cell_area, flags)
        elif status in (UpdateStatus.Error, UpdateStatus.Cancelled):
            self.draw_icon('qubes-delete-x', context, cell_area)
        elif status == UpdateStatus.ProgressUnknown:
            Gtk.CellRendererProgress.do_render(
                self, context, widget, background_area, cell_area, flags)
        else:
            self.set_property("pulse", -1)
            Gtk.CellRendererProgress.do_render(
                self, context, widget, background_area, cell_area, flags)

    def draw_icon(self, icon_name: str, context, cell_area):
        pixbuf = load_icon_at_gtk_size(icon_name, Gtk.IconSize.SMALL_TOOLBAR)
        Gdk.cairo_set_source_pixbuf(
            context,
            pixbuf,
            cell_area.x + self.props.xpad,
            cell_area.y + self.props.ypad
        )
        context.paint()


GObject.type_register(CellRendererProgressWithResult)


def sort_func(model, iter1, iter2, data):
    # Get the values at the two iter indices
    value1 = model[iter1][data]
    value2 = model[iter2][data]

    # Compare the values and return -1, 0, or 1
    if value1 < value2:
        return -1
    elif value1 == value2:
        return 0
    else:
        return 1


def get_domain_icon(vm):
    icon_vm = Gtk.IconTheme.get_default().load_icon(vm.label.icon, 16, 0)
    return icon_vm


def shutdown_domains(to_shutdown):
    """
    Try to shut down vms and wait to finish.
    """
    wait_for = []
    for vm in to_shutdown:
        try:
            vm.shutdown(force=True)
            wait_for.append(vm)
        except exc.QubesVMError:
            pass

    asyncio.run(wait_for_domain_shutdown(wait_for))

    return wait_for


def restart_vms(to_restart):
    """
    Try to restart vms.
    """
    shutdowns = shutdown_domains(to_restart)

    # restart shutdown qubes
    for vm in shutdowns:
        try:
            vm.start()
        except exc.QubesVMError:
            pass


def main():
    qapp = Qubes()
    app = QubesUpdater(qapp)
    app.run()


if __name__ == '__main__':
    main()
