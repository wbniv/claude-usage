# Homebrew cask for the macOS menu-bar build — the apt.indri.studio / .deb
# analog. Lives in a tap repo (e.g. wbniv/homebrew-tap); `version` + `sha256`
# are stamped by the release workflow when it attaches the built .app zip.
#
#   brew install --cask wbniv/tap/claude-usage
#
# The .app is ad-hoc-signed (not notarized); Homebrew clears the quarantine
# attribute on cask-installed apps, so Gatekeeper lets it launch. See
# docs/plans/2026-06-18-macos-port.md for the notarization upgrade path.
cask "claude-usage" do
  version "0.11.29"
  sha256 :no_check # release workflow pins the real digest of the attached zip

  url "https://github.com/wbniv/claude-usage/releases/download/v#{version}/claude-usage-macos-#{version}.zip"
  name "Claude Usage"
  desc "Menu-bar indicator for your Claude.ai weekly usage"
  homepage "https://github.com/wbniv/claude-usage"

  depends_on macos: ">= :ventura"

  app "claude-usage.app"

  # Install + load the LaunchAgent shipped inside the bundle (the systemd-unit
  # analog). launchctl bootstrap runs in the user's GUI session.
  postflight do
    plist_src = "#{appdir}/claude-usage.app/Contents/Resources/studio.indri.claude-usage.plist"
    plist_dst = "#{Dir.home}/Library/LaunchAgents/studio.indri.claude-usage.plist"
    FileUtils.mkdir_p("#{Dir.home}/Library/LaunchAgents")
    FileUtils.cp(plist_src, plist_dst)
    system_command "/bin/launchctl",
                   args: ["bootstrap", "gui/#{Process.uid}", plist_dst],
                   sudo: false
  end

  # quit the running app + bootout the agent on uninstall.
  uninstall quit:      "studio.indri.claude-usage",
            launchctl: "studio.indri.claude-usage"

  # `brew uninstall --zap` also wipes per-user state (cache, config, agent).
  zap trash: [
    "~/.cache/claude-usage",
    "~/.config/claude-usage",
    "~/Library/LaunchAgents/studio.indri.claude-usage.plist",
  ]
end
