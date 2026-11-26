// Embed the resolved framework versions (from Cargo.lock) into the binary for result metadata.
fn main() {
    let lock = std::fs::read_to_string("Cargo.lock").unwrap_or_default();
    for (name, var) in [("diesel", "DIESEL_VERSION"), ("sea-orm", "SEAORM_VERSION"), ("sqlx", "SQLX_VERSION")] {
        let mut ver = "unknown".to_string();
        let mut it = lock.lines();
        while let Some(l) = it.next() {
            if l == format!("name = \"{name}\"") {
                if let Some(v) = it.next() { ver = v.trim_start_matches("version = ").trim_matches('"').to_string(); }
                break;
            }
        }
        println!("cargo:rustc-env={var}={ver}");
    }
    println!("cargo:rerun-if-changed=Cargo.lock");
}
