#!/usr/bin/env bash
# deploy-install-worker.sh — publish slo's install.sh on Cloudflare as a Worker.
#
# WHAT IT DOES (read before running):
#   1. Verifies your Cloudflare API token can see the account.
#   2. Resolves the install.sh to publish:
#        - default: fetches the COMMITTED public copy from GitLab at
#          SLO_SOURCE_REF (no repository credentials), or
#        - override: if INSTALL_SH points at a local file, publishes that
#          (for testing an un-committed copy — prints a warning).
#   3. base64-encodes it (avoids every shell/JS escaping pitfall) and uploads a
#      tiny Worker that returns it at "/" and "/install.sh".
#   4. (zone given) binds https://<SLO_HOSTNAME>/ on your domain (auto-creates
#      proxied DNS); otherwise enables the free *.workers.dev URL.
#
# CREDENTIALS:
#   CF_API_TOKEN   operator: deploys the Worker (this script).
#   The source repository and installer are public. No repository credential is
#   required, used, or baked into the Worker.
#
# REQUIRED env:
#   CF_API_TOKEN    scoped Cloudflare API token. Permissions:
#                     Account → Workers Scripts: Edit   (always)
#                   For a custom domain, also on your zone:
#                     Zone → Zone: Read, DNS: Edit, Workers Routes: Edit
#   CF_ACCOUNT_ID   your Cloudflare account id
# OPTIONAL env:
#   SLO_SOURCE_REF    repo ref to publish the SCRIPT from (default: main)
#   PUBLISH_SLO_REF   pin the hosted default INSTALL ref, e.g. v0.3.2. Bakes
#                     SLO_REF default into the served script so `curl … | bash`
#                     installs that release (a user can still override SLO_REF).
#                     Omit → the served script defaults to main.
#   SLO_REPO_PROJECT  GitLab project path             (default: core-27/slo)
#   SLO_SOURCE_PATH   path of install.sh in the repo  (default: install.sh)
#   INSTALL_SH        local file to publish INSTEAD of the repo copy (testing)
#   CF_ZONE_NAME      your domain/zone, e.g. example.com  (omit → workers.dev URL)
#   CLOUDFLARE_ZONE_ID  the zone id directly. Takes precedence over CF_ZONE_NAME
#                     and skips the zones?name= lookup, so the token needs no
#                     account-wide Zone:Read. (CF_ZONE_ID is accepted too.)
#   SLO_HOSTNAME      full hostname, e.g. slo.example.com (with either zone var)
#   WORKER_NAME       Worker script name              (default: slo-install)
#
# Tokens are read only from env vars; never printed or written to disk.
set -euo pipefail

CF_API="https://api.cloudflare.com/client/v4"
WORKER_NAME="${WORKER_NAME:-slo-install}"
COMPAT_DATE="2024-11-01"
SLO_SOURCE_REF="${SLO_SOURCE_REF:-main}"
SLO_REPO_PROJECT="${SLO_REPO_PROJECT:-core-27/slo}"
SLO_SOURCE_PATH="${SLO_SOURCE_PATH:-install.sh}"

log() { printf '→ %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
urlenc() { python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"; }

# ---- 1. validate inputs ----------------------------------------------------
# Accept env var names from environments/development.env with CF_* fallbacks.
CF_API_TOKEN="${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN:-}}"
CF_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-${CF_ACCOUNT_ID:-}}"
CF_ZONE_ID="${CLOUDFLARE_ZONE_ID:-${CF_ZONE_ID:-}}"
: "${CF_API_TOKEN:?set CLOUDFLARE_API_TOKEN (a scoped Cloudflare API token)}"
: "${CF_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID}"
command -v curl    >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required (used to parse API JSON)"
command -v base64  >/dev/null || die "base64 is required"

auth=(-H "Authorization: Bearer ${CF_API_TOKEN}")

# cf METHOD URL [extra curl args...] — call the CF API, fail loudly on success:false.
cf() {
    local method="$1" url="$2"; shift 2
    local out
    out="$(curl -fsS -X "$method" "${auth[@]}" "$@" "$url")" \
        || die "HTTP call failed: $method $url"
    if ! printf '%s' "$out" | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('success') else 1)"; then
        printf '%s' "$out" | python3 -c "import json,sys; print('Cloudflare errors:', json.load(sys.stdin).get('errors'), file=sys.stderr)" || true
        die "Cloudflare reported failure for: $method $url"
    fi
    printf '%s' "$out"
}

# ---- 2. verify token can reach the account's Workers ----------------------
# List Workers scripts (needs Workers Scripts: Read, implied by Edit) rather
# than GET /accounts/{id} (which needs Account Settings: Read — a permission we
# don't otherwise require).
log "verifying the token can access Workers on account ${CF_ACCOUNT_ID}"
cf GET "${CF_API}/accounts/${CF_ACCOUNT_ID}/workers/scripts" >/dev/null

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
SRC="$WORKDIR/install.sh"

# ---- 3. resolve the install.sh to publish ---------------------------------
if [ -n "${INSTALL_SH:-}" ]; then
    [ -f "$INSTALL_SH" ] || die "INSTALL_SH set but not found: $INSTALL_SH"
    log "WARNING: publishing LOCAL file ${INSTALL_SH} (not the committed repo copy)"
    cp "$INSTALL_SH" "$SRC"
