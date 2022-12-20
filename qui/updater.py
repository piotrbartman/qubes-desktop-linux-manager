#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error

import re
import time
import threading
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Union

import pkg_resources
import gi  # isort:skip
gi.require_version('Gtk', '3.0')  # isort:skip
from gi.repository import Gtk, Gdk, GObject, Gio, GLib, GdkPixbuf  # isort:skip
from qubesadmin import Qubes
from qubesadmin import exc

# using locale.gettext is necessary for Gtk.Builder translation support to work
# in most cases gettext is better, but it cannot handle Gtk.Builder/glade files
import locale
from locale import gettext as _
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

    def perform_setup(self, *_args, **_kwargs):
        # pylint: disable=attribute-defined-outside-init
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain("desktop-linux-manager")
        self.builder.add_from_file(pkg_resources.resource_filename(
            __name__, 'updater.glade'))

        self.main_window = self.builder.get_object("main_window")

        self.vm_list = self.builder.get_object("vm_list")

        # Create a cell renderer for the checkboxes
        cellrenderer0 = Gtk.CellRendererToggle()

        # Create some columns for the tree view
        self.column0 = Gtk.TreeViewColumn("[]", cellrenderer0, active=0)

        # Connect the cell renderer's "toggled" signal to a callback function
        cellrenderer0.connect("toggled", self.on_checkbox_toggled)
        self.vm_list.append_column(self.column0)

        column1 = Gtk.TreeViewColumn(
            "", Gtk.CellRendererPixbuf(), pixbuf=1
        )
        self.vm_list.append_column(column1)

        headers = [(2, "Qube name", 2), (3, "Updates available", 3),
                   (5, "Last checked", 5), (6, "Last updated", 6)]

        def cell_data_func(column, cell, model, it, data):
            title = column.get_properties("title")
            if title[0] == "Updates available":  # TODO
                col = 3
                obj = model.get_value(it, col)
                cell.set_property("text", obj.value)
                cell.set_property("foreground", "red")
                return
            else:
                col = 5
            # Get the object from the model
            obj = model.get_value(it, col)
            date_format = "%Y-%m-%d"
            date_str = obj.strftime(date_format)
            today_str = datetime.today().strftime(date_format)
            yesterday = datetime.today() - timedelta(days=1)
            yesterday_str = yesterday.strftime(date_format)
            if date_str == today_str:
                date_repr = "today"
            elif date_str == yesterday_str:
                date_repr = "yesterday"
            else:
                date_repr = date_str
            # Set the cell value to the name of the object
            cell.set_property("text", date_repr)

        for col, header, sort_col in headers:
            renderer = Gtk.CellRendererText()
            if col in (3, 5):
                column = Gtk.TreeViewColumn(header, renderer)
                column.set_cell_data_func(renderer, cell_data_func)
            else:
                column = Gtk.TreeViewColumn(header, renderer, text=col)
            if col > 2:
                # center column content
                renderer.props.xalign = 0.5
                # center column header
                column.set_alignment(0.5)

            self.vm_list.append_column(column)
            column.set_sort_column_id(sort_col)

        self.updates_available = self.populate_vm_list()

        self.no_updates_available_label = \
            self.builder.get_object("no_updates_available")
        self.no_updates_available_label.set_visible(not self.updates_available)

        self.allow_update_unavailable_check = \
            self.builder.get_object("allow_update_unavailable")
        self.allow_update_unavailable_check.connect("clicked",
                                                    self.set_update_available)

        self.next_button = self.builder.get_object("button_next")
        self.next_button.connect("clicked", self.next_clicked)

        self.cancel_button = self.builder.get_object("button_cancel")
        self.cancel_button.connect("clicked", self.cancel_updates)
        self.main_window.connect("delete-event", self.window_close)
        self.main_window.connect("key-press-event", self.check_escape)

        self.stack = self.builder.get_object("main_stack")
        self.list_page = self.builder.get_object("list_page")
        self.progress_page = self.builder.get_object("progress_page")
        self.finish_page = self.builder.get_object("finish_page")
        self.progress_textview = self.builder.get_object("progress_textview")
        self.progress_scrolled_window = self.builder.get_object(
            "progress_scrolled_window")
        self.progress_listview = self.builder.get_object("progress_listview")

        self.details_visible = True
        self.details_icon = self.builder.get_object("details_icon")
        self.builder.get_object("details_icon_events").connect(
            "button-press-event", self.toggle_details)
        self.builder.get_object("details_label").connect(
            "clicked", self.toggle_details)

        self.load_css()

        self.main_window.show_all()
        self.toggle_details()

        self.update_thread = None
        self.exit_triggered = False

    def on_checkbox_toggled(self, widget, path):
        if path is not None:
            it = self.list_store.get_iter(path)
            self.list_store[it][0] = not self.list_store[it][0]

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
        self.list_store = Gtk.ListStore(
            bool, GdkPixbuf.Pixbuf, str, object, int, object, str)  # TODO rename
        def sort_func(model, iter1, iter2, data):
            # Get the values at the two iter indices
            value1 = model[iter1][5]
            value2 = model[iter2][5]

            # Compare the values and return -1, 0, or 1
            if value1 < value2:
                return -1
            elif value1 == value2:
                return 0
            else:
                return 1
        self.list_store.set_sort_func(5, sort_func)
        def sort_func(model, iter1, iter2, data):
            # Get the values at the two iter indices
            value1 = model[iter1][3]
            value2 = model[iter2][3]

            # Compare the values and return -1, 0, or 1
            if value1 < value2:
                return -1
            elif value1 == value2:
                return 0
            else:
                return 1
        self.list_store.set_sort_func(3, sort_func)
        for vm in self.qapp.domains:
            if vm.klass == 'AdminVM':
                try:
                    state = vm.features.get('updates-available', False)
                except exc.QubesDaemonCommunicationError:
                    state = False
                result = result or state
                self.list_store.append([False, get_domain_icon(vm), vm.name, UpdatesAvailable(True), UpdatesAvailable(True).order, datetime(2020, 1, 1), "02.02.2022"])
                devel_deb = self.qapp.domains['devel-debian']
                self.list_store.append([False, get_domain_icon(devel_deb), devel_deb.name, UpdatesAvailable(None), UpdatesAvailable(None).order, datetime.today() - timedelta(days=1), "yesterday"])
                self.list_store.append([False, get_domain_icon(vm), "zzz", UpdatesAvailable(False), UpdatesAvailable(False).order, datetime.today(), "today"])

        # output = subprocess.check_output(
        #     ['qubes-vm-update', '--dry-run', '--n', f'{7}'])
        #
        # to_update = [vm_name.strip() for vm_name
        #              in output.decode().split("\n")[0].split(":")[1].split(",")]
        #
        # for vm in self.qapp.domains:
        #     if getattr(vm, 'updateable', False) and vm.klass != 'AdminVM':
        #         state = vm.name in to_update
        #         vmrow = VMListBoxRow(vm, state)
        #         self.vm_list.add(vmrow)
        #         vmrow.checkbox.connect('toggled', self.checkbox_checked)
        #
        # # TODO
        # devel_deb = self.qapp.domains['devel-debian']
        # vmrow = VMListBoxRow(devel_deb, True)
        # self.vm_list.add(vmrow)
        # vmrow.checkbox.connect('toggled', self.checkbox_checked)
        # devel_fed = self.qapp.domains['devel-fedora']
        # vmrow = VMListBoxRow(devel_fed, True)
        # self.vm_list.add(vmrow)
        # vmrow.checkbox.connect('toggled', self.checkbox_checked)
        # # END TODO

        # self.vm_list.connect("row-activated", self.toggle_row_selection)

        self.vm_list.set_model(self.list_store)
        return result

    def checkbox_checked(self, _emitter, *_args):
        for vm_row in self.vm_list:
            if vm_row.checkbox.get_active():
                self.next_button.set_sensitive(True)
                return
            self.next_button.set_sensitive(False)

    @staticmethod
    def toggle_row_selection(_emitter, row):
        if row:
            row.checkbox.set_active(not row.checkbox.get_active())
            row.set_label_text()

    def set_update_available(self, _emitter):
        for vm_row in self.vm_list:
            if not vm_row.updates_available:
                vm_row.set_sensitive(
                    self.allow_update_unavailable_check.get_active())
                if not vm_row.get_sensitive():
                    vm_row.checkbox.set_active(False)

    def next_clicked(self, _emitter):
        if self.stack.get_visible_child() == self.list_page:
            self.stack.set_visible_child(self.progress_page)

            for row in self.vm_list:
                if row.checkbox.get_active():
                    self.progress_listview.add(ProgressListBoxRow(row.vm))

            self.progress_listview.show_all()

            self.next_button.set_sensitive(False)
            self.next_button.set_label(_("_Finish"))

            # pylint: disable=attribute-defined-outside-init
            self.update_thread = threading.Thread(target=self.perform_update)
            self.update_thread.start()

        elif self.stack.get_visible_child() == self.progress_page:
            self.cancel_updates()
            return

    def toggle_details(self, *_args, **_kwargs):
        # pylint: disable=attribute-defined-outside-init
        self.details_visible = not self.details_visible
        self.progress_textview.set_visible(self.details_visible)

        if self.details_visible:
            self.progress_textview.show()
            self.progress_scrolled_window.show()
        else:
            self.progress_textview.hide()
            self.progress_scrolled_window.hide()

        if self.details_visible:
            self.details_icon.set_from_icon_name("pan-down-symbolic",
                                                 Gtk.IconSize.BUTTON)
        else:
            self.details_icon.set_from_icon_name("pan-end-symbolic",
                                                 Gtk.IconSize.BUTTON)

    def append_text_view(self, text):
        buffer = self.progress_textview.get_buffer()
        buffer.insert(buffer.get_end_iter(), text + '\n')

    def perform_update(self):
        admin = [row for row in self.progress_listview
                 if row.vm.klass == 'AdminVM']
        templs = [row for row in self.progress_listview
                  if row.vm.klass != 'AdminVM']

        if admin:
            if self.exit_triggered:
                GObject.idle_add(admin[0].set_status, 'failure')
                GObject.idle_add(
                    self.append_text_view,
                    _("Canceled update for {}\n").format(admin[0].vm.name))

            try:
                output = subprocess.check_output(
                    ['sudo', 'qubesctl', '--dom0-only', '--no-color',
                     'pkg.upgrade', 'refresh=True'],
                    stderr=subprocess.STDOUT).decode()
                ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
                output = ansi_escape.sub('', output)

                GObject.idle_add(self.append_text_view, output)
                GObject.idle_add(admin[0].set_status, 'success')
            except subprocess.CalledProcessError as ex:
                GObject.idle_add(
                    self.append_text_view,
                    _("Error on updating {}: {}\n{}").format(
                        admin[0].vm.name, str(ex), ex.output.decode()))
                GObject.idle_add(admin[0].set_status, 'failure')

        if templs:
            if self.exit_triggered:
                for row in templs:
                    GObject.idle_add(row.set_status, 'failure')
                    GObject.idle_add(
                        self.append_text_view,
                        _("Canceled update for {}\n").format(row.vm.name))

            for row in templs:
                GObject.idle_add(
                    self.append_text_view,
                    _("Updating {}\n").format(row.vm.name))
                GObject.idle_add(row.set_status, 'in-progress')

            try:
                targets = ",".join((row.vm.name for row in templs))
                rows = {row.vm.name: row for row in templs}
                proc = subprocess.Popen(
                    ['sudo', 'qubes-vm-update', '--show-output',
                     '--just-print-progress', '--targets', targets],
                    stderr=subprocess.PIPE, stdout=subprocess.PIPE)

                for untrusted_line in iter(proc.stderr.readline, ''):
                    if untrusted_line:
                        line = untrusted_line.decode().rstrip()
                        try:
                            name, prog = line.split()
                            progress = float(prog)
                        except ValueError:
                            continue

                        if progress == 100.:
                            GObject.idle_add(rows[name].set_status, 'success')

                        GObject.idle_add(rows[name].update, progress)
                    else:
                        break
                proc.stderr.close()

                stdout = b''
                for untrusted_line in iter(proc.stdout.readline, ''):
                    if untrusted_line:
                        stdout += untrusted_line
                    else:
                        break
                proc.stdout.close()

                proc.wait()
                output = stdout.decode()

                GObject.idle_add(self.append_text_view, output)

            except subprocess.CalledProcessError as ex:
                for row in templs:
                    GObject.idle_add(
                        self.append_text_view,
                        _("Error on updating {}: {}\n{}").format(
                            row.vm.name, str(ex), ex.output.decode()))
                    GObject.idle_add(row.set_status, 'failure')

        GObject.idle_add(self.next_button.set_sensitive, True)
        GObject.idle_add(self.cancel_button.set_visible, False)

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


