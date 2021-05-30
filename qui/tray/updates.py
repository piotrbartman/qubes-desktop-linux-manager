#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error
''' A widget that monitors update availability and notifies the user
 about new updates to templates and standalone VMs'''
import asyncio
import sys
import traceback
import subprocess

import qubesadmin
import qubesadmin.events
from qubesadmin import exc

import gi  # isort:skip
gi.require_version('Gtk', '3.0')  # isort:skip
from gi.repository import Gtk, Gio  # isort:skip

import gbulb
gbulb.install()

import gettext
t = gettext.translation("desktop-linux-manager", fallback=True)
_ = t.gettext


class UpdatesTray(Gtk.Application):
    def __init__(self, app_name, qapp, dispatcher):
        super().__init__()
        self.name = app_name

        self.dispatcher = dispatcher
        self.qapp = qapp

        self.set_application_id(self.name)
        self.register()  # register Gtk Application

        self.widget_icon = Gtk.StatusIcon()
        self.widget_icon.set_from_icon_name('software-update-available')
        self.widget_icon.set_visible(False)
        self.widget_icon.connect('button-press-event', self.show_menu)
        self.widget_icon.set_tooltip_markup(_(
            '<b>Qubes Update</b>\nUpdates are available.'))

        self.vms_needing_update = set()

        self.tray_menu = Gtk.Menu()

    def run(self):  # pylint: disable=arguments-differ
        self.check_vms_needing_update()
        self.connect_events()

        self.update_indicator_state()

    def setup_menu(self):
        title_label = Gtk.Label(xalign=0)
        title_label.set_markup(_("<b>Qube Updates Available</b>"))
        title_menu_item = Gtk.MenuItem()
        title_menu_item.add(title_label)
        title_menu_item.set_sensitive(False)

        subtitle_label = Gtk.Label(xalign=0)
        subtitle_label.set_markup(
            _("<i>Updates available for {} qubes</i>").format(
                len(self.vms_needing_update)))
        subtitle_menu_item = Gtk.MenuItem()
        subtitle_menu_item.set_margin_left(10)
        subtitle_menu_item.add(subtitle_label)
        subtitle_menu_item.set_sensitive(False)

        run_label = Gtk.Label(xalign=0)
        run_label.set_text(_("Launch updater"))
        run_menu_item = Gtk.MenuItem()
        run_menu_item.set_margin_left(10)
        run_menu_item.add(run_label)
        run_menu_item.connect('activate', self.launch_updater)

        self.tray_menu.append(title_menu_item)
        self.tray_menu.append(subtitle_menu_item)
        self.tray_menu.append(run_menu_item)

        self.tray_menu.show_all()

    def show_menu(self, _unused, _event):
        self.tray_menu = Gtk.Menu()

        self.setup_menu()

        self.tray_menu.popup_at_pointer(None)  # use current event

    @staticmethod
    def launch_updater(*_args, **_kwargs):
        subprocess.Popen(['qubes-update-gui'])

    def check_vms_needing_update(self):
        self.vms_needing_update.clear()
        for vm in self.qapp.domains:
            try:
                updates_available = vm.features.get('updates-available', False)
            except exc.QubesDaemonCommunicationError:
                updates_available = False
            if updates_available and \
                    (getattr(vm, 'updateable', False) or vm.klass == 'AdminVM'):
                self.vms_needing_update.add(vm.name)

    def connect_events(self):
        self.dispatcher.add_handler('domain-feature-set:updates-available',
                                    self.feature_set)
        self.dispatcher.add_handler('domain-feature-delete:updates-available',
                                    self.feature_unset)
        self.dispatcher.add_handler('domain-add', self.domain_added)
        self.dispatcher.add_handler('domain-delete', self.domain_removed)

    def domain_added(self, _submitter, _event, vm, *_args, **_kwargs):
        try:
            vm_object = self.qapp.domains[vm]
        except exc.QubesException:
            # a disposableVM crashed on start
            return
        try:
            updates_available = vm_object.features.get(
                'updates-available', False)
        except exc.QubesDaemonCommunicationError:
            updates_available = False
        if updates_available and (getattr(vm_object, 'updateable', False) or
                                  vm_object.klass == 'AdminVM'):
            self.vms_needing_update.add(vm_object.name)
            self.update_indicator_state()

    def domain_removed(self, _submitter, _event, vm, *_args, **_kwargs):
        if vm in self.vms_needing_update:
            self.vms_needing_update.remove(vm)
            self.update_indicator_state()

    def feature_unset(self, vm, event, feature, **_kwargs):
        # pylint: disable=unused-argument
        if vm in self.vms_needing_update:
            self.vms_needing_update.remove(vm)
            self.update_indicator_state()

    def feature_set(self, vm, event, feature, value, **_kwargs):
        # pylint: disable=unused-argument
        if value and vm not in self.vms_needing_update and\
                getattr(vm, 'updateable', False):
            self.vms_needing_update.add(vm)

            notification = Gio.Notification.new(
                _("New updates are available for {}").format(vm.name))
            notification.set_priority(Gio.NotificationPriority.NORMAL)
            self.send_notification(None, notification)
        elif not value and vm in self.vms_needing_update:
            self.vms_needing_update.remove(vm)

        self.update_indicator_state()

    def update_indicator_state(self):
        if self.vms_needing_update:
            self.widget_icon.set_visible(True)
        else:
            self.widget_icon.set_visible(False)


def main():
    qapp = qubesadmin.Qubes()
    dispatcher = qubesadmin.events.EventsDispatcher(qapp)
    app = UpdatesTray(
        'org.qubes.qui.tray.Updates', qapp, dispatcher)
    app.run()

    loop = asyncio.get_event_loop()

    done, _unused = loop.run_until_complete(asyncio.ensure_future(
        dispatcher.listen_for_events()))

    exit_code = 0

    for d in done:  # pylint: disable=invalid-name
        try:
            d.result()
        except Exception:  # pylint: disable=broad-except
            exc_type, exc_value = sys.exc_info()[:2]
            dialog = Gtk.MessageDialog(
                None, 0, Gtk.MessageType.ERROR, Gtk.ButtonsType.OK)
            dialog.set_title(_("Houston, we have a problem..."))
            dialog.set_markup(_(
                "<b>Whoops. A critical error in Updates Widget has occured.</b>"
                " This is most likely a bug in the widget. To restart the "
                "widget, run 'qui-updates' in dom0."))
            dialog.format_secondary_markup(
                "\n<b>{}</b>: {}\n{}".format(
                   exc_type.__name__, exc_value, traceback.format_exc(limit=10)
                ))
            dialog.run()
            exit_code = 1
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
