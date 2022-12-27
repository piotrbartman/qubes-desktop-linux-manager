#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error

import re
import time
import threading
import subprocess
from datetime import datetime, timedelta
from enum import Enum
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


class Settings:
    def __init__(self, builder):
        self.builder = builder
        self.settings_window = self.builder.get_object("settings_window")
        self.settings_window.connect("delete-event", self.close_window)
        self.cancel_button = self.builder.get_object("button_settings_cancel")
        self.cancel_button.connect(
            "clicked", lambda _: self.settings_window.close())
        self.save_button = self.builder.get_object("button_settings_save")
        self.save_button.connect(
            "clicked", lambda _: self.settings_window.close())

    def show(self):
        self.settings_window.show_all()

    def close_window(self, _emitter, _):
        self.settings_window.hide()
        return True


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
        self.settings = Settings(self.builder)

        self.vm_list = self.builder.get_object("vm_list")

        checkbox_column = self.builder.get_object("checkbox_column")
        header_button = checkbox_column.get_button()

        def pass_through_event_window(button):
            if not isinstance(button, Gtk.Button):
                raise TypeError("%r is not a gtk.Button" % button)
            event_window = button.get_event_window()
            event_window.set_pass_through(True)

        header_button.connect('realize', pass_through_event_window)

        self.block = False
        self.checkbox_column_header = Select.WITH_UPDATES
        self.checkbox_column_button = self.builder.get_object("checkbox_header")
        self.checkbox_column_button.set_inconsistent(True)
        self.checkbox_column_button.connect("toggled", self.on_header_toggled)

        # Connect the cell renderer's "toggled" signal to a callback function
        toggle_renderer = self.builder.get_object("toggle_renderer")
        toggle_renderer.connect("toggled", self.on_checkbox_toggled)

        headers = [(3, "available"),
                   (4, "check"), (5, "update")]

        def cell_data_func(column, cell, model, it, data):
            # Get the object from the model
            obj = model.get_value(it, data)
            # Set the cell value to the name of the object
            cell.set_property("text", str(obj))

        for col, name in headers:
            renderer = self.builder.get_object(name + "_renderer")
            column = self.builder.get_object(name + "_column")
            column.set_cell_data_func(renderer, cell_data_func, col)
            renderer.props.xalign = 0.5

        self.populate_vm_list()

        self.restart = self.builder.get_object("restart")

        self.button_settings = self.builder.get_object("button_settings")
        self.button_settings.connect("clicked", self.open_settings_window)

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

    def on_checkbox_toggled(self, _emitter, path):
        self.block = True
        if path is not None:
            it = self.list_store.get_iter(path)
            self.list_store[it][0] = not self.list_store[it][0]
            selected = 0
            for vm_row in self.list_store:
                if vm_row[0]:
                    selected += 1
            if selected == len(self.list_store):
                self.checkbox_column_header = Select.ALL
                self.checkbox_column_button.set_inconsistent(False)
                self.checkbox_column_button.set_active(True)
                self.next_button.set_sensitive(True)
            elif selected == 0:
                self.checkbox_column_header = Select.NONE
                self.checkbox_column_button.set_inconsistent(False)
                self.checkbox_column_button.set_active(False)
                self.next_button.set_sensitive(False)
            else:
                self.checkbox_column_header = Select.SELECTED
                self.checkbox_column_button.set_inconsistent(True)
                self.next_button.set_sensitive(True)
        self.block = False

    def on_header_toggled(self, _emitter):
        if self.block:
            return
        self.block = True
        self.checkbox_column_header = self.checkbox_column_header.next()
        if self.checkbox_column_header == Select.ALL:
            self.checkbox_column_button.set_inconsistent(False)
            self.checkbox_column_button.set_active(True)
            self.next_button.set_sensitive(True)
            allowed = ("YES", "MAYBE", "NO")
        elif self.checkbox_column_header == Select.WITH_MAYBE_UPDATES:
            self.checkbox_column_button.set_inconsistent(True)
            self.next_button.set_sensitive(True)
            allowed = ("YES", "MAYBE")
        elif self.checkbox_column_header == Select.WITH_UPDATES:
            self.checkbox_column_button.set_inconsistent(True)
            self.next_button.set_sensitive(True)
            allowed = ("YES",)
        else:
            self.checkbox_column_button.set_inconsistent(False)
            self.checkbox_column_button.set_active(False)
            self.next_button.set_sensitive(False)
            allowed = ()
        for row in self.list_store:
            if row[3].value in allowed:
                row[0] = True
            else:
                row[0] = False
        self.block = False

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
        self.list_store.set_sort_func(3, sort_func, 3)
        self.list_store.set_sort_func(4, sort_func, 4)
        self.list_store.set_sort_func(5, sort_func, 5)
        self.list_store.set_sort_func(6, sort_func, 6)
        for vm in self.qapp.domains:
            if vm.klass == 'AdminVM':
                try:
                    state = bool(vm.features.get('updates-available', False))
                except exc.QubesDaemonCommunicationError:
                    state = False
                result = result or state
                qube_info = QubeUpdateRow(vm, state)
                self.list_store.append(qube_info.qube_row)

                # TODO
                devel_deb = self.qapp.domains['devel-debian']
                qube_info = QubeUpdateRow(devel_deb, True)
                self.list_store.append(qube_info.qube_row)
                # END TODO

        output = subprocess.check_output(
            ['qubes-vm-update', '--dry-run', '--update-if-stale', f'{7}'])

        to_update = [vm_name.strip() for vm_name
                     in output.decode().split("\n")[0].split(":")[1].split(",")]

        for vm in self.qapp.domains:
            if getattr(vm, 'updateable', False) and vm.klass != 'AdminVM':
                qube_info = QubeUpdateRow(vm, bool(vm.name in to_update))
                self.list_store.append(qube_info.qube_row)

        return result

    def next_clicked(self, _emitter):
        if self.stack.get_visible_child() == self.list_page:
            self.stack.set_visible_child(self.progress_page)

            for row in self.list_store:
                if row[0]:
                    self.progress_listview.add(ProgressListBoxRow(row[-1].qube))

            self.progress_listview.show_all()

            # self.next_button.set_sensitive(False)
            # self.next_button.set_label(_("_Finish"))

            # pylint: disable=attribute-defined-outside-init
            # self.update_thread = threading.Thread(target=self.perform_update)
            # self.update_thread.start()

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


