# Sourced by a game's install.sh: `ga_need base steam dotnet` runs lab/images/common/install-<layer>.sh for each layer the image does
# not have yet. In the published chain (FROM gameanything-lab-dotnet ...) they are all there already and nothing runs; on a plain
# ubuntu:24.04 (a docker-rt test sandbox) every one is installed. Each layer leaves /opt/gameanything/layers/<layer>.
_GA_COMMON=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ga_need() {
  local l s
  for l in "$@"; do
    [ -f "/opt/gameanything/layers/$l" ] && continue
    s="$_GA_COMMON/install-$l.sh"; [ "$l" = base ] && s="$_GA_COMMON/install-system.sh"
    echo "== layer $l ($s)"; bash "$s"
  done
}
