# pylint: disable=wrong-import-position,import-error
import asyncio
import sys

import traceback

import gi
gi.require_version('Gtk', '3.0')  # isort:skip
gi.require_version('AppIndicator3', '0.1')  # isort:skip
from gi.repository import Gtk, Gio  # isort:skip

import qubesadmin
import qubesadmin.events
import qubesadmin.devices
import qubesadmin.exc
import qui.decorators

import gbulb
gbulb.install()


import gettext
t = gettext.translation("desktop-linux-manager", fallback=True)
_ = t.gettext

DEV_TYPES = ['block', 'usb', 'mic']
DEV_TYPE_NAMES = {
    'block': 'Data (Block) Devices',
    'usb': 'USB Devices',
    'mic': 'Audio Input'
}


class DomainMenuItem(Gtk.ImageMenuItem):
    """ A submenu item for the device menu. Displays attachment status.
     Allows attaching/detaching the device."""

    def __init__(self, device, vm, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.vm = vm

        self.device = device

        # if we cannot access vm icon, show default appvm-black
        icon = getattr(self.vm, 'icon', 'appvm-black')

        self.set_image(qui.decorators.create_icon(icon))
        self._hbox = qui.decorators.device_domain_hbox(self.vm, self.attached)
        self.add(self._hbox)

    @property
    def attached(self):
        return str(self.vm) in self.device.attachments


class DomainMenu(Gtk.Menu):
    def __init__(self, device, domains, qapp, gtk_app, **kwargs):
        super().__init__(**kwargs)
        self.device = device
        self.domains = domains
        self.qapp = qapp
        self.gtk_app = gtk_app

        for vm in self.domains:
            if vm != device.backend_domain:
                menu_item = DomainMenuItem(self.device, vm)
                menu_item.connect('activate', self.toggle)
                self.append(menu_item)

    def toggle(self, menu_item):
        if menu_item.attached:
            self.detach_item()
        else:
            self.attach_item(menu_item)

    def attach_item(self, menu_item):
        detach_successful = self.detach_item()

        if not detach_successful:
            return

        try:
            assignment = qubesadmin.devices.DeviceAssignment(
                self.device.backend_domain, self.device.ident, persistent=False)

            vm_to_attach = self.qapp.domains[str(menu_item.vm)]
            vm_to_attach.devices[menu_item.device.devclass].attach(assignment)

            self.gtk_app.emit_notification(
                _("Attaching device"),
                _("Attaching {} to {}").format(self.device.description,
                                               menu_item.vm),
                Gio.NotificationPriority.NORMAL,
                notification_id=self.device.backend_domain + self.device.ident)
        except Exception as ex:  # pylint: disable=broad-except
            self.gtk_app.emit_notification(
                _("Error"),
                _("Attaching device {0} to {1} failed. "
                  "Error: {2} - {3}").format(
                    self.device.description, menu_item.vm, type(ex).__name__,
                    ex),
                Gio.NotificationPriority.HIGH,
                error=True,
                notification_id=self.device.backend_domain + self.device.ident)
            self.update_dev_attachments()
            traceback.print_exc(file=sys.stderr)

    def detach_item(self):
        for vm in self.device.attachments:
            self.gtk_app.emit_notification(
                _("Detaching device"),
                _("Detaching {} from {}").format(self.device.description, vm),
                Gio.NotificationPriority.NORMAL,
                notification_id=self.device.backend_domain + self.device.ident)
            try:
                assignment = qubesadmin.devices.DeviceAssignment(
                    self.device.backend_domain, self.device.ident,
                    persistent=False)
                self.qapp.domains[vm].devices[self.device.devclass].detach(
                    assignment)
            except qubesadmin.exc.QubesException as ex:
                self.gtk_app.emit_notification(
                    _("Error"),
                    _("Detaching device {0} from {1} failed. "
                      "Error: {2}").format(self.device.description, vm, ex),
                    Gio.NotificationPriority.HIGH,
                    error=True,
                    notification_id=(self.device.backend_domain +
                                     self.device.ident))
                self.update_dev_attachments()
                return False
        return True

    def update_dev_attachments(self):
        # use this only in cases of error, when there is a reason
        # to suspect the correct detach/attach events were not fired
        self.device.attachments = set()

        for vm in self.qapp.domains:
            try:
                for device in vm.devices[self.device.devclass].attached():
                    if str(device) == self.device.dev_name:
                        self.device.attachments.add(vm.name)
            except qubesadmin.exc.QubesDaemonAccessError:
                continue


class DeviceItem(Gtk.ImageMenuItem):
    """ MenuItem showing the device data and a :class:`DomainMenu`. """

    def __init__(self, device, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.device = device

        self.hbox = qui.decorators.device_hbox(self.device)  # type: Gtk.Box

        self.set_image(qui.decorators.create_icon(self.device.vm_icon))

        self.add(self.hbox)


class DevclassHeaderMenuItem(Gtk.MenuItem):
    """ MenuItem with a header, non-interactive """

    def __init__(self, devclass, *args, **kwargs):
        super().__init__(*args, **kwargs)

        label = Gtk.Label(xalign=0)
        label.set_markup("<b>{}</b>".format(
            DEV_TYPE_NAMES.get(devclass, "Other Devices")))

        self.add(label)
        self.set_sensitive(False)


class Device:
    def __init__(self, dev):
        self.dev_name = str(dev)
        self.ident = getattr(dev, 'ident', 'unknown')
        self.description = getattr(dev, 'description', 'unknown')
        self.devclass = getattr(dev, 'devclass', 'unknown')
        self.data = getattr(dev, 'data', {})
        self.attachments = set()
        self.backend_domain = str(getattr(dev, 'backend_domain', 'unknown'))

        try:
            self.vm_icon = getattr(dev.backend_domain, 'icon',
                                   dev.backend_domain.label.icon)
        except qubesadmin.exc.QubesException:
            self.vm_icon = 'appvm-black'

    def __str__(self):
        return self.dev_name

    def __eq__(self, other):
        return str(self) == str(other)


class VM:
    def __init__(self, vm):
        self.__hash = hash(vm)
        self.vm_name = vm.name

        try:
            self.icon = getattr(vm, 'icon', vm.label.icon)
        except qubesadmin.exc.QubesException:
            self.icon = 'appvm-black'

    def __str__(self):
        return self.vm_name

    def __eq__(self, other):
        return str(self) == str(other)

    def __lt__(self, other):
        return str(self) < str(other)

    def __hash__(self):
        return self.__hash


class DevicesTray(Gtk.Application):
    def __init__(self, app_name, qapp, dispatcher):
        super().__init__()
        self.name = app_name

        self.devices = {}
        self.vms = set()

        self.dispatcher = dispatcher
        self.qapp = qapp

        self.set_application_id(self.name)
        self.register()  # register Gtk Application

        self.initialize_vm_data()
        self.initialize_dev_data()

        for devclass in DEV_TYPES:
            self.dispatcher.add_handler('device-attach:' + devclass,
                                        self.device_attached)
            self.dispatcher.add_handler('device-detach:' + devclass,
                                        self.device_detached)
            self.dispatcher.add_handler('device-list-change:' + devclass,
                                        self.device_list_update)

        self.dispatcher.add_handler('domain-shutdown',
                                    self.vm_shutdown)
        self.dispatcher.add_handler('domain-start-failed',
                                    self.vm_shutdown)
        self.dispatcher.add_handler('domain-start', self.vm_start)
        self.dispatcher.add_handler('property-set:label', self.on_label_changed)

        self.widget_icon = Gtk.StatusIcon()
        self.widget_icon.set_from_icon_name('media-removable')
        self.widget_icon.connect('button-press-event', self.show_menu)
        self.widget_icon.set_tooltip_markup(
            _('<b>Qubes Devices</b>\nView and manage devices.'))

    def device_list_update(self, vm, _event, **_kwargs):

        changed_devices = []

        # create list of all current devices from the changed VM
        try:
            for devclass in DEV_TYPES:
                for device in vm.devices[devclass]:
                    changed_devices.append(Device(device))
        except qubesadmin.exc.QubesException:
            changed_devices = []  # VM was removed

        for dev in changed_devices:
            if str(dev) not in self.devices:
                self.devices[str(dev)] = dev
                self.emit_notification(
                    _("Device available"),
                    _("Device {} is available.").format(dev.description),
                    Gio.NotificationPriority.NORMAL,
                    notification_id=(dev.backend_domain +
                                     dev.ident))

        dev_to_remove = [name for name, dev in self.devices.items()
                         if dev.backend_domain == vm
                         and name not in changed_devices]
        for dev_name in dev_to_remove:
            self.emit_notification(
                _("Device removed"),
                _("Device {} has been removed.").format(
                    self.devices[dev_name].description),
                Gio.NotificationPriority.NORMAL,
                notification_id=(self.devices[dev_name].backend_domain +
                                 self.devices[dev_name].ident))
            del self.devices[dev_name]

    def initialize_vm_data(self):
        for vm in self.qapp.domains:
            try:
                if vm.klass != 'AdminVM' and vm.is_running():
                    self.vms.add(VM(vm))
            except qubesadmin.exc.QubesException:
                # we don't have access to VM state
                pass

    def initialize_dev_data(self):

        # list all devices
        for domain in self.qapp.domains:
            for devclass in DEV_TYPES:
                try:
                    for device in domain.devices[devclass]:
                        self.devices[str(device)] = Device(device)
                except qubesadmin.exc.QubesException:
                    # we have no permission to access VM's devices
                    continue

        # list existing device attachments
        for domain in self.qapp.domains:
            for devclass in DEV_TYPES:
                try:
                    for device in domain.devices[devclass].attached():
                        dev = str(device)
                        if dev in self.devices:
                            # occassionally ghost UnknownDevices appear when a
                            # device was removed but not detached from a VM
                            self.devices[dev].attachments.add(domain.name)
                except qubesadmin.exc.QubesException:
                    # we have no permission to access VM's devices
                    continue

    def device_attached(self, vm, _event, device, **_kwargs):
        try:
            if not vm.is_running() or device.devclass not in DEV_TYPES:
                return
        except qubesadmin.exc.QubesPropertyAccessError:
            # we don't have access to VM state
            return

        if str(device) not in self.devices:
            self.devices[str(device)] = Device(device)

        self.devices[str(device)].attachments.add(str(vm))

    def device_detached(self, vm, _event, device, **_kwargs):
        try:
            if not vm.is_running():
                return
        except qubesadmin.exc.QubesPropertyAccessError:
            # we don't have access to VM state
            return

        device = str(device)

        if device in self.devices:
            self.devices[device].attachments.discard(str(vm))

    def vm_start(self, vm, _event, **_kwargs):
        self.vms.add(VM(vm))
        for devclass in DEV_TYPES:
            try:
                for device in vm.devices[devclass].attached():
                    dev = str(device)
                    if dev in self.devices:
                        self.devices[dev].attachments.add(vm.name)
            except qubesadmin.exc.QubesDaemonAccessError:
                # we don't have access to devices
                return

    def vm_shutdown(self, vm, _event, **_kwargs):
        self.vms.discard(vm)

        for dev in self.devices.values():
            dev.attachments.discard(str(vm))

    def on_label_changed(self, vm, _event, **_kwargs):
        if not vm:  # global properties changed
            return
        try:
            name = vm.name
        except qubesadmin.exc.QubesPropertyAccessError:
            return  # the VM was deleted before its status could be updated
        for domain in self.vms:
            if str(domain) == name:
                try:
                    domain.icon = vm.label.icon
                except qubesadmin.exc.QubesPropertyAccessError:
                    domain.icon = 'appvm-block'

        for device in self.devices.values():
            if device.backend_domain == name:
                try:
                    device.vm_icon = vm.label.icon
                except qubesadmin.exc.QubesPropertyAccessError:
                    device.vm_icon = 'appvm-black'

    def show_menu(self, _unused, _event):
        tray_menu = Gtk.Menu()

        # create menu items
        menu_items = []
        sorted_vms = sorted(self.vms)
        for dev in self.devices.values():
            domain_menu = DomainMenu(dev, sorted_vms, self.qapp, self)
            device_menu = DeviceItem(dev)
            device_menu.set_submenu(domain_menu)
            menu_items.append(device_menu)

        menu_items.sort(key=(lambda x: x.device.devclass + str(x.device)))

        if menu_items:
            tray_menu.add(DevclassHeaderMenuItem(menu_items[0].device.devclass))

        for i, item in enumerate(menu_items):
            if i > 0 and item.device.devclass != \
                    menu_items[i-1].device.devclass:
                tray_menu.add(
                    DevclassHeaderMenuItem(item.device.devclass))
            tray_menu.add(item)

        tray_menu.show_all()
        tray_menu.popup_at_pointer(None)  # use current event

    def emit_notification(self, title, message, priority, error=False,
                          notification_id=None):
        notification = Gio.Notification.new(title)
        notification.set_body(message)
        notification.set_priority(priority)
        if error:
            notification.set_icon(Gio.ThemedIcon.new('dialog-error'))
            if notification_id:
                notification_id += 'ERROR'
        self.send_notification(notification_id, notification)


def main():
    qapp = qubesadmin.Qubes()
    dispatcher = qubesadmin.events.EventsDispatcher(qapp)
    app = DevicesTray(
        'org.qubes.qui.tray.Devices', qapp, dispatcher)

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
                "<b>Whoops. A critical error in Qubes Domains has occurred.</b>"
                " This is most likely a bug in the widget. To restart the "
                "widget, run 'qui-domains' in dom0."))
            dialog.format_secondary_markup(
                "\n<b>{}</b>: {}\n{}".format(
                   exc_type.__name__, exc_value, traceback.format_exc(limit=10)
                ))
            dialog.run()
            exit_code = 1
    del app
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
