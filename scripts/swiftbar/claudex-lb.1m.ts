#!/bin/bash
// 2>/dev/null; for b in "$HOME/.bun/bin/bun" /opt/homebrew/bin/bun /usr/local/bin/bun; do [ -x "$b" ] && exec "$b" "$0" "$@"; done; echo "⇄ bun?"; echo "---"; echo "bun not found — install from https://bun.sh"; exit 0

// <xbar.title>claudex-lb account switcher</xbar.title>
// <xbar.desc>Claude + Codex sections: shows which account claudex-lb will serve the next request from, per provider (+quota stats), pins accounts manually, restarts Claude 5h windows, and switches Claude Code between the proxy and a local login.</xbar.desc>
// <xbar.dependencies>bun</xbar.dependencies>
//
// SwiftBar plugin for claudex-lb. Bash/TypeScript polyglot: SwiftBar runs it
// as bash, the header execs bun on this same file, bun runs the TypeScript
// (the .ts extension is load-bearing — bun picks its loader by extension).
//
// Setup (one-time):
//   mkdir -p ~/.config/claudex-lb
//   printf '{"baseUrl": "https://codex-proxy.aiwerke.de"}' > ~/.config/claudex-lb/menubar.json
//   chmod 600 ~/.config/claudex-lb/menubar.json
//   security add-generic-password -s claudex-lb-dashboard -a menubar -w '<dashboard password>'
//   ln -sf "$(pwd)/scripts/swiftbar/claudex-lb.1m.ts" ~/Library/Application\ Support/SwiftBar/Plugins/
//
// The password may alternatively live in menubar.json as "password" (keychain wins if both).
// Subcommands (invoked by the menu itself):
//   switch <account_id>            make the pool serve this account first
//   auto [openai|anthropic]        back to balancing: un-pause + clear burn-first
//   warmup <account_id>            open a fresh Claude 5h window now (one-token ping)
//   warmup-all                     same, for every eligible Claude account
//   autowarm <account_id> <on|off> per-account automatic restart when a window ends
//   autowarm-all <on|off>          the server-wide automatic-restart switch
//   login                          add a Claude account: runs Anthropic's OAuth
//                                  flow in a Terminal window and imports the
//                                  result (needs a TTY; nothing local is touched)
//   route <proxy|local>            point Claude Code at the proxy, or at its local login
//   pace <account_id> <pct|clear>  pace-diagonal margin for the 5h window
//   prereset <account_id> <min|clear>  serve only in the last N min before reset
//   menu-blocks                    #BEGIN:-separated blocks the live
//                                  proxy-status menu embeds (silent + exit 1
//                                  when the server is unreachable)
//   claude-menu                    the same data as one standalone block
//
// Provider scoping happens CLIENT-SIDE on the `provider` field of every
// account: deployed servers may ignore the ?provider= query param, so pinning
// inside one section never touches the other provider's accounts.

import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { createInterface } from "node:readline";

const CFG_DIR = join(homedir(), ".config", "claudex-lb");
const CFG_PATH = join(CFG_DIR, "menubar.json");
const COOKIE_PATH = join(CFG_DIR, "menubar-session.cookie");
const SELF = process.argv[1] ?? "";

// Claude Code's live settings plus the profile that carries the proxy env block.
// `route` edits the live file the same way the SAP-HAI switcher does: top-level
// keys from the profile are applied, live-only keys (PAI hooks) are preserved.
const CLAUDE_DIR = join(homedir(), ".claude");
const CLAUDE_SETTINGS = join(CLAUDE_DIR, "settings.json");
const CLAUDE_PROXY_PROFILE = join(CLAUDE_DIR, "settings-personal.json");
const CLAUDE_JSON = join(homedir(), ".claude.json");
// The env keys that make Claude Code talk to claudex-lb instead of Anthropic.
// _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL is in the set because a proxied
// base URL otherwise costs Opus its native 1M context window.
const PROXY_ENV_KEYS = [
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN",
  "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL",
] as const;

const PROVIDERS = [
  { key: "anthropic", label: "Claude", icon: "✳" },
  { key: "openai", label: "Codex", icon: "⇄" },
] as const;
type ProviderKey = (typeof PROVIDERS)[number]["key"];

interface Config {
  baseUrl: string;
  password?: string;
}

interface AccountUsage {
  primaryRemainingPercent?: number | null;
  secondaryRemainingPercent?: number | null;
  monthlyRemainingPercent?: number | null;
}

interface RequestUsage {
  requestCount?: number;
  totalTokens?: number;
  totalCostUsd?: number;
}

// A usage-based seat's dollar budget. Such a seat reports no rolling window, so
// this is the only quota figure it has.
interface SpendBudget {
  usedPercent: number;
  used?: number | null;
  limit?: number | null;
  remaining?: number | null;
  currency?: string | null;
  resetAt?: string | null;
}

// The top-up pool behind the plan's own allowance. Reported even when switched
// off, so `enabled` is what decides whether the seat can spend from it.
interface ExtraCredits {
  enabled: boolean;
  usedPercent: number;
  used?: number | null;
  limit?: number | null;
  remaining?: number | null;
  currency?: string | null;
}

// Last warm-up attempt for an account, as recorded by the server.
interface AccountLimitWarmup {
  window: string;
  resetAt: number;
  status: string;
  model: string;
  attemptedAt: string;
  completedAt?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
}

interface Account {
  accountId: string;
  provider?: string;
  email: string;
  alias?: string | null;
  displayName?: string;
  planType?: string;
  status: string;
  routingPolicy?: string;
  pinned?: boolean;
  paceMarginPrimaryPct?: number | null;
  preResetWindowMinutes?: number | null;
  usage?: AccountUsage | null;
  resetAtPrimary?: string | null;
  resetAtSecondary?: string | null;
  resetAtMonthly?: string | null;
  requestUsage?: RequestUsage | null;
  quotaKind?: "auto" | "subscription" | "usage_based";
  spendBudget?: SpendBudget | null;
  extraCredits?: ExtraCredits | null;
  limitWarmupEnabled?: boolean;
  limitWarmup?: AccountLimitWarmup | null;
}

interface RequestLogEntry {
  requestedAt: string;
  accountId?: string | null;
  model: string;
  status: string;
}

interface NextUpEntry {
  provider: string;
  accountId?: string | null;
  certain?: boolean;
  errorMessage?: string | null;
}

// Set for subcommands that run in a Terminal the operator is watching rather
// than behind the menu. SwiftBar's contract is "print a menu and exit 0", which
// is exactly wrong there: `login` holds a freshly minted, single-use Anthropic
// refresh token by the time it talks to the proxy, and an exit 0 would drop it
// while reporting success.
let terminalMode = false;

function fail(title: string, lines: string[]): never {
  if (terminalMode) {
    // Menu actions ("Aktualisieren | refresh=true") are instructions to
    // SwiftBar, not to a reader; only the prose survives.
    const prose = lines.filter((l) => !l.includes("refresh=true")).map((l) => l.split(" | ")[0]);
    throw new Error(prose.join(" — ") || "failed");
  }
  console.log(`⇄ ${title}`);
  console.log("---");
  for (const line of lines) console.log(line);
  process.exit(0);
}

function loadConfig(): Config {
  if (!existsSync(CFG_PATH)) {
    fail("setup", [
      "claudex-lb menubar: Konfiguration fehlt | color=#e74c3c",
      `Erwartet: ${CFG_PATH}`,
      'Anlegen: printf \'{"baseUrl": "https://codex-proxy.aiwerke.de"}\' > ~/.config/claudex-lb/menubar.json',
      "Passwort: security add-generic-password -s claudex-lb-dashboard -a menubar -w '<pw>'",
    ]);
  }
  let cfg: Config;
  try {
    cfg = JSON.parse(readFileSync(CFG_PATH, "utf8"));
  } catch {
    fail("cfg!", [`${CFG_PATH} ist kein gültiges JSON | color=#e74c3c`]);
  }
  if (!cfg.baseUrl) fail("cfg!", ['menubar.json braucht "baseUrl" | color=#e74c3c']);
  cfg.baseUrl = cfg.baseUrl.replace(/\/+$/, "");
  return cfg;
}

