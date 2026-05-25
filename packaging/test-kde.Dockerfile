# Plasma 6 smoke-test image for the KDE plasmoid. Mirrors test-gnome.Dockerfile.
#
# Base: ubuntu:26.04 LTS — the project's canonical target (also test-gnome's
# default). Ships Plasma 6 in its repos. "Kubuntu" is just Ubuntu + these KDE
# packages; there is no separate kubuntu Docker image. (KDE neon's Docker tags
# are stale: kdeneon/plasma:user is still 22.04 + Plasma 5.27.) plasma-workspace
# provides the org.kde.plasma.* / plasma5support / kirigami QML modules a
# plasmoid imports; plasma-sdk provides plasmoidviewer. We run as a non-root
# user because KDE refuses to run as root. The plasmoid is bind-mounted at
# /plasmoid at run time so iterating doesn't rebuild the image.
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
# Retry transient mirror fetch failures (archive.ubuntu.com via Cloudflare can
# flake intermittently from CI networks).
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/99retries
# plasma-desktop provides the org.kde.desktopcontainment containment that
# plasmoidviewer needs to host an applet (plasma-workspace alone lacks it).
# libxcb-cursor0 is required by Qt 6's xcb platform plugin (used under Xvfb).
RUN apt-get update && apt-get install -y --no-install-recommends \
        plasma-workspace \
        plasma-desktop \
        plasma-sdk \
        libxcb-cursor0 \
        xvfb \
        dbus-x11 \
        python3 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m tester

USER tester
ENV HOME=/home/tester
# Both the plasmoid (/plasmoid) and the verify script (/verify.sh) are
# bind-mounted at run time so iterating on either needs no image rebuild.
CMD ["bash", "/verify.sh", "/plasmoid"]
