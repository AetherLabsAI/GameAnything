# Agents under their own OS accounts

Status: implemented behind a switch, **off by default** (`GAMEANYTHING_AGENT_USERS=on`, or `agent_users: on` in `settings.yaml`).
Code: `gameanything/isolation.py` (accounts, layout, guard), `gameanything/gate.py` (the request channel), `gameanything/decisions.py`
(signatures, ledger chain), `gameanything/isolation_setup.py` (`gameanything isolation status | migrate | rollback`).
Tests: `tests/test_agent_isolation.py` (the attacks run as real throwaway OS accounts where the machine allows it).

## 1. Why

Three QA rounds (2026-10-29/30) showed that while the agents, the UI / hub server and agentd all run as the same OS user, every
software guard can be walked around by a shell command or a small script:

| QA id | What the agent did | Why software could not stop it |
|---|---|---|
| ★1 / qa3-a | imported `decisions`, called `serve_signing()` then `record()`; its public key landed in the keyring | same user: it can run the server's code and write the server's files |
| H1 / ★2 | `curl -H 'Sec-Fetch-Dest: document'` got the decision cookie, then POSTed with an Origin | a header is the client's word |
| H2 / ★3 | read `hub_secret` / `users.yaml` and forged any session (`users.make_session`); copied the Chrome cookie | same user can read every file |
| H3 | appended a `from: user` card answer to `thread.jsonl`: plan approved, paid generation and builds unlocked | the thread is a plain file |
| H4 / ★4 | changed `config/project.yaml` `id:`, dropped `decisions: strict`, moved the ledger | strictness was keyed by an editable id |
| M | deleted her later "draft" line from the ledger | lines were not chained |

Deny rules on literal command lines do not help: a script file, string splicing or another interpreter gets around them.

## 2. Threat model

In scope: an agent run (resident, builder, critic; Claude Code, Codex, Gemini CLI, OpenCode) that is buggy, prompt-injected through
her material or the web, or simply over-eager, with a full shell. Its goals: (a) make a decision in her name (a confirmation, a card
answer, a go), (b) read or change another user's projects, keys or logins, (c) read server secrets, (d) get root.

Out of scope: a malicious operator (root), kernel bugs, the provider's own servers, a user attacking their own projects through their
own browser.

Trust boundary: **the OS account**. The service account (root on this host) runs the UI / hub server, agentd and the gate. Every agent CLI
run runs as an unprivileged *agent account*. The kernel enforces file permissions, socket credentials (SO_PEERCRED), `/proc/net/tcp`
ownership and signal permissions; nothing the agent prints, sets or writes can change them.

## 3. Accounts

| Install | Accounts | Group |
|---|---|---|
| Hub (users.yaml exists) | `ga-<user>` per hub user (`ga-wenyi`, `ga-lucy`, `ga-yuru`) | all in `ga-agents` |
| Single user | `ga-agent` | `ga-agents` |

The account of a project is derived from the server's view: its owner (`users.owner_of`) for a hub, else `ga-agent`. Once a project
folder is in the isolated layout its group is that account's group; agentd refuses to run a project whose folder group and owner
disagree (an agent that edits `config/project.yaml owner:` gets no other user's account or login).

**Why one OS account per hub user, and not one agent account plus per-run namespaces?** On this host the container has no
`CAP_SYS_ADMIN`: mount namespaces fail for root (`unshare -m`), and inside an unprivileged user namespace the process keeps the real
uid's file access (root's!) and can undo the mounts it made itself, so namespaces could only *hide* paths, not deny them. With one shared
agent uid, Lucy's run could read, write, `ptrace` and signal Wenyi's run and files. Separate uids are the only kernel-enforced boundary
available everywhere (containers, VMs, bare Linux, macOS). Runs of the *same* user share an account; their projects are the same user's data
(signatures still cover the project id, so a moved card or ledger line does not count elsewhere).

## 4. Who may touch what

`<agent root>` = `GAMEANYTHING_AGENT_ROOT` / `agent_root:` (default `/var/lib/gameanything-agents`; on this host
`/workspace/gameanything-agents`, persistent JuiceFS).