function keychainPassword(): string | null {
  // timeout guards against a keychain ACL prompt blocking the render loop —
  // a timed-out or denied lookup falls through to cfg.password.
  const res = spawnSync("/usr/bin/security", ["find-generic-password", "-s", "claudex-lb-dashboard", "-w"], {
    encoding: "utf8",
    timeout: 5000,
  });
  const pw = res.status === 0 ? res.stdout.trim() : "";
  return pw.length > 0 ? pw : null;
}

function resolvePassword(cfg: Config): string {
  const pw = keychainPassword() ?? cfg.password ?? "";
  if (!pw) {
    fail("🔐", [
      "Dashboard-Passwort fehlt | color=#e74c3c",
      "Keychain: security add-generic-password -s claudex-lb-dashboard -a menubar -w '<pw>'",
      `…oder "password" in ${CFG_PATH}`,
    ]);
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

// Memoize the in-flight login so concurrent cold-cookie callers share one POST.
let loginInFlight: Promise<string> | null = null;

async function login(cfg: Config): Promise<string> {
  if (loginInFlight) return loginInFlight;
  loginInFlight = doLogin(cfg).finally(() => {
    loginInFlight = null;
  });
  return loginInFlight;
}

async function doLogin(cfg: Config): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${cfg.baseUrl}/api/dashboard-auth/password/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: resolvePassword(cfg) }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    fail("⚠️", [`${cfg.baseUrl} nicht erreichbar | color=#e67e22`, "Aktualisieren | refresh=true"]);
  }
  if (!res.ok) {
    fail("🔐", [
      `Login fehlgeschlagen (HTTP ${res.status}) | color=#e74c3c`,
      "Passwort prüfen (Keychain: claudex-lb-dashboard)",
      "Aktualisieren | refresh=true",
    ]);
  }
  const setCookie = res.headers.get("set-cookie") ?? "";
  const match = setCookie.match(/codex_lb_dashboard_session=([^;]+)/);
  if (!match) fail("🔐", ["Login ohne Session-Cookie beantwortet | color=#e74c3c"]);
  const cookie = `codex_lb_dashboard_session=${match[1]}`;
  writeCookie(cookie);
  return cookie;
}

async function apiFetch(cfg: Config, path: string, init: RequestInit = {}, retried = false, soft = false): Promise<any> {
  const cookie = readCookie() ?? (await login(cfg));
  let res: Response;
  try {
    res = await fetch(`${cfg.baseUrl}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), Cookie: cookie },
      signal: AbortSignal.timeout(15_000),
    });
  } catch (err) {
    // soft callers (non-essential data) get the error to handle; hard callers
    // render the offline state.
    if (soft) throw err instanceof Error ? err : new Error(String(err));
    fail("⚠️", [`${cfg.baseUrl} nicht erreichbar | color=#e67e22`, "Aktualisieren | refresh=true"]);
  }
  if (res.status === 401 && !retried) {
    await login(cfg);
    return apiFetch(cfg, path, init, true, soft);
  }
  if (!res.ok) {
    const body = (await res.text()).slice(0, 400);
    throw new Error(errorMessage(res.status, path, body));
  }
  return res.status === 204 ? null : res.json();
}

// Dashboard errors arrive as {"error": {"code", "message"}}; show the message
// alone so a notification reads like a sentence instead of a JSON dump.
function errorMessage(status: number, path: string, body: string): string {
  try {
    const parsed = JSON.parse(body);
    const msg = parsed?.error?.message ?? parsed?.detail ?? parsed?.message;
    if (typeof msg === "string" && msg.length > 0) return msg;
  } catch {
    // fall through to the raw body
  }
  return `HTTP ${status} on ${path}: ${body.slice(0, 200)}`;
}

// Actions run headless from the menu, so their only channel is a notification.
// Strip newlines, truncate, then escape backslashes before quotes so the
// (semi-trusted, server-derived) text cannot break the AppleScript.
function notify(message: string): void {
  const msg = message
    .replace(/[\r\n]+/g, " ")
    .slice(0, 200)
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"');
  spawnSync("/usr/bin/osascript", ["-e", `display notification "${msg}" with title "claudex-lb switcher"`]);
}

function providerOf(acc: Account): string {
  return acc.provider ?? "openai";
}

// The pin has its own field. A server that has not been upgraded (or whose
// migration has not run) still reports it as a routing policy, and reading only
// the new field there would show "Auto" over a hard-pinned pool and make the
// Auto button clear nothing.
function isPinned(acc: Account): boolean {
  return acc.pinned === true || acc.routingPolicy === "pinned";
}

// soft=true is for the embedded block: it must raise instead of rendering the
// plugin-level offline state into somebody else's menu.
async function allAccounts(cfg: Config, soft = false): Promise<Account[]> {
  const data = await apiFetch(cfg, "/api/accounts?provider=all", {}, false, soft);
  return data?.accounts ?? [];
}

// Newest request per provider, resolved client-side via the account map
// (deployed servers may ignore the ?provider= filter on request-logs).
// limit=100: both providers share one window, so a busy provider must not
// crowd the quiet one out. Purely cosmetic data — a failure here must never
// take down the accounts/pinning menu, so it degrades to [].
async function recentRequests(cfg: Config): Promise<RequestLogEntry[]> {
  try {
    const data = await apiFetch(cfg, "/api/request-logs?limit=100", {}, false, true);
    return data?.requests ?? [];
  } catch {
    return [];
  }
}

// Which account each provider would route the *next* request to. The pool runs
// its own selector as a dry run, so this survives a pin, a pause, or a limit --
// all the moments the newest request log row goes stale while still looking
// authoritative. Degrades to [] like the request log: the accounts and pinning
// menu must render without it.
async function nextUpAccounts(cfg: Config): Promise<NextUpEntry[]> {
  try {
    const data = await apiFetch(cfg, "/api/accounts/next-up", {}, false, true);
    return data?.nextUp ?? [];
  } catch {
    return [];
  }
}

function lastFor(requests: RequestLogEntry[], accounts: Account[]): RequestLogEntry | null {
  const ids = new Set(accounts.map((a) => a.accountId));
  return requests.find((r) => r.accountId && ids.has(r.accountId)) ?? null;
}

const PAUSABLE = new Set(["active", "rate_limited", "quota_exceeded"]);

// "Switch to this account" sets the account's pin, which the server treats as a
// hard override: while the account can serve it is the only candidate, and when
// it cannot the pool falls back to its automatic rules on its own. The others
// stay live rather than being paused, so failover has somewhere to go and their
// five-hour windows can still be restarted.
//
// The pin is its own field, so it no longer overwrites the routing policy --
// switching to a seat and back leaves a `preserve` seat still preserved.
//
// Reactivating the provider's paused accounts used to be part of this, back
// when pinning meant pausing everything else. It no longer is: a hard pin does
// not need the pool cleared, and un-pausing a seat somebody parked on purpose
// is a surprise, not a service.
async function cmdSwitch(cfg: Config, targetId: string): Promise<void> {
  const accounts = await allAccounts(cfg);
  const target = accounts.find((a) => a.accountId === targetId);
  if (!target) throw new Error(`Account ${targetId} not found`);
  if (target.status !== "active" && target.status !== "paused") {
    throw new Error(`Target account is ${target.status} — it cannot serve requests`);
  }
  const scope = providerOf(target);
  const failures: string[] = [];
  // Pin first, reactivate second. The reverse order leaves a half-applied
  // switch behind when the pin write fails -- against a server too old to have
  // the endpoint, the account would be un-paused for nothing.
  await setPinned(cfg, targetId, true);
  if (target.status === "paused") {
    // A pin on a paused account would never fire, so it has to come back.
    try {
      await apiFetch(cfg, `/api/accounts/${targetId}/reactivate`, { method: "POST" });
    } catch (err) {
      failures.push(`reactivate ${name(target)}: ${String(err).slice(0, 50)}`);
    }
  }
  // The server clears the provider's previous *pin* itself. A leftover
  // burn-first mark is a different thing — an old pin from before the pin
  // existed — and would go on quietly outranking `normal`, so clear it here.
  for (const acc of accounts) {
    if (acc.accountId === targetId || providerOf(acc) !== scope) continue;
    if (acc.routingPolicy !== "burn_first") continue;
    try {
      await setRoutingPolicy(cfg, acc.accountId, "normal");
    } catch (err) {
      failures.push(`${name(acc)}: ${String(err).slice(0, 50)}`);
    }
  }
  if (failures.length > 0) throw new Error(`Pinned ${name(target)}, but: ${failures.join("; ")}`);
  notify(`${name(target)} now serves everything until it runs out`);
}

async function setPinned(cfg: Config, accountId: string, pinned: boolean): Promise<void> {
  try {
    await apiFetch(cfg, `/api/accounts/${accountId}/pin`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    });
  } catch (err) {
    // The pin moved off routing_policy and onto its own endpoint. A proxy that
    // predates that has no route here, and answers 405 (the dashboard's
    // GET-only SPA fallback catches the path) or 404. Say so outright --
    // otherwise the operator reads "Method Not Allowed" as a broken account.
    const message = String(err);
    if (/\b40[45]\b|not found|method not allowed/i.test(message)) {
      throw new Error("This proxy is older than the pin endpoint — deploy claudex-lb on the server first");
    }
    throw err;
  }
}

