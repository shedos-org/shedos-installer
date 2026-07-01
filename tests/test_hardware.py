

def _gpu(series, is_nvidia=True, pci_addr=""):
    from shedos_installer.utils.hardware import GpuInfo
    return GpuInfo(
        vendor="NVIDIA" if is_nvidia else "AMD",
        model="test",
        pci_id="0000",
        driver="nvidia" if is_nvidia else "amdgpu",
        is_nvidia=is_nvidia,
        nvidia_series=series,
        pci_addr=pci_addr,
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


def test_should_install_nvidia_gates_on_gpu_support_only():
    from shedos_installer.utils.hardware import should_install_nvidia

    # Any GPU the open modules can drive → yes, even alongside an iGPU.
    assert should_install_nvidia([_gpu("Turing")])
    assert should_install_nvidia([_gpu(None, is_nvidia=False), _gpu("Ampere")])
    # Nothing supported → no. No profile condition is involved.
    assert not should_install_nvidia([_gpu("Pascal/Maxwell")])
    assert not should_install_nvidia([_gpu(None, is_nvidia=False)])
    assert not should_install_nvidia([])


def test_gpu_topology():
    from shedos_installer.utils.hardware import gpu_topology

    assert gpu_topology([_gpu("Turing"), _gpu(None, is_nvidia=False)]) == "hybrid"
    assert gpu_topology([_gpu("Turing")]) == "nvidia-only"
    assert gpu_topology([_gpu(None, is_nvidia=False)]) == "other"
    assert gpu_topology([]) == "other"


def test_gpu_env_lines_hybrid_keeps_igpu_primary():
    from shedos_installer.utils.hardware import gpu_env_lines

    igpu = _gpu(None, is_nvidia=False, pci_addr="0000:00:02.0")
    dgpu = _gpu("Turing", pci_addr="0000:01:00.0")
    joined = "\n".join(gpu_env_lines([igpu, dgpu]))
    # iGPU node first in AQ_DRM_DEVICES; no global nvidia block; prime-run noted.
    assert ("AQ_DRM_DEVICES=/dev/dri/by-path/pci-0000:00:02.0-card:"
            "/dev/dri/by-path/pci-0000:01:00.0-card") in joined
    assert "GBM_BACKEND" not in joined
    assert "LIBVA_DRIVER_NAME" not in joined
    assert "prime-run" in joined


def test_gpu_env_lines_nvidia_only_sets_render_env():
    from shedos_installer.utils.hardware import gpu_env_lines

    joined = "\n".join(gpu_env_lines([_gpu("Ampere", pci_addr="0000:01:00.0")]))
    assert "AQ_DRM_DEVICES=/dev/dri/by-path/pci-0000:01:00.0-card" in joined
    assert "GBM_BACKEND=nvidia-drm" in joined
    assert "__GLX_VENDOR_LIBRARY_NAME=nvidia" in joined


def test_gpu_env_lines_single_other_gpu_is_empty():
    from shedos_installer.utils.hardware import gpu_env_lines

    assert gpu_env_lines([_gpu(None, is_nvidia=False)]) == []
