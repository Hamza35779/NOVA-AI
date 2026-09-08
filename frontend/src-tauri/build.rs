fn main() {
    // windres (via embed-resource → tauri-build) shells its default C
    // preprocessor through cmd's popen, which mangles the project path
    // ("D:\My Softwares\...") at the first space. Point it at a batch
    // wrapper that hardcodes the 8.3 short path of the WinLibs cpp.exe.
    // See .cargo/config.toml and build-tools/cppwrap.bat.
    if std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("gnu") {
        if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
            let wrapper = std::path::Path::new(&manifest_dir).join("build-tools/cppwrap.bat");
            if wrapper.exists() {
                std::env::set_var("RC", wrapper.to_string_lossy().as_ref());
            }
        }
    }
    tauri_build::build();
}