class QubeUpdateRow(GObject.GObject):
    def __init__(self, qube, to_update: bool):
        super().__init__()
        self.qube = qube
        updates_available = bool(qube.features.get('updates-available', False))
        if to_update and not updates_available:
            updates_available = None
        selected = updates_available is True
        last_updates_check = qube.features.get('last-updates-check', None)
        last_update = qube.features.get('last-update', None)
        self.qube_row = [
            selected,
            get_domain_icon(qube),
            qube.name,
            UpdatesAvailable(updates_available),
            Date(last_updates_check),
            Date(last_update),
            self
        ]

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


class Select(Enum):
    NONE = 0
    WITH_UPDATES = 1
    WITH_MAYBE_UPDATES = 2
    ALL = 3
    SELECTED = 4

    def next(self):
        new_value = (self.value + 1) % 4
        return Select(new_value)


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


class UpdatesAvailable(GObject.GObject):
    def __init__(self, value: Union[Optional[bool], str]):
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
        elif value:
            self.value = "YES"
            self.order = 0
        else:
            self.value = "NO"
            self.order = 2

    def __str__(self):
        return self.value

    def __eq__(self, other):
        return self.order == other.order

    def __lt__(self, other):
        return self.order < other.order


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
        self.icon = Gtk.Image.new_from_pixbuf(
            get_domain_icon(self.vm))

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

        self.icon = Gtk.Image.new_from_pixbuf(
            get_domain_icon(self.vm))
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
