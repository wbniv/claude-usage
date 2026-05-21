ARG UBUNTU_VERSION=26.04
FROM ubuntu:${UBUNTU_VERSION}
ARG UBUNTU_VERSION
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnome-shell gjs libglib2.0-bin \
    && rm -rf /var/lib/apt/lists/*

COPY gnome-extension/ /root/.local/share/gnome-shell/extensions/claude-usage@indri.studio/
RUN glib-compile-schemas \
    /root/.local/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/

COPY packaging/test-gnome-verify.sh /verify.sh
RUN chmod +x /verify.sh
CMD ["/verify.sh"]