else
    log "fetching ${SLO_SOURCE_PATH} from ${SLO_REPO_PROJECT}@${SLO_SOURCE_REF} (canonical public copy)"
    curl -fsSL \
        "https://gitlab.com/${SLO_REPO_PROJECT}/-/raw/$(urlenc "$SLO_SOURCE_REF")/${SLO_SOURCE_PATH}" \
        -o "$SRC" \
        || die "failed to fetch install.sh from public GitLab (check SLO_REPO_PROJECT, SLO_SOURCE_REF, and SLO_SOURCE_PATH)"
fi
[ -s "$SRC" ] || die "resolved install.sh is empty"

# ---- 3b. (optional) pin the hosted default install ref --------------------
# Insert a SLO_REF default right after the shebang so `curl … | bash` (no
# SLO_REF) installs the pinned release. install.sh's own `SLO_REF="${SLO_REF:-main}"`
# then sees SLO_REF already set and keeps it; an installer can still override.
if [ -n "${PUBLISH_SLO_REF:-}" ]; then
    log "pinning hosted default SLO_REF=${PUBLISH_SLO_REF} (installer can still override)"
    {
        head -n 1 "$SRC"
        printf 'SLO_REF="${SLO_REF:-%s}"  # pinned at publish time by deploy-install-worker.sh\n' "$PUBLISH_SLO_REF"
        tail -n +2 "$SRC"
    } > "$SRC.pinned"
    mv "$SRC.pinned" "$SRC"
fi

# ---- 4. build the Worker (install.sh embedded as base64) ------------------
log "encoding install.sh ($(wc -c <"$SRC" | tr -d ' ') bytes)"
B64="$(base64 < "$SRC" | tr -d '\n')"

cat > "$WORKDIR/worker.js" <<JS
// Auto-generated by deploy-install-worker.sh — serves slo's install.sh.
const B64 = "${B64}";
const SCRIPT = Uint8Array.from(atob(B64), (c) => c.charCodeAt(0));
export default {
  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/" || path === "/install.sh") {
      return new Response(SCRIPT, {
        headers: { "content-type": "text/x-shellscript; charset=utf-8" },
      });
    }
    return new Response("not found\n", { status: 404 });
  },
};
JS

printf '{"main_module":"worker.js","compatibility_date":"%s"}' "$COMPAT_DATE" \
    > "$WORKDIR/metadata.json"

# ---- 5. upload the Worker --------------------------------------------------
log "uploading Worker '${WORKER_NAME}'"
cf PUT "${CF_API}/accounts/${CF_ACCOUNT_ID}/workers/scripts/${WORKER_NAME}" \
    -F "metadata=@${WORKDIR}/metadata.json;type=application/json" \
    -F "worker.js=@${WORKDIR}/worker.js;type=application/javascript+module" \
    >/dev/null
log "Worker uploaded"

# ---- 6. publish a URL ------------------------------------------------------
if [ -n "${CF_ZONE_ID:-}" ] || [ -n "${CF_ZONE_NAME:-}" ]; then
    : "${SLO_HOSTNAME:?set SLO_HOSTNAME (e.g. slo.example.com) when CF_ZONE_ID or CF_ZONE_NAME is set}"
    if [ -n "${CF_ZONE_ID:-}" ]; then
        # An explicit zone id skips the zones?name= lookup, so the token does
        # not need account-wide Zone:Read — useful for a scoped CI token.
        log "using supplied zone id ${CF_ZONE_ID}"
        zone_id="${CF_ZONE_ID}"
    else
        log "resolving zone id for ${CF_ZONE_NAME}"
        zone_id="$(cf GET "${CF_API}/zones?name=${CF_ZONE_NAME}" \
            | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r[0]['id'] if r else '')")"
        [ -n "$zone_id" ] || die "no zone named '${CF_ZONE_NAME}' on this account/token"
    fi
    log "binding ${SLO_HOSTNAME} → Worker ${WORKER_NAME} (auto-creates proxied DNS)"
    body="$(python3 -c "import json,sys; print(json.dumps({'environment':'production','hostname':sys.argv[1],'service':sys.argv[2],'zone_id':sys.argv[3]}))" \
        "$SLO_HOSTNAME" "$WORKER_NAME" "$zone_id")"
    cf PUT "${CF_API}/accounts/${CF_ACCOUNT_ID}/workers/domains" \
        -H "Content-Type: application/json" --data "$body" >/dev/null
    INSTALL_URL="https://${SLO_HOSTNAME}/install.sh"
else
    log "no CF_ZONE_NAME — enabling the free workers.dev URL"
    cf POST "${CF_API}/accounts/${CF_ACCOUNT_ID}/workers/scripts/${WORKER_NAME}/subdomain" \
        -H "Content-Type: application/json" --data '{"enabled":true}' >/dev/null
    sub="$(cf GET "${CF_API}/accounts/${CF_ACCOUNT_ID}/workers/subdomain" \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['result'].get('subdomain',''))")"
    INSTALL_URL="https://${WORKER_NAME}.${sub}.workers.dev/install.sh"
fi

# ---- 7. done ---------------------------------------------------------------
cat >&2 <<DONE

✅ Deployed (script source: ${INSTALL_SH:-${SLO_REPO_PROJECT}@${SLO_SOURCE_REF}}; default install ref: ${PUBLISH_SLO_REF:-main}).
Production install command:

   curl -fsSL ${INSTALL_URL} | SLO_VERSION=${PUBLISH_SLO_REF:-main} bash

Install the dev (main) branch:

   curl -fsSL ${INSTALL_URL} | SLO_VERSION=dev bash

(DNS + edge propagation can take a minute on first custom-domain bind.)
Re-run after a new install.sh is committed to publish the update.
DONE
