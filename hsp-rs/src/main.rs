use std::process::ExitCode;

use hsp_rs::config::{Config, ConfigError};

fn main() -> ExitCode {
    match Config::from_env_args(std::env::args()) {
        Ok(config) => match hsp_rs::runtime::run(config) {
            Ok(()) => ExitCode::SUCCESS,
            Err(error) => {
                eprintln!("runtime error: {error}");
                ExitCode::from(1)
            }
        },
        Err(ConfigError::Help(text)) => {
            println!("{text}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("config error: {error}");
            ExitCode::from(2)
        }
    }
}
