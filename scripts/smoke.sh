#!/usr/bin/env bash
# Production smoke test for a deployed Rubbish environment.
#
# Runs a handful of fast checks against BASE_URL to answer "is this
# deployment actually serving users?" right after a release:
# health, security headers, auth gating, a register->login roundtrip,
# and single-port static serving.
#
# Usage:  ./scripts/smoke.sh [BASE_URL] [options]
#         BASE_URL defaults to http://127.0.0.1:8000 (or $SMOKE_BASE_URL)
# Options:
#   --admin-user USER   Use this account's login instead of the register
#                       path when registration is blocked (captcha/closed).
#                       Env fallback: SMOKE_ADMIN_USER
#   --admin-pass PASS   Env fallback: SMOKE_ADMIN_PASSWORD
#   -h, --help          Show this help.
#
# Dependencies: curl, grep, sed — no jq (tokens are extracted with sed).
# Exit code: 0 = all checks PASS or SKIP, 1 = at least one FAIL.

set -uo pipefail

BASE_URL="${SMOKE_BASE_URL:-http://127.0.0.1:8000}"
ADMIN_USER="${SMOKE_ADMIN_USER:-}"
ADMIN_PASS="${SMOKE_ADMIN_PASSWORD:-}"

PASS=0
SKIP=0
FAIL=0

ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
skip() { printf '  \033[33mSKIP\033[0m %s\n' "$1"; SKIP=$((SKIP + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }
head_() { printf '\n\033[36m%s\033[0m\n' "$1"; }

usage() {
    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
}

# HTTP helper: performs the request, sets $CODE and $BODY in the caller.
# Response is captured in a variable (not curl -o), because native curl
# builds on some platforms (Windows) cannot write to MSYS temp paths.
# The status code is appended after a newline and split off below.
BODY=""
CODE=""
http() {
    # $1=method $2=path, remaining args passed through to curl.
    local _raw=""
    _raw="$(curl -sS --max-time 10 -w '\n%{http_code}' \
        -X "$1" "$BASE_URL$2" "${@:3}")" || { CODE="000"; BODY=""; return 0; }
    CODE="${_raw##*$'\n'}"
    BODY="${_raw%$'\n'*}"
}
body_has()      { printf '%s' "$BODY" | grep -q "$1"; }
body_has_regex(){ printf '%s' "$BODY" | grep -qiE "$1"; }
token_from_body(){ printf '%s' "$BODY" | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'; }

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --admin-user) ADMIN_USER="$2"; shift 2 ;;
        --admin-pass) ADMIN_PASS="$2"; shift 2 ;;
        -*) printf 'Unknown option: %s (see --help)\n' "$1" >&2; exit 2 ;;
        *) BASE_URL="$1"; shift ;;
    esac
done

# Strip trailing slash so "$BASE_URL/api/..." never doubles up.
BASE_URL="${BASE_URL%/}"

head_ "Smoke: $BASE_URL"

# --- Preflight: target must be reachable at all ---------------------------
# Verifies DNS/TLS/firewall basics. Failure means the service is down,
# the port is not published, or a reverse proxy sits in front but is
# misrouted — nothing else in the suite can be meaningful yet.
http GET /api/health
if [ "$CODE" = "000" ]; then
    bad "target unreachable — $BASE_URL did not answer (service down / port not published / DNS or firewall)"
    printf '\n\033[36mSummary\033[0m  pass=%s skip=%s fail=%s\n' "$PASS" "$SKIP" "$FAIL"
    exit 1
fi

head_ "Health"
# 1. /api/health must answer 200 with {"status":"ok"}.
# Failure means the app process is up but broken: bad env config, failed
# lifespan (DB unreachable), or a proxy routing /api to the wrong backend.
if [ "$CODE" = "200" ] && body_has '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    ok "/api/health -> 200 {\"status\":\"ok\"}"
else
    bad "/api/health -> $CODE (expected 200 with status=ok) — app running but unhealthy: check DB config and backend logs"
fi

# 2. Security headers on every response (set by SecurityHeadersMiddleware).
# Missing headers mean the deployment is not running the app's own
# middleware — typically a reverse proxy stripping headers or serving a
# stale/cached variant.
HDRS="$(curl -sS --max-time 10 -D - -o /dev/null "$BASE_URL/api/health" 2>/dev/null)"
if printf '%s' "$HDRS" | grep -qi '^x-content-type-options:[[:space:]]*nosniff'; then
    ok "X-Content-Type-Options: nosniff present"
else
    bad "X-Content-Type-Options missing — security headers middleware not applied (proxy stripping headers?)"
fi
if printf '%s' "$HDRS" | grep -qi '^x-frame-options:[[:space:]]*deny'; then
    ok "X-Frame-Options: DENY present"
else
    bad "X-Frame-Options missing — clickjacking protection absent (proxy stripping headers?)"
fi

head_ "Auth gating"
# 3. A protected endpoint must reject anonymous access with 401/403.
# A 200 here means auth dependencies are not enforced on this deployment —
# a critical data-exposure bug (wrong build, debug mode, proxy to dev app).
http GET /api/auth/me
if [ "$CODE" = "401" ] || [ "$CODE" = "403" ]; then
    ok "GET /api/auth/me without token -> $CODE"
