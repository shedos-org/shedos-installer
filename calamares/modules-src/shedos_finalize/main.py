#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS finalization module for Calamares.

Runs inside the live ISO with the target root mounted at
libcalamares.globalstorage["rootMountPoint"]. Anything that fails here is
logged as a Calamares *warning* (not debug) so it shows up in
/var/log/calamares/session.log without needing --debug.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import libcalamares


# Services this module enables on the installed system.
#
# Other ShedOS services (tlp, ananicy-cpp, snapper-timeline,
# snapper-cleanup, systemd-oomd) are owned by shedos-system's
# post_install hook, not this module. ufw stays off by default; the
# firewall is reconciled via [network.firewall] in system.toml. sshd
# is left off because it's security-sensitive — user opts in.
SERVICES = [
    "NetworkManager.service",
    "bluetooth.service",
    "iwd.service",
    "seatd.service",
    "greetd.service",
    "fstrim.timer",

    # shedos-pg-initdb.service is enabled by shedos-system's .install hook
    # (post_install) — no need to duplicate that work here.
    "postgresql.service",
    "docker.service",

    "thermald.service",
]


def _run(cmd, *, capture=True):
    """Run a command, capture stdout+stderr, log it. Never raises."""
    libcalamares.utils.debug(f"shedos_finalize: exec: {shlex.join(cmd)}")
    return subprocess.run(cmd, capture_output=capture, text=True, check=False)


def _log_cmd_failure(label, result):
    libcalamares.utils.warning(
        f"shedos_finalize: {label} FAILED (rc={result.returncode})\n"
        f"  stdout: {(result.stdout or '').strip()}\n"
        f"  stderr: {(result.stderr or '').strip()}"
    )


def _chroot(root_mount_point, cmd):
    return ["arch-chroot", root_mount_point, *cmd]


def _pg_quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def _pg_quote_literal(value):
    """E'…' form when the value contains a backslash (required for
    standard_conforming_strings safety), otherwise plain '…' with
    single-quote doubling."""
    escaped = value.replace("'", "''")
    if "\\" in value:
        escaped = escaped.replace("\\", "\\\\")
        return "E'" + escaped + "'"
    return "'" + escaped + "'"