class UpdatesAvailable:
    def __init__(self, value: Union[Optional[bool], str]):
        if isinstance(value, str):
            if value.upper() == "No":
                value = False
            elif value.upper() == "YES":
                value = True
            else:
                value = None

        if value is None:
            self.value = "MAYBE"
            self.order = 1
        elif value:
            self.value = "YES"
            self.order = 0
        else:
            self.value = "NO"
            self.order = 2

    def __eq__(self, other):
        return self.order == other.order

    def __ne__(self, other):
        return self.order != other.order

    def __lt__(self, other):
        return self.order < other.order

    def __le__(self, other):
        return self.order <= other.order

    def __gt__(self, other):
        return self.order > other.order

    def __ge__(self, other):
        return self.order >= other.order



def get_domain_icon(vm):
    icon_vm = Gtk.IconTheme.get_default().load_icon(vm.label.icon, 16, 0)
    return icon_vm


class VMListBoxRow(Gtk.ListBoxRow):
    def __init__(self, vm, updates_available, **properties):
        super().__init__(**properties)
        self.vm = vm

        hbox = Gtk.HBox(orientation=Gtk.Orientation.HORIZONTAL)

        self.label_text = vm.name
        self.updates_available = updates_available
        if self.updates_available:
            self.label_text = _("{vm} (updates available)").format(
                vm=self.label_text)
        self.label = Gtk.Label()
        self.icon = get_domain_icon(self.vm)

        self.checkbox = Gtk.CheckButton()
        self.checkbox.set_active(self.updates_available)
        self.checkbox.set_margin_right(10)

        self.checkbox.connect("clicked", self.set_label_text)
        self.set_sensitive(self.updates_available)

        self.set_label_text()

        hbox.pack_start(self.checkbox, False, False, 0)
        hbox.pack_start(self.icon, False, False, 0)
        hbox.pack_start(self.label, False, False, 0)

        # check for VMs that may be restored from older Qubes versions
        # and not support updating; this is a heuristic and may not always work
        try:
            if vm.features.get('qrexec', False) and \
                    vm.features.get('gui', False) and \
                    not vm.features.get('os', False):
                warn_icon = Gtk.Image.new_from_pixbuf(
                    Gtk.IconTheme.get_default().load_icon(
                        'dialog-warning', 12, 0))
                warn_icon.set_tooltip_text(_(
                    'This qube may have been restored from an older version of '
                    'Qubes OS and may not be able to update itself correctly. '
                    'Please check the documentation if problems occur.'))
                hbox.pack_start(warn_icon, False, False, 0)
        except exc.QubesDaemonCommunicationError:
            # we have no permission to access the vm's features, there's no
            # point in guessing original Qubes version
            pass

        self.add(hbox)

    def set_label_text(self, _=None):
        if self.checkbox.get_active():
            self.label.set_markup(f"<b>{self.label_text}</b>")
        else:
            self.label.set_markup(self.label_text)