| Path | Owner : group | Mode | Agent of that user | Other agents |
|---|---|---|---|---|
| `<project>/` | root : ga-&lt;u&gt; | 3770 (setgid, sticky) | add files; cannot rename or remove root's (`conversation/`) | nothing |
| `<project>/conversation/` and all in it | root : ga-&lt;u&gt; | 2750 / 0640 | read only | nothing |
| `thread.jsonl`, `.user_decisions.jsonl`, `.server.json`, `.agentd_*`, `.gen_queue/`, `.refs_queue/`, `.agentd_inbox/` | root | 0640 | read only | nothing |
| everything else in the project (`0_inbox` … `5_build`, `feedback/`, `config/`) | ga-&lt;u&gt; : ga-&lt;u&gt; | 2770 / 0660, default ACL group rwx | read, write | nothing |
| `5_build/<m>/.build_run.json` (agentd's record) | root | 0640 | read only; a replaced one is ignored | nothing |
| `~/.config/gameanything/` (projects.yaml, users.yaml, hub_secret, settings, `server/` keys) | root | as now, plus ACL `g:ga-agents:---` | nothing | nothing |
| `<agent root>/public/` (keyring, strict list, ledger heads) | root | 0755 / 0644 | read only | read only |
| `<agent root>/gate/agent.sock` | root : ga-agents | 0660 | connect | connect (refused: not its run) |
| `<agent root>/homes/ga-<u>/` (HOME, TMPDIR, provider logins) | ga-&lt;u&gt; | 0700 | read, write | nothing |
| code checkout, venv, Python, node, the agent CLIs | root | as now + traverse ACLs | read, run | read, run |
| `/root/wenyi/.env`, other users' env files, browser profiles, `~/.claude` of root | root | as now + `g:ga-agents:---` | nothing | nothing |
| docker-rt socket, lab broker files | root : docker-rt | 0660 | nothing (through the gate) | nothing |

"Traverse ACLs": `/root` is 0700. The migration gives `ga-agents` `--x` (enter, never list) on the folders on the way to the code, the
venv's Python, node and the CLIs, and `u:ga-<u>:--x` on the way to that user's projects and logins. Every world-readable entry *next to*
such a way gets `g:ga-agents:---` (a named group entry beats "other"), so opening `/root` does not open `~/.claude`, `~/.config`,
other users' folders, the checkout's `.git`, and so on. POSIX ACLs are set as `system.posix_acl_*` xattrs (no `setfacl` needed);
JuiceFS keeps and enforces them (probed 2026-10-30, also default ACLs).

## 5. The request channel (the gate)

Everything an agent used to write directly and must not forge now goes through `<agent root>/gate/agent.sock`, served by a thread of
agentd (the service account). The agent's CLI does this by itself: `cli.main` in *client mode* (isolation on, not the service account)
forwards these commands instead of running them:

| Command | Who | Notes |
|---|---|---|
| `chat claim / wait / read / say / card / progress / idle / release` | resident | `say --user`, `claim --force`, `--session`, `wait --all/--unowned` refused |
| `agentd request` (build_start, build_change, question, gen_request_ready, other) | resident, builder | `--details @file`: the client sends the bytes |
| `agentd notify` | builder | `--from builder` forced |
| `gen request`, `refs fetch` | resident, builder | `--inputs` / `--image`: project-relative paths only |
| `build status`, `build deliver` | resident, builder | `--chapters`: bytes |
| `lessons add / show` | resident, builder | |
| `lab env up/status`, `lab heartbeat`, `lab run <tool> …` | builder | the run's lease is used, never one the agent names |

Wire format: a 4-byte big-endian length, then JSON `{"argv": [...], "stdin": str|null, "files": [{"name", "orig", "data": base64}]}`;
the reply is `{"code", "stdout", "stderr"}` or `{"error"}`.

What the gate does with a request:
1. `SO_PEERCRED` gives the caller's pid and uid. The uid must be an agent account.
2. The run: the caller (or a parent of it, `/proc/<pid>/stat`) must be the process of a live agentd run (resident: `.agentd_run.json`;
   builder: `.build_run.json` that agentd wrote) of a project of that account. A process that left its run's tree is refused.
3. The command must be in the table, with allowed flags only (exact names, so argparse abbreviations do not help). `--project` and
   `--session` are always the run's; files are the bytes the agent itself read and sent; nothing the agent names is opened by the
   service account outside the project.
4. It runs `python -m gameanything …` as the service account, in an empty root-only folder, with this code on `PYTHONPATH` and the run's
   `GAMEANYTHING_SESSION` / `GAMEANYTHING_INSTANCE` / `GAMEANYTHING_ROLE` / lease. `Thread.append` refuses `from: user` and answers there,
   and stamps the agent's events `via: gate`, `run: <run id>`.

An agent that bypasses its CLI (its own socket client, unsetting `GAMEANYTHING_GATE`, writing files) gets exactly the same: the gate
checks the same things, and the files are not writable for it.

## 6. Her decisions: signatures and the ledger

- **Only the page server signs.** Ed25519 key per server start, private key in memory only (`decisions.serve_signing`). An agent
  account cannot run code in that process, cannot append to the keyring (`<home>/server/decision-keys.txt`, root 0600; agents read the
  public copy in `<agent root>/public/`), and cannot write the ledger.
- **The page tells agents from her browser by the kernel, not by headers.** With isolation on, the UI looks up the TCP peer of each
  connection in `/proc/net/tcp` (its uid). A connection from an agent account may GET pages and media (cards `curl /media/...`), but is
  never given the decision cookie and every POST is refused (403), even with a stolen cookie. In the hub, agent accounts cannot log in.
- **Card answers are signed** (`decisions.sign_event`, in `Thread.append` of the page / hub server): kid + Ed25519 over the project id,
  event id, time, card, answer, source and author. With isolation on, `Thread.events()` drops every `from: user` answer without a
  valid signature after the project's `answers_from` line (answers from before signing existed keep counting). Flow, paid generation
  (`genrun`), builds and reference downloads all read answers through it. A `thread.jsonl` that is not the service account's file
  counts no unsigned answer at all.
- **Strictness is the server's.** With isolation on, `project_id` is the server's project-list id (agents read it from the root-owned
  `conversation/.server.json`); editing `config/project.yaml id:` or `decisions:` changes nothing. The strict list lives in the
  server folder (public copy for agents).
- **The ledger is tamper-evident.** Every new line carries `prev` (hash of the line before) and `n` (its place), both under the
  signature. The server keeps a head per project (`ledger-heads.json`: `n`, hash of the last line, `answers_from`). With isolation on
  a ledger that is shorter than its head, differs at the head, breaks the chain, or is not the service account's file counts no
  confirmation and `flow check` reports it (`tampered()`); lines after the head never count. Old ledgers are sealed (head set) at the next
  server start or by the migration.
- When isolation is off, all of this is *recorded* (signatures, chain, heads) but not *enforced*: the old rules apply unchanged.

## 7. The service account never follows an agent's link

The service account still writes into the agent's folders (review files, uploads, build records, reference pictures, `answers.md`).
An agent could plant `feedback/board_review.yaml -> /root/.config/gameanything/users.yaml`. With isolation on, every service process
(`cli.main` as root) installs `isolation.install_guard()`: `open`, `os.open`, `rename`, `replace`, `unlink`, `remove`, `rmdir`, `mkdir`,
`chmod` on a path inside a prepared project or an agent home walk the path from the project folder with `O_NOFOLLOW` at every step
(openat-style, so there is no check-then-use race); a link that stays inside the project is followed, one that leaves it raises
`PermissionError`. Hard links to root's files are already impossible (`fs.protected_hardlinks=1`).
Paid-generation scripts (`genrun`) are the project's own code: they run **as the project's account** (with the paid key in their env, as
before), never as root.

## 8. The agent's environment

`isolation.run_env` (agentd and builds, before `provider.launch`):
- `HOME=<agent root>/homes/<acct>/home`, `TMPDIR` = the run's own folder (`agent_providers.run_tmpdir`, handed to the account).
- Provider homes: the hub user's own (`users.yaml claude_config_dir`, `codex_home`, `gemini_home`, `opencode_home`) when the account
  owns them (the migration hands them over), else folders in the account's home (`.claude`, `.codex`, `gemini-home`, `opencode-home`).
  The operator's `~/.claude` is never used.
- `GAMEANYTHING_GATE=1`, `GAMEANYTHING_GATE_SOCKET`, `GAMEANYTHING_DECISION_KEYS=<agent root>/public`, a `GAMEANYTHING_HOME` of its own,
  `GAMEANYTHING_KEYS_FILE` removed (the account could not read it anyway). Paid keys stay with agentd (unchanged: `agent_env`).
- Spawned with `user=`, `group=`, `extra_groups=[own group, ga-agents]`, `umask 007`, its own process group.

## 9. Lab and builds

Builders are **not** in the `docker-rt` group: the socket gives full control of every sandbox (anyone's seat, any container), i.e. a
lease would mean nothing. Lab work goes through the gate instead: `lab env up/status`, `lab heartbeat` and `lab run <tool> …` run as the
service account with the run's own lease (`GAMEANYTHING_LEASE` from agentd's build record, never from the agent). `lab run` accepts
only tools of the allowlist (`agent_lab_tools:` in settings, default: gamebench `hosting/launch_rt/*` and `hosting/lab/*`).
Seats are still acquired and released by agentd only; `lab acquire` is not a gate command.
Before turning isolation on for lab builds, the builder docs (skills `roles/builder.md`, the game packs' lab docs) must say
`gameanything lab run <tool>` where they now call the tool directly (see 12).

## 10. Migration (existing data, nothing moves)

`gameanything isolation migrate` is a dry run: it lists every account, folder, ACL entry, project ownership change and login hand-over
(`--json` for the full list). `--apply --journal FILE` does it and writes the old state of every changed path to FILE;
`gameanything isolation rollback --journal FILE [--apply]` puts it back. `--enable` also writes `agent_users: on`.

What `--apply` does, in order (each step journaled first):
1. `groupadd ga-agents`; per account `groupadd` + `useradd -M -u <stable uid> -g ga-<u> -G ga-agents -s /usr/sbin/nologin`
   (uids from 39100, remembered in `<home>/server/agent-accounts.json` so a re-created container gets the same ones).
2. `<agent root>` folders (public, gate, homes).
3. The project parents that others could write (`chmod go-w`).
4. The ACL entries of section 4.
5. Each project into the isolated layout (`isolation.prepare_project`): `conversation/` stays root, the rest goes to the account.
6. Hub users' provider login folders `chown -R` to their account (the operator's default `~/.claude` is not; that user logs in
   once as the account, or `--copy-logins` on a single-user install).
7. Ledger heads and `answers_from` for every project with a ledger; `conversation/.server.json`.

A host whose `/etc/passwd` is not persistent (a container re-created from its image) must re-create the accounts with the same uids
after a reboot: run `gameanything isolation migrate --apply --journal …` again (idempotent; files already have the right owners).

## 11. Single user vs hub

| | Single user | Hub |
|---|---|---|
| Accounts | `ga-agent` | `ga-<user>` per user |
| Provider login | `ga-agent`'s own (log in once, or `--copy-logins`) | the user's own login folder, handed to their account |
| Decisions | the UI server signs | the hub server signs; agent accounts cannot log in |
| Other users | none | cannot read each other's projects, logins, env files, runs |

Isolation needs Linux (or macOS) and a service account that can create users. Windows / desktop installs keep the one-user model
(the switch stays off; `client_mode()` is never true there).

## 12. Residual risks and what is not covered yet

- **The service account still runs some agent-provided input**: lab tools via `lab run` get the agent's arguments (each allowlisted tool
  must treat them as untrusted); `yaml.safe_load` of project files; ffmpeg / Pillow on her uploads. The guard covers file paths, not
  parser bugs.
