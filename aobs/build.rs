fn main() {
    slint_build::compile("ui/app.slint").expect("ui/app.slint failed to compile");

    // 01-boot-layer.md §1 requires SOURCE_DATE_EPOCH pinned from the first build. The
    // date the appliance displays (§10) is read from the same variable, so the number on
    // screen and the number stamped into the ISO cannot disagree. Unset means a
    // developer build, and it says `unknown` rather than inventing a date
    // (standing rule 8).
    let epoch = std::env::var("SOURCE_DATE_EPOCH").unwrap_or_else(|_| "unknown".to_string());
    println!("cargo:rustc-env=AOBS_BUILD_EPOCH={epoch}");

    println!("cargo:rerun-if-env-changed=SOURCE_DATE_EPOCH");
    println!("cargo:rerun-if-changed=ui/app.slint");
}
