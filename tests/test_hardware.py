

def _gpu(series, is_nvidia=True):
    from shedos_installer.utils.hardware import GpuInfo
    return GpuInfo(
        vendor="NVIDIA" if is_nvidia else "AMD",
        model="test",
        pci_id="0000",
        driver="nvidia" if is_nvidia else "amdgpu",
        is_nvidia=is_nvidia,
        nvidia_series=series,
    )


def test_nvidia_open_supported_turing_and_newer():
    from shedos_installer.utils.hardware import nvidia_open_supported

    for series in ("Turing", "Ampere", "Ada Lovelace", "Blackwell"):
        assert nvidia_open_supported(_gpu(series))


def test_nvidia_open_unsupported_pre_turing():
    from shedos_installer.utils.hardware import nvidia_open_supported

    assert not nvidia_open_supported(_gpu("Pascal/Maxwell"))


def test_nvidia_open_unknown_series_assumed_new():
    from shedos_installer.utils.hardware import nvidia_open_supported

    assert nvidia_open_supported(_gpu(None))
    assert not nvidia_open_supported(_gpu(None, is_nvidia=False))
