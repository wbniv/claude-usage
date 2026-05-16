# Prebaked test image for `task test-deb-fast`.
#
# Installs all .deb dependencies once so subsequent test runs only have to
# `dpkg -i` the package itself (~10 s vs ~4 min for the full apt-install path).
#
# Rebuild trigger: packaging/control changes (Task's `sources:` field tracks it).
FROM ubuntu:24.04

ARG DEPS
ENV DEBIAN_FRONTEND=noninteractive

# --no-install-recommends keeps the image lean. Explicit additions:
#   libglib2.0-bin     — glib-compile-schemas (postinst hard-requires it)
#   desktop-file-utils — update-desktop-database (postinst/postrm best-effort)
# Both are present on any real GNOME desktop via transitive recommends;
# we pull them in explicitly so the test image mirrors that environment.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ${DEPS} \
        libglib2.0-bin \
        desktop-file-utils \
 && rm -rf /var/lib/apt/lists/*
