# coding=utf-8
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2023  Piotr Bartman <prbartman@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
import re
import selectors
import subprocess
import threading
import time
from gi.repository import Gtk, Gdk, GObject
from locale import gettext as _

from qubes_config.widgets.gtk_utils import copy_to_global_clipboard, \
    load_icon_at_gtk_size
from qubes_config.widgets.utils import get_feature
from qui.updater.utils import UpdateStatus

from locale import gettext as l


class ProgressPage:

    def __init__(
            self,
            builder,
            theme,
            header_label,
            next_button,
            cancel_button
    ):
        self.builder = builder
        self.theme = theme
        self.header_label = header_label
        self.next_button = next_button
        self.cancel_button = cancel_button
        self.vms_to_update = None
        self.exit_triggered = False
        self.update_thread = None

        self.update_details = QubeUpdateDetails(self.builder)

        self.stack = self.builder.get_object("main_stack")
        self.page = self.builder.get_object("progress_page")
        self.progressbar = self.builder.get_object("progressbar")
        progress_store = self.progressbar.get_model()
        progress_store.append([0])
        self.total_progress = progress_store[-1]
        self.progressbar_renderer = self.builder.get_object(
            "progressbar_renderer")
        self.progressbar_renderer.set_fixed_size(-1, 26)

        self.stack = self.builder.get_object("main_stack")

        self.progress_list = self.builder.get_object("progress_list")
        self.progress_list.connect("row-activated", self.row_selected)
        progress_column = self.builder.get_object("progress_column")
        renderer = CellRendererProgressWithResult()
        renderer.props.ypad = 10
        progress_column.pack_start(renderer, True)
        progress_column.add_attribute(renderer, "pulse", 7)
        progress_column.add_attribute(renderer, "value", 7)
        progress_column.add_attribute(renderer, "status", 8)

    def init_update(self, vms_to_update, settings):
        """Starts `perform_update` in new thread."""
        self.vms_to_update = vms_to_update
        self.progress_list.set_model(vms_to_update.list_store_raw)
        self.next_button.set_sensitive(False)
        self.cancel_button.set_sensitive(True)
        self.cancel_button.set_label(l("_Cancel updates"))
        self.cancel_button.show()

        self.header_label.set_text(l("Update in progress..."))
        self.header_label.set_halign(Gtk.Align.CENTER)

        # pylint: disable=attribute-defined-outside-init
        self.update_thread = threading.Thread(
            target=self.perform_update,
            args=(settings,)
        )
        self.update_thread.start()

    def perform_update(self, settings):
        """Updates dom0 and then other vms."""
        admins = [row for row in self.vms_to_update
                  if row.vm.klass == 'AdminVM']
        templs = [row for row in self.vms_to_update
                  if row.vm.klass != 'AdminVM']

        if admins:
            self.update_admin_vm(admins)

        if templs:
            self.update_templates(templs, settings)

        GObject.idle_add(self.next_button.set_sensitive, True)
        GObject.idle_add(self.header_label.set_text, _("Update finished"))
        GObject.idle_add(self.cancel_button.set_visible, False)

    @property
    def is_visible(self):
        """Returns True if page is shown by stack."""
        return self.stack.get_visible_child() == self.page

    def update_templates(self, templs, settings):
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
            self.do_update_templates(templs, settings)
        except subprocess.CalledProcessError as ex:
            for row in templs:
                GObject.idle_add(
                    row.append_text_view,
                    _("Error on updating {}: {}\n{}").format(
                        row.name, str(ex), ex.output.decode()))
                GObject.idle_add(row.set_status, UpdateStatus.Error)
            self.update_details.update_buffer()

    def do_update_templates(self, templs, settings):
        targets = ",".join((row.name for row in templs))
        rows = {row.name: row for row in templs}

        args = []
        if settings.max_concurrency is not None:
            args.extend(
                ('--max-concurrency',
                 str(settings.max_concurrency)))
        proc = subprocess.Popen(
            ['qubes-vm-update',
             '--show-output',
             '--just-print-progress',
             *args,
             '--targets', targets],
            stderr=subprocess.PIPE, stdout=subprocess.PIPE)

        thread = threading.Thread(target=self.read_stdouts, args=(proc, rows))
        thread.start()

        self.read_stderrs(proc, rows)
        # self.read_stdouts(proc, rows)

        thread.join()
        proc.wait()

        self.set_statuses(rows)

        GObject.idle_add(self.set_total_progress, 100)

    def read_stderrs(self, proc, rows):
        for untrusted_line in iter(proc.stderr.readline, ''):
            if untrusted_line:
                self.handle_err_line(untrusted_line, rows)
            else:
                break
        proc.stderr.close()

    def read_stdouts(self, proc, rows):
        self.curr_name_out = ""
        for untrusted_line in iter(proc.stdout.readline, ''):
            if untrusted_line:
                self.handle_out_line(untrusted_line, rows)
            else:
                break
        self.update_details.update_buffer()
        proc.stdout.close()

    @staticmethod
    def set_statuses(rows):
        for row in rows.values():
            progress = row.get_update_progress()
            if progress == 100.:
                if get_feature(row.vm, "last-updates-check") \
                        == get_feature(row.vm, "last-update"):
                    GObject.idle_add(
                        row.set_status, UpdateStatus.Success)
                else:
                    GObject.idle_add(
                        row.set_status,
                        UpdateStatus.NoUpdatesFound
                    )
            else:
                GObject.idle_add(row.set_status, UpdateStatus.Error)

    def update_admin_vm(self, admins):
        """Run command to update dom0."""
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

        self.update_details.update_buffer()

        try:
            with Ticker(admin):
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

        self.update_details.update_buffer()

    def handle_err_line(self, untrusted_line, rows):
        line = untrusted_line.decode().rstrip()
        try:
            name, prog = line.split()
            progress = int(float(prog))
        except ValueError:
            return

        GObject.idle_add(
            rows[name].set_update_progress, progress)
        total_progress = sum(
            row.get_update_progress()
            for row in rows.values()) / len(rows)

        GObject.idle_add(
            self.set_total_progress, total_progress)

    def handle_out_line(self, untrusted_line, rows):
        line = untrusted_line.decode()
        maybe_name, text = line.split(' ', 1)
        if maybe_name[:-1] in rows.keys():
            self.curr_name_out = maybe_name[:-1]
        GObject.idle_add(
            rows[self.curr_name_out].append_text_view, text)

    def set_total_progress(self, progress):
        """Set the value of main big progressbar."""
        self.total_progress[0] = progress

    def back_by_row_selection(self, _emitter, path, *args):
        """Show this page and select row selected on summary page."""
        self.show()
        self.row_selected(_emitter, path, *args)

    def show(self):
        """Show this page and handle buttons."""
        self.update_details.set_active_row(None)
        self.stack.set_visible_child(self.page)

        self.next_button.set_label(_("_Next"))
        self.cancel_button.hide()

    def row_selected(self, _emitter, path, _col):
        """Handle clicking on a row to show more info.

        Set updated details (name of vm and textview)."""
        self.update_details.set_active_row(
            self.vms_to_update[path.get_indices()[0]])

    def get_update_summary(self):
        """Returns update summary.

        It is a triple of:
        1. number of updated vms,
        2. number of vms that tried to update but no update was found,
        3. vms that update was canceled before starting.
        """
        vm_updated_num = len(
            [row for row in self.vms_to_update
             if row.status == UpdateStatus.Success])
        vm_no_updates_num = len(
            [row for row in self.vms_to_update
             if row.status == UpdateStatus.NoUpdatesFound])
        vm_failed_num = len(
            [row for row in self.vms_to_update
             if row.status in (UpdateStatus.Error, UpdateStatus.Cancelled)])
        return vm_updated_num, vm_no_updates_num, vm_failed_num


class Ticker:
    """Helper for dom0 progressbar."""
    def __init__(self, *args):
        self.ticker_done = False
        self.args = args

    def __enter__(self):
        thread = threading.Thread(target=self.tick, args=self.args)
        thread.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.ticker_done = True

    def tick(self, row):
        while not self.ticker_done:
            new_value = (row.get_update_progress()) % 96 + 1
            row.set_update_progress(new_value)
            time.sleep(1 / 12)


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


class CellRendererProgressWithResult(
    Gtk.CellRendererProgress
):
    """
    Custom Cell Renderer to show progressbar or finish icon.
    """
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


GObject.type_register(CellRendererProgressWithResult)  # TODO
