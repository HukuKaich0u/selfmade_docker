use std::path::PathBuf;

use clap::{Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(name = "mydocker")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Debug, Subcommand)]
pub enum Commands {
    Run(RunArgs),
    Create(CreateArgs),
    Start(ContainerArgs),
    Delete(ContainerArgs),
    State(ContainerArgs),
}

#[derive(Debug, clap::Args)]
pub struct RunArgs {
    pub bundle: PathBuf,
}

#[derive(Debug, clap::Args)]
pub struct CreateArgs {
    pub bundle: PathBuf,
}

#[derive(Debug, clap::Args)]
pub struct ContainerArgs {
    pub container_id: String,
}
