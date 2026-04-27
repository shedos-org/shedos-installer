#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Finalization Module for Calamares

Final installation steps, run INSIDE the live ISO with the target root
mounted at libcalamares.globalstorage["rootMountPoint"]:

  1. Remove live-ISO-only files (motd, shedos-live.sh, issue)
  2. Rewrite /etc/issue for the installed system
  3. Set zsh as the user's default shell
  4. Add the user to `docker` and `libvirt` groups
  5. Initialize the pacman keyring
  6. Install fonts, rebuild fontconfig cache
  7. Initialize the PostgreSQL cluster (`initdb`)
  8. Enable systemd services (with a manual-symlink fallback)
  9. Configure git globals for the user
 10. Create XDG user directories + ~/projects, ~/work
 11. Enforce the Catppuccin SDDM theme and write autologin config

Anything that fails here is logged as a Calamares *warning* (not debug), so
it shows up in /var/log/calamares/session.log without needing --debug.
"""

import os
import shlex
import subprocess
from pathlib import Path

import libcalamares


# Services to enable on the installed system.
#
# Deliberately NOT enabled:
#   - auto-cpufreq.service, tlp.service — compete with power-profiles-daemon
#   - ufw.service                       — firewall off by default
#   - sshd.service                      — security-sensitive, user opts in
SERVICES = [
    # Core
    "NetworkManager.service",
    "bluetooth.service",
    "iwd.service",
    "sddm.service",
    "fstrim.timer",

    # Databases / dev daemons
    # NOTE: shedos-pg-initdb.service is enabled by shedos-system's .install
    # hook (post_install) — no need to duplicate that work here.
    "postgresql.service",             # initdb done below, BEFORE enable
    "docker.service",                 # containerized dev workflows

    # System services
    "cronie.service",                 # cron (timeshift dep + user crontabs)
    "avahi-daemon.service",           # mDNS / .local discovery
    "thermald.service",               # Intel CPU thermal mgmt (no-op on AMD)
    "power-profiles-daemon.service",  # desktop-integrated power profiles

    # Socket-activated (zero idle cost, start on first connection)
    "cups.socket",                    # printing
]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _run(cmd, *, capture=True):
    """
    Run a command, capture stdout+stderr, and log the result.

    Returns the CompletedProcess. Never raises — caller inspects returncode.
    """
    libcalamares.utils.debug(f"shedos_finalize: exec: {shlex.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=False,
    )
    return result


def _log_cmd_failure(label, result):
    """Format a failed subprocess result and log it as a Calamares warning."""
    libcalamares.utils.warning(
        f"shedos_finalize: {label} FAILED (rc={result.returncode})\n"
        f"  stdout: {(result.stdout or '').strip()}\n"
        f"  stderr: {(result.stderr or '').strip()}"
    )


def _chroot(root_mount_point, cmd):
    """Prepend arch-chroot to a command list."""
    return ["arch-chroot", root_mount_point, *cmd]


# ─────────────────────────────────────────────────────────────
# PostgreSQL user bootstrap
# ─────────────────────────────────────────────────────────────

def _pg_quote_ident(name):
    """Double-quote a SQL identifier, escaping embedded double-quotes."""
    return '"' + name.replace('"', '""') + '"'


def _pg_quote_literal(value):
    """
    Return a Postgres string literal. Uses the E'…' form when the value
    contains a backslash (required for standard_conforming_strings safety),
    otherwise plain '…' with single-quote doubling.
    """
    escaped = value.replace("'", "''")
    if "\\" in value:
        escaped = escaped.replace("\\", "\\\\")
        return "E'" + escaped + "'"
    return "'" + escaped + "'"


def _bootstrap_pg_user(root_mount_point, username):
    """
    Start an ephemeral postgres, create a role + database for `username`,
    optionally set the user's install password, and stop the server.

    All failures are logged but never raised. An end-to-end diagnostic
    report is ALWAYS written to /var/log/shedos-pg-bootstrap.log on the
    installed target, regardless of success or failure — Calamares' own
    session.log lives on the live ISO and is gone once the user reboots,
    so this persisted file is the only way a post-install user finds out
    what happened.
    """
    import datetime

    pgdata = "/var/lib/postgres/data"
    logfile = "/tmp/pg-bootstrap.log"
    sockdir = "/tmp"
    persisted_log_host = Path(root_mount_point) / "var/log/shedos-pg-bootstrap.log"

    report_lines = [
        f"# shedos-finalize PG bootstrap report — {datetime.datetime.now().isoformat()}",
        f"# username={username!r}",
    ]

    def _record_cmd(label, result):
        report_lines.append(f"\n[{label}] rc={result.returncode}")
        if result.stdout:
            report_lines.append(f"  stdout:\n{result.stdout.rstrip()}")
        if result.stderr:
            report_lines.append(f"  stderr:\n{result.stderr.rstrip()}")

    def _persist_report():
        # The ephemeral postgres server log (pg_ctl -l $LOGFILE) lives in the
        # arch-chroot's private mount namespace and evaporates when bash
        # exits. We dump it to stdout inside the bash script instead (see
        # `=== server log ===` section below), so _record_cmd already picked
        # it up as part of the bootstrap result's stdout.
        try:
            persisted_log_host.parent.mkdir(parents=True, exist_ok=True)
            persisted_log_host.write_text("\n".join(report_lines) + "\n")
        except Exception as e:
            libcalamares.utils.warning(
                f"shedos_finalize: could not persist pg-bootstrap report: {e}"
            )

    # Password may or may not be exposed by Calamares' users module. If it's
    # hashed (shadow $id$…$ form), it's useless for postgres — skip.
    raw_pw = libcalamares.globalstorage.value("password")
    if not raw_pw or (isinstance(raw_pw, str) and raw_pw.startswith("$")):
        raw_pw = None
    report_lines.append(f"# raw_pw_available={bool(raw_pw)}")

    ident = _pg_quote_ident(username)
    name_lit = _pg_quote_literal(username)

    sql = (
        f"DO $$ BEGIN\n"
        f"  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {name_lit}) THEN\n"
        f"    CREATE ROLE {ident} WITH LOGIN CREATEDB;\n"
        f"  END IF;\n"
        f"END $$;\n"
    )
    if raw_pw:
        sql += f"ALTER ROLE {ident} WITH PASSWORD {_pg_quote_literal(raw_pw)};\n"
    sql += (
        f"SELECT 'CREATE DATABASE {ident} OWNER {ident}'\n"
        f"  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = {name_lit})\n"
        f"\\gexec\n"
    )

    # Run pg_ctl start, psql, pg_ctl stop as a single arch-chroot invocation.
    # Separate invocations each get their own private /tmp under recent
    # util-linux, so the ephemeral socket created by pg_ctl at /tmp/.s.PGSQL.*
    # isn't visible to a later psql call. Keeping everything in one shell
    # session fixes that.
    #
    # The SQL is passed inside a single-quoted heredoc — no shell substitution
    # happens on its contents, so psql-escaped values from _pg_quote_literal
    # reach postgres unmolested.
    pg_opts = f"-c listen_addresses='' -c unix_socket_directories={sockdir}"
    script = f"""set -u