async function setRoutingPolicy(cfg: Config, accountId: string, policy: string): Promise<void> {
  await apiFetch(cfg, `/api/accounts/${accountId}/routing-policy`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ routingPolicy: policy }),
  });
}

// The server-wide warm-up switch. Cosmetic for the render path (a failure
// degrades to "unknown"), authoritative for the toggle.
async function fetchSettings(cfg: Config): Promise<{ limitWarmupEnabled?: boolean } | null> {
  try {
    return await apiFetch(cfg, "/api/settings", {}, false, true);
  } catch {
    return null;
  }
}

// An account is warmable when the server would accept a trigger: Claude, able
// to serve, and with a five-hour window on record to reopen.
function warmable(acc: Account): boolean {
  if (providerOf(acc) !== "anthropic") return false;
  if (acc.status !== "active" && acc.status !== "paused") return false;
  return acc.resetAtPrimary != null;
}

async function cmdWarmup(cfg: Config, accountId: string): Promise<void> {
  const res = await apiFetch(cfg, `/api/accounts/${accountId}/limit-warmup/trigger`, { method: "POST" });
  notify(warmupOutcome(res));
}

function warmupOutcome(res: any): string {
  if (res?.success) {
    const ms = res?.latencyMs != null ? ` · ${res.latencyMs} ms` : "";
    return `5h window opened (${res?.model ?? "?"}${ms})`;
  }
  if (res?.sent === false) return "A warm-up for this account is already in flight";
  return `Warm-up failed: ${res?.errorMessage ?? res?.errorCode ?? "unknown error"}`;
}

async function cmdWarmupAll(cfg: Config): Promise<void> {
  const targets = (await allAccounts(cfg)).filter(warmable);
  if (targets.length === 0) throw new Error("No Claude account has a five-hour window to reopen");
  const ok: string[] = [];
  const bad: string[] = [];
  for (const acc of targets) {
    try {
      const res = await apiFetch(cfg, `/api/accounts/${acc.accountId}/limit-warmup/trigger`, { method: "POST" });
      (res?.success ? ok : bad).push(`${name(acc)}${res?.success ? "" : `: ${res?.errorCode ?? "failed"}`}`);
    } catch (err) {
      bad.push(`${name(acc)}: ${String(err).slice(0, 40)}`);
    }
  }
  const parts = [ok.length > 0 ? `opened: ${ok.join(", ")}` : "", bad.length > 0 ? `failed: ${bad.join(", ")}` : ""];
  notify(parts.filter(Boolean).join(" · "));
}

async function cmdAutoWarm(cfg: Config, accountId: string, mode: string): Promise<void> {
  const enabled = mode === "on";
  await apiFetch(cfg, `/api/accounts/${accountId}/limit-warmup`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  notify(`Automatic 5h restart ${enabled ? "on" : "off"} for this account`);
}

async function cmdAutoWarmAll(cfg: Config, mode: string): Promise<void> {
  const enabled = mode === "on";
  await apiFetch(cfg, "/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ limitWarmupEnabled: enabled }),
  });
  notify(`Automatic 5h restart ${enabled ? "on" : "off"} server-wide`);
}

// Back to load balancing: un-pause everything and drop the burn-first marking
// so selection is driven by quota and pace again.
// "The diagonal": skip an account once it has burned more than the even pace
// through its window, minus this margin. Higher margin = held back sooner.
async function cmdPace(cfg: Config, accountId: string, raw: string): Promise<void> {
  const value = raw === "clear" ? null : Number(raw);
  if (value !== null && !Number.isFinite(value)) throw new Error(`Not a percentage: ${raw}`);
  await apiFetch(cfg, `/api/accounts/${accountId}/pace-gates`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paceMarginPrimaryPct: value }),
  });
  notify(value === null ? "Pace gate cleared for this account" : `Pace margin set to ${value}%`);
}

// Hold an account back until its 5h window is about to reset, then let it serve
// so the remaining quota gets used instead of expiring.
async function cmdPreReset(cfg: Config, accountId: string, raw: string): Promise<void> {
  const value = raw === "clear" ? null : Number(raw);
  if (value !== null && !Number.isInteger(value)) throw new Error(`Not a minute count: ${raw}`);
  await apiFetch(cfg, `/api/accounts/${accountId}/pace-gates`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preResetWindowMinutes: value }),
  });
  notify(value === null ? "Pre-reset hold cleared" : `Serves only in the last ${value} min before reset`);
}

async function cmdAuto(cfg: Config, provider?: string): Promise<void> {
  const accounts = await allAccounts(cfg);
  const failures: string[] = [];
  for (const acc of accounts) {
    if (provider && providerOf(acc) !== provider) continue;
    if (acc.status === "paused") {
      try {
        await apiFetch(cfg, `/api/accounts/${acc.accountId}/reactivate`, { method: "POST" });
      } catch (err) {
        failures.push(`${name(acc)}: ${String(err).slice(0, 60)}`);
      }
    }
    // Clear both the pin and any leftover burn-first mark: "auto" means quota
    // and pace decide, and either would keep overriding that. They are separate
    // writes now, so lifting a pin no longer flattens the account's policy.
    if (isPinned(acc)) {
      try {
        await setPinned(cfg, acc.accountId, false);
      } catch (err) {
        failures.push(`${name(acc)}: ${String(err).slice(0, 60)}`);
      }
    }
    if (acc.routingPolicy === "burn_first") {
      try {
        await setRoutingPolicy(cfg, acc.accountId, "normal");
      } catch (err) {
        failures.push(`${name(acc)}: ${String(err).slice(0, 60)}`);
      }
    }
  }
  if (failures.length > 0) throw new Error(`Auto mode incomplete: ${failures.join("; ")}`);
}

// ── Claude Code routing (proxy ↔ local login) ───────────────────────────────