- **Subprocesses of the service account inside project folders** (e.g. ffmpeg started by the UI) are not covered by the Python guard;
  they write only to paths the server chose, but a planted link in the target folder would be followed. To audit before enabling.
- **Same-user projects share an account**: a run of project A can change the working files of project B of the same user (never her
  decisions: those are in B's root-owned `conversation/` and signed with B's id).
- **Configuration the agent can still edit**: `config/project.yaml` keys other than id / owner / strictness (e.g. `chat_model`,
  `build_model`) are the agent's file. The go card is stamped with the build model by the server when it is posted.
- **Default ACLs** are needed for files the service account writes into agent folders to stay agent-editable. On a file system without
  POSIX ACLs isolation cannot be set up (the migration says so).
- **What the agent's own checks see**: it cannot reach the docker-rt socket, so a resident's own `setup` / `buildmode` probe says "no
  Docker here" (seen in the e2e: it told her the sandbox needs an admin). The lab state must come from the service side (a gate
  command or a public status file) before lab builds run isolated.
- **Builder skills** still call lab tools directly; with isolation on and a lab build, they must use `gameanything lab run`.
- **/proc/net/tcp** must show the agent's sockets (same network namespace as the UI). Behind a reverse proxy the peer is the proxy, which
  is fine: agent accounts never reach the UI through it (the proxy listens on the service side).