PGDATA={shlex.quote(pgdata)}
LOGFILE={shlex.quote(logfile)}
SOCKDIR={shlex.quote(sockdir)}
PGOPTS={shlex.quote(pg_opts)}

start_rc=0 psql_rc=0 stop_rc=0

echo '=== pg_ctl start ==='
runuser -u postgres -- pg_ctl -D "$PGDATA" -l "$LOGFILE" -w -o "$PGOPTS" start
start_rc=$?
echo "start_rc=$start_rc"

if [ "$start_rc" -eq 0 ]; then
    cat > /tmp/pg-bootstrap.sql <<'SHEDOS_SQL_EOF'
{sql}SHEDOS_SQL_EOF

    echo '=== psql bootstrap ==='
    runuser -u postgres -- psql -h "$SOCKDIR" -U postgres -d postgres \\
        -v ON_ERROR_STOP=1 -f /tmp/pg-bootstrap.sql
    psql_rc=$?
    echo "psql_rc=$psql_rc"
    rm -f /tmp/pg-bootstrap.sql

    echo '=== pg_ctl stop ==='
    runuser -u postgres -- pg_ctl -D "$PGDATA" -m fast stop
    stop_rc=$?
    echo "stop_rc=$stop_rc"
fi

echo '=== server log ==='
# $LOGFILE lives in the ephemeral chroot /tmp and dies with this shell —
# read it here so the captured stdout preserves it for the persisted report.
if [ -r "$LOGFILE" ]; then
    cat "$LOGFILE"