def _bootstrap_pg_user(root_mount_point, username):
    """Start an ephemeral postgres, create a role + database for `username`,
    optionally set the install password, and stop the server.

    All failures are logged but never raised. An end-to-end report is
    ALWAYS written to /var/log/shedos-pg-bootstrap.log on the target —
    Calamares' session.log lives on the live ISO and is gone once the
    user reboots, so this persisted file is the only record post-install.
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
        try:
            persisted_log_host.parent.mkdir(parents=True, exist_ok=True)
            persisted_log_host.write_text("\n".join(report_lines) + "\n")
        except Exception as e:
            libcalamares.utils.warning(
                f"shedos_finalize: could not persist pg-bootstrap report: {e}"
            )

    # Password may or may not be exposed by Calamares' users module. If
    # it's hashed (shadow $id$…$ form), it's useless for postgres.
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

    # pg_ctl start, psql, pg_ctl stop must run as a single arch-chroot
    # invocation. Separate invocations each get their own private /tmp
    # under recent util-linux, so the ephemeral socket created by pg_ctl
    # at /tmp/.s.PGSQL.* isn't visible to a later psql call.
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


def _enable_one_service(root_mount_point, root_mount, service):
    """Enable a unit in the target root. Tries three strategies and
    returns True on the first success:

      1. systemctl --root=<target> enable <unit>   (canonical, no chroot)
      2. arch-chroot <target> systemctl enable     (fallback)
      3. parse [Install] and create the symlink manually  (last resort)
    """
    r1 = _run(["systemctl", f"--root={root_mount_point}", "enable", service])
    if r1.returncode == 0:
        libcalamares.utils.debug(f"shedos_finalize: enabled {service} (--root)")
        return True

    r2 = _run(_chroot(root_mount_point, ["systemctl", "enable", service]))
    if r2.returncode == 0:
        libcalamares.utils.debug(f"shedos_finalize: enabled {service} (chroot)")
        return True

    if _manual_enable(root_mount, service):
        libcalamares.utils.debug(f"shedos_finalize: enabled {service} (manual)")
        return True

    libcalamares.utils.warning(
        f"shedos_finalize: could not enable {service}\n"
        f"  --root:    rc={r1.returncode} stderr={(r1.stderr or '').strip()!r}\n"
        f"  chroot:    rc={r2.returncode} stderr={(r2.stderr or '').strip()!r}\n"
        f"  manual:    unit has no [Install] section or file missing"
    )
    return False


def _manual_enable(root_mount, service):
    """Read the unit's [Install] section and create WantedBy/RequiredBy
    symlinks manually. Returns True on success."""
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

    # Absolute path inside the target — the link works on the running
    # system even though we create it from the live ISO's perspective.
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


def _persist_wifi_profiles(root_mount_point, root_mount):
    """Copy NetworkManager + iwd WiFi profiles from the live ISO onto
    the installed system, ship the NM-through-iwd routing drop-in,
    and mirror the psk-flags=0 default for new connections joined
    post-install.

    Calamares' networkcfg module can be flaky, and live-session
    secrets are often only in the keyring (not on disk), so the
    active connection's secrets are forced to file via nmcli first.

    Failures are logged; never raises.
    """
    libcalamares.utils.debug("shedos_finalize: Persisting NetworkManager connections...")
    try:
        try:
            output = subprocess.check_output(
                ["nmcli", "-t", "-f", "UUID,TYPE,DEVICE",
                 "connection", "show", "--active"],
                text=True,
            ).strip()

            for line in output.split('\n'):
                if not line:
                    continue
                parts = line.split(':')
                if len(parts) >= 2 and parts[1] == "802-11-wireless":
                    uuid = parts[0]
                    libcalamares.utils.debug(f"shedos_finalize: Found active WiFi UUID: {uuid}")

                    # psk-flags=0   → store secret on disk, not keyring
                    # permissions="" → available to all users
                    # save           → flush to disk immediately
                    subprocess.run(
                        ["nmcli", "connection", "modify", uuid,
                         "802-11-wireless-security.psk-flags", "0"],
                        check=False,
                    )
                    subprocess.run(
                        ["nmcli", "connection", "modify", uuid,
                         "connection.permissions", ""],
                        check=False,
                    )
                    subprocess.run(
                        ["nmcli", "connection", "save", uuid],
                        check=False,
                    )
                    libcalamares.utils.debug(f"shedos_finalize: Forced persistence for {uuid}")
        except Exception as nm_e:
            libcalamares.utils.warning(f"shedos_finalize: Failed to prepare NM connections: {nm_e}")

        source_connections = Path("/etc/NetworkManager/system-connections")
        target_connections = root_mount / "etc/NetworkManager/system-connections"

        nm_count = 0
        if not source_connections.exists() or not source_connections.is_dir():
            libcalamares.utils.warning(
                f"shedos_finalize: {source_connections} missing on live ISO; "
                f"no NetworkManager profiles to persist"
            )
        else:
            nm_sources = sorted(p.name for p in source_connections.iterdir())
            libcalamares.utils.debug(
                f"shedos_finalize: NM source listing: {nm_sources}"
            )
            if not nm_sources:
                libcalamares.utils.warning(
                    "shedos_finalize: /etc/NetworkManager/system-connections is "
                    "empty — user may have joined wifi via iwd only (that's OK, "
                    "iwd profiles are copied separately below)"
                )
            target_connections.mkdir(parents=True, exist_ok=True)
            for conn_file in source_connections.iterdir():
                if conn_file.is_file() and not conn_file.name.endswith(".example"):
                    dest = target_connections / conn_file.name
                    shutil.copy2(conn_file, dest)
                    os.chmod(dest, 0o600)
                    nm_count += 1
            if nm_count > 0:
                libcalamares.utils.debug(
                    f"shedos_finalize: Copied {nm_count} NM connection profiles"
                )
                chown_res = subprocess.run(
                    ["chown", "-R", "root:root", str(target_connections)],
                    capture_output=True,
                    text=True,
                )
                if chown_res.returncode != 0:
                    libcalamares.utils.warning(
                        f"shedos_finalize: chown of NM target returned "
                        f"{chown_res.returncode}: {chown_res.stderr}"
                    )
            nm_landed = sorted(p.name for p in target_connections.iterdir())
            libcalamares.utils.warning(
                f"shedos_finalize: NM target listing: {nm_landed}"
            )
            # Inspect copied .nmconnection files for psk presence so we
            # can tell post-install whether secrets actually transferred.
            for nm_file in sorted(target_connections.iterdir()):
                if not nm_file.is_file() or not nm_file.name.endswith(".nmconnection"):
                    continue
                try:
                    contents = nm_file.read_text()
                except OSError:
                    continue
                has_psk = "\npsk=" in ("\n" + contents)
                psk_flags = "0"
                for line in contents.splitlines():
                    if line.startswith("psk-flags="):
                        psk_flags = line.split("=", 1)[1].strip()
                        break
                libcalamares.utils.warning(
                    f"shedos_finalize: NM {nm_file.name}: psk={'present' if has_psk else 'MISSING'}, psk-flags={psk_flags}"
                )

        # iwd profiles. The waybar network icon launches impala (an iwd
        # TUI), so most users connect via iwd — whose profiles live in
        # /var/lib/iwd/*.psk, NOT in NetworkManager's dir. Without this
        # copy, wifi credentials entered during install are lost on reboot.
        source_iwd = Path("/var/lib/iwd")
        target_iwd = root_mount / "var/lib/iwd"
        iwd_count = 0
        if not source_iwd.exists() or not source_iwd.is_dir():
            libcalamares.utils.warning(
                f"shedos_finalize: {source_iwd} missing on live ISO; "
                f"no iwd profiles to persist"
            )
        else:
            try:
                iwd_sources = sorted(p.name for p in source_iwd.iterdir())
                libcalamares.utils.warning(
                    f"shedos_finalize: iwd source listing: {iwd_sources}"
                )
            except PermissionError as pe:
                libcalamares.utils.warning(
                    f"shedos_finalize: Cannot read /var/lib/iwd (need root): {pe}"
                )
                iwd_sources = []
            target_iwd.mkdir(parents=True, exist_ok=True)
            try:
                for psk_file in source_iwd.iterdir():
                    if psk_file.is_file() and psk_file.suffix in (".psk", ".open", ".8021x"):
                        dest = target_iwd / psk_file.name
                        shutil.copy2(psk_file, dest)
                        os.chmod(dest, 0o600)
                        iwd_count += 1
            except PermissionError as pe:
                libcalamares.utils.warning(
                    f"shedos_finalize: Cannot read /var/lib/iwd (need root): {pe}"
                )
            if iwd_count > 0:
                libcalamares.utils.warning(
                    f"shedos_finalize: Copied {iwd_count} iwd profiles"
                )
                os.chmod(target_iwd, 0o700)
                iwd_chown = subprocess.run(
                    ["chown", "-R", "root:root", str(target_iwd)],
                    capture_output=True,
                    text=True,
                )
                if iwd_chown.returncode != 0:
                    libcalamares.utils.warning(
                        f"shedos_finalize: chown of iwd target returned "
                        f"{iwd_chown.returncode}: {iwd_chown.stderr}"
                    )
            if target_iwd.exists():
                iwd_landed = sorted(p.name for p in target_iwd.iterdir())
                libcalamares.utils.warning(
                    f"shedos_finalize: iwd target listing: {iwd_landed}"
                )
                # Inspect copied iwd psk files for actual secret content
                # so we know post-install whether the password is in there.
                for psk_file in sorted(target_iwd.iterdir()):
                    if not psk_file.is_file() or psk_file.suffix not in (".psk", ".open", ".8021x"):
                        continue
                    try:
                        contents = psk_file.read_text()
                    except OSError:
                        continue
                    has_secret = "PreSharedKey=" in contents or "Passphrase=" in contents
                    libcalamares.utils.warning(
                        f"shedos_finalize: iwd {psk_file.name}: secret={'present' if has_secret else 'MISSING'}"
                    )

        # Loud warning when both sources are empty — the user will have
        # to re-enter wifi on first boot, and this is the symptom we want
        # to catch loud rather than silently.
        if nm_count == 0 and iwd_count == 0:
            libcalamares.utils.warning(
                "shedos_finalize: WiFi profiles NOT persisted — user will have "
                "to re-enter wifi password on first boot. Both "
                "/etc/NetworkManager/system-connections and /var/lib/iwd were "
                "empty or unreadable on the live ISO."
            )

        # Route NetworkManager's WiFi through iwd in the installed
        # system. Both services are enabled and without this config they
        # fight over the WiFi device. With iwd as the backend, NM
        # presents iwd's stored profiles as its own on boot.
        nm_conf_d = root_mount / "etc/NetworkManager/conf.d"
        nm_conf_d.mkdir(parents=True, exist_ok=True)
        (nm_conf_d / "wifi_backend.conf").write_text(
            "# ShedOS: route NetworkManager WiFi through iwd (see /var/lib/iwd/)\n"
            "[device]\n"
            "wifi.backend=iwd\n"
        )
        libcalamares.utils.debug("shedos_finalize: Wrote NM wifi_backend.conf (iwd)")

        # Ship the live-ISO psk-flags=0 NM drop-in to the installed
        # system too. Without it, any wifi joined for the FIRST time
        # AFTER install reverts to agent-owned secrets (stored in the
        # user's login keyring only) and won't auto-connect on cold boot.
        nm_defaults_src = Path(
            "/etc/NetworkManager/conf.d/20-connection-defaults.conf"
        )
        nm_defaults_dst = nm_conf_d / "20-connection-defaults.conf"
        if nm_defaults_src.exists():
            shutil.copy2(nm_defaults_src, nm_defaults_dst)
            libcalamares.utils.debug(
                f"shedos_finalize: Copied {nm_defaults_src.name} to target"
            )
        else:
            libcalamares.utils.warning(
                f"shedos_finalize: {nm_defaults_src} missing on live ISO; "
                f"new wifi connections on the installed system won't persist"
            )
    except Exception as e:
        libcalamares.utils.warning(f"shedos_finalize: Failed to persist wifi profiles: {e}")


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

    issue_content = "\nShedOS\nKernel: \\r on \\m\nTTY: \\l\n\n"
    try:
        (root_mount / "etc" / "issue").write_text(issue_content)
        libcalamares.utils.debug("shedos_finalize: Updated /etc/issue")
    except Exception as e:
        libcalamares.utils.warning(
            f"shedos_finalize: Could not update /etc/issue: {e}"
        )

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

    r = _run(_chroot(root_mount_point, ["usermod", "-aG", "docker", username]))
    if r.returncode != 0:
        _log_cmd_failure(f"usermod -aG docker {username}", r)

    r = _run(_chroot(root_mount_point,
                     ["pacman", "-S", "--noconfirm", "--needed",
                      "ttf-font-awesome", "ttf-nerd-fonts-symbols"]))
    if r.returncode != 0:
        libcalamares.utils.debug(
            "shedos_finalize: font pacman -S didn't succeed "
            "(likely already installed); not fatal"
        )
    _run(_chroot(root_mount_point, ["fc-cache", "-f"]))

    # PostgreSQL cluster init. Use `runuser -u postgres --` instead of
    # `su - postgres -c`: inside arch-chroot there's no real logind/PAM
    # session, and `su -` can fail silently when pam_systemd can't establish
    # one. runuser bypasses the PAM session stack and is the canonical
    # choice for chroot/scripted user switches.
    pgdata = root_mount / "var/lib/postgres/data"
    if pgdata.exists() and (pgdata / "PG_VERSION").exists():
        libcalamares.utils.debug("shedos_finalize: PG cluster already present")
    else:
        libcalamares.utils.debug("shedos_finalize: Initializing PG cluster")

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

        if not (pgdata / "PG_VERSION").exists():
            libcalamares.utils.warning(
                "shedos_finalize: PG_VERSION missing after initdb. "
                "postgresql.service will not start on first boot unless the "
                "shedos-pg-initdb.service fallback succeeds. To fix manually: "
                "`sudo -iu postgres initdb --locale=en_US.UTF-8 "
                "--encoding=UTF8 --data-checksums -D /var/lib/postgres/data`."
            )

    # Bootstrap a PG role + database for the installed user. Arch's
    # default pg_hba has `local all all peer` so they can `psql` from
    # their shell with no flags after first boot.
    if (pgdata / "PG_VERSION").exists() and username:
        _bootstrap_pg_user(root_mount_point, username)

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

    _persist_wifi_profiles(root_mount_point, root_mount)

    # libseat group membership — Hyprland and any other libseat client
    # need this to acquire seat0. Calamares' users module SHOULD have
    # added it via defaultGroups, but past releases shipped without; this
    # is the belt-and-braces guarantee. Idempotent.
    if username:
        _run(_chroot(root_mount_point, ["groupadd", "-r", "-f", "seat"]))
        r = _run(_chroot(root_mount_point,
                         ["usermod", "-aG", "seat", username]))
        if r.returncode != 0:
            _log_cmd_failure(f"usermod -aG seat {username}", r)

    _run(_chroot(root_mount_point,
                 ["su", "-", username, "-c", "xdg-user-dirs-update"]))
    for user_dir in ("Projects", "Work"):
        _run(_chroot(root_mount_point,
                     ["su", "-", username, "-c", f"mkdir -p ~/{user_dir}"]))

    # /etc/shedos/login-user — shedos-greeter reads this to know which
    # account to authenticate. Falls back to /etc/passwd auto-detect if
    # the file is missing, but writing it here makes the choice explicit
    # and survives package upgrades that might add another uid >= 1000.
    login_user_file = root_mount / "etc" / "shedos" / "login-user"
    try:
        login_user_file.parent.mkdir(parents=True, exist_ok=True)
        login_user_file.write_text(f"{username}\n")
        libcalamares.utils.debug(
            f"shedos_finalize: wrote login user '{username}' to {login_user_file}"
        )
    except Exception as e:
        libcalamares.utils.warning(
            f"shedos_finalize: writing {login_user_file}: {e}"
        )

    # greetd autologin: strip the [initial_session] block left over from
    # the live ISO (which autologs the live `shedos` user); if Calamares
    # set autologinUser, write a new [initial_session] for that user.
    greetd_config = root_mount / "etc" / "greetd" / "config.toml"
    try:
        if greetd_config.exists():
            import tomlkit
            doc = tomlkit.parse(greetd_config.read_text())
            if "initial_session" in doc:
                del doc["initial_session"]

            autologin_user = libcalamares.globalstorage.value("autologinUser")
            if autologin_user:
                initial = tomlkit.table()
                initial["command"] = "Hyprland"
                initial["user"] = autologin_user
                doc["initial_session"] = initial
                libcalamares.utils.debug(
                    f"shedos_finalize: greetd autologin set for {autologin_user}"
                )

            greetd_config.write_text(tomlkit.dumps(doc))
    except Exception as e:
        libcalamares.utils.warning(
            f"shedos_finalize: greetd autologin setup: {e}"
        )

    os.system("sync")
    libcalamares.utils.debug("shedos_finalize: Installation finalized")
    return None