function readJson(path: string): any {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

// Which endpoint the next Claude Code start will use, read from the live
// settings rather than this process's own environment: a running session keeps
// whatever it started with, so the env var would answer the wrong question.
function routeMode(): "proxy" | "local" | "unknown" {
  const live = readJson(CLAUDE_SETTINGS);
  if (live === null) return "unknown";
  return live?.env?.ANTHROPIC_BASE_URL ? "proxy" : "local";
}

function proxyHost(): string {
  const url = readJson(CLAUDE_SETTINGS)?.env?.ANTHROPIC_BASE_URL;
  if (typeof url !== "string") return "";
  try {
    return new URL(url).host;
  } catch {
    return sane(url);
  }
}

// The account a local login would serve from, for the menu label only.
function localLoginEmail(): string {
  const email = readJson(CLAUDE_JSON)?.oauthAccount?.emailAddress;
  return typeof email === "string" ? sane(email) : "";
}

function cmdRoute(mode: string): void {
  const live = readJson(CLAUDE_SETTINGS);
  if (live === null) throw new Error(`${CLAUDE_SETTINGS} is missing or not valid JSON`);
  if (mode === "proxy") {
    const profile = readJson(CLAUDE_PROXY_PROFILE);
    if (profile === null) throw new Error(`${CLAUDE_PROXY_PROFILE} is missing or not valid JSON`);
    if (!profile?.env?.ANTHROPIC_BASE_URL) throw new Error("Proxy profile carries no ANTHROPIC_BASE_URL");
    // Top-level merge, not overwrite: keys that live only in settings.json
    // (hooks, statusLine) must survive the swap.
    Object.assign(live, profile);
  } else {
    const env = live.env ?? {};
    for (const key of PROXY_ENV_KEYS) delete env[key];
    live.env = env;
  }
  writeFileSync(CLAUDE_SETTINGS, `${JSON.stringify(live, null, 2)}\n`);
  notify(
    mode === "proxy"
      ? "Claude Code → claudex-lb proxy. Restart Claude Code to pick it up."
      : "Claude Code → local login. Restart Claude Code to pick it up.",
  );
}

// ── formatting ──────────────────────────────────────────────────────────────

// SwiftBar treats "|" as the title/params separator — strip it (and newlines)
// from every dynamic value that lands in a menu line.
function sane(v: string | null | undefined): string {
  return (v ?? "").replace(/[|\r\n]/g, "/");
}

function name(acc: Account): string {
  return sane(acc.alias || acc.displayName || acc.email || acc.accountId.slice(0, 8));
}

function remaining(iso: string | null | undefined): string {
  if (!iso) return "";
  const diff = Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
  if (!Number.isFinite(diff)) return "";
  if (diff <= 0) return "now";
  const d = Math.floor(diff / 86400);
  const h = Math.floor((diff % 86400) / 3600);
  const m = Math.floor((diff % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function pct(v: number | null | undefined): string {
  return v == null ? "–" : `${Math.round(v)}%`;
}

function money(v: number | null | undefined, currency: string | null | undefined): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  const symbol = currency == null || currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${v.toFixed(2)}`;
}

interface QuotaPool {
  label: string;
  /** null when the pool reports no limit, so there is no ratio to take. */
  remainingPercent: number | null;
  remaining?: number | null;
  currency?: string | null;
  spent: boolean;
  measurable: boolean;
}

// The dollar pool a usage-based seat can still spend from. A seat draws its plan
// allowance down first and only then the top-up pool behind it, so "live" is the
// first of the two with headroom. Reading only the budget reported a live
// enterprise seat as `0% left · $0.00` while $115 of its top-up sat unspent.
//
// Mirrors resolveLiveQuotaPool in the dashboard frontend; the plugin is a
// standalone script and cannot import from it.
function livePool(acc: Account | null | undefined): QuotaPool | null {
  // The plan budget's utilization is always real -- the poller only recognizes a
  // dollar bucket that states a limit. The top-up pool below is the asymmetric
  // one, where used_percent 0 doubles as "no limit set".
  const b = acc?.spendBudget;
  const budget: QuotaPool | null =
    b == null
      ? null
      : {
          label: "Budget",
          remainingPercent: Math.max(0, Math.min(100, 100 - b.usedPercent)),
          remaining: b.remaining,
          currency: b.currency,
          spent: b.usedPercent >= 100,
          measurable: true,
        };
  // A switched-off pool still carries a limit and a remainder, which is money
  // the seat cannot spend. Dropped rather than ranked below the budget.
  const e = acc?.extraCredits?.enabled === true ? acc.extraCredits : null;
  const extraMeasurable = e?.limit != null;
  const extra: QuotaPool | null =
    e == null
      ? null
      : {
          label: "Extra usage",
          remainingPercent: extraMeasurable ? Math.max(0, Math.min(100, 100 - e.usedPercent)) : null,
          remaining: e.remaining,
          currency: e.currency,
          spent: extraMeasurable && e.usedPercent >= 100,
          measurable: extraMeasurable,
        };

  // Headroom needs a limit to have headroom in. The poller stores used_percent
  // 0 for a pool with no limit -- "no ratio to take" -- and reading that as
  // "nothing spent" would claim a full pool on a seat whose state is unknown.
  if (budget != null && budget.measurable && !budget.spent) return budget;
  if (extra != null && extra.measurable && !extra.spent) return extra;
  const unmeasurable = [extra, budget].find((p) => p != null && !p.measurable);
  if (unmeasurable != null) return unmeasurable;
  return extra ?? budget;
}

function badge(acc: Account): string {
  const p =
    acc.usage?.primaryRemainingPercent ?? acc.usage?.secondaryRemainingPercent ?? acc.usage?.monthlyRemainingPercent;
  // A budget seat has no window to report a remainder for, so its badge is what
  // is left of its live pool rather than "unknown". `quotaKind` is honoured the
  // same way the web surfaces honour it: a seat an operator has declared
  // usage-based follows its pool even while stale window figures linger, so the
  // menu bar and the dashboard cannot describe one account two ways.
  const pool = p == null || acc.quotaKind === "usage_based" ? livePool(acc) : null;
  if (pool != null) {
    const left = money(pool.remaining, pool.currency);
    if (!pool.measurable) return `${pool.label.toLowerCase()} · no limit reported`;
    return `${pct(pool.remainingPercent)} left${left ? ` · ${left}` : ""}`;
  }
  const reset = remaining(acc.resetAtPrimary ?? acc.resetAtSecondary ?? acc.resetAtMonthly);
  const statusMark =
    acc.status === "paused"
      ? " ⏸"
      : acc.status === "reauth_required"
        ? " 🔑"
        : acc.status === "deactivated"
          ? " ✖︎"
          : ["rate_limited", "quota_exceeded"].includes(acc.status)
            ? " ⏳"
            : "";
  // With no usage data the core already names the status — skip the mark.
  const core = p == null ? sane(acc.status).replace(/_/g, " ") : `${pct(p)} left${reset ? ` · ${reset}` : ""}`;
  return p == null ? core : `${core}${statusMark}`;
}

function relTime(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (!Number.isFinite(diff)) return "";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function action(label: string, args: string[], extra = ""): string {
  const params = args.map((a, i) => `param${i + 1}="${a}"`).join(" ");
  return `${label} | bash="/bin/bash" ${params} terminal=false refresh=true${extra}`;
}

// ── render ──────────────────────────────────────────────────────────────────

interface Section {
  key: ProviderKey;
  label: string;
  icon: string;
  accounts: Account[];
  healthy: Account[];
  manual: boolean;
  preferred: Account | null;
  /** The account the next request lands on, per the pool's own dry run. */
  current: Account | null;
  /** False when the pool named a front-runner rather than a settled answer. */
  certain: boolean;
  /** Why nobody is next, when the pool answered that nobody is. */
  noneReason: string | null;
  last: RequestLogEntry | null;
}

function buildSection(
  def: (typeof PROVIDERS)[number],
  accounts: Account[],
  requests: RequestLogEntry[],
  nextUp: NextUpEntry[],
): Section | null {
  const mine = accounts.filter((a) => providerOf(a) === def.key);
  if (mine.length === 0) return null;
  // "healthy" (status active) drives the X/Y count and manual detection;
  // rate_limited/quota_exceeded accounts are poolable but not healthy.
  const healthy = mine.filter((a) => a.status === "active");
  const pausable = mine.filter((a) => PAUSABLE.has(a.status));
  // Manual = an explicit pin, or the legacy shape where every other account was
  // paused to force one.
  const preferred = mine.find((a) => isPinned(a) && a.status === "active") ?? null;
  const manual = preferred !== null || (healthy.length === 1 && mine.some((a) => a.status === "paused"));
  const last = lastFor(requests, mine);
  // The account named here is the one the *next* request lands on, straight
  // from the pool's own dry-run selection. The newest request log row used to
  // answer this, and it was wrong in exactly the cases worth looking at: right
  // after a pin, a pause, or a limit it goes on naming the previous account
  // until fresh traffic arrives, and on an idle pool it never catches up.
  //
  // Reading the pin as truth was the other failed attempt: a pinned account
  // still gets gated out by its own quota. The dry run settles both, because it
  // runs the same eligibility filters the real selection does.
  const answer = nextUp.find((entry) => entry.provider === def.key) ?? null;
  const nextAcc = answer?.accountId ? mine.find((a) => a.accountId === answer.accountId) : undefined;
  const lastAcc = last?.accountId ? mine.find((a) => a.accountId === last.accountId) : undefined;
  // An answer naming nobody is an answer: the pool has nothing that can serve.
  // Guessing a name there would reproduce the bug this change removes -- the
  // menu confidently naming an account that is serving nothing.
  const answered = answer != null;
  const nothingEligible = answered && !answer?.accountId;
  // Everything after `nextAcc` is the offline path: with no answer at all from
  // the server, a plausible name beats an empty menu.
  const current = nothingEligible
    ? null
    : nextAcc ||
      preferred ||
      (lastAcc && PAUSABLE.has(lastAcc.status) ? lastAcc : null) ||
      healthy[0] ||
      pausable[0] ||
      lastAcc ||
      mine[0] ||
      null;
  const certain = nextAcc != null && answer?.certain !== false;
  const noneReason = nothingEligible ? (answer?.errorMessage ?? "no account can serve") : null;
  return {
    key: def.key,
    label: def.label,
    icon: def.icon,
    accounts: mine,
    healthy,
    manual,
    preferred,
    current,
    certain,
    noneReason,
    last,
  };
}

function titlePart(s: Section): string {
  const p =
    s.current?.usage?.primaryRemainingPercent ??
    s.current?.usage?.secondaryRemainingPercent ??
    s.current?.usage?.monthlyRemainingPercent;
  return `${s.icon}${p == null ? "" : pct(p)}${s.manual ? "📌" : ""}`;
}

// Menu bar text: how much of the next account's 5h window is used, the same
// metric the account lines show, plus 📌 when the pool is pinned to one account.
// A usage-based seat has no window at all, so fall back to the least-used window
// in the pool — the one with the most room left.
function menuBarTitle(s: Section): string {
  const pin = s.manual ? "📌" : "";
  const own = usedPercent(s.current);
  if (own != null) return `${pct(own)}${pin}`;
  const pool = s.accounts
    .filter((a) => a.status !== "reauth_required" && a.status !== "deactivated")
    .map(usedPercent)
    .filter((p): p is number => p != null);
  if (pool.length > 0) return `${pct(Math.min(...pool))}${pin}`;
  return `${sane(s.current?.status ?? "?").replace(/_/g, " ")}${pin}`;
}

function usedPercent(acc: Account | null | undefined): number | null {
  const left =
    acc?.quotaKind === "usage_based"
      ? null
      : (acc?.usage?.primaryRemainingPercent ??
        acc?.usage?.secondaryRemainingPercent ??
        acc?.usage?.monthlyRemainingPercent);
  if (left != null) return 100 - left;
  // Fall back to the live pool so the icon shows a number for a seat whose quota
  // is dollars rather than a window. A seat with every pool spent reports
  // nothing: `100%` is a true statement about money nobody can spend, printed
  // where the reader is asking how much room there is. Returning null lets
  // menuBarTitle fall through to a window that still means something.
  // An unmeasurable pool contributes nothing either: `0% used` on a pool with no
  // reported limit would assert the whole section is untouched, and the title
  // takes the minimum across the pool.
  const pool = livePool(acc);
  if (pool == null || pool.spent || !pool.measurable || pool.remainingPercent == null) return null;
  return 100 - pool.remainingPercent;
}

function renderSection(s: Section, globalWarmup: boolean | null, separator = true): void {
  if (separator) console.log("---");
  const pinnedName = s.preferred ? name(s.preferred) : s.healthy.length > 0 ? name(s.healthy[0]) : "?";
  console.log(
    `${s.icon} ${s.label}: ${s.manual ? `📌 ${pinnedName} first` : `Auto · ${s.healthy.length}/${s.accounts.length} active`} | size=13`,
  );
  const cur = s.current;
  if (cur == null && s.noneReason) {
    console.log(`Next: nobody — ${s.noneReason} | color=#e67e22`);
  }
  if (cur) {
    console.log(`${s.certain ? "Next" : "Likely next"}: ${name(cur)}${cur.planType ? ` (${sane(cur.planType)})` : ""}`);
    const p5 = cur.usage?.primaryRemainingPercent;
    if (p5 != null || cur.resetAtPrimary) {
      console.log(`5h window: ${p5 == null ? "–" : `${pct(p5)} left`}${remaining(cur.resetAtPrimary) ? ` · resets ${remaining(cur.resetAtPrimary)}` : ""}`);
    }
    if (cur.usage?.secondaryRemainingPercent != null) {
      console.log(`Weekly: ${pct(cur.usage.secondaryRemainingPercent)} left${remaining(cur.resetAtSecondary) ? ` · resets ${remaining(cur.resetAtSecondary)}` : ""}`);
    }
    if (cur.spendBudget != null) {
      const b = cur.spendBudget;
      const spent = money(b.used, b.currency);
      const cap = money(b.limit, b.currency);
      const amounts = spent && cap ? ` (${spent} of ${cap})` : "";
      console.log(
        `Budget: ${b.usedPercent.toFixed(1)}% used${amounts}${remaining(b.resetAt) ? ` · resets ${remaining(b.resetAt)}` : ""}`,
      );
    }
    // Shown beside the budget rather than instead of it: once the budget is
    // spent this pool is the only thing keeping the seat serving, and its
    // remainder is the figure that answers "how much is left".
    //
    // Every seat reports the pool, most of them switched off and empty, so the
    // line appears only when it carries something: money moving through the
    // pool, or a seat that has run out of budget and could turn it on. The
    // dashboard is where a quiet, switched-off pool is still worth stating.
    const credits = cur.extraCredits;
    const budgetSpent = cur.spendBudget != null && cur.spendBudget.usedPercent >= 100;
    if (credits != null && (budgetSpent || (credits.enabled && credits.usedPercent > 0))) {
      const spent = money(credits.used, credits.currency);
      const cap = money(credits.limit, credits.currency);
      const amounts = spent && cap ? ` (${spent} of ${cap})` : "";
      console.log(
        credits.enabled
          ? `Extra usage: ${credits.usedPercent.toFixed(1)}% used${amounts}`
          : "Extra usage: off — the budget is spent",
      );
    }
    const ru = cur.requestUsage;
    if (ru && (ru.requestCount ?? 0) > 0) {
      const cost = ru.totalCostUsd != null ? ` · $${ru.totalCostUsd.toFixed(2)}` : "";
      const tok = ru.totalTokens != null ? ` · ${(ru.totalTokens / 1e6).toFixed(1)}M tok` : "";
      console.log(`Requests: ${ru.requestCount}${tok}${cost}`);
    }
  }
  if (s.last) {
    const st = (s.last.status ?? "").toLowerCase();
    const suffix = st && !["completed", "ok", "success"].includes(st) ? ` · ${sane(st)}` : "";
    const when = relTime(s.last.requestedAt);
    console.log(`Last request: ${sane(s.last.model)}${when ? ` · ${when}` : ""}${suffix}`);
  }
  console.log(`${s.label} accounts (click to serve first)`);
  for (const acc of s.accounts) {
    const isCurrent = cur != null && acc.accountId === cur.accountId;
    const mark = isPinned(acc) ? "📌" : isCurrent ? "●" : acc.status === "paused" ? "⏸" : "○";
    const line = `${mark} ${name(acc)} — ${badge(acc)}`;
    if (acc.status === "reauth_required" || acc.status === "deactivated") {
      console.log(`--${line} | color=#e74c3c`);
    } else if (acc.status !== "active" && acc.status !== "paused") {
      // rate_limited / quota_exceeded: visible but not a valid pin target
      console.log(`--${line} | color=#e67e22`);
    } else if (isPinned(acc)) {
      // Already pinned; clicking it again would do nothing.
      console.log(`--${line}`);
    } else {
      console.log(`--${action(line, [SELF, "switch", acc.accountId])}`);
    }
  }
  // Claude only: this runs Anthropic's OAuth flow. Codex accounts are added
  // through the dashboard's own ChatGPT flow, which is a different protocol
  // with a different client — one button cannot serve both.
  //
  // terminal=true because the flow has to show a URL and read a pasted code;
  // a headless action has nowhere to put either.
  if (s.key === "anthropic") {
    console.log(`--➕ Add a Claude account… | bash="/bin/bash" param1="${SELF}" param2="login" terminal=true refresh=true`);
  }
  console.log(
    action(s.manual ? `⚖️ ${s.label}: Auto (balance across all)` : `⚖️ ${s.label}: Reset to auto`, [SELF, "auto", s.key]),
  );
  if (s.key === "anthropic") renderWarmup(s, globalWarmup);
}

// Claude 5h windows: manual restarts plus the automatic one. A window opens on
// an account's first request and closes five hours later no matter what happens
// in between, so an idle account keeps a spent window alive — the restart is a
// one-token ping that starts a fresh one.
function renderWarmup(s: Section, globalWarmup: boolean | null): void {
  const active = s.accounts.filter((a) => a.status === "active");
  const targets = active.filter(warmable);
  const autoState = globalWarmup == null ? "unknown" : globalWarmup ? "on" : "off";
  console.log(`⏱ 5h limits — auto-restart: ${autoState}`);
  for (const acc of targets) {
    const open = remaining(acc.resetAtPrimary);
    const when = open && open !== "now" ? ` (window open · ${open} left)` : " (window elapsed)";
    console.log(`--${action(`🔁 Restart now: ${name(acc)}${when}`, [SELF, "warmup", acc.accountId])}`);
  }
  for (const acc of active.filter((a) => !warmable(a))) {
    // An account that has served requests and still has no five-hour window is
    // a usage-based seat: its responses carry overage headers, not a 5h claim,
    // so there is no window to reopen — ever, not just not yet.
    const served = (acc.requestUsage?.requestCount ?? 0) > 0;
    const why = served ? "usage-based seat, no 5h window" : "no 5h window on record yet";
    console.log(`--🔁 ${name(acc)} — ${why} | color=#7f8c8d`);
  }
  if (targets.length > 1) {
    console.log(`--${action(`🔁 Restart all eligible (${targets.length})`, [SELF, "warmup-all"])}`);
  }
  console.log("-----");
  if (globalWarmup != null) {
    console.log(
      `--${action(`${globalWarmup ? "✅" : "☐"} Auto-restart when a window ends`, [
        SELF,
        "autowarm-all",
        globalWarmup ? "off" : "on",
      ])}`,
    );
  }
  for (const acc of active) {
    const on = acc.limitWarmupEnabled === true;
    console.log(
      `--${action(`${on ? "☑︎" : "☐"} ${name(acc)} · auto-restart ${on ? "on" : "off"}`, [
        SELF,
        "autowarm",
        acc.accountId,
        on ? "off" : "on",
      ])}`,
    );
  }
  const last = s.accounts
    .map((acc) => ({ acc, w: acc.limitWarmup }))
    .filter((e): e is { acc: Account; w: AccountLimitWarmup } => e.w != null)
    .sort((a, b) => new Date(b.w.attemptedAt).getTime() - new Date(a.w.attemptedAt).getTime())[0];
  if (last) {
    const ok = last.w.status === "succeeded" || last.w.status === "success";
    const detail = ok ? "ok" : sane(last.w.errorCode ?? last.w.status);
    console.log(`--Last restart: ${name(last.acc)} · ${detail} · ${relTime(last.w.attemptedAt)} | size=11`);
  }
}

// ── Claude Code routing block ───────────────────────────────────────────────

function renderRouting(): void {
  const mode = routeMode();
  const host = proxyHost();
  const local = localLoginEmail();
  console.log("---");
  console.log(
    `🔀 Claude Code routes to: ${mode === "proxy" ? `proxy${host ? ` (${host})` : ""}` : mode === "local" ? "local login" : "unknown"}`,
  );
  console.log(`--${action(`${mode === "proxy" ? "●" : "○"} Route via claudex-lb proxy`, [SELF, "route", "proxy"])}`);
  console.log(
    `--${action(`${mode === "local" ? "●" : "○"} Use local login${local ? ` (${local})` : ""}`, [SELF, "route", "local"])}`,
  );
  console.log("--Takes effect on the next Claude Code start | size=11 color=#7f8c8d");
}

// The Claude block on its own, for embedding in another SwiftBar plugin (the
// live proxy-status menu owns the menu bar; this is the part that has to talk
// to claudex-lb). Prints nothing and exits non-zero when the server is
// unreachable, so the host can fall back instead of rendering a broken block.
async function renderClaudeMenu(cfg: Config): Promise<void> {
  let accounts: Account[];
  let requests: RequestLogEntry[];
  let nextUp: NextUpEntry[];
  let settings: { limitWarmupEnabled?: boolean } | null;
  try {
    [accounts, requests, nextUp, settings] = await Promise.all([
      allAccounts(cfg, true),
      recentRequests(cfg),
      nextUpAccounts(cfg),
      fetchSettings(cfg),
    ]);
  } catch {
    process.exit(1);
  }
  const section = buildSection(PROVIDERS[0], accounts, requests, nextUp);
  if (section === null) process.exit(1);
  const globalWarmup = typeof settings?.limitWarmupEnabled === "boolean" ? settings.limitWarmupEnabled : null;
  // The host prints the menu bar title before this block, so hand it the
  // Claude part on a marker line it strips out again. The title is the next
  // account's remaining quota and nothing else — that number is the icon.
  console.log(`#TITLE:${menuBarTitle(section)}`);
  renderSection(section, globalWarmup, false);
  // The Codex pool gets the same section below Claude's, so one embedded menu
  // switches both assistants. `renderSection` is provider-generic — it already
  // limits the 5h-window restarts to anthropic — and a provider with zero
  // accounts renders nothing at all.
  const codex = buildSection(PROVIDERS[1], accounts, requests, nextUp);
  if (codex !== null) renderSection(codex, globalWarmup);
}

// Everything the live proxy-status plugin embeds, in one request. Sections are
// separated by #BEGIN: markers the host splits on; the shapes match the menu
// entries the local switcher used to print, so only the data source and the
// click actions changed.
async function renderMenuBlocks(cfg: Config): Promise<void> {
  let accounts: Account[];
  let requests: RequestLogEntry[];
  let nextUp: NextUpEntry[];
  let settings: { limitWarmupEnabled?: boolean } | null;
  try {
    [accounts, requests, nextUp, settings] = await Promise.all([
      allAccounts(cfg, true),
      recentRequests(cfg),
      nextUpAccounts(cfg),
      fetchSettings(cfg),
    ]);
  } catch {
    process.exit(1);
  }
  const s = buildSection(PROVIDERS[0], accounts, requests, nextUp);
  if (s === null) process.exit(1);
  const globalWarmup = typeof settings?.limitWarmupEnabled === "boolean" ? settings.limitWarmupEnabled : null;
  const cur = s.current;

  console.log(`#TITLE:${menuBarTitle(s)}`);

  // The 5h window headline for whichever account is up next.
  console.log("#BEGIN:window");
  const used = usedPercent(cur);
  const resetIn = remaining(cur?.resetAtPrimary);
  if (used != null) {
    const at = clockTime(cur?.resetAtPrimary);
    console.log(`⏱ 5h Window: ${pct(used)}${resetIn ? ` — resets in ${resetIn}${at ? ` → ${at}` : ""}` : ""} | size=12`);
  } else {
    console.log(`⏱ 5h Window: usage-based seat (no window) | size=12`);
  }

  // Manual restarts, then the automatic one.
  console.log("#BEGIN:limits");
  for (const acc of s.accounts.filter(warmable)) {
    console.log(`--${action(`🔁 Restart limit: ${name(acc)}`, [SELF, "warmup", acc.accountId])}`);
  }
  const targets = s.accounts.filter(warmable);
  if (targets.length > 1) console.log(`--${action("🔁 Restart ALL limits", [SELF, "warmup-all"])}`);
  for (const acc of s.accounts.filter((a) => !warmable(a))) {
    console.log(`--🔁 ${name(acc)} — ${whyNotWarmable(acc)} | color=#7f8c8d`);
  }
  if (globalWarmup != null) {
    console.log(
      `--${action(`${globalWarmup ? "✅" : "☐"} Auto-restart when a window ends`, [
        SELF,
        "autowarm-all",
        globalWarmup ? "off" : "on",
      ])}`,
    );
  }

  // Header line for the account section.
  console.log("#BEGIN:current");
  const label = cur
    ? `${name(cur)}${s.certain ? "" : " (likely)"}`
    : s.noneReason
      ? `nobody — ${s.noneReason}`
      : "no account";
  // A pin that is not the next account is worth naming. With a hard pin it no
  // longer means the server declined a preference — it means the pinned account
  // cannot currently serve at all, which is the one thing worth saying.
  const pinned = s.preferred;
  const pinNote =
    pinned == null
      ? s.manual
        ? " 📌"
        : ""
      : cur != null && pinned.accountId === cur.accountId
        ? " 📌"
        : ` · 📌 ${name(pinned)} pinned, cannot serve`;
  console.log(`👤 Claude via claudex-lb → ${label}${pinNote} | size=12`);

  // One line per account, click switches the proxy; settings sit underneath.
  console.log("#BEGIN:accounts");
  for (const acc of s.accounts) renderAccountLine(acc, cur, s);
  // The way back out of a manual choice: un-pause everything and drop the
  // burn-first marking so quota and pace decide again.
  console.log(`--${action("⚖️ Auto: balance across all accounts", [SELF, "auto", "anthropic"])}`);

  // Codex rides in the same block rather than a new #BEGIN: marker: the host
  // splits on the markers it knows, so anything under a new one would be
  // dropped silently. Same account lines, same click-to-serve action, scoped
  // client-side to openai so pinning here never touches a Claude account.
  const codex = buildSection(PROVIDERS[1], accounts, requests, nextUp);
  if (codex !== null) {
    const codexCur = codex.current;
    console.log(`--⇄ Codex: ${codexCur ? name(codexCur) : "no account"}${codex.manual ? " 📌" : ""} | size=12`);
    for (const acc of codex.accounts) renderAccountLine(acc, codexCur, codex);
    console.log(`--${action("⚖️ Auto: balance across all Codex accounts", [SELF, "auto", "openai"])}`);
  }

  console.log("#BEGIN:end");
}

function renderAccountLine(acc: Account, cur: Account | null, s: Section): void {
  const next = cur != null && acc.accountId === cur.accountId;
  const dead = acc.status === "reauth_required" || acc.status === "deactivated";
  const icon = isPinned(acc) ? "📌" : next ? "✅" : dead ? "💀" : acc.status === "paused" ? "⏸" : "🔄";
  const suffix = next
    ? s.certain
      ? " • next"
      : " • likely next"
    : dead
      ? ` • ${sane(acc.status).replace(/_/g, " ")}`
      : "";
  const line = `${icon} ${name(acc)} — ${accountBadge(acc)}${suffix}`;
  if (dead) {
    console.log(`--${line} | color=#e74c3c`);
  } else if (next && isPinned(acc)) {
    console.log(`--${line}`);
  } else {
    console.log(`--${action(line, [SELF, "switch", acc.accountId])}`);
  }
  // Per-account controls, nested exactly where "Remove account" used to sit.
  if (warmable(acc)) {
    console.log(`----${action("🔁 Restart 5h limit now", [SELF, "warmup", acc.accountId])}`);
  }
  // Window restarts are a Claude-only concept — a Codex account has nothing to
  // warm, so it must not be offered the toggle.
  if (providerOf(acc) === "anthropic") {
    const warm = acc.limitWarmupEnabled === true;
    console.log(
      `----${action(`${warm ? "☑︎" : "☐"} Auto-restart this account`, [SELF, "autowarm", acc.accountId, warm ? "off" : "on"])}`,
    );
  }
  console.log(`----⚙ Pace margin (5h): ${acc.paceMarginPrimaryPct == null ? "off" : `${acc.paceMarginPrimaryPct}%`} | size=11`);
  for (const opt of [null, 0, 5, 10, 20]) {
    const mark = (acc.paceMarginPrimaryPct ?? null) === opt ? "• " : "  ";
    console.log(
      `----${action(`${mark}${opt === null ? "off" : `${opt}%`}`, [SELF, "pace", acc.accountId, opt === null ? "clear" : String(opt)])}`,
    );
  }
  console.log(
    `----⏰ Use up before reset: ${acc.preResetWindowMinutes == null ? "off" : `${acc.preResetWindowMinutes} min`} | size=11`,
  );
  for (const opt of [null, 30, 60, 120]) {
    const mark = (acc.preResetWindowMinutes ?? null) === opt ? "• " : "  ";
    console.log(
      `----${action(`${mark}${opt === null ? "off" : `${opt} min`}`, [SELF, "prereset", acc.accountId, opt === null ? "clear" : String(opt)])}`,
    );
  }
}

// Badge in the shape the menu used before: 5h used · when it resets · 7d used
// (when that resets).
function accountBadge(acc: Account): string {
  const parts: string[] = [];
  const primary = acc.usage?.primaryRemainingPercent;
  if (primary != null) {
    parts.push(pct(100 - primary));
    const resets = remaining(acc.resetAtPrimary);
    if (resets) parts.push(resets);
  }
  const weekly = acc.usage?.secondaryRemainingPercent;
  if (weekly != null) {
    const resets = remaining(acc.resetAtSecondary);
    parts.push(`${pct(100 - weekly)} 7d${resets ? ` (${resets})` : ""}`);
  }
  if (parts.length === 0) return acc.status === "active" ? "usage-based" : sane(acc.status).replace(/_/g, " ");
  return parts.join(" · ");
}

function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function whyNotWarmable(acc: Account): string {
  if (acc.status !== "active" && acc.status !== "paused") return sane(acc.status).replace(/_/g, " ");
  if ((acc.requestUsage?.requestCount ?? 0) > 0 && acc.resetAtPrimary == null) return "usage-based seat, no 5h window";
  return "no 5h window on record yet";
}

async function render(cfg: Config): Promise<void> {
  const [accounts, requests, nextUp, settings] = await Promise.all([
    allAccounts(cfg),
    recentRequests(cfg),
    nextUpAccounts(cfg),
    fetchSettings(cfg),
  ]);

  if (accounts.length === 0) {
    fail("0", ["Keine Accounts in claudex-lb", `Dashboard öffnen | href=${cfg.baseUrl}`]);
  }

  const sections = PROVIDERS.map((p) => buildSection(p, accounts, requests, nextUp)).filter(
    (s): s is Section => s !== null,
  );
  const globalWarmup = typeof settings?.limitWarmupEnabled === "boolean" ? settings.limitWarmupEnabled : null;

  console.log(sections.length > 0 ? sections.map(titlePart).join(" ") : "⇄ ?");

  for (const s of sections) renderSection(s, globalWarmup);

  renderRouting();

  console.log("---");
  console.log(`Open dashboard | href=${cfg.baseUrl}`);
  console.log("Refresh | refresh=true");
}

// ── main ────────────────────────────────────────────────────────────────────

// ---------------------------------------------------------------------------
// Adding a Claude account
//
// Runs Anthropic's own authorization-code flow and hands the result straight to
// the proxy. Deliberately NOT `claude login` + push-account: that route writes
// the new account over this Mac's keychain, which strands whatever chain was
// there if it had not been pushed yet, and it has to go hunting in
// ~/.claude.json for an email that the credential itself does not carry. The
// token response states the email outright, so the account arrives with its own
// identity instead of a synthetic @imported.local address that can never dedupe.
//
// Nothing local is touched: no keychain write, no ~/.claude.json, no effect on
// whichever account Claude Code is logged into here.

// Claude Code's public client. The authorize host bounces through claude.com for
// attribution and lands on claude.ai; the manual redirect is the paste-the-code
// page, which is what makes this work without a callback listener.
const OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const OAUTH_AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize";
const OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token";
const OAUTH_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback";
const OAUTH_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile";
const OAUTH_SCOPES = [
  "org:create_api_key",
  "user:profile",
  "user:inference",
  "user:sessions:claude_code",
  "user:mcp_servers",
  "user:file_upload",
].join(" ");

function b64url(bytes: Buffer): string {
  return bytes.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

async function readLine(promptText: string): Promise<string> {
  process.stdout.write(promptText);
  const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: false });
  try {
    for await (const line of rl) return line.trim();
  } finally {
    rl.close();
  }
  return "";
}

async function cmdLogin(cfg: Config): Promise<void> {
  // Prove we can reach the proxy and authenticate BEFORE sending anyone to a
  // sign-in page. Discovering a rotated dashboard password after the exchange
  // costs a single-use Anthropic refresh token that exists nowhere else: the
  // flow has no way to re-deliver it, and re-running means signing in again.
  // Cheap authenticated GET; the cookie it establishes is reused by the import.
  await apiFetch(cfg, "/api/settings");

  const verifier = b64url(randomBytes(32));
  const challenge = b64url(createHash("sha256").update(verifier).digest());
  const state = b64url(randomBytes(32));

  const url = new URL(OAUTH_AUTHORIZE_URL);
  url.searchParams.set("code", "true");
  url.searchParams.set("client_id", OAUTH_CLIENT_ID);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("redirect_uri", OAUTH_REDIRECT_URI);
  url.searchParams.set("scope", OAUTH_SCOPES);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("state", state);

  console.log("Add a Claude account to claudex-lb\n");
  console.log("1. Sign in on the page that just opened (use a private window to");
  console.log("   add an account other than the one your browser is signed into).");
  console.log("2. Copy the code it gives you and paste it below.\n");
  console.log(`${url}\n`);
  spawnSync("/usr/bin/open", [url.toString()]);

  // The callback page hands back "code#state" as one string.
  const pasted = await readLine("Code: ");
  const [code, returnedState] = pasted.split("#");
  if (!code || !returnedState) {
    throw new Error("that does not look like a full code — it should contain a '#'");
  }
  if (returnedState !== state) {
    throw new Error("the code came back with a different state than this sign-in started with");
  }

  const tokenRes = await fetch(OAUTH_TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "authorization_code",
      code,
      redirect_uri: OAUTH_REDIRECT_URI,
      client_id: OAUTH_CLIENT_ID,
      code_verifier: verifier,
      state: returnedState,
    }),
    signal: AbortSignal.timeout(20_000),
  });
  if (!tokenRes.ok) {
    throw new Error(`token exchange failed (HTTP ${tokenRes.status}): ${(await tokenRes.text()).slice(0, 200)}`);
  }
  const tok = (await tokenRes.json()) as {
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
    scope?: string;
    account?: { email_address?: string };
  };
  if (!tok.access_token || !tok.refresh_token) {
    throw new Error("token exchange returned no token pair");
  }

  // The plan comes from the profile; the email from the token response, which
  // states it directly. A profile that will not load costs the plan label only —
  // the poller corrects it on its first read — so it must not fail the import.
  let email = tok.account?.email_address ?? "";
  let subscriptionType: string | undefined;
  try {
    const profRes = await fetch(OAUTH_PROFILE_URL, {
      headers: { Authorization: `Bearer ${tok.access_token}`, "Content-Type": "application/json" },
      signal: AbortSignal.timeout(15_000),
    });
    if (profRes.ok) {
      const prof = (await profRes.json()) as {
        account?: { email?: string };
        organization?: { organization_type?: string };
      };
      email = prof.account?.email || email;
      // claude_max -> max, so the import stores plan_type "claude_max".
      subscriptionType = prof.organization?.organization_type?.replace(/^claude_/, "");
    }
  } catch {
    /* plan label only */
  }
  if (!email) throw new Error("could not determine the account's email address");

  const claudeAiOauth = {
    accessToken: tok.access_token,
    refreshToken: tok.refresh_token,
    // Milliseconds, matching what Claude Code writes and what the import reads.
    expiresAt: Date.now() + (tok.expires_in ?? 3600) * 1000,
    scopes: (tok.scope ?? OAUTH_SCOPES).split(" ").filter(Boolean),
    ...(subscriptionType ? { subscriptionType } : {}),
  };

  const form = new FormData();
  form.append(
    "auth_json",
    new Blob([JSON.stringify({ email, claudeAiOauth })], { type: "application/json" }),
    "auth.json",
  );
  const result = await apiFetch(cfg, "/api/accounts/import", { method: "POST", body: form });

  console.log(`\n✓ added ${email}${subscriptionType ? ` (${subscriptionType})` : ""}`);
  console.log(`  account_id=${result.accountId ?? result.account_id} status=${result.status}`);
  console.log("\nThe proxy owns this credential. Nothing on this Mac was changed.");
  notify(`Added ${email} to claudex-lb`);
}

