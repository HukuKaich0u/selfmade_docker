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
        cli::Commands::Create(args) => {
            let container_id = mydocker::create_container(&args.bundle)?;
            println!("{container_id}");
            Ok(())
        }
        cli::Commands::Start(args) => mydocker::start_container(&args.container_id),
        cli::Commands::Delete(args) => mydocker::delete_container(&args.container_id),
        cli::Commands::State(args) => {
            let state = mydocker::read_state(&args.container_id)?;
            println!("{}", serde_json::to_string_pretty(&state).unwrap());
            Ok(())
        }
    }
}
