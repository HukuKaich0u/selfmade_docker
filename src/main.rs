mod cli;

use clap::Parser;
use std::process::ExitCode;

fn main() -> ExitCode {
    match try_main() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}

fn try_main() -> Result<(), mydocker::error::AppError> {
    match cli::Cli::parse().command {
        cli::Commands::Run(args) => mydocker::run_bundle(&args.bundle),
    }
}