const [, , cmd, arg, arg2] = process.argv;
const ACTIONS = new Set([
  "switch",
  "auto",
  "warmup",
  "warmup-all",
  "autowarm",
  "autowarm-all",
  "route",
  "pace",
  "prereset",
]);
// Before loadConfig, which can fail() too.
terminalMode = cmd === "login";
const cfg = loadConfig();

try {
  if (cmd === "switch" && arg) {
    await cmdSwitch(cfg, arg);
  } else if (cmd === "auto") {
    await cmdAuto(cfg, arg);
  } else if (cmd === "warmup" && arg) {
    await cmdWarmup(cfg, arg);
  } else if (cmd === "warmup-all") {
    await cmdWarmupAll(cfg);
  } else if (cmd === "autowarm" && arg && arg2) {
    await cmdAutoWarm(cfg, arg, arg2);
  } else if (cmd === "autowarm-all" && arg) {
    await cmdAutoWarmAll(cfg, arg);
  } else if (cmd === "route" && (arg === "proxy" || arg === "local")) {
    cmdRoute(arg);
  } else if (cmd === "pace" && arg && arg2) {
    await cmdPace(cfg, arg, arg2);
  } else if (cmd === "prereset" && arg && arg2) {
    await cmdPreReset(cfg, arg, arg2);
  } else if (cmd === "login") {
    await cmdLogin(cfg);
  } else if (cmd === "menu-blocks") {
    await renderMenuBlocks(cfg);
  } else if (cmd === "claude-menu") {
    await renderClaudeMenu(cfg);
  } else {
    await render(cfg);
  }
} catch (err) {
  if (cmd === "login") {
    // Runs in a Terminal window the operator is looking at; SwiftBar menu lines
    // would be noise there, and a notification would scroll past the detail
    // that says which step failed.
    console.error(`\n✗ ${String(err).replace(/^Error:\s*/, "")}`);
    process.exit(1);
  }
  if (cmd !== undefined && ACTIONS.has(cmd)) {
    // Actions run headless from the menu — the notification is the only channel.
    notify(String(err));
    process.exit(1);
  }
  fail("⚠️", [`Fehler: ${String(err).slice(0, 160)} | color=#e74c3c`, "Aktualisieren | refresh=true"]);
}
