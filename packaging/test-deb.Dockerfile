# Prebaked test image for `task test-deb-fast`.
#
# Installs all .deb dependencies once so subsequent test runs only have to
# `dpkg -i` the package itself (~10 s vs ~4 min for the full apt-install path).
#
# Rebuild trigger: packaging/control changes (Task's `sources:` field tracks it).
FROM ubuntu:24.04

ARG DEPS
ENV DEBIAN_FRONTEND=noninteractive

# --no-install-recommends keeps the image lean; the .deb's postinst only
# needs core schema/desktop/icon-cache helpers, which gnome-shell pulls
# transitively as direct deps.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ${DEPS} \
 && rm -rf /var/lib/apt/lists/*
