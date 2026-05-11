CC      = gcc
CFLAGS  = -O2 -Wall -Wextra -fPIC
SO_LDFLAGS = -shared -ldl -lpthread

INSTALL_DIR  = $(HOME)/.local/share/applications
ICON_DIR     = $(HOME)/.local/share/icons/hicolor/128x128/apps
DESKTOP_FILE = $(HOME)/.local/share/applications/speedhack.desktop
ABS_DIR      = $(shell pwd)

.PHONY: all clean install uninstall

all: speedhack.so speedctl speedhack.png

speedhack.so: speedhack.c
	$(CC) $(CFLAGS) $(SO_LDFLAGS) -o $@ $<

speedctl: speedctl.c
	$(CC) -O2 -Wall -Wextra -o $@ $<

speedhack.png: speedhack.svg
	convert -background none $< -resize 128x128 $@ 2>/dev/null || \
	rsvg-convert -w 128 -h 128 $< -o $@ 2>/dev/null || \
	echo "警告: 无法转换图标（需要 imagemagick 或 librsvg2-bin）"

install: all
	mkdir -p $(INSTALL_DIR) $(ICON_DIR)
	cp speedhack.png $(ICON_DIR)/speedhack.png
	sed "s|/home/fluorene/speedhack|$(ABS_DIR)|g" speedhack.desktop.in > $(DESKTOP_FILE)
	chmod +x $(DESKTOP_FILE)
	cp $(DESKTOP_FILE) $(HOME)/Desktop/speedhack.desktop 2>/dev/null || true
	chmod +x $(HOME)/Desktop/speedhack.desktop 2>/dev/null || true
	gio set $(HOME)/Desktop/speedhack.desktop metadata::trusted true 2>/dev/null || true
	update-desktop-database $(INSTALL_DIR) 2>/dev/null || true
	gtk-update-icon-cache -f -t $(ICON_DIR)/../../.. 2>/dev/null || true
	@echo "已安装。在应用菜单搜索 SpeedHack 即可启动。"

uninstall:
	rm -f $(DESKTOP_FILE) $(HOME)/Desktop/speedhack.desktop
	rm -f $(ICON_DIR)/speedhack.png
	update-desktop-database $(INSTALL_DIR) 2>/dev/null || true

clean:
	rm -f speedhack.so speedctl speedhack.png
