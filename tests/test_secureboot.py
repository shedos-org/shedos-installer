"""SecureBootEnroller — provision/enroll only in Setup Mode, never on BIOS."""

from shedos_installer.core.secureboot import SecureBootEnroller


def _enroller(tmp_path, uefi=True):
    (tmp_path / "etc").mkdir(exist_ok=True)
    return SecureBootEnroller(mount_point=str(tmp_path), uefi=uefi)


def test_bios_never_touches_firmware(tmp_path, mock_run_command):
    e = _enroller(tmp_path, uefi=False)
    assert e.enroll([str(tmp_path / "BOOTX64.EFI")]) is True
    assert mock_run_command.call_count == 0


def test_user_mode_skips_everything(tmp_path, mock_run_command, monkeypatch):
    e = _enroller(tmp_path)
    monkeypatch.setattr(e, "probe_setup_mode", lambda: False)
    assert e.enroll([str(tmp_path / "BOOTX64.EFI")]) is True
    # Self-signing with keys the firmware hasn't enrolled is worse than
    # unsigned (firmware rejects it), so outside Setup Mode we do nothing.
    assert mock_run_command.call_count == 0
    assert not (tmp_path / "etc" / "kernel" / "uki.conf").exists()


def test_generate_keys_mints_pcr_pair_and_runs_sbctl(tmp_path, mock_run_command):
    e = _enroller(tmp_path)
    assert e.generate_keys() is True
    cmds = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("create-keys" in c for c in cmds)
    assert any("openssl genpkey" in c and "pcr-private.pem" in c for c in cmds)
    assert (tmp_path / "etc" / "shedos" / "secureboot").is_dir()


def test_rewrite_uki_conf_is_signing_form(tmp_path):
    e = _enroller(tmp_path)
    e.rewrite_uki_conf()
    conf = (tmp_path / "etc" / "kernel" / "uki.conf").read_text()
    assert "SecureBootPrivateKey=/var/lib/sbctl/keys/db/db.key" in conf
    assert "SecureBootCertificate=/var/lib/sbctl/keys/db/db.pem" in conf
    assert "[PCRSignature:initrd]" in conf
    assert "pcr-private.pem" in conf and "pcr-public.pem" in conf


def test_setup_mode_enrolls_signs_and_rewrites(tmp_path, mock_run_command, monkeypatch):
    e = _enroller(tmp_path)
    monkeypatch.setattr(e, "probe_setup_mode", lambda: True)
    target = tmp_path / "BOOTX64.EFI"
    target.write_bytes(b"MZ")
    assert e.enroll([str(target)]) is True
    cmds = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("enroll-keys" in c for c in cmds)
    assert not any("--microsoft" in c for c in cmds)   # no Windows on this ESP
    assert any("sign -s" in c for c in cmds)            # Limine copy signed
    assert (tmp_path / "etc" / "kernel" / "uki.conf").exists()


def test_dualboot_enroll_keeps_microsoft(tmp_path, mock_run_command, monkeypatch):
    e = _enroller(tmp_path)
    monkeypatch.setattr(e, "probe_setup_mode", lambda: True)
    win = tmp_path / "boot" / "efi" / "EFI" / "Microsoft" / "Boot"
    win.mkdir(parents=True)
    (win / "bootmgfw.efi").write_bytes(b"MZ")
    e.enroll([str(tmp_path / "BOOTX64.EFI")])
    cmds = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("enroll-keys" in c and "--microsoft" in c for c in cmds)


def test_enroll_failure_is_loud_not_silent(tmp_path, monkeypatch):
    """A failed firmware enrollment must NOT report success — the box is left
    provisioned (keys minted, uki.conf signing, images signed) but enroll()
    returns False so the caller/status can't mistake it for active Secure Boot."""
    from tests.conftest import make_result

    e = _enroller(tmp_path)
    monkeypatch.setattr(e, "probe_setup_mode", lambda: True)

    def fake(cmd, **kw):
        if "enroll-keys" in cmd:
            return make_result(returncode=1, stderr="firmware rejected the keys")
        return make_result()

    monkeypatch.setattr("shedos_installer.core.secureboot.run_chroot", fake)
    target = tmp_path / "BOOTX64.EFI"
    target.write_bytes(b"MZ")
    assert e.enroll([str(target)]) is False
    assert (tmp_path / "etc" / "kernel" / "uki.conf").exists()   # still signing-form