- Without isolation (the default) nothing of this is enforced; the one-user residual risk documented in `decisions.py` stays.

## 13. End-to-end check (2026-10-30)

Scratch home / data / agent root, UI on :8951, its own agentd, single-user `ga-agent` created by `isolation migrate --apply` and removed
by `isolation rollback --apply`. One project on Claude Code (sonnet), one on Gemini CLI (gemini-3.5-flash): both walked from new project
through perceive permission, people, 「确认这一天」, plan to the build go card, every agent write through the gate (`via: gate`, run id),
her clicks signed by the page. Then, as `ga-agent` with a run's environment: `serve_signing()+record()`, appending a public key, the
`Sec-Fetch-Dest` cookie trick and a POST in her name (403), reading hub_secret / users.yaml / the service home / her `.env` / the browser
profile / root's Claude login, appending an answer to the thread, moving the ledger or `conversation/`, rewriting the ledger or the heads,
and a gate call from outside a run: all refused. Editing `config/project.yaml id:` worked (the agent's file) and changed nothing on the
server (same id, still strict, her confirmations intact, the go card unanswered). Claude refused to run the attack script itself when
asked through a coordinator note.

## 14. Before turning it on (live server)

1. Finish or pause running builds (agentd adopts runs by pid; a run started as root keeps root's view).
2. `gameanything isolation migrate --code <checkout>` (dry run) and read it; `--apply --journal …` as root.
3. Each hub user logs in to their agent once as their account (or the admin copies the login into the account's config folder).
4. Builder docs: `gameanything lab run …`; `chmod 644` the lab broker files.
5. `agent_users: on` (or `--enable`), restart agentd and the UI / hub servers.
6. Rollback: `gameanything isolation rollback --journal … --apply`, `agent_users: off`, restart.