else
    bad "GET /api/auth/me without token -> $CODE (expected 401/403) — protected data may be publicly readable"
fi

head_ "Auth roundtrip"
# 4. Register -> login roundtrip (or admin login fallback).
# Failure means the auth pipeline is broken end-to-end: password hashing,
# JWT signing, or tenant bootstrap. SKIP is reserved for policy blocks
# (captcha enabled, registration closed, 2FA) — those are config, not bugs.
REG_USER="smoke_$$_$(date +%s)"
REG_EMAIL="$REG_USER@smoke.example"
REG_PASS="SmokeTest12345!"
_payload="{\"email\":\"$REG_EMAIL\",\"username\":\"$REG_USER\",\"password\":\"$REG_PASS\"}"
http POST /api/auth/register -H 'Content-Type: application/json' -d "$_payload"
REG_CODE="$CODE"   # snapshot: auth_via_login below overwrites $CODE

auth_via_login() {
    # $1=username $2=password: login and extract an access token.
    _lp="{\"username\":\"$1\",\"password\":\"$2\"}"
    http POST /api/auth/login -H 'Content-Type: application/json' -d "$_lp"
    _LT="$(token_from_body)"
}

# 4b. Positive authorization: an issued token must not only exist but
# actually resolve to its user. 200 from /api/auth/me WITH the Bearer
# token — and the username echoed in the body — proves JWT verification,
# token_version checks and user serialization all work; a wrong JWT
# secret (e.g. rotated on one replica but not another) would still issue
# tokens at login yet fail here. Call only after a successful login.
authz_check() {  # $1=access_token $2=expected username
    http GET /api/auth/me -H "Authorization: Bearer $1"
    if [ "$CODE" = "200" ] && body_has "$2"; then
        ok "GET /api/auth/me with Bearer token -> 200 (identity: $2)"
    else
        bad "GET /api/auth/me with Bearer token -> $CODE (expected 200 identifying $2) — token issued but identity unverifiable: check JWT secret consistency / user serialization"
    fi
}

if [ "$CODE" = "201" ]; then
    # 注册端点对成功与冲突返回同一 MessageResponse（防枚举），不再下发令牌；
    # 真实注册由下面的登录步骤验证。
    ok "POST /api/auth/register -> 201 (uniform anti-enumeration response)"
    auth_via_login "$REG_USER" "$REG_PASS"
    if [ "$CODE" = "200" ] && [ -n "${_LT:-}" ]; then
        ok "POST /api/auth/login -> 200 with access token (fresh user)"
        authz_check "$_LT" "$REG_USER"
    elif body_has 'pending_token'; then
        skip "login returned 2FA challenge — TOTP cannot be automated by smoke; verify manually"
    else
        bad "login for freshly registered user -> $CODE — auth pipeline broken (JWT config / tenant bootstrap)"
    fi
elif [ "$CODE" = "400" ] || [ "$CODE" = "403" ] || [ "$CODE" = "422" ] || [ "$CODE" = "429" ]; then
    # Captcha required (422), registration closed (403), rate limited (429):
    # deployment policy, not an outage. Fall back to admin login if given.
    if [ -n "$ADMIN_USER" ] && [ -n "$ADMIN_PASS" ]; then
        auth_via_login "$ADMIN_USER" "$ADMIN_PASS"
        if [ "$CODE" = "200" ] && [ -n "${_LT:-}" ]; then
            skip "register -> $REG_CODE (captcha/registration policy); admin login PASS instead"
            authz_check "$_LT" "$ADMIN_USER"
        elif body_has 'pending_token'; then
            skip "register -> $REG_CODE and admin account has 2FA — verify admin login manually"
        else
            bad "register -> $REG_CODE and admin login -> $CODE — auth pipeline broken (check admin credentials/JWT config)"
        fi
    else
        skip "register -> $REG_CODE (captcha required / registration closed / rate limit) — pass --admin-user/--admin-pass to smoke auth via admin login"
    fi
else
    bad "POST /api/auth/register -> $CODE (unexpected) — registration endpoint broken or proxy misrouting POST bodies"
fi

head_ "Static frontend"
# 5. Root path must serve the SPA (single-port mode: RUBBISH_STATIC_DIR
# set, index.html returned) or, in API-only mode, the API banner JSON.
# A non-200 means the static mount points at a missing/wrong dist directory
# and users see an error instead of the app.
http GET /
if [ "$CODE" = "200" ] && body_has_regex '<html|rubbish api'; then
    ok "GET / -> 200 with HTML or API banner"
else
    bad "GET / -> $CODE without HTML — static serving broken (RUBBISH_STATIC_DIR wrong or dist missing)"
fi

printf '\n\033[36mSummary\033[0m  pass=%s skip=%s fail=%s\n' "$PASS" "$SKIP" "$FAIL"
if [ "$FAIL" -eq 0 ]; then
    printf '\033[32mSmoke PASSED.\033[0m\n'
    exit 0
fi
printf '\033[31mSmoke FAILED — %d check(s) must be investigated before go-live.\033[0m\n' "$FAIL"
exit 1
