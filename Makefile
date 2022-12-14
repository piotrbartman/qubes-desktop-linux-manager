default: help

help:
	@echo "Use setup.py to build"
	@echo "Extra make targets available:"
	@echo " install-autostart - install autostart files (xdg, systemd)"
	@echo " install-icons - install icons"
	@echo " install - calls both of the above (but calling setup.py is still necessary)"

install-icons:
	mkdir -p $(DESTDIR)/usr/share/icons/Adwaita/22x22/devices/
	mkdir -p $(DESTDIR)/usr/share/icons/Adwaita/22x22/status/
	cp icons/22x22/generic-usb.png $(DESTDIR)/usr/share/icons/Adwaita/22x22/devices/generic-usb.png
	cp icons/outdated.png $(DESTDIR)/usr/share/icons/Adwaita/22x22/status/
	mkdir -p $(DESTDIR)/usr/share/applications
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/16x16/apps/
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/24x24/apps/
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/32x32/apps/
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/40x40/apps/
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/48x48/apps/
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/72x72/apps/
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/96x96/apps/
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/128x128/apps/
	cp icons/16x16/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/16x16/apps/qui-domains.png
	cp icons/24x24/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/24x24/apps/qui-domains.png
	cp icons/32x32/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/32x32/apps/qui-domains.png
	cp icons/40x40/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/40x40/apps/qui-domains.png
	cp icons/48x48/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/48x48/apps/qui-domains.png
	cp icons/72x72/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/72x72/apps/qui-domains.png
	cp icons/96x96/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/96x96/apps/qui-domains.png
	cp icons/128x128/qui-domains.png $(DESTDIR)/usr/share/icons/hicolor/128x128/apps/qui-domains.png
	mkdir -p $(DESTDIR)/usr/share/icons/hicolor/scalable/apps
	cp icons/scalable/check-yes.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-check-yes.svg
	cp icons/scalable/check-maybe.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-check-maybe.svg
	cp icons/scalable/delete_icon.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-delete.svg
	cp icons/scalable/delete-x.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-delete-x.svg
	cp icons/scalable/config-program-icon.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-global-config.svg
	cp icons/scalable/new-qube-program-icon.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-new-qube.svg
	cp icons/scalable/ok_icon.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-ok.svg
	cp icons/scalable/padlock_icon.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-padlock.svg
	cp icons/scalable/qubes-info.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-info.svg
	cp icons/scalable/qubes-key.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-key.svg
	cp icons/scalable/qubes_ask.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-ask.svg
	cp icons/scalable/qubes_customize.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-customize.svg
	cp icons/scalable/qubes_expander_hidden-black.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-expander-hidden-black.svg
	cp icons/scalable/qubes_expander_hidden-white.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-expander-hidden-white.svg
	cp icons/scalable/qubes_expander_shown-black.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-expander-shown-black.svg
	cp icons/scalable/qubes_expander_shown-white.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-expander-shown-white.svg
	cp icons/scalable/qubes_logo.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-logo.svg
	cp icons/scalable/question_icon.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-question.svg
	cp icons/scalable/question_icon_light.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-question-light.svg
	cp icons/scalable/this-device-icon.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-this-device.svg
	cp icons/scalable/check_no.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/check_no.svg
	cp icons/scalable/check_yes.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/check_yes.svg
	cp icons/scalable/check_maybe.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/check_maybe.svg
	cp icons/scalable/qubes_policy_editor.svg $(DESTDIR)/usr/share/icons/hicolor/scalable/apps/qubes-policy-editor.svg

install-autostart:
	mkdir -p $(DESTDIR)/etc/xdg/autostart
	cp autostart/qui-domains.desktop $(DESTDIR)/etc/xdg/autostart
	cp autostart/qui-devices.desktop $(DESTDIR)/etc/xdg/autostart
	cp autostart/qui-clipboard.desktop $(DESTDIR)/etc/xdg/autostart
	cp autostart/qui-disk-space.desktop $(DESTDIR)/etc/xdg/autostart
	cp autostart/qui-updates.desktop $(DESTDIR)/etc/xdg/autostart
	mkdir -p $(DESTDIR)/usr/share/applications
	cp desktop/qubes-update-gui.desktop $(DESTDIR)/usr/share/applications/
	mkdir -p $(DESTDIR)/usr/bin
	cp qui/widget-wrapper $(DESTDIR)/usr/bin/widget-wrapper
	mkdir -p $(DESTDIR)/lib/systemd/user/
	cp linux-systemd/qubes-widget@.service $(DESTDIR)/lib/systemd/user/
	cp desktop/qubes-global-config.desktop $(DESTDIR)/usr/share/applications/
	cp desktop/qubes-new-qube.desktop $(DESTDIR)/usr/share/applications/
	cp desktop/qubes-policy-editor.desktop $(DESTDIR)/usr/share/applications/

install-lang:
	mkdir -p $(DESTDIR)/usr/share/gtksourceview-4/language-specs/
	cp qubes_config/policy_editor/qubes-rpc.lang $(DESTDIR)/usr/share/gtksourceview-4/language-specs/

install: install-autostart install-icons install-lang

.PHONY: clean
clean:
