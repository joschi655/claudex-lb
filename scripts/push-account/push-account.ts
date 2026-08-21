#!/usr/bin/env bun
// push-account.ts — hand this Mac's live Claude Code credential to claudex-lb.
//
// Replaces the old switcher's "Repair from Mac", which scp'd credential files to
// a path on ubuntu that nothing reads any more. claudex-lb ingests credentials
// only through POST /api/accounts/import, which is what this does.
//
// Usage:
//   bun scripts/push-account/push-account.ts --dry-run     # inspect, push nothing
//   bun scripts/push-account/push-account.ts               # push the live account
//   bun scripts/push-account/push-account.ts --from-backup a@b.c  # push a non-active account
//   bun scripts/push-account/push-account.ts --email a@b.c # override the identity
//
// Setup is shared with the SwiftBar plugin:
//   ~/.config/claudex-lb/menubar.json  -> {"baseUrl": "..."}
//   security add-generic-password -s claudex-lb-dashboard -a menubar -w '<pw>'
//
// Handover semantics: after a push the proxy owns this credential chain. Anything
// on this Mac that still rotates the same chain will strand one side or the other,
// because Claude refresh tokens are single-use. Two *separate* logins are fine; one
// chain in two custodians is not.

import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const CFG_DIR = join(homedir(), ".config", "claudex-lb");
const CFG_PATH = join(CFG_DIR, "menubar.json");
const COOKIE_PATH = join(CFG_DIR, "menubar-session.cookie");
const CLAUDE_JSON = join(homedir(), ".claude.json");
const KEYCHAIN_LABEL = "Claude Code-credentials";

interface Config {
  baseUrl: string;
  password?: string;
}

interface ClaudeAiOauth {
  accessToken?: string;
  refreshToken?: string;
  expiresAt?: number;
  refreshTokenExpiresAt?: number;
  scopes?: string[];
  subscriptionType?: string;
}

function die(msg: string, ...detail: string[]): never {
  console.error(`✗ ${msg}`);
  for (const line of detail) console.error(`  ${line}`);
  process.exit(1);
}

function loadConfig(): Config {
  if (!existsSync(CFG_PATH)) {
    die(`missing ${CFG_PATH}`, `printf '{"baseUrl": "https://proxy.example.com"}' > ${CFG_PATH}`);
  }
  let cfg: Config;
  try {
    cfg = JSON.parse(readFileSync(CFG_PATH, "utf8"));
  } catch {
    die(`${CFG_PATH} is not valid JSON`);
  }
  if (!cfg.baseUrl) die(`${CFG_PATH} needs "baseUrl"`);
  cfg.baseUrl = cfg.baseUrl.replace(/\/+$/, "");
  return cfg;
}

function resolvePassword(cfg: Config): string {
  const res = spawnSync("/usr/bin/security", ["find-generic-password", "-s", "claudex-lb-dashboard", "-w"], {
    encoding: "utf8",
    timeout: 5000,
  });
  const pw = (res.status === 0 ? res.stdout.trim() : "") || cfg.password || "";
  if (!pw) {
    die(
      "dashboard password not found",
      "security add-generic-password -s claudex-lb-dashboard -a menubar -w '<pw>'",
    );
  }
  return pw;
}

function readCookie(): string | null {
  try {
    const c = readFileSync(COOKIE_PATH, "utf8").trim();
    return c.length > 0 ? c : null;
  } catch {
    return null;
  }
}

function writeCookie(cookie: string): void {
  mkdirSync(CFG_DIR, { recursive: true });
  writeFileSync(COOKIE_PATH, cookie, { mode: 0o600 });
  chmodSync(COOKIE_PATH, 0o600);
}

async function login(cfg: Config): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${cfg.baseUrl}/api/dashboard-auth/password/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: resolvePassword(cfg) }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    die(`${cfg.baseUrl} unreachable`);
  }
  if (!res.ok) die(`dashboard login failed (HTTP ${res.status})`, "check the claudex-lb-dashboard keychain entry");
  const match = (res.headers.get("set-cookie") ?? "").match(/codex_lb_dashboard_session=([^;]+)/);
  if (!match) die("login returned no session cookie");
  const cookie = `codex_lb_dashboard_session=${match[1]}`;
  writeCookie(cookie);
  return cookie;
}

