mod cli;

use clap::Parser;

fn main() {
    match try_main() {
        Ok(()) => {}
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(error.exit_code());
        }
    }
}

fn try_main() -> Result<(), mydocker::error::AppError> {
    match cli::Cli::parse().command {
        cli::Commands::Run(args) => mydocker::run_bundle(&args.bundle),
    }
}