else
    echo "(server log $LOGFILE not readable — pg_ctl may not have reached it)"
fi

exit $(( start_rc | psql_rc | stop_rc ))
"""

    cmd = _chroot(root_mount_point, ["bash", "-c", script])
    try:
        libcalamares.utils.debug(
            "shedos_finalize: exec: arch-chroot <root> bash -c <bootstrap script>"
        )
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        _record_cmd("bootstrap (pg_ctl start / psql / pg_ctl stop)", r)
        if r.returncode != 0:
            _log_cmd_failure(f"pg bootstrap for {username}", r)
            libcalamares.utils.warning(
                "shedos_finalize: pg bootstrap did not fully succeed; see "
                "/var/log/shedos-pg-bootstrap.log on the installed system. "
                "The shedos-pg-user-bootstrap.service first-boot unit will "
                "retry on next boot."
            )
        else:
            pw_note = "with password" if raw_pw else "peer-auth only (no password)"
            libcalamares.utils.debug(
                f"shedos_finalize: created PG role + DB for {username} ({pw_note})"
            )
    finally:
        _persist_report()


# ─────────────────────────────────────────────────────────────
# Service enablement
# ─────────────────────────────────────────────────────────────

def _enable_one_service(root_mount_point, root_mount, service):
    """
    Enable a single systemd unit in the target root. Tries three strategies
    and returns True on the first one that works:

      1. `systemctl --root=<target> enable <unit>`
         The canonical offline path. Doesn't need a chroot. Preferred.

      2. `arch-chroot <target> systemctl enable <unit>`
         Traditional fallback. Works if the host's systemctl can't parse
         something in the target root.

      3. Parse the unit's [Install] section and manually create the
         WantedBy/RequiredBy symlink. Last resort for truly odd cases
         (e.g. systemd version mismatch). Independent of systemctl entirely.
    """
    # Strategy 1: systemctl --root=
    r1 = _run(["systemctl", f"--root={root_mount_point}", "enable", service])
    if r1.returncode == 0:
        libcalamares.utils.debug(f"shedos_finalize: enabled {service} (--root)")
        return True

    # Strategy 2: arch-chroot systemctl
    r2 = _run(_chroot(root_mount_point, ["systemctl", "enable", service]))
    if r2.returncode == 0:
        libcalamares.utils.debug(f"shedos_finalize: enabled {service} (chroot)")
        return True

    # Strategy 3: manual symlink from [Install] section
    if _manual_enable(root_mount, service):
        libcalamares.utils.debug(f"shedos_finalize: enabled {service} (manual)")
        return True

    # All three strategies failed — log loudly.
    libcalamares.utils.warning(
        f"shedos_finalize: could not enable {service}\n"
        f"  --root:    rc={r1.returncode} stderr={(r1.stderr or '').strip()!r}\n"
        f"  chroot:    rc={r2.returncode} stderr={(r2.stderr or '').strip()!r}\n"
        f"  manual:    unit has no [Install] section or file missing"
    )
    return False


def _manual_enable(root_mount, service):
    """
    Read the unit file's [Install] section and create the appropriate
    WantedBy/RequiredBy symlinks manually. Returns True on success.
    """
    unit_path = None
    for candidate in (
        root_mount / "usr/lib/systemd/system" / service,
        root_mount / "etc/systemd/system" / service,
    ):
        if candidate.exists():
            unit_path = candidate
            break
    if unit_path is None:
        return False

    try:
        content = unit_path.read_text()
    except Exception:
        return False

    in_install = False
    wanted_by, required_by = [], []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_install = (stripped == "[Install]")
            continue
        if not in_install or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        key, val = key.strip(), val.strip()
        if key == "WantedBy":
            wanted_by.extend(val.split())
        elif key == "RequiredBy":
            required_by.extend(val.split())

    if not wanted_by and not required_by:
        return False

    # The symlink target is an ABSOLUTE path inside the target root, so
    # it'll work on the running installed system even though we're creating
    # the link from the live ISO's perspective.
    target_rel = f"/usr/lib/systemd/system/{service}"

    def _mklink(subdir_name, target_name):
        subdir = root_mount / "etc/systemd/system" / f"{target_name}.{subdir_name}"
        subdir.mkdir(parents=True, exist_ok=True)
        link = subdir / service
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target_rel)

    for t in wanted_by:
        _mklink("wants", t)
    for t in required_by:
        _mklink("requires", t)
    return True


# ─────────────────────────────────────────────────────────────
# Calamares entry point
# ─────────────────────────────────────────────────────────────

def pretty_name():
    return "Finalizing ShedOS installation"


def run():
    libcalamares.utils.debug("shedos_finalize: Starting finalization")

    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        libcalamares.utils.warning("shedos_finalize: No rootMountPoint found")
        return ("No root mount point found.", "")

    root_mount = Path(root_mount_point)
    libcalamares.utils.debug(f"shedos_finalize: Root mount: {root_mount}")

    username = libcalamares.globalstorage.value("username")
    fullname = libcalamares.globalstorage.value("fullname") or username
    libcalamares.utils.debug(
        f"shedos_finalize: username={username}, fullname={fullname}"
    )
    if not username:
        libcalamares.utils.warning("shedos_finalize: No username found")
        return None

    # ── 1. Remove live-ISO-only files ──────────────────────────────────
    for file_path in (
        root_mount / "etc" / "profile.d" / "shedos-live.sh",
        root_mount / "etc" / "motd",
    ):
        try:
            if file_path.exists():
                file_path.unlink()
                libcalamares.utils.debug(f"shedos_finalize: Removed {file_path}")
        except Exception as e:
            libcalamares.utils.warning(
                f"shedos_finalize: Could not remove {file_path}: {e}"
            )

    # ── 2. Rewrite /etc/issue ──────────────────────────────────────────
    issue_content = "\nshedOS\nKernel: \\r on \\m\nTTY: \\l\n\n"
    try:
        (root_mount / "etc" / "issue").write_text(issue_content)
        libcalamares.utils.debug("shedos_finalize: Updated /etc/issue")
    except Exception as e:
        libcalamares.utils.warning(
            f"shedos_finalize: Could not update /etc/issue: {e}"
        )

    # ── 3. Default shell = zsh ─────────────────────────────────────────
    r = _run(_chroot(root_mount_point, ["chsh", "-s", "/usr/bin/zsh", username]))
    if r.returncode != 0:
        _log_cmd_failure(f"chsh -s zsh {username}", r)

    shells_file = root_mount / "etc" / "shells"
    try:
        if shells_file.exists() and "/usr/bin/zsh" not in shells_file.read_text():
            with open(shells_file, "a") as f:
                f.write("/usr/bin/zsh\n")
    except Exception as e:
        libcalamares.utils.warning(f"shedos_finalize: /etc/shells update: {e}")

    # ── 4. Groups: docker ──────────────────────────────────────────────
    # libvirt was dropped from the default install; users who add libvirt
    # later can `usermod -aG libvirt $USER` themselves.
    r = _run(_chroot(root_mount_point, ["usermod", "-aG", "docker", username]))
    if r.returncode != 0:
        _log_cmd_failure(f"usermod -aG docker {username}", r)

    # ── 5. Pacman keyring init ─────────────────────────────────────────
    for kcmd in (["pacman-key", "--init"],
                 ["pacman-key", "--populate", "archlinux"]):
        r = _run(_chroot(root_mount_point, kcmd))
        if r.returncode != 0:
            _log_cmd_failure(" ".join(kcmd), r)

    # Sync databases (may fail offline — not fatal)
    r = _run(_chroot(root_mount_point, ["pacman", "-Sy", "--noconfirm"]))
    if r.returncode != 0:
        libcalamares.utils.debug(
            "shedos_finalize: pacman -Sy didn't succeed (probably offline); "
            "not fatal"
        )

    # ── 6. Font packages + cache ───────────────────────────────────────
    r = _run(_chroot(root_mount_point,
                     ["pacman", "-S", "--noconfirm", "--needed",
                      "ttf-font-awesome", "ttf-nerd-fonts-symbols"]))
    if r.returncode != 0:
        libcalamares.utils.debug(
            "shedos_finalize: font pacman -S didn't succeed "
            "(likely already installed); not fatal"
        )
    _run(_chroot(root_mount_point, ["fc-cache", "-f"]))

    # ── 7. PostgreSQL cluster init ─────────────────────────────────────
    # Use `runuser -u postgres --` instead of `su - postgres -c "..."`:
    # inside arch-chroot there's no real logind/PAM session, and `su -` can
    # fail silently when pam_systemd/pam_loginuid can't establish one.
    # `runuser` bypasses the PAM session stack and is the canonical choice
    # for chroot/scripted user switches — it's what Arch's own postgresql
    # hooks use.
    pgdata = root_mount / "var/lib/postgres/data"
    if pgdata.exists() and (pgdata / "PG_VERSION").exists():
        libcalamares.utils.debug("shedos_finalize: PG cluster already present")
    else:
        libcalamares.utils.debug("shedos_finalize: Initializing PG cluster")

        # Ensure data dir exists and is owned by postgres (0700). The package
        # post-install should have done this, but we don't want to rely on it.
        for cmd in (
            ["mkdir", "-p", "/var/lib/postgres/data"],
            ["chown", "postgres:postgres",
             "/var/lib/postgres", "/var/lib/postgres/data"],
            ["chmod", "0700", "/var/lib/postgres/data"],
        ):
            r = _run(_chroot(root_mount_point, cmd))
            if r.returncode != 0:
                _log_cmd_failure(" ".join(cmd), r)

        r = _run(_chroot(
            root_mount_point,
            ["runuser", "-u", "postgres", "--",
             "initdb",
             "--locale=en_US.UTF-8",
             "--encoding=UTF8",
             "--data-checksums",
             "-D", "/var/lib/postgres/data"],
        ))
        if r.returncode != 0:
            _log_cmd_failure("postgres initdb", r)

        # Verify from Python — exit codes lie sometimes.
        if not (pgdata / "PG_VERSION").exists():
            libcalamares.utils.warning(
                "shedos_finalize: PG_VERSION missing after initdb. "
                "postgresql.service will not start on first boot unless the "
                "shedos-pg-initdb.service fallback succeeds. To fix manually: "
                "`sudo -iu postgres initdb --locale=en_US.UTF-8 "
                "--encoding=UTF8 --data-checksums -D /var/lib/postgres/data`."
            )

    # ── 7b. Bootstrap a Postgres role + database for the installed user ──
    # Runs an ephemeral postgres via pg_ctl (no systemd) bound to a unix
    # socket in /tmp, creates a role matching the OS username with LOGIN +
    # CREATEDB, optionally sets the install password, and creates a same-
    # named database they own. Arch's default pg_hba has `local all all peer`
    # so they can `psql` from their shell with no flags.
    if (pgdata / "PG_VERSION").exists() and username:
        _bootstrap_pg_user(root_mount_point, username)

    # ── 8. Enable services ─────────────────────────────────────────────
    libcalamares.utils.debug("shedos_finalize: Enabling services")
    ok, bad = [], []
    for service in SERVICES:
        if _enable_one_service(root_mount_point, root_mount, service):
            ok.append(service)
        else:
            bad.append(service)
    libcalamares.utils.debug(
        f"shedos_finalize: services enabled {len(ok)}/{len(SERVICES)}"
    )
    if bad:
        libcalamares.utils.warning(
            f"shedos_finalize: {len(bad)} service(s) could not be enabled: "
            f"{', '.join(bad)}. Run `shedos-check-services` on the installed "
            f"system to diagnose."
        )

    # ── 9. Git config for the user ─────────────────────────────────────
    if username and fullname:
        git_settings = [
            ("user.name", fullname),
            ("init.defaultBranch", "main"),
            ("core.editor", "nvim"),
            ("pull.rebase", "false"),
            ("push.default", "current"),
            ("push.autoSetupRemote", "true"),
            ("color.ui", "auto"),
            ("alias.st", "status"),
            ("alias.co", "checkout"),
            ("alias.br", "branch"),
            ("alias.ci", "commit"),
            ("alias.lg", "log --oneline --graph --decorate"),
            ("alias.last", "log -1 HEAD"),
            ("alias.unstage", "reset HEAD --"),
        ]
        git_failed = []
        for key, value in git_settings:
            r = _run(_chroot(
                root_mount_point,
                ["su", "-", username, "-c",
                 f"git config --global {shlex.quote(key)} "
                 f"{shlex.quote(value)}"],
            ))
            if r.returncode != 0:
                git_failed.append(key)
        if git_failed:
            libcalamares.utils.warning(
                f"shedos_finalize: git config failed for keys: {git_failed}"
            )
        else:
            libcalamares.utils.debug(
                f"shedos_finalize: git configured ({len(git_settings)} keys)"
            )

    # ── 10. XDG user directories + ~/projects, ~/work ──────────────────
    _run(_chroot(root_mount_point,
                 ["su", "-", username, "-c", "xdg-user-dirs-update"]))
    for user_dir in ("projects", "work"):
        _run(_chroot(root_mount_point,
                     ["su", "-", username, "-c", f"mkdir -p ~/{user_dir}"]))

    # ── 11. SDDM theme + autologin ─────────────────────────────────────
    sddm_dir = root_mount / "etc" / "sddm.conf.d"
    try:
        sddm_dir.mkdir(parents=True, exist_ok=True)
        (sddm_dir / "theme.conf").write_text(
            "[Theme]\nCurrent=catppuccin-mocha-mauve\n"
        )

        # Drop the live-ISO autologin if present
        live_autologin = sddm_dir / "live-session-autologin.conf"
        if live_autologin.exists():
            live_autologin.unlink()

        # Write installed-system autologin.
        # NOTE: Session= is the filename STEM of a .desktop in
        # /usr/share/wayland-sessions/. For Hyprland that is `hyprland` (from
        # hyprland.desktop). Do NOT change to `start-hyprland` — that's the
        # wrapper binary the .desktop invokes via Exec=, not the session name.
        # A wrong value makes SDDM silently fall back to the login form.
        (sddm_dir / "autologin.conf").write_text(
            f"[Autologin]\nUser={username}\nSession=hyprland\nRelogin=false\n"
        )
        libcalamares.utils.debug(
            f"shedos_finalize: wrote SDDM autologin for {username}"
        )

        # Replace 'Current=breeze' anywhere the displaymanager module wrote it
        for conf_file in sddm_dir.glob("*.conf"):
            if conf_file.name == "theme.conf":
                continue
            try:
                content = conf_file.read_text()
                if "Current=breeze" in content:
                    conf_file.write_text(
                        content.replace("Current=breeze",
                                        "Current=catppuccin-mocha-mauve")
                    )
            except Exception as e:
                libcalamares.utils.warning(
                    f"shedos_finalize: checking {conf_file}: {e}"
                )
    except Exception as e:
        libcalamares.utils.warning(
            f"shedos_finalize: SDDM theme/autologin setup: {e}"
        )

    # ── Final sync ─────────────────────────────────────────────────────
    os.system("sync")
    libcalamares.utils.debug("shedos_finalize: Installation finalized")
    return None
