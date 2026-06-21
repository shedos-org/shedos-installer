"""SecureBootEnroller — provision (sign + verify) is split from the single
irreversible arm step, so a failure anywhere leaves Secure Boot off and the box
bootable, and arming only ever follows a verified-signed chain."""

from shedos_installer.core.secureboot import SecureBootEnroller


def _enroller(tmp_path, uefi=True):
    (tmp_path / "etc").mkdir(exist_ok=True)
    return SecureBootEnroller(mount_point=str(tmp_path), uefi=uefi)


def test_bios_provision_is_noop(tmp_path, mock_run_command):
    e = _enroller(tmp_path, uefi=False)
    assert e.provision([str(tmp_path / "BOOTX64.EFI")]) is False
    assert mock_run_command.call_count == 0


def test_user_mode_provision_skips_everything(tmp_path, mock_run_command, monkeypatch):
    e = _enroller(tmp_path)
    monkeypatch.setattr(e, "probe_setup_mode", lambda: False)
    # Self-signing with keys the firmware hasn't enrolled is worse than
    # unsigned (firmware rejects it), so outside Setup Mode we do nothing.
    assert e.provision([str(tmp_path / "BOOTX64.EFI")]) is False
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


def test_provision_signs_verifies_and_does_not_arm(tmp_path, mock_run_command, monkeypatch):
    """provision signs + sbverifies the Limine copies and rewrites uki.conf, but
    NEVER arms firmware — enroll-keys is the caller's last step."""
    e = _enroller(tmp_path)
    monkeypatch.setattr(e, "probe_setup_mode", lambda: True)
    target = tmp_path / "BOOTX64.EFI"
    target.write_bytes(b"MZ")
    assert e.provision([str(target)]) is True
    cmds = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("sign -s" in c for c in cmds)            # signed
    assert any("sbverify" in c for c in cmds)           # and verified
    assert not any("enroll-keys" in c for c in cmds)    # but NOT armed
    assert (tmp_path / "etc" / "kernel" / "uki.conf").exists()


def test_provision_blocks_when_signature_unverified(tmp_path, monkeypatch):
    """A Limine copy that fails sbverify must make provision return False so the
    caller never arms a chain the firmware would reject (the brick the review
    caught: arm-before-verify)."""
    from tests.conftest import make_result

    e = _enroller(tmp_path)
    monkeypatch.setattr(e, "probe_setup_mode", lambda: True)

    def fake(cmd, **kw):
        if "sbverify" in cmd:
            return make_result(returncode=1, stderr="No signature table present")
        return make_result()

    monkeypatch.setattr("shedos_installer.core.secureboot.run_chroot", fake)
    target = tmp_path / "BOOTX64.EFI"
    target.write_bytes(b"MZ")
    assert e.provision([str(target)]) is False


def test_arm_enrolls_without_microsoft_single_boot(tmp_path, mock_run_command):
    e = _enroller(tmp_path)
    assert e.arm(has_windows=False) is True
    cmds = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("enroll-keys" in c for c in cmds)
    assert not any("--microsoft" in c for c in cmds)


def test_arm_keeps_microsoft_when_windows_present(tmp_path, mock_run_command):
    e = _enroller(tmp_path)
    assert e.arm(has_windows=True) is True
    cmds = [" ".join(c.args[0]) for c in mock_run_command.call_args_list]
    assert any("enroll-keys" in c and "--microsoft" in c for c in cmds)


def test_arm_failure_is_loud(tmp_path, monkeypatch):
    """A rejected enrollment returns False (not a false success); the box still
    boots and shedman secureboot enroll completes it later."""
    from tests.conftest import make_result

    e = _enroller(tmp_path)
    monkeypatch.setattr(
        "shedos_installer.core.secureboot.run_chroot",
        lambda cmd, **kw: make_result(returncode=1, stderr="firmware rejected the keys"),
    )
    assert e.arm(has_windows=False) is False