async function apiFetch(cfg: Config, path: string, init: RequestInit = {}, retried = false): Promise<any> {
  const cookie = readCookie() ?? (await login(cfg));
  let res: Response;
  try {
    res = await fetch(`${cfg.baseUrl}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), Cookie: cookie },
      signal: AbortSignal.timeout(30_000),
    });
  } catch (err) {
    die(`${cfg.baseUrl}${path} failed`, String(err));
  }
  if (res.status === 401 && !retried) {
    await login(cfg);
    return apiFetch(cfg, path, init, true);
  }
  if (!res.ok) die(`HTTP ${res.status} on ${path}`, (await res.text()).slice(0, 300));
  return res.status === 204 ? null : res.json();
}

// The keychain blob is sometimes hex-encoded and always carries unrelated keys
// (mcpOAuth). Decode defensively, then VALIDATE — never push something that only
// looks credential-shaped. A blob without claudeAiOauth is exactly what broke the
// old switcher: it treated the miss as "account dead" and restored a stale copy.
function readLiveCredential(): { oauth: ClaudeAiOauth; otherKeys: string[] } {
  const res = spawnSync("/usr/bin/security", ["find-generic-password", "-l", KEYCHAIN_LABEL, "-w"], {
    encoding: "utf8",
    timeout: 10_000,
  });
  if (res.status !== 0 || !res.stdout.trim()) {
    die(`no keychain item labelled "${KEYCHAIN_LABEL}"`, "log in with `claude login` first");
  }
  let text = res.stdout.trim();
  if (!text.startsWith("{") && /^[0-9a-fA-F]+$/.test(text)) {
    const decoded = Buffer.from(text, "hex").toString("utf8");
    if (decoded.trimStart().startsWith("{")) text = decoded;
  }
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(text);
  } catch {
    die("keychain item is not JSON — refusing to push");
  }
  const oauth = parsed.claudeAiOauth as ClaudeAiOauth | undefined;
  if (!oauth || typeof oauth !== "object") {
    die(
      "keychain item has no claudeAiOauth block — refusing to push",
      `top-level keys: ${Object.keys(parsed).join(", ") || "(none)"}`,
      "this is the state the old switcher misread as a dead account; run `claude login`",
    );
  }
  if (!oauth.accessToken) die("claudeAiOauth has no accessToken — refusing to push");
  if (!oauth.refreshToken) {
    die(
      "claudeAiOauth has no refreshToken — refusing to push",
      "without one the proxy would store this as a static key it can never refresh",
    );
  }
  const otherKeys = Object.keys(parsed).filter((k) => k !== "claudeAiOauth");
  return { oauth, otherKeys };
}

// Push a non-active account without disturbing the live session. The switcher keeps
// a per-account bundle at ~/.claude-keychain-<email>.json; its email is unambiguous
// (it is the filename), so no identity cross-check is needed. Safe only because
// nothing on this Mac rotates these any more — the daemon is disabled and the
// menubar's refresh-usage-cache kick is off.
function readBackupCredential(email: string): { oauth: ClaudeAiOauth; otherKeys: string[] } {
  const path = join(homedir(), `.claude-keychain-${email}.json`);
  if (!existsSync(path)) die(`no backup at ${path}`);
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    die(`${path} is not valid JSON`);
  }
  const oauth = parsed.claudeAiOauth as ClaudeAiOauth | undefined;
  if (!oauth?.accessToken) die(`${path} has no claudeAiOauth.accessToken — refusing to push`);
  if (!oauth.refreshToken) die(`${path} has no refreshToken — refusing to push`);
  return { oauth, otherKeys: Object.keys(parsed).filter((k) => k !== "claudeAiOauth") };
}

// Real Claude Code exports carry no email. Without one the import mints a synthetic
// @imported.local address, and anthropic slot identity is (provider, email) — so a
// synthetic address can never dedupe and every push would add a duplicate row.
//
// The identity lives in ~/.claude.json while the token lives in the keychain: two
// files, two writers. Claude Code writes both on login and the switcher restores
// both together, so they normally agree — but a half-applied swap would mean
// pushing one account's chain under another account's name, which would overwrite
// a healthy row on the proxy. verifyIdentity() below refuses that.
function resolveIdentity(override?: string): { email: string; accountUuid?: string } {
  let email: string | undefined;
  let accountUuid: string | undefined;
  try {
    const claudeJson = JSON.parse(readFileSync(CLAUDE_JSON, "utf8"));
    const oa = claudeJson?.oauthAccount ?? {};
    if (typeof oa.emailAddress === "string" && oa.emailAddress.includes("@")) email = oa.emailAddress;
    if (typeof oa.accountUuid === "string") accountUuid = oa.accountUuid;
  } catch {
    /* fall through */
  }
  if (override) return { email: override, accountUuid };
  if (email) return { email, accountUuid };
  return die(
    "could not resolve the account email",
    `expected oauthAccount.emailAddress in ${CLAUDE_JSON}`,
    "pass --email <address> to override",
  );
}

// Cross-check the live token against the on-disk backup for the resolved email.
// Not a fully independent oracle (the switcher writes that backup from the same
// keychain), but it catches the realistic failure: keychain swapped without
// ~/.claude.json following, or vice versa.
function verifyIdentity(email: string, liveAccessToken: string, force: boolean): void {
  const backupPath = join(homedir(), `.claude-keychain-${email}.json`);
  if (!existsSync(backupPath)) return;
  let backupToken: string | undefined;
  try {
    backupToken = JSON.parse(readFileSync(backupPath, "utf8"))?.claudeAiOauth?.accessToken;
  } catch {
    return;
  }
  if (!backupToken || backupToken === liveAccessToken) return;
  const msg = [
    `the live keychain token does not match the backup for ${email}`,
    `backup: ${backupPath}`,
    "the active account may have been swapped without ~/.claude.json following —",
    "pushing now could overwrite a different account's row on the proxy",
    "re-run `claude login` for the account you mean, or pass --force if you are sure",
  ];
  if (!force) die("identity cross-check failed", ...msg);
  console.warn(`⚠ identity cross-check failed (--force): ${msg[0]}`);
}

// Record the handover so the Mac stops rotating this chain. claude-auto-switch.sh
// checks this file at its single rotation choke point (refresh_backup_token).
const PROXY_OWNED = join(homedir(), ".claude", "proxy-owned-accounts.txt");

function markProxyOwned(email: string): void {
  let lines: string[] = [];
  try {
    lines = readFileSync(PROXY_OWNED, "utf8").split("\n").filter((l) => l.trim().length > 0);
  } catch {
    /* first entry */
  }
  if (lines.includes(email)) return;
  lines.push(email);
  writeFileSync(PROXY_OWNED, lines.join("\n") + "\n", { mode: 0o600 });
}

function releaseProxyOwned(email: string): void {
  let lines: string[] = [];
  try {
    lines = readFileSync(PROXY_OWNED, "utf8").split("\n").filter((l) => l.trim().length > 0);
  } catch {
    console.log(`${email} was not marked proxy-owned`);
    return;
  }
  const kept = lines.filter((l) => l !== email);
  writeFileSync(PROXY_OWNED, kept.length ? kept.join("\n") + "\n" : "", { mode: 0o600 });
  console.log(`✓ released ${email} — this Mac may rotate its token again`);
  console.log("  Remove it from the proxy too, or both sides will fight over the chain.");
}

function fmtTs(v?: number): string {
  if (!v) return "—";
  const ms = v > 1e12 ? v : v * 1000;
  return new Date(ms).toISOString().replace("T", " ").slice(0, 19) + "Z";
}

function expired(v?: number): boolean {
  if (!v) return false;
  return (v > 1e12 ? v : v * 1000) < Date.now();
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const dryRun = argv.includes("--dry-run");

  const emailIdx = argv.indexOf("--email");
  const emailOverride = emailIdx >= 0 ? argv[emailIdx + 1] : undefined;

  const releaseIdx = argv.indexOf("--release");
  if (releaseIdx >= 0) {
    const target = argv[releaseIdx + 1];
    if (!target) die("--release needs an email address");
    releaseProxyOwned(target);
    return;
  }

  const backupIdx = argv.indexOf("--from-backup");
  const fromBackup = backupIdx >= 0 ? argv[backupIdx + 1] : undefined;
  if (backupIdx >= 0 && !fromBackup) die("--from-backup needs an email address");

  const cfg = loadConfig();
  let oauth: ClaudeAiOauth;
  let otherKeys: string[];
  let email: string;
  let accountUuid: string | undefined;
  let source: string;

  if (fromBackup) {
    ({ oauth, otherKeys } = readBackupCredential(fromBackup));
    email = fromBackup;
    source = `backup ~/.claude-keychain-${fromBackup}.json`;
  } else {
    ({ oauth, otherKeys } = readLiveCredential());
    ({ email, accountUuid } = resolveIdentity(emailOverride));
    verifyIdentity(email, oauth.accessToken!, argv.includes("--force"));
    source = "live keychain";
  }

  console.log(`account            ${email}`);
  console.log(`source             ${source}`);
  console.log(`accountUuid        ${accountUuid ?? "—"}`);
  console.log(`plan               ${oauth.subscriptionType ?? "unknown"}`);
  console.log(`access expires     ${fmtTs(oauth.expiresAt)}${expired(oauth.expiresAt) ? "  (EXPIRED)" : ""}`);
  console.log(`refresh expires    ${fmtTs(oauth.refreshTokenExpiresAt)}`);
  console.log(`scopes             ${(oauth.scopes ?? []).join(" ") || "—"}`);
  if (otherKeys.length) console.log(`ignored blob keys  ${otherKeys.join(", ")}`);
  console.log(`target             ${cfg.baseUrl}`);

  if (expired(oauth.refreshTokenExpiresAt)) {
    die("refresh token is past its expiry — run `claude login` before pushing");
  }

  if (dryRun) {
    console.log("\n(dry run — nothing pushed)");
    return;
  }

  // Only claudeAiOauth travels. mcpOAuth and friends are unrelated local state.
  const payload = JSON.stringify({ email, claudeAiOauth: oauth });
  const form = new FormData();
  form.append("auth_json", new Blob([payload], { type: "application/json" }), "auth.json");

  const result = await apiFetch(cfg, "/api/accounts/import", { method: "POST", body: form });
  console.log(`\n✓ pushed — account_id=${result.accountId ?? result.account_id} status=${result.status}`);
  markProxyOwned(email);
  console.log(`✓ marked proxy-owned — this Mac will no longer rotate ${email}`);

  // No probe step: /api/accounts/{id}/probe calls _require_openai_provider and
  // rejects anthropic rows. Verify by sending real traffic through the proxy and
  // looking for an anthropic-* account_id in request_logs.
  console.log(
    `\nThe proxy now owns this chain. Do not let anything on this Mac rotate ${email} again —\n` +
      "point Claude Code at the proxy instead of logging in locally.",
  );
}

await main();
