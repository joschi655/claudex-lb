#!/bin/bash
// 2>/dev/null; for b in "$HOME/.bun/bin/bun" /opt/homebrew/bin/bun /usr/local/bin/bun; do [ -x "$b" ] && exec "$b" "$0" "$@"; done; echo "⇄ bun?"; echo "---"; echo "bun not found — install from https://bun.sh"; exit 0

// <xbar.title>claudex-lb account switcher</xbar.title>
// <xbar.desc>Claude + Codex sections: shows which account claudex-lb is serving per provider (+quota stats), pins accounts manually, restarts Claude 5h windows, and switches Claude Code between the proxy and a local login.</xbar.desc>
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
  paceMarginPrimaryPct?: number | null;
  preResetWindowMinutes?: number | null;
  usage?: AccountUsage | null;
  resetAtPrimary?: string | null;
  resetAtSecondary?: string | null;
  resetAtMonthly?: string | null;
  requestUsage?: RequestUsage | null;
  spendBudget?: SpendBudget | null;
  limitWarmupEnabled?: boolean;
  limitWarmup?: AccountLimitWarmup | null;
}

interface RequestLogEntry {
  requestedAt: string;
  accountId?: string | null;
  model: string;
  status: string;
}

function fail(title: string, lines: string[]): never {
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

function lastFor(requests: RequestLogEntry[], accounts: Account[]): RequestLogEntry | null {
  const ids = new Set(accounts.map((a) => a.accountId));
  return requests.find((r) => r.accountId && ids.has(r.accountId)) ?? null;
}

const PAUSABLE = new Set(["active", "rate_limited", "quota_exceeded"]);

// "Switch to this account" writes routing_policy=pinned, which the server
// treats as a hard override: while the account can serve it is the only
// candidate, and when it cannot the pool falls back to its automatic rules on
// its own. The others stay live rather than being paused, so failover has
// somewhere to go and their five-hour windows can still be restarted.
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
  if (target.status === "paused") {
    // The one exception: a pin on a paused account would never fire.
    try {
      await apiFetch(cfg, `/api/accounts/${targetId}/reactivate`, { method: "POST" });
    } catch (err) {
      failures.push(`reactivate ${name(target)}: ${String(err).slice(0, 50)}`);
    }
  }
  await setRoutingPolicy(cfg, targetId, "pinned");
  // The server demotes the provider's previous *pin* itself. A leftover
  // burn-first mark is a different thing — an old pin from before `pinned`
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
    // and pace decide, and either value would keep overriding that.
    if (acc.routingPolicy === "pinned" || acc.routingPolicy === "burn_first") {
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

function badge(acc: Account): string {
  const p =
    acc.usage?.primaryRemainingPercent ?? acc.usage?.secondaryRemainingPercent ?? acc.usage?.monthlyRemainingPercent;
  // A budget seat has no window to report a remainder for, so its badge is what
  // is left of the budget rather than "unknown".
  if (p == null && acc.spendBudget != null) {
    const left = money(acc.spendBudget.remaining, acc.spendBudget.currency);
    const budgetLeft = Math.max(0, 100 - acc.spendBudget.usedPercent);
    return `${pct(budgetLeft)} left${left ? ` · ${left}` : ""}`;
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
  current: Account | null;
  last: RequestLogEntry | null;
}

function buildSection(
  def: (typeof PROVIDERS)[number],
  accounts: Account[],
  requests: RequestLogEntry[],
): Section | null {
  const mine = accounts.filter((a) => providerOf(a) === def.key);
  if (mine.length === 0) return null;
  // "healthy" (status active) drives the X/Y count and manual detection;
  // rate_limited/quota_exceeded accounts are poolable but not healthy.
  const healthy = mine.filter((a) => a.status === "active");
  const pausable = mine.filter((a) => PAUSABLE.has(a.status));
  // Manual = an explicit burn-first preference, or the legacy shape where every
  // other account was paused to force one.
  const preferred = mine.find((a) => a.routingPolicy === "pinned" && a.status === "active") ?? null;
  const manual = preferred !== null || (healthy.length === 1 && mine.some((a) => a.status === "paused"));
  const last = lastFor(requests, mine);
  // Which account is serving is a question about traffic, so the newest request
  // log entry answers it -- not the burn-first marking, which is only a request
  // the server may decline. A pinned account still gets gated out by its pace
  // margin, its pre-reset window or its own quota, and reading the pin as truth
  // made the menu name an account that was serving nothing.
  //
  // The pin still shows (as 📌, via `preferred`); it just no longer overrides
  // the evidence. It does win before any traffic exists, so clicking "switch"
  // on an idle pool still gives immediate feedback.
  const lastAcc = last?.accountId ? mine.find((a) => a.accountId === last.accountId) : undefined;
  const current =
    (lastAcc && PAUSABLE.has(lastAcc.status) ? lastAcc : null) ||
    preferred ||
    healthy[0] ||
    pausable[0] ||
    lastAcc ||
    mine[0] ||
    null;
  return { key: def.key, label: def.label, icon: def.icon, accounts: mine, healthy, manual, preferred, current, last };
}

function titlePart(s: Section): string {
  const p =
    s.current?.usage?.primaryRemainingPercent ??
    s.current?.usage?.secondaryRemainingPercent ??
    s.current?.usage?.monthlyRemainingPercent;
  return `${s.icon}${p == null ? "" : pct(p)}${s.manual ? "📌" : ""}`;
}

// Menu bar text for the embedded block: the remaining percentage on the account
// that is serving, plus 📌 when the pool is pinned to one account. Falls back to
// the status when a usage-based seat reports no percentage at all.
// Menu bar text: how much of the serving account's 5h window is used, the same
// metric the account lines show. A usage-based seat has no window at all, so fall
// back to the least-used window in the pool — the one with the most room left.
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
    acc?.usage?.primaryRemainingPercent ??
    acc?.usage?.secondaryRemainingPercent ??
    acc?.usage?.monthlyRemainingPercent;
  if (left != null) return 100 - left;
  // Fall back to the budget so the icon shows a number for a seat whose quota is
  // dollars rather than a window.
  return acc?.spendBudget?.usedPercent ?? null;
}

function renderSection(s: Section, globalWarmup: boolean | null, separator = true): void {
  if (separator) console.log("---");
  const pinnedName = s.preferred ? name(s.preferred) : s.healthy.length > 0 ? name(s.healthy[0]) : "?";
  console.log(
    `${s.icon} ${s.label}: ${s.manual ? `📌 ${pinnedName} first` : `Auto · ${s.healthy.length}/${s.accounts.length} active`} | size=13`,
  );
  const cur = s.current;
  if (cur) {
    console.log(`Current: ${name(cur)}${cur.planType ? ` (${sane(cur.planType)})` : ""}`);
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
    const mark =
      acc.routingPolicy === "pinned" ? "📌" : isCurrent ? "●" : acc.status === "paused" ? "⏸" : "○";
    const line = `${mark} ${name(acc)} — ${badge(acc)}`;
    if (acc.status === "reauth_required" || acc.status === "deactivated") {
      console.log(`--${line} | color=#e74c3c`);
    } else if (acc.status !== "active" && acc.status !== "paused") {
      // rate_limited / quota_exceeded: visible but not a valid pin target
      console.log(`--${line} | color=#e67e22`);
    } else if (acc.routingPolicy === "pinned") {
      // Already pinned; clicking it again would do nothing.
      console.log(`--${line}`);
    } else {
      console.log(`--${action(line, [SELF, "switch", acc.accountId])}`);
    }
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
  let settings: { limitWarmupEnabled?: boolean } | null;
  try {
    [accounts, requests, settings] = await Promise.all([
      allAccounts(cfg, true),
      recentRequests(cfg),
      fetchSettings(cfg),
    ]);
  } catch {
    process.exit(1);
  }
  const section = buildSection(PROVIDERS[0], accounts, requests);
  if (section === null) process.exit(1);
  const globalWarmup = typeof settings?.limitWarmupEnabled === "boolean" ? settings.limitWarmupEnabled : null;
  // The host prints the menu bar title before this block, so hand it the
  // Claude part on a marker line it strips out again. The title is the serving
  // account's remaining quota and nothing else — that number is the icon.
  console.log(`#TITLE:${menuBarTitle(section)}`);
  renderSection(section, globalWarmup, false);
  // The Codex pool gets the same section below Claude's, so one embedded menu
  // switches both assistants. `renderSection` is provider-generic — it already
  // limits the 5h-window restarts to anthropic — and a provider with zero
  // accounts renders nothing at all.
  const codex = buildSection(PROVIDERS[1], accounts, requests);
  if (codex !== null) renderSection(codex, globalWarmup);
}

// Everything the live proxy-status plugin embeds, in one request. Sections are
// separated by #BEGIN: markers the host splits on; the shapes match the menu
// entries the local switcher used to print, so only the data source and the
// click actions changed.
async function renderMenuBlocks(cfg: Config): Promise<void> {
  let accounts: Account[];
  let requests: RequestLogEntry[];
  let settings: { limitWarmupEnabled?: boolean } | null;
  try {
    [accounts, requests, settings] = await Promise.all([
      allAccounts(cfg, true),
      recentRequests(cfg),
      fetchSettings(cfg),
    ]);
  } catch {
    process.exit(1);
  }
  const s = buildSection(PROVIDERS[0], accounts, requests);
  if (s === null) process.exit(1);
  const globalWarmup = typeof settings?.limitWarmupEnabled === "boolean" ? settings.limitWarmupEnabled : null;
  const cur = s.current;

  console.log(`#TITLE:${menuBarTitle(s)}`);

  // The 5h window headline for whichever account is serving.
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
  const label = cur ? name(cur) : "no account";
  // A pin that is not the serving account is worth naming. With a hard pin it
  // no longer means the server declined a preference — it means the pinned
  // account cannot currently serve at all, which is the one thing worth saying.
  const pinned = s.preferred;
  const pinNote =
    pinned == null
      ? s.manual
        ? " 📌"
        : ""
      : cur != null && pinned.accountId === cur.accountId
        ? " 📌"
        : ` · 📌 ${name(pinned)} pinned, not serving`;
  console.log(`👤 Claude via claudex-lb: ${label}${pinNote} | size=12`);

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
  const codex = buildSection(PROVIDERS[1], accounts, requests);
  if (codex !== null) {
    const codexCur = codex.current;
    console.log(`--⇄ Codex: ${codexCur ? name(codexCur) : "no account"}${codex.manual ? " 📌" : ""} | size=12`);
    for (const acc of codex.accounts) renderAccountLine(acc, codexCur, codex);
    console.log(`--${action("⚖️ Auto: balance across all Codex accounts", [SELF, "auto", "openai"])}`);
  }

  console.log("#BEGIN:end");
}

function renderAccountLine(acc: Account, cur: Account | null, s: Section): void {
  const serving = cur != null && acc.accountId === cur.accountId;
  const dead = acc.status === "reauth_required" || acc.status === "deactivated";
  const icon = acc.routingPolicy === "pinned" ? "📌" : serving ? "✅" : dead ? "💀" : acc.status === "paused" ? "⏸" : "🔄";
  const suffix = serving ? " • serving" : dead ? ` • ${sane(acc.status).replace(/_/g, " ")}` : "";
  const line = `${icon} ${name(acc)} — ${accountBadge(acc)}${suffix}`;
  if (dead) {
    console.log(`--${line} | color=#e74c3c`);
  } else if (serving && acc.routingPolicy === "pinned") {
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
  const [accounts, requests, settings] = await Promise.all([
    allAccounts(cfg),
    recentRequests(cfg),
    fetchSettings(cfg),
  ]);

  if (accounts.length === 0) {
    fail("0", ["Keine Accounts in claudex-lb", `Dashboard öffnen | href=${cfg.baseUrl}`]);
  }

  const sections = PROVIDERS.map((p) => buildSection(p, accounts, requests)).filter(
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
  } else if (cmd === "menu-blocks") {
    await renderMenuBlocks(cfg);
  } else if (cmd === "claude-menu") {
    await renderClaudeMenu(cfg);
  } else {
    await render(cfg);
  }
} catch (err) {
  if (cmd !== undefined && ACTIONS.has(cmd)) {
    // Actions run headless from the menu — the notification is the only channel.
    notify(String(err));
    process.exit(1);
  }
  fail("⚠️", [`Fehler: ${String(err).slice(0, 160)} | color=#e74c3c`, "Aktualisieren | refresh=true"]);
}
