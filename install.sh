#!/usr/bin/env bash
# install.sh — bootstrap de l'environnement de développement oxo-hep-bridge
#
# Couvre le maximum de dépendances système via le gestionnaire de paquets natif :
#   - Debian 12+ / Ubuntu 22.04, 24.04  →  apt
#   - Rocky Linux 9 / RHEL 9            →  dnf (+ EPEL)
#
# Puis installe l'environnement Python via uv (https://docs.astral.sh/uv/) :
#   loguru, ruff, mypy, pytest, pre-commit  (via  uv sync --extra dev)
#
# Usage:
#   ./install.sh                 # installe tout (système + venv)
#   ./install.sh --no-sudo       # saute les paquets système (déjà installés)
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

NO_SUDO=0
for arg in "$@"; do
    case "$arg" in
        --no-sudo) NO_SUDO=1 ;;
        -h|--help)
            sed -n '2,16p' "$0"; exit 0 ;;
        *) ;;
    esac
done

# --- couleurs ---
C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_OFF=$'\033[0m'
info() { printf '%s▸ %s%s\n' "$C_BLUE" "$*" "$C_OFF"; }
ok()   { printf '%s✓ %s%s\n' "$C_GREEN" "$*" "$C_OFF"; }
err()  { printf '%s✗ %s%s\n' "$C_RED" "$*" "$C_OFF" >&2; }

# --- détection distribution ---
DISTRO_ID=""; DISTRO_LIKE=""; VERSION_ID=""
if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="$ID"
    DISTRO_LIKE="${ID_LIKE:-}"
    VERSION_ID="${VERSION_ID:-}"
fi

is_debian_like() {
    [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" \
       || "$DISTRO_LIKE" == *debian* ]]
}
is_rhel_like() {
    [[ "$DISTRO_ID" == "rocky" || "$DISTRO_ID" == "rhel" || "$DISTRO_ID" == "almalinux" \
       || "$DISTRO_LIKE" == *rhel* || "$DISTRO_LIKE" == *fedora* ]]
}

# --- sudo ---
SUDO=""
if [[ $EUID -ne 0 ]]; then
    if [[ $NO_SUDO -eq 1 ]]; then
        info "Mode --no-sudo : étape système ignorée (on suppose tshark+python déjà là)."
    else
        if ! sudo -n true 2>/dev/null; then
            info "Mot de passe sudo requis pour les paquets système."
        fi
        SUDO="sudo"
    fi
fi

# --- étape 1 : paquets système ---
install_system_debian() {
    info "Installation paquets Debian/Ubuntu (apt)..."
    $SUDO apt-get update -y
    # software-properties-common pour add-apt-repository (PPA deadsnakes si <3.11)
    $SUDO apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release \
        software-properties-common \
        python3 python3-venv python3-pip python3-dev \
        tshark git build-essential pkg-config
    # Ubuntu 22.04 fournit python 3.10 → on ajoute 3.11 via PPA deadsnakes
    if [[ "$DISTRO_ID" == "ubuntu" && "$VERSION_ID" == "22.04" ]]; then
        $SUDO add-apt-repository -y ppa:deadsnakes/ppa
        $SUDO apt-get update -y
        $SUDO apt-get install -y --no-install-recommends python3.11 python3.11-venv python3.11-dev
    fi
}

install_system_rhel() {
    info "Installation paquets Rocky/RHEL 9 (dnf + EPEL)..."
    $SUDO dnf install -y epel-release
    $SUDO dnf install -y \
        ca-certificates curl \
        python3.11 python3.11-pip python3.11-devel \
        wireshark-cli git gcc make pkgconfig
    # wireshark-cli fournit tshark via EPEL sur RHEL/Rocky
}

if [[ $NO_SUDO -eq 0 ]]; then
    if is_debian_like; then
        install_system_debian
    elif is_rhel_like; then
        install_system_rhel
    else
        err "Distribution non reconnue ($DISTRO_ID). Installez manuellement : tshark, python>=3.11, git."
        err "Puis relancez : ./install.sh --no-sudo"
        exit 1
    fi
    ok "Paquets système installés"
fi

# --- étape 2 : tshark présent ? ---
if ! command -v tshark >/dev/null 2>&1; then
    err "tshark absent du PATH. Installez-le (apt: tshark / dnf: wireshark-cli) ou relancez sans --no-sudo."
    exit 1
fi
ok "tshark : $(tshark --version 2>/dev/null | head -1)"

# --- étape 3 : choisir Python >= 3.11 ---
pick_python() {
    for c in python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1; then
            if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
                echo "$c"; return 0
            fi
        fi
    done
    return 1
}

if ! PY="$(pick_python)"; then
    err "Python >= 3.11 introuvable. Installez python3.11 puis relancez."
    exit 1
fi
ok "Python : $PY ($($PY --version))"

# --- étape 4 : uv (gestionnaire d'environnement/dépendances) ---
if ! command -v uv >/dev/null 2>&1; then
    info "uv absent du PATH, installation via le script officiel astral.sh..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # L'installeur officiel pose le binaire dans ~/.local/bin, pas encore
    # dans le PATH de ce process shell tant qu'un nouveau shell n'est pas
    # ouvert.
    export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
    err "uv toujours introuvable après installation. Voir https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi
ok "uv : $(uv --version)"

info "Synchronisation de l'environnement (uv sync --extra dev, interpréteur $PY)..."
uv sync --extra dev --python "$PY"

# --- étape 5 : pre-commit ---
uv run pre-commit install >/dev/null 2>&1 && ok "Hooks pre-commit installés"

# --- étape 6 : vérification rapide ---
info "Smoke test : décodage d'une capture d'exemple"
SAMPLE="$PROJECT_DIR/sample_captures/ua3g_freeseating_ipv4.pcap"
if [[ -f "$SAMPLE" ]]; then
    if tshark -r "$SAMPLE" -T fields -e uaudp.opcode 2>/dev/null | head -1 | grep -q .; then
        ok "tshark décode bien uaudp sur la capture d'exemple"
    else
        err "tshark n'a pas décodé uaudp — vérifier l'installation du dissecteur"
    fi
fi

cat <<EOF

${C_GREEN}✓ Environnement prêt (.venv géré par uv).${C_OFF}

Lance une commande dans l'environnement (pas besoin d'activer le venv) :
  uv run pytest
  uv run oxo-hep-bridge --pcap sample_captures/ua3g_freeseating_ipv4.pcap --dry-run

...ou active le venv comme d'habitude si tu préfères :
  source .venv/bin/activate
  oxo-hep-bridge --pcap sample_captures/ua3g_freeseating_ipv4.pcap --dry-run

Raccourcis équivalents :
  make test        # uv run pytest
  make lint        # uv run ruff check . && uv run ruff format --check .
  make typecheck   # uv run mypy

EOF