class ProgressListBoxRow(Gtk.ListBoxRow):
    def __init__(self, vm):
        super().__init__()

        self.vm = vm

        hbox = Gtk.HBox(orientation=Gtk.Orientation.HORIZONTAL)

        self.icon = get_domain_icon(self.vm)
        self.icon.set_margin_right(10)

        self.label = Gtk.Label(vm.name)
        self.label.set_margin_right(10)

        self.progress_box = Gtk.HBox(orientation=Gtk.Orientation.HORIZONTAL)
        self.prog = None

        hbox.pack_start(self.icon, False, False, 0)
        hbox.pack_start(self.label, False, False, 0)
        hbox.pack_start(self.progress_box, False, False, 0)

        self.set_status('not-started')
        self.add(hbox)

    def set_status(self, status):

        if status == 'not-started':
            widget = Gtk.ProgressBar()
            self.prog = widget
        elif status == 'in-progress':
            self.prog.set_fraction(0)
            widget = self.prog
        elif status == 'success':
            widget = Gtk.Image.new_from_icon_name("gtk-apply",
                                                  Gtk.IconSize.BUTTON)
        elif status == 'failure':
            widget = Gtk.Image.new_from_icon_name("gtk-cancel",
                                                  Gtk.IconSize.BUTTON)
        else:
            raise ValueError(_("Unknown status {}").format(status))

        for child in self.progress_box.get_children():
            self.progress_box.remove(child)
        self.progress_box.pack_start(widget, False, False, 0)
        widget.show()

    def update(self, progress):
        if self.prog is not None:
            self.prog.set_fraction(progress/100)


def main():
    qapp = Qubes()
    app = QubesUpdater(qapp)
    app.run()


if __name__ == '__main__':
    main()
